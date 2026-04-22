# modules/vision.py — Thread caméra : détection visage + émotion
# Utilise Mediapipe FaceMesh (468 landmarks) + heuristiques géométriques.

import time
import threading
import logging
from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np
import mediapipe as mp

import config

logger = logging.getLogger("walle.vision")

# ---------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------
@dataclass
class FaceData:
    """Résultat d'une frame analysée, poussé dans face_q."""
    x: int              # Bounding box coin haut-gauche
    y: int
    w: int
    h: int
    cx: float           # Centre du visage normalisé [-1, +1]
    cy: float
    emotion: str        # "neutral", "happy", "sad", "pain"
    confidence: float   # Confiance détection visage (0–1)
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------
# Indices FaceMesh pour les heuristiques émotionnelles
# Réf : https://github.com/google-ai-edge/mediapipe/blob/master
#        /mediapipe/modules/face_geometry/data/canonical_face_model_uv_visualization.png
# ---------------------------------------------------------------

# Bouche — pour MAR (Mouth Aspect Ratio)
_MOUTH_TOP     = 13    # Lèvre supérieure centre
_MOUTH_BOTTOM  = 14    # Lèvre inférieure centre
_MOUTH_LEFT    = 308   # Coin gauche
_MOUTH_RIGHT   = 78    # Coin droit
# Points supplémentaires pour détecter le sourire
_MOUTH_CORNER_L = 61   # Commissure gauche haute
_MOUTH_CORNER_R = 291  # Commissure droite haute

# Yeux — pour EAR (Eye Aspect Ratio)
_EYE_L_TOP     = 159
_EYE_L_BOTTOM  = 145
_EYE_L_LEFT    = 33
_EYE_L_RIGHT   = 133
_EYE_R_TOP     = 386
_EYE_R_BOTTOM  = 374
_EYE_R_LEFT    = 362
_EYE_R_RIGHT   = 263

# Sourcils — distance verticale pour tristesse
_BROW_L_INNER  = 70
_BROW_R_INNER  = 300
_NOSE_TIP      = 4     # Référence stable pour normalisation


# ---------------------------------------------------------------
# Fonctions utilitaires géométriques
# ---------------------------------------------------------------
def _dist(p1, p2):
    """Distance euclidienne 2D entre deux landmarks."""
    return np.sqrt((p1.x - p2.x) ** 2 + (p1.y - p2.y) ** 2)


def _compute_mar(landmarks):
    """Mouth Aspect Ratio : hauteur bouche / largeur bouche.
    Élevé = bouche ouverte / sourire large."""
    top    = landmarks[_MOUTH_TOP]
    bottom = landmarks[_MOUTH_BOTTOM]
    left   = landmarks[_MOUTH_LEFT]
    right  = landmarks[_MOUTH_RIGHT]
    vertical   = _dist(top, bottom)
    horizontal = _dist(left, right)
    if horizontal < 1e-6:
        return 0.0
    return vertical / horizontal


def _compute_smile_score(landmarks):
    """Score de sourire basé sur l'élévation des coins de la bouche
    par rapport au centre de la lèvre supérieure.
    Positif = sourire, négatif = moue."""
    top_center = landmarks[_MOUTH_TOP]
    corner_l   = landmarks[_MOUTH_CORNER_L]
    corner_r   = landmarks[_MOUTH_CORNER_R]
    # Les coins sont-ils plus hauts que le centre ? (y inversé en image)
    avg_corner_y = (corner_l.y + corner_r.y) / 2
    return top_center.y - avg_corner_y  # positif = sourire


def _compute_ear(landmarks):
    """Eye Aspect Ratio moyen (gauche + droit).
    Faible = yeux plissés (douleur)."""
    def _ear_one(top, bottom, left, right):
        v = _dist(landmarks[top], landmarks[bottom])
        h = _dist(landmarks[left], landmarks[right])
        return v / h if h > 1e-6 else 0.0

    ear_l = _ear_one(_EYE_L_TOP, _EYE_L_BOTTOM, _EYE_L_LEFT, _EYE_L_RIGHT)
    ear_r = _ear_one(_EYE_R_TOP, _EYE_R_BOTTOM, _EYE_R_LEFT, _EYE_R_RIGHT)
    return (ear_l + ear_r) / 2


