#!/usr/bin/env python3
# tests/test_vision.py — Test Phase 2 : caméra + détection visage + émotion
#
# Usage :
#   python tests/test_vision.py              → mode webcam (affiche la fenêtre)
#   python tests/test_vision.py --headless   → mode sans écran (log terminal uniquement)
#   python tests/test_vision.py --dry-run    → mode sans caméra (vérifie les imports)
#
# Appuie sur 'q' pour quitter en mode webcam.

import sys
import os
import time
import argparse
import logging
from queue import Queue

# Ajouter le dossier racine au path pour importer config et modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from modules.vision import VisionThread, FaceData

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_vision")


def test_dry_run():
    """Vérifie que tous les imports fonctionnent sans caméra."""
    logger.info("=== MODE DRY-RUN ===")
    logger.info("Import config .............. OK")

    import cv2
    logger.info("Import cv2 ................. OK (v%s)", cv2.__version__)

    import mediapipe as mp
    logger.info("Import mediapipe ........... OK (v%s)", mp.__version__)

    import numpy as np
    logger.info("Import numpy ............... OK (v%s)", np.__version__)

    from modules.vision import (
        VisionThread, FaceData, EmotionSmoother,
        _compute_mar, _compute_ear, _compute_brow_distance, _detect_emotion,
    )
    logger.info("Import modules/vision ...... OK")

    # Test EmotionSmoother
    smoother = EmotionSmoother(window_size=5)
    for _ in range(3):
        smoother.update("happy")
    for _ in range(2):
        smoother.update("sad")
    result = smoother.update("happy")
    assert result == "happy", f"Smoother attendu 'happy', obtenu '{result}'"
    logger.info("EmotionSmoother ............ OK")

    # Test FaceData
    fd = FaceData(x=10, y=20, w=100, h=120, cx=0.1, cy=-0.2, emotion="happy", confidence=0.85)
    assert fd.emotion == "happy"
    logger.info("FaceData dataclass ......... OK")

    logger.info("")
    logger.info("✅ DRY-RUN RÉUSSI — Tous les imports et les classes fonctionnent.")
    logger.info("   Branche une caméra et relance sans --dry-run pour tester en live.")


def test_with_camera(headless=False):
    """Lance le thread vision avec une vraie caméra."""
    import cv2
    import threading

    logger.info("=== MODE %s ===", "HEADLESS" if headless else "WEBCAM")
    logger.info("Caméra index : %d | Résolution : %dx%d | Skip : %d",
                config.CAMERA_INDEX, config.CAMERA_WIDTH, config.CAMERA_HEIGHT,
                config.VISION_SKIP_FRAMES)

    # Queue partagée
    face_q = Queue(maxsize=10)
    stop_event = threading.Event()

    # Lancer le thread vision
    vision = VisionThread(face_q, stop_event)
    vision.start()
    logger.info("Thread vision lancé, en attente de frames...")

    # Stats
    frames_received = 0
    emotions_seen = set()
    start_time = time.time()

    try:
        while True:
            # Lire la queue
            if not face_q.empty():
                face: FaceData = face_q.get()
                frames_received += 1
                emotions_seen.add(face.emotion)

                # Log toutes les 10 détections
                if frames_received % 10 == 0 or frames_received <= 3:
                    logger.info(
                        "Face #%04d | pos=(%d,%d) %dx%d | centre=(%.2f, %.2f) | "
                        "émotion=%s (%.0f%%) | FPS=%.1f",
                        frames_received,
                        face.x, face.y, face.w, face.h,
                        face.cx, face.cy,
                        face.emotion, face.confidence * 100,
                        vision.fps,
                    )

            # Affichage fenêtre (mode webcam uniquement)
            if not headless and vision.last_frame is not None:
                frame = vision.last_frame.copy()

                # Ajouter infos en overlay
                info_lines = [
                    f"FPS: {vision.fps:.1f}",
                    f"Detections: {frames_received}",
                    f"Emotions vues: {', '.join(sorted(emotions_seen)) or 'aucune'}",
                ]
                for i, line in enumerate(info_lines):
                    cv2.putText(frame, line, (10, 25 + i * 25),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

                cv2.imshow("Baymax Vision Test — appuie 'q' pour quitter", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    logger.info("Touche 'q' détectée, arrêt...")
                    break

            # Mode headless : arrêter après 30 secondes
            if headless and (time.time() - start_time) > 30:
                logger.info("30 secondes écoulées, arrêt mode headless...")
                break

            time.sleep(0.01)

    except KeyboardInterrupt:
        logger.info("Ctrl+C détecté, arrêt...")

    finally:
        stop_event.set()
        vision.join(timeout=3)
        if not headless:
            cv2.destroyAllWindows()

    # --- Rapport final ---
    elapsed = time.time() - start_time
    logger.info("")
    logger.info("=" * 50)
    logger.info("RAPPORT DE TEST")
    logger.info("=" * 50)
    logger.info("Durée totale      : %.1f s", elapsed)
    logger.info("Frames détectés   : %d", frames_received)
    logger.info("FPS moyen vision  : %.1f", vision.fps)
    logger.info("Émotions détectées: %s", ", ".join(sorted(emotions_seen)) or "aucune")
    logger.info("")

    if frames_received > 0:
        logger.info("✅ TEST RÉUSSI — La détection de visage fonctionne.")
        if "happy" in emotions_seen or "sad" in emotions_seen or "pain" in emotions_seen:
            logger.info("✅ BONUS — Des émotions non-neutres ont été détectées !")
        else:
            logger.info("ℹ️  Seule l'émotion 'neutral' a été vue. Normal si tu es resté neutre.")
            logger.info("   Essaie de sourire largement ou de faire une grimace pour tester.")
    else:
        logger.warning("⚠️  Aucun visage détecté. Vérifie :")
        logger.warning("   - La caméra est branchée et non utilisée par un autre programme")
        logger.warning("   - Tu es face à la caméra avec un éclairage correct")
        logger.warning("   - config.CAMERA_INDEX est le bon index (essaie 0, 1, 2)")


def main():
    parser = argparse.ArgumentParser(description="Test Phase 2 — Vision Baymax")
    parser.add_argument("--dry-run", action="store_true",
                        help="Vérifie les imports sans caméra")
    parser.add_argument("--headless", action="store_true",
                        help="Mode sans affichage (terminal uniquement, 30 s)")
    parser.add_argument("--camera", type=int, default=None,
                        help="Index caméra (override config.CAMERA_INDEX)")
    parser.add_argument("--skip", type=int, default=None,
                        help="Skip frames (override config.VISION_SKIP_FRAMES)")
    args = parser.parse_args()

    # Overrides en ligne de commande
    if args.camera is not None:
        config.CAMERA_INDEX = args.camera
    if args.skip is not None:
        config.VISION_SKIP_FRAMES = args.skip

    if args.dry_run:
        test_dry_run()
    else:
        test_with_camera(headless=args.headless)


if __name__ == "__main__":
    main()
