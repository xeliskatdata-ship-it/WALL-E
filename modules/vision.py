# modules/vision.py - Thread camera : detection visage + emotion
# v3 (Phase post-F) : refactor complet. Mediapipe ne fournit pas de wheel aarch64
# sur PyPI/piwheels -> on degage la dette et on passe a OpenCV YuNet + FER+ ONNX.
# Contrat preserve : FaceData identique, emotion in {neutral, happy, sad, pain},
# VisionThread(face_q, stop_event) identique, wrappers camera intacts.
# v3.1 : ajuste mapping surprise -> neutral apres smoke test webcam (faux positifs en lecture).

import time
import threading
import logging
import platform
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

import config

logger = logging.getLogger("walle.vision")


# ---------------------------------------------------------------
# Data classes (contrat inchange v2 -> v3)
# ---------------------------------------------------------------
@dataclass
class FaceData:
    """Une frame de detection visage + emotion lissee."""
    detected: bool
    emotion: str        # "neutral", "happy", "sad", "pain"
    confidence: float   # Confiance emotion (0-1), softmax max
    bbox: tuple = None  # (x, y, w, h) ou None
    debug: dict = field(default_factory=dict)


# ---------------------------------------------------------------
# Detection visage - YuNet (OpenCV 4.6+)
# ---------------------------------------------------------------
class _YuNetDetector:
    # YuNet est integre a OpenCV via cv2.FaceDetectorYN. Pas besoin de session ONNX manuelle,
    # OpenCV gere tout en interne. Faster + plus compact que SSD-MobileNet pour ce use case.

    def __init__(self, model_path, score_threshold=0.6, nms_threshold=0.3):
        self._detector = cv2.FaceDetectorYN.create(
            model=str(model_path),
            config="",
            input_size=(320, 320),       # resize dynamique a chaque detect
            score_threshold=score_threshold,
            nms_threshold=nms_threshold,
            top_k=5,                     # 5 visages max remontes (on en garde 1)
        )

    def detect(self, frame_bgr):
        # YuNet veut la taille reelle de l'image en input
        h, w = frame_bgr.shape[:2]
        self._detector.setInputSize((w, h))
        _, faces = self._detector.detect(frame_bgr)
        if faces is None or len(faces) == 0:
            return None
        # faces[i] : [x, y, w, h, lm0_x, lm0_y, ..., lm4_x, lm4_y, score]
        # On prend le plus gros visage (presume le user au premier plan)
        face = max(faces, key=lambda f: f[2] * f[3])
        x, y, fw, fh = [int(v) for v in face[:4]]
        score = float(face[-1])
        return {"bbox": (x, y, fw, fh), "score": score}


# ---------------------------------------------------------------
# Emotion - FER+ ONNX (8 classes -> 4)
# ---------------------------------------------------------------
class _EmotionEngine:
    # FER+ : input [1, 1, 64, 64] grayscale float32, output logits [1, 8]
    # On softmax + mapping 8 -> 4 classes du contrat existant.

    _FER_LABELS = [
        "neutral", "happiness", "surprise", "sadness",
        "anger", "disgust", "fear", "contempt",
    ]

    # Mapping vers contrat WALL-E (cf. brain Phase 8.4)
    _MAP = {
        "neutral":   "neutral",
        "contempt":  "neutral",
        "happiness": "happy",
        "surprise":  "neutral",    # v2.5.1 : FER+ over-detecte surprise en concentration/lecture
        "sadness":   "sad",
        "anger":     "pain",
        "disgust":   "pain",
        "fear":      "pain",
    }

    def __init__(self, model_path):
        # CPUExecutionProvider partout (Pi 5 + Windows). XNNPACK possible plus tard si besoin perf.
        self._session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
        self._input_name = self._session.get_inputs()[0].name

    def predict(self, face_crop_bgr):
        # Preprocess : BGR -> gris -> 64x64 -> float32 [1,1,64,64]
        gray = cv2.cvtColor(face_crop_bgr, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)
        x = resized.astype(np.float32).reshape(1, 1, 64, 64)

        logits = self._session.run(None, {self._input_name: x})[0][0]

        # Softmax numeriquement stable
        e = np.exp(logits - logits.max())
        probs = e / e.sum()

        idx = int(probs.argmax())
        raw_label = self._FER_LABELS[idx]
        mapped = self._MAP[raw_label]
        confidence = float(probs[idx])

        debug = {
            "raw_label": raw_label,
            "probs": {l: round(float(p), 3) for l, p in zip(self._FER_LABELS, probs)},
        }
        return mapped, confidence, debug


# ---------------------------------------------------------------
# Lissage temporel (inchange v2 -> v3)
# ---------------------------------------------------------------
class EmotionSmoother:
    """Moyenne glissante : evite les sauts d'emotion frame par frame."""
    def __init__(self, window_size=5):
        self._history = deque(maxlen=window_size)

    def update(self, emotion):
        self._history.append(emotion)
        counts = {}
        for e in self._history:
            counts[e] = counts.get(e, 0) + 1
        return max(counts, key=counts.get)


