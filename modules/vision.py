# modules/vision.py — Thread caméra : détection visage + émotion
# Utilise Mediapipe FaceMesh (468 landmarks) + heuristiques géométriques.
# v2 (Phase 8.4 fix) : refactor _compute_smile_score + _compute_brow_distance + _detect_emotion
# avec seuils calibres sur des donnees reelles webcam.

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
    """Une frame de detection visage + emotion lissee."""
    detected: bool
    emotion: str        # "neutral", "happy", "sad", "pain"
    confidence: float   # Confiance détection visage (0–1)
    bbox: tuple = None  # (x, y, w, h) ou None
    debug: dict = field(default_factory=dict)  # v2 : valeurs intermediaires pour debug


# ---------------------------------------------------------------
# Indices landmarks FaceMesh (468 points)
# ---------------------------------------------------------------
# Bouche
_MOUTH_TOP      = 13     # Haut de la levre superieure
_MOUTH_BOTTOM   = 14
_MOUTH_LEFT     = 78
_MOUTH_RIGHT    = 308
_MOUTH_CORNER_L = 61
_MOUTH_CORNER_R = 291

# Yeux
_EYE_L_TOP    = 159
_EYE_L_BOTTOM = 145
_EYE_L_LEFT   = 33
_EYE_L_RIGHT  = 133
_EYE_R_TOP    = 386
_EYE_R_BOTTOM = 374
_EYE_R_LEFT   = 362
_EYE_R_RIGHT  = 263

# Sourcils — distance verticale pour tristesse
_BROW_L_INNER  = 70
_BROW_R_INNER  = 300
_NOSE_TIP      = 4     # Référence stable pour normalisation

# v2 : reference pour normaliser les distances par taille du visage
_FACE_LEFT  = 234   # Tempe gauche
_FACE_RIGHT = 454   # Tempe droite


# ---------------------------------------------------------------
# Fonctions utilitaires géométriques
# ---------------------------------------------------------------
def _dist(p1, p2):
    """Distance euclidienne 2D entre deux landmarks."""
    return np.sqrt((p1.x - p2.x) ** 2 + (p1.y - p2.y) ** 2)


def _face_width(landmarks):
    """v2 : largeur du visage pour normalisation. Stable peu importe la distance camera."""
    return _dist(landmarks[_FACE_LEFT], landmarks[_FACE_RIGHT])


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
    """v2 : score de sourire normalise par la largeur du visage.

    Logique : on mesure la position verticale moyenne des coins de la bouche
    par rapport au centre de la levre superieure, normalisee par la taille du visage.

    Plus le retour est proche de 0 ou positif, plus c'est un sourire.
    Plus c'est negatif, plus c'est neutre/moue.

    Note : la valeur absolue varie selon la geometrie du visage. Le calibrage
    se fait via des seuils relatifs (cf. config.SMILE_HAPPY_THRESHOLD).
    """
    top_center = landmarks[_MOUTH_TOP]
    corner_l   = landmarks[_MOUTH_CORNER_L]
    corner_r   = landmarks[_MOUTH_CORNER_R]
    avg_corner_y = (corner_l.y + corner_r.y) / 2

    # En image, axe Y vers le bas : sourire = coins plus hauts = corner.y < top.y
    raw = top_center.y - avg_corner_y

    # v2 : normalisation par largeur du visage
    fw = _face_width(landmarks)
    if fw < 1e-6:
        return 0.0
    return raw / fw


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


def _compute_brow_squeeze(landmarks):
    """v2 : ressere des sourcils, normalise par la largeur du visage.

    Faible = sourcils rapproches (frons, fronceemnt = tristesse / douleur).
    Eleve = sourcils ecartes (etat normal).
    """
    brow_l = landmarks[_BROW_L_INNER]
    brow_r = landmarks[_BROW_R_INNER]
    fw = _face_width(landmarks)
    if fw < 1e-6:
        return 0.0
    # On mesure l'ecartement horizontal des sourcils internes, normalise.
    return _dist(brow_l, brow_r) / fw


def _compute_brow_drop(landmarks):
    """v2 : descente des sourcils par rapport au nez, normalisee par largeur visage.

    Faible = sourcils proches du nez (sourcils baisses, frons).
    Eleve = sourcils releves.
    """
    brow_l = landmarks[_BROW_L_INNER]
    brow_r = landmarks[_BROW_R_INNER]
    nose   = landmarks[_NOSE_TIP]
    brow_mid_y = (brow_l.y + brow_r.y) / 2
    fw = _face_width(landmarks)
    if fw < 1e-6:
        return 0.0
    # Distance verticale brow -> nose, normalisee
    return abs(nose.y - brow_mid_y) / fw


