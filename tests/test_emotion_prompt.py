# tests/test_emotion_prompt.py - Tests Phase 8.4 (emotion injectee dans prompt)
# Mock de FaceData pour tester sans camera physique.

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_emotion")


@dataclass
class MockFaceData:
    """Mimique FaceData de modules/vision.py pour les tests."""
    emotion: str
    confidence: float


def _pick_parent_id():
    import config
    for uid, info in config.USERS.items():
        if info["role"] == "parent":
            return uid
    raise RuntimeError("Aucun parent")


def _pick_child_id():
    import config
    for uid, info in config.USERS.items():
        if info["role"] == "child":
            return uid
    raise RuntimeError("Aucun enfant")


def test_no_emotion_no_block():
    """Sans emotion fournie, le prompt ne doit pas contenir de bloc emotion."""
    logger.info("--- Test : pas d'emotion -> pas de bloc ---")
    from brain.identity import Identity
    from brain.prompts import build_system_prompt

    parent = Identity.from_user_id(_pick_parent_id())
    sys_prompt = build_system_prompt(
        parent, "save_memory, search_memory", [], [],
        emotion_data=None,
    )
    assert "EMOTION DETECTEE" not in sys_prompt, \
        "Pas d'emotion -> pas de bloc EMOTION_CONTEXT"
    logger.info("Sans emotion -> bloc absent ... OK")


def test_emotion_happy_block():
    """Avec emotion happy, le prompt doit contenir l'instruction enjoue."""
    logger.info("--- Test : emotion happy ---")
    from brain.identity import Identity
    from brain.prompts import build_system_prompt

    parent = Identity.from_user_id(_pick_parent_id())
    face = MockFaceData(emotion="happy", confidence=0.85)
    sys_prompt = build_system_prompt(
        parent, "save_memory", [], [],
        emotion_data=face,
    )
    assert "EMOTION DETECTEE" in sys_prompt, "Bloc emotion present"
    assert "happy" in sys_prompt, "Label emotion happy present"
    assert "85%" in sys_prompt, "Confidence affichee"
    assert "enjoue" in sys_prompt or "complice" in sys_prompt, "Instruction ton happy"
    logger.info("Emotion happy ............... OK")


def test_emotion_sad_block():
    """Avec emotion sad, le prompt doit contenir l'instruction doux."""
    logger.info("--- Test : emotion sad ---")
    from brain.identity import Identity
    from brain.prompts import build_system_prompt

    child = Identity.from_user_id(_pick_child_id())
    face = MockFaceData(emotion="sad", confidence=0.75)
    sys_prompt = build_system_prompt(
        child, "save_memory", [], [],
        emotion_data=face,
    )
    assert "EMOTION DETECTEE" in sys_prompt
    assert "sad" in sys_prompt
    assert "doux" in sys_prompt or "chaleureux" in sys_prompt
    assert "Pas de blagues" in sys_prompt
    # Le display_name de l'enfant doit etre dans l'instruction
    assert child.display_name in sys_prompt
    logger.info("Emotion sad ................. OK")


def test_emotion_pain_block():
    logger.info("--- Test : emotion pain ---")
    from brain.identity import Identity
    from brain.prompts import build_system_prompt

    parent = Identity.from_user_id(_pick_parent_id())
    face = MockFaceData(emotion="pain", confidence=0.6)
    sys_prompt = build_system_prompt(
        parent, "save_memory", [], [],
        emotion_data=face,
    )
    assert "pain" in sys_prompt
    assert "concerne" in sys_prompt or "douleur" in sys_prompt
    logger.info("Emotion pain ................ OK")


def test_emotion_neutral_block():
    logger.info("--- Test : emotion neutral ---")
    from brain.identity import Identity
    from brain.prompts import build_system_prompt

    parent = Identity.from_user_id(_pick_parent_id())
    face = MockFaceData(emotion="neutral", confidence=0.9)
    sys_prompt = build_system_prompt(
        parent, "save_memory", [], [],
        emotion_data=face,
    )
    assert "neutral" in sys_prompt
    assert "nominal" in sys_prompt
    logger.info("Emotion neutral ............. OK")


def test_low_confidence_treated_as_neutral():
    """Si confidence < 0.4, l'emotion est traitee comme neutral."""
    logger.info("--- Test : confidence basse -> neutral ---")
    from brain.identity import Identity
    from brain.prompts import build_system_prompt

    parent = Identity.from_user_id(_pick_parent_id())
    face = MockFaceData(emotion="happy", confidence=0.20)  # confiance basse
    sys_prompt = build_system_prompt(
        parent, "save_memory", [], [],
        emotion_data=face,
    )
    assert "nominal" in sys_prompt, "Confidence basse -> traitement neutral"
    logger.info("Confidence basse -> neutral . OK")


def test_unknown_emotion_fallback():
    """Une emotion inconnue ne doit pas crasher, fallback neutral."""
    logger.info("--- Test : emotion inconnue -> fallback ---")
    from brain.identity import Identity
    from brain.prompts import build_system_prompt

    parent = Identity.from_user_id(_pick_parent_id())
    face = MockFaceData(emotion="surprised", confidence=0.8)  # pas dans EMOTION_TONE_INSTRUCTIONS
    sys_prompt = build_system_prompt(
        parent, "save_memory", [], [],
        emotion_data=face,
    )
    # Pas de crash, et fallback sur neutral
    assert "EMOTION DETECTEE" in sys_prompt
    assert "nominal" in sys_prompt
    logger.info("Emotion inconnue ............ OK (fallback neutral)")


def test_get_latest_face_helper():
    """Le helper _get_latest_face draine la queue et garde la derniere FaceData."""
    logger.info("--- Test : helper _get_latest_face ---")
    from queue import Queue
    from brain.agent import _get_latest_face

    q = Queue()
    # Cas 1 : queue vide -> None
    assert _get_latest_face(q) is None
    logger.info("Queue vide -> None .......... OK")

    # Cas 2 : queue None -> None
    assert _get_latest_face(None) is None
    logger.info("Queue None -> None .......... OK")

    # Cas 3 : plusieurs items -> garde le dernier
    q.put(MockFaceData(emotion="neutral", confidence=0.5))
    q.put(MockFaceData(emotion="happy", confidence=0.7))
    q.put(MockFaceData(emotion="sad", confidence=0.9))
    last = _get_latest_face(q)
    assert last.emotion == "sad", f"Doit garder le dernier, eu {last.emotion}"
    assert q.qsize() == 0, "Queue doit etre videe"
    logger.info("Drain et dernier item ....... OK")


def main():
    parser = argparse.ArgumentParser(description="Tests Phase 8.4 emotion prompt")
    args = parser.parse_args()

    test_no_emotion_no_block()
    test_emotion_happy_block()
    test_emotion_sad_block()
    test_emotion_pain_block()
    test_emotion_neutral_block()
    test_low_confidence_treated_as_neutral()
    test_unknown_emotion_fallback()
    test_get_latest_face_helper()

    logger.info("=== TOUS LES TESTS PHASE 8.4 PASSES ===")


if __name__ == "__main__":
    main()