# ---------------------------------------------------------------
# Wrappers camera cross-platform (inchanges v2.4 -> v3)
# ---------------------------------------------------------------
class _Picamera2Capture:
    """Wrapper picamera2 qui retourne du BGR pour rester compat avec le pipeline cv2."""
    def __init__(self, width, height):
        from picamera2 import Picamera2
        self._cam = Picamera2()
        cfg = self._cam.create_video_configuration(
            main={"size": (width, height), "format": "RGB888"}
        )
        self._cam.configure(cfg)
        self._cam.start()
        time.sleep(0.5)
        self._opened = True

    def read(self):
        try:
            arr = self._cam.capture_array()
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            return True, bgr
        except Exception as e:
            logger.debug("picamera2 read KO : %s", e)
            return False, None

    def release(self):
        try: self._cam.stop()
        except Exception: pass
        self._opened = False

    def isOpened(self):
        return self._opened


class _CV2Capture:
    """Wrapper cv2.VideoCapture (Windows / webcam USB / Linux non-Pi)."""
    def __init__(self, index, width=None, height=None, fps=None):
        backend = cv2.CAP_DSHOW if platform.system() == "Windows" else 0
        self._cap = cv2.VideoCapture(index, backend)
        if width:  self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        if height: self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if fps:    self._cap.set(cv2.CAP_PROP_FPS, fps)

    def read(self):    return self._cap.read()
    def release(self): self._cap.release()
    def isOpened(self):return self._cap.isOpened()


def _open_camera():
    width  = getattr(config, "CAMERA_WIDTH",  1280)
    height = getattr(config, "CAMERA_HEIGHT", 720)
    fps    = getattr(config, "CAMERA_FPS",    30)
    is_pi  = getattr(config, "IS_RASPBERRY_PI", False)

    if is_pi:
        try:
            cam = _Picamera2Capture(width, height)
            logger.info("Camera : backend picamera2 (%dx%d)", width, height)
            return cam
        except Exception as e:
            logger.warning("picamera2 KO (%s), fallback cv2", e)

    cam = _CV2Capture(config.CAMERA_INDEX, width, height, fps)
    if not cam.isOpened():
        logger.error("cv2.VideoCapture KO sur index=%d", config.CAMERA_INDEX)
        return None
    logger.info("Camera : backend cv2 (index=%d, %dx%d)", config.CAMERA_INDEX, width, height)
    return cam


# ---------------------------------------------------------------
# Thread vision (interface inchangee v2 -> v3)
# ---------------------------------------------------------------
class VisionThread(threading.Thread):
    """Thread camera : capture -> YuNet -> crop face -> FER+ -> face_q."""

    def __init__(self, face_q, stop_event=None):
        super().__init__(name="VisionThread", daemon=True)
        self.face_q = face_q
        self.stop_event = stop_event or threading.Event()
        self._smoother = EmotionSmoother(config.EMOTION_SMOOTHING)
        self._frame_count = 0
        self._fps = 0.0
        self._last_frame = None

        # Chargement des modeles (au boot du thread, fail-fast si manquants)
        models_dir = Path(getattr(config, "MODELS_DIR", "models"))
        yunet_path   = models_dir / "face_detection_yunet_2023mar.onnx"
        ferplus_path = models_dir / "emotion-ferplus-8.onnx"

        if not yunet_path.exists() or not ferplus_path.exists():
            raise FileNotFoundError(
                f"Modeles ONNX manquants dans {models_dir.resolve()}. "
                "Lance : python models/download_models.py"
            )

        self._detector = _YuNetDetector(
            yunet_path,
            score_threshold=config.VISION_MIN_CONFIDENCE,
        )
        self._emotion = _EmotionEngine(ferplus_path)
        logger.info("Modeles ONNX charges (YuNet + FER+)")

    def run(self):
        logger.info("Demarrage du thread vision")
        cap = _open_camera()
        if cap is None:
            logger.error("Impossible d'ouvrir la camera")
            return

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

                face = self._detector.detect(frame)

                if face is None:
                    # Pas de visage detecte
                    self._push(FaceData(detected=False, emotion="neutral", confidence=0.0))
                    continue

                x, y, fw, fh = face["bbox"]

                # Clamp dans les limites de l'image (YuNet peut sortir des bbox legerement out-of-bounds)
                h_img, w_img = frame.shape[:2]
                x1 = max(0, x); y1 = max(0, y)
                x2 = min(w_img, x + fw); y2 = min(h_img, y + fh)
                if x2 - x1 < 20 or y2 - y1 < 20:
                    # Crop degenere, on skip
                    self._push(FaceData(detected=False, emotion="neutral", confidence=0.0))
                    continue

                crop = frame[y1:y2, x1:x2]
                emotion_raw, score, debug_vals = self._emotion.predict(crop)
                emotion_smoothed = self._smoother.update(emotion_raw)

                # Log periodique (toutes les 30 frames ~= 2s)
                if config.VISION_DEBUG_LOG and self._frame_count % 30 == 0:
                    logger.debug(
                        "Frame %d: raw=%s lisse=%s conf=%.2f bbox=%s | %s",
                        self._frame_count, emotion_raw, emotion_smoothed,
                        score, face["bbox"], debug_vals
                    )

                self._push(FaceData(
                    detected=True,
                    emotion=emotion_smoothed,
                    confidence=score,
                    bbox=face["bbox"],
                    debug=debug_vals,
                ))

        finally:
            cap.release()
            logger.info("Thread vision arrete (FPS moyen : %.1f)", self._fps)

    def _push(self, fd):
        # Helper : push non-bloquant, drop si la queue est pleine
        try:
            self.face_q.put_nowait(fd)
        except Exception:
            pass