# ---------------------------------------------------------------
# Détection émotion combinée
# ---------------------------------------------------------------
def _detect_emotion(landmarks):
    """v2.1 : analyse les landmarks FaceMesh et retourne (emotion, score, debug_dict).

    Logique calibree sur des donnees reelles webcam :
    - HAPPY : MAR ouvert + EAR plus faible (sourire dents + yeux plisses du rire)
    - PAIN  : MAR ouvert + sourcils tres baisses (grimace de douleur)
    - SAD   : MAR ferme + smile tres negatif + sourcils baisses
    """
    mar    = _compute_mar(landmarks)
    smile  = _compute_smile_score(landmarks)
    ear    = _compute_ear(landmarks)
    brow_s = _compute_brow_squeeze(landmarks)
    brow_d = _compute_brow_drop(landmarks)

    debug = {
        "mar": round(mar, 3),
        "smile": round(smile, 4),
        "ear": round(ear, 3),
        "brow_squeeze": round(brow_s, 4),
        "brow_drop": round(brow_d, 4),
    }

    scores = {
        "happy":   0.0,
        "sad":     0.0,
        "pain":    0.0,
        "neutral": 0.3,  # Biais leger vers neutre
    }

    bouche_ouverte = mar > config.MAR_OPEN_THRESHOLD

    # === HAPPY === bouche ouverte + yeux plisses du rire (ear bas)
    if bouche_ouverte and ear < config.EAR_HAPPY_MAX:
        # Plus l'ear est bas, plus le score est haut
        intensity = (config.EAR_HAPPY_MAX - ear) * 4
        scores["happy"] = min(1.0, 0.5 + intensity)

    # === PAIN === bouche ouverte (grimace) + sourcils tres descendus
    if bouche_ouverte and brow_d > config.BROW_DROP_PAIN_THRESHOLD:
        intensity = (brow_d - config.BROW_DROP_PAIN_THRESHOLD) * 5
        scores["pain"] = min(1.0, 0.5 + intensity)

    # === SAD === bouche fermee + coins tres tombants + sourcils descendus
    if (not bouche_ouverte
            and smile < config.SMILE_SAD_THRESHOLD
            and brow_d > config.BROW_DROP_SAD_THRESHOLD):
        intensity = (config.SMILE_SAD_THRESHOLD - smile) * 10
        intensity += (brow_d - config.BROW_DROP_SAD_THRESHOLD) * 5
        scores["sad"] = min(1.0, 0.4 + intensity)

    # === ARBITRAGE ===
    emotion = max(scores, key=scores.get)
    score = scores[emotion]

    if score < config.EMOTION_MIN_SCORE:
        emotion = "neutral"
        score = scores["neutral"]

    return emotion, round(score, 2), debug


# ---------------------------------------------------------------
# Lissage temporel des émotions (moyenne glissante)
# ---------------------------------------------------------------
class EmotionSmoother:
    """Lissage par moyenne glissante : evite les sauts d'emotion frame par frame."""
    def __init__(self, window_size=5):
        self._history = deque(maxlen=window_size)
        self._counts = {"neutral": 0, "happy": 0, "sad": 0, "pain": 0}

    def update(self, emotion):
        self._history.append(emotion)
        # Reconstruction des counts a partir de l'historique courant
        self._counts = {"neutral": 0, "happy": 0, "sad": 0, "pain": 0}
        for e in self._history:
            self._counts[e] = self._counts.get(e, 0) + 1
        # Emotion dominante = celle qui apparait le plus souvent
        return max(self._counts, key=self._counts.get)


# ---------------------------------------------------------------
# Thread vision
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
        cap = cv2.VideoCapture(config.CAMERA_INDEX)
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
                    time.sleep(0.05)
                    continue

                self._last_frame = frame
                self._frame_count += 1
                fps_count += 1

                # FPS update toutes les secondes
                now = time.time()
                if now - fps_timer >= 1.0:
                    self._fps = fps_count / (now - fps_timer)
                    fps_count = 0
                    fps_timer = now

                # Conversion BGR -> RGB pour MediaPipe
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = face_mesh.process(rgb)

                if results.multi_face_landmarks:
                    landmarks = results.multi_face_landmarks[0].landmark
                    emotion_raw, score, debug_vals = _detect_emotion(landmarks)
                    emotion_smoothed = self._smoother.update(emotion_raw)

                    # Log periodique pour debug (toutes les 30 frames ~= 2s)
                    if config.VISION_DEBUG_LOG and self._frame_count % 30 == 0:
                        logger.debug(
                            "Frame %d: raw=%s lisse=%s score=%.2f | %s",
                            self._frame_count, emotion_raw, emotion_smoothed,
                            score, debug_vals
                        )

                    fd = FaceData(
                        detected=True,
                        emotion=emotion_smoothed,
                        confidence=score,
                        debug=debug_vals,
                    )
                    try:
                        self.face_q.put_nowait(fd)
                    except Exception:
                        # Queue pleine - on drop
                        pass
                else:
                    # Pas de visage : on pousse un FaceData neutre
                    fd = FaceData(detected=False, emotion="neutral", confidence=0.0)
                    try:
                        self.face_q.put_nowait(fd)
                    except Exception:
                        pass

        finally:
            cap.release()
            face_mesh.close()
            logger.info("Thread vision arrêté (FPS moyen : %.1f)", self._fps)