def _compute_brow_distance(landmarks):
    """Distance normalisée entre les sourcils intérieurs.
    Faible = sourcils froncés (tristesse / douleur).
    Normalisé par la distance nez-sourcil pour être indépendant de la distance caméra."""
    brow_l = landmarks[_BROW_L_INNER]
    brow_r = landmarks[_BROW_R_INNER]
    nose   = landmarks[_NOSE_TIP]
    brow_dist = _dist(brow_l, brow_r)
    # Normalisation par la distance verticale nez → milieu sourcils
    brow_mid_y = (brow_l.y + brow_r.y) / 2
    ref_dist = abs(nose.y - brow_mid_y)
    if ref_dist < 1e-6:
        return 0.0
    return brow_dist / ref_dist


# ---------------------------------------------------------------
# Détection émotion combinée
# ---------------------------------------------------------------
def _detect_emotion(landmarks):
    """Analyse les landmarks FaceMesh et retourne (emotion, score).
    Logique à seuils, pas de ML — tourne sur Pi sans GPU."""

    mar   = _compute_mar(landmarks)
    smile = _compute_smile_score(landmarks)
    ear   = _compute_ear(landmarks)
    brow  = _compute_brow_distance(landmarks)

    scores = {
        "happy":   0.0,
        "sad":     0.0,
        "pain":    0.0,
        "neutral": 0.3,  # Biais léger vers neutre
    }

    # Joie : bouche ouverte + coins relevés
    if mar > config.MAR_HAPPY_THRESHOLD and smile > 0.005:
        scores["happy"] = min(1.0, mar * 1.2 + smile * 10)

    # Douleur : yeux très plissés + sourcils froncés
    if ear < config.EAR_PAIN_THRESHOLD:
        scores["pain"] = min(1.0, (config.EAR_PAIN_THRESHOLD - ear) * 8)
        if brow < config.BROW_SAD_THRESHOLD:
            scores["pain"] += 0.2

    # Tristesse : coins bouche abaissés + sourcils rapprochés
    if smile < -0.003 and brow < config.BROW_SAD_THRESHOLD * 1.2:
        scores["sad"] = min(1.0, abs(smile) * 15 + (config.BROW_SAD_THRESHOLD - brow) * 5)

    # Émotion dominante
    emotion = max(scores, key=scores.get)
    score   = scores[emotion]

    # Si le score max est trop faible, c'est neutre
    if score < config.EMOTION_MIN_SCORE:
        emotion = "neutral"
        score   = scores["neutral"]

    return emotion, round(score, 2)


# ---------------------------------------------------------------
# Lissage temporel des émotions (moyenne glissante)
# ---------------------------------------------------------------
class EmotionSmoother:
    """Évite les changements d'expression intempestifs en lissant
    sur N frames consécutives."""

    def __init__(self, window_size=5):
        self._history = deque(maxlen=window_size)
        self._current = "neutral"

    def update(self, emotion):
        self._history.append(emotion)
        if len(self._history) < self._history.maxlen:
            return self._current

        # L'émotion la plus fréquente sur la fenêtre
        from collections import Counter
        counts = Counter(self._history)
        dominant, count = counts.most_common(1)[0]

        # Seuil de majorité : l'émotion doit apparaître > 60% de la fenêtre
        if count >= self._history.maxlen * 0.6:
            self._current = dominant

        return self._current

    def reset(self):
        self._history.clear()
        self._current = "neutral"


