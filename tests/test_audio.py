# tests/test_audio.py - Tests Phase 8.3 reste : TTS + filtre robot
# Tests live (necessite haut-parleur).
# Usage : python tests/test_audio.py

import argparse
import logging
import sys
import time
from pathlib import Path
from queue import Queue
import threading

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_audio")


def test_imports():
    logger.info("--- Test imports ---")
    from modules.audio import AudioThread, _apply_robot_filter
    import pyttsx3
    import sounddevice as sd
    from scipy.signal import butter
    import numpy as np
    logger.info("Imports OK (pyttsx3, sounddevice, scipy, numpy, audio)")


def test_french_voice_available():
    logger.info("--- Test voix francaise disponible ---")
    import pyttsx3
    e = pyttsx3.init()
    voices = e.getProperty("voices")
    fr_voices = [v for v in voices
                 if "fr" in str(v.languages).lower() or "french" in v.name.lower()]
    if not fr_voices:
        logger.error("Aucune voix francaise trouvee !")
        for v in voices:
            logger.info("  Disponible : %s (%s)", v.name, v.languages)
        raise AssertionError("Pas de voix francaise installee sur ce systeme")

    logger.info("%d voix francaise(s) detectee(s) :", len(fr_voices))
    for v in fr_voices:
        logger.info("  - %s", v.name)


def test_robot_filter():
    logger.info("--- Test filtre robot (synthese sans audio) ---")
    import numpy as np
    from modules.audio import _apply_robot_filter

    # Genere un signal test (sinusoide 440Hz, 1s a 22050Hz)
    sample_rate = 22050
    duration = 1.0
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    audio = np.sin(2 * np.pi * 440 * t).astype(np.float32)

    filtered = _apply_robot_filter(audio, sample_rate)
    assert filtered.shape == audio.shape, "Le filtre doit conserver la forme"
    assert filtered.dtype == np.float32, "Le filtre doit retourner float32"
    assert np.abs(filtered).max() <= 1.0, "Le filtre ne doit pas saturer hors [-1, 1]"
    logger.info("Filtre robot OK (in=%s out=%s, max=%.3f)",
                audio.shape, filtered.shape, np.abs(filtered).max())


def test_tts_live():
    logger.info("--- Test live : WALL-E parle (avec filtre robot) ---")
    logger.info("Attention : doit etre lance avec un haut-parleur actif")

    from modules.audio import AudioThread

    audio_q = Queue()
    stop = threading.Event()
    at = AudioThread(audio_q=audio_q, stop_event=stop, robot_filter=True)
    at.start()

    # Donner du temps pour init du moteur TTS
    time.sleep(0.5)

    phrases = [
        "Salut, je suis Wall-E.",
        "Aujourd'hui je teste ma voix robot.",
        "Coucou ! Ca va ?",
    ]
    for p in phrases:
        logger.info(">>> %s", p)
        audio_q.put(p)

    # Attendre que la queue soit vidée
    while not audio_q.empty():
        time.sleep(0.5)
    time.sleep(2)  # laisse finir la derniere phrase

    stop.set()
    at.join(timeout=3)
    logger.info("Test TTS live termine")


def test_tts_no_filter():
    logger.info("--- Test live : WALL-E sans filtre (voix Hortense brute) ---")
    from modules.audio import AudioThread

    audio_q = Queue()
    stop = threading.Event()
    at = AudioThread(audio_q=audio_q, stop_event=stop, robot_filter=False)
    at.start()
    time.sleep(0.5)

    audio_q.put("Voici Hortense sans aucun filtre, ma voix d'origine.")

    while not audio_q.empty():
        time.sleep(0.5)
    time.sleep(2)

    stop.set()
    at.join(timeout=3)
    logger.info("Test sans filtre termine")


def main():
    parser = argparse.ArgumentParser(description="Tests audio Phase 8.3 reste")
    parser.add_argument("--dry-run", action="store_true",
                        help="Tests sans audio (imports, voix dispo, filtre)")
    parser.add_argument("--live", action="store_true",
                        help="Test TTS live avec haut-parleur")
    parser.add_argument("--no-filter", action="store_true",
                        help="Test live SANS filtre robot (voix brute)")
    args = parser.parse_args()

    if not any([args.dry_run, args.live, args.no_filter]):
        parser.print_help()
        return

    if args.dry_run:
        test_imports()
        test_french_voice_available()
        test_robot_filter()
        logger.info("=== TESTS DRY-RUN PASSES ===")

    if args.live:
        test_tts_live()

    if args.no_filter:
        test_tts_no_filter()


if __name__ == "__main__":
    main()