# ---------------------------------------------------------------
# Thread principal Vision
# ---------------------------------------------------------------
class VisionThread(threading.Thread):
    """Thread caméra : capture → FaceMesh → émotion → face_q."""

    def __init__(self, face_q, stop_event=None):
        super().__init__(name="VisionThread", daemon=True)
        self.face_q = face_q
        self.stop_event = stop_event or threading.Event()
        self._smoother = EmotionSmoother(config.EMOTION_SMOOTHING)
        self._frame_count = 0
        self._fps = 0.0
        self._last_frame = None  # Dernier frame pour debug/affichage externe

    def run(self):
        logger.info("Démarrage du thread vision")

        # Init caméra
        cap = cv2.VideoCapture(config.CAMERA_INDEX)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, config.VISION_FPS_TARGET)

        if not cap.isOpened():
            logger.error("Impossible d'ouvrir la caméra (index %d)", config.CAMERA_INDEX)
            return

        # Init FaceMesh
        mp_face = mp.solutions.face_mesh
        face_mesh = mp_face.FaceMesh(
            static_image_mode=False,
            max_num_faces=config.VISION_MAX_FACES,
            refine_landmarks=True,
            min_detection_confidence=config.VISION_MIN_CONFIDENCE,
            min_tracking_confidence=0.5,
        )

        fps_timer = time.time()
        fps_count = 0

        try:
            while not self.stop_event.is_set():
                ret, frame = cap.read()
                if not ret:
                    logger.warning("Frame vide, tentative suivante...")
                    time.sleep(0.01)
                    continue

                self._frame_count += 1

                # Skip frames pour économiser le CPU
                if self._frame_count % config.VISION_SKIP_FRAMES != 0:
                    continue

                # FPS counter
                fps_count += 1
                elapsed = time.time() - fps_timer
                if elapsed >= 1.0:
                    self._fps = fps_count / elapsed
                    fps_count = 0
                    fps_timer = time.time()

                # Conversion BGR → RGB pour Mediapipe
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = face_mesh.process(rgb)

                if not results.multi_face_landmarks:
                    # Aucun visage détecté — on garde le dernier frame pour l'affichage
                    self._last_frame = frame
                    continue

                # Prendre le premier visage détecté
                face_landmarks = results.multi_face_landmarks[0]
                landmarks = face_landmarks.landmark
                h, w = frame.shape[:2]

                # Bounding box à partir des landmarks
                xs = [lm.x * w for lm in landmarks]
                ys = [lm.y * h for lm in landmarks]
                x_min, x_max = int(min(xs)), int(max(xs))
                y_min, y_max = int(min(ys)), int(max(ys))
                box_w = x_max - x_min
                box_h = y_max - y_min

                # Centre normalisé [-1, +1]
                cx = ((x_min + x_max) / 2 - w / 2) / (w / 2)
                cy = ((y_min + y_max) / 2 - h / 2) / (h / 2)

                # Détection émotion
                raw_emotion, confidence = _detect_emotion(landmarks)
                smoothed_emotion = self._smoother.update(raw_emotion)

                # Construire le résultat
                face_data = FaceData(
                    x=x_min, y=y_min, w=box_w, h=box_h,
                    cx=round(cx, 3), cy=round(cy, 3),
                    emotion=smoothed_emotion,
                    confidence=confidence,
                )

                # Pousser dans la queue (non-bloquant, on drop si pleine)
                if not self.face_q.full():
                    self.face_q.put(face_data)

                # Stocker le frame annoté pour le mode debug
                self._last_frame = frame.copy()
                cv2.rectangle(self._last_frame, (x_min, y_min), (x_max, y_max), (0, 255, 0), 2)
                label = f"{smoothed_emotion} ({confidence:.0%})"
                cv2.putText(self._last_frame, label, (x_min, y_min - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        except Exception as e:
            logger.exception("Erreur dans le thread vision : %s", e)
        finally:
            face_mesh.close()
            cap.release()
            logger.info("Thread vision arrêté (FPS moyen : %.1f)", self._fps)

    # --- API publique (thread-safe en lecture seule) ---

    @property
    def fps(self):
        return self._fps

    @property
    def last_frame(self):
        """Dernier frame avec annotations (pour affichage debug)."""
        return self._last_frame
