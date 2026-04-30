#!/usr/bin/env python3
# walle.py - Orchestrateur WALL-E
# v2.0 : backend Ollama 100% offline + STT
# v2.1 : pseudonymisation - default user lu dynamiquement
# v2.3 : Phase 8.4 - lance VisionThread et branche face_q sur le brain

import argparse
import logging
import threading
from queue import Queue, Empty

from dotenv import load_dotenv
load_dotenv()

import config

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(name)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("walle")

from brain.agent import BrainThread
from brain.identity import Identity, parse_prefix


def print_welcome(current_user, stt_enabled, vision_enabled):
    print()
    print("=" * 60)
    title = "  WALL-E reveille - v2.3 (Ollama offline, multi-user)"
    if stt_enabled:
        title += " + STT"
    if vision_enabled:
        title += " + Vision"
    print(title)
    print(f"  Backend : {config.LLM_BACKEND} / {config.OLLAMA_MODEL}")
    print(f"  Host    : {config.OLLAMA_HOST}")
    age_str = f", {current_user.age} ans" if current_user.age else ""
    print(f"  Locuteur courant : {current_user.display_name} ({current_user.role}{age_str})")
    print()
    print("  Commandes (clavier) :")
    print("    [user_id] bonjour...   changer de locuteur et continuer la phrase")
    print("    /who                   qui parle actuellement ?")
    print("    /users                 liste des users connus")
    print("    /reset                 efface la conv du locuteur courant")
    print("    /quit, Ctrl+C          sortir")
    if stt_enabled:
        print("  Micro actif : tu peux aussi parler (FR, pause ~1s pour valider)")
    if vision_enabled:
        print("  Camera active : WALL-E adapte son ton selon ton expression")
    print("=" * 60)
    print()


def keyboard_worker(user_in_q, stop_event):
    while not stop_event.is_set():
        try:
            line = input()
        except EOFError:
            break
        line = line.strip()
        if line:
            try:
                user_in_q.put_nowait(("keyboard", line))
            except Exception:
                pass


def main():
    default_user = getattr(config, "DEFAULT_USER", "parent_1")

    parser = argparse.ArgumentParser(description="WALL-E v2.3 multi-user + STT + Vision")
    parser.add_argument("--user", type=str, default=default_user,
                        help=f"Locuteur par defaut (defaut : {default_user})")
    parser.add_argument("--no-stt", action="store_true",
                        help="Desactive le STT meme si config.STT_ENABLED=True")
    parser.add_argument("--no-vision", action="store_true",
                        help="Desactive la vision (camera + emotion)")
    args = parser.parse_args()

    current_identity = Identity.from_user_id(args.user)
    if current_identity.user_id == "unknown":
        first_user = next(iter(config.USERS.keys()), default_user)
        print(f"ATTENTION : user '{args.user}' inconnu, fallback sur '{first_user}'")
        current_identity = Identity.from_user_id(first_user)

    brain_in_q = Queue(maxsize=20)
    brain_out_q = Queue(maxsize=20)
    user_in_q = Queue(maxsize=20)
    face_q = Queue(maxsize=20)                  # v2.3 Phase 8.4
    stop_event = threading.Event()

    # === VisionThread (Phase 2 + Phase 8.4) ===
    vision_thread = None
    vision_enabled = not args.no_vision
    if vision_enabled:
        try:
            from modules.vision import VisionThread
            vision_thread = VisionThread(
                face_q=face_q,
                stop_event=stop_event,
            )
            vision_thread.start()
            logger.info("VisionThread demarre")
        except Exception as e:
            logger.error(f"VisionThread non demarre : {e}")
            vision_enabled = False
            face_q = None  # Pas de face_q si pas de vision

    # === BrainThread ===
    brain = BrainThread(brain_in_q, brain_out_q, stop_event,
                        face_q=face_q)         # v2.3 : passe face_q
    brain.start()

    # === STT ===
    stt_thread = None
    stt_enabled = config.STT_ENABLED and not args.no_stt
    if stt_enabled:
        try:
            from modules.stt import STTThread
            stt_thread = STTThread(
                out_q=user_in_q,
                stop_event=stop_event,
                language=config.STT_LANGUAGE,
                sample_rate=config.STT_SAMPLE_RATE,
                device=config.STT_DEVICE,
                silence_threshold=config.STT_SILENCE_THRESHOLD,
                silence_duration=config.STT_SILENCE_DURATION,
                max_phrase_duration=config.STT_MAX_PHRASE,
            )
            stt_thread.start()
        except Exception as e:
            logger.error(f"STT non demarre : {e}")
            stt_enabled = False

    # === Clavier ===
    kb_thread = threading.Thread(
        target=keyboard_worker, args=(user_in_q, stop_event),
        daemon=True, name="KeyboardThread",
    )
    kb_thread.start()

    print_welcome(current_identity, stt_enabled, vision_enabled)

    try:
        while not stop_event.is_set():
            try:
                source, line = user_in_q.get(timeout=0.5)
            except Empty:
                continue

            label = "[voix]" if source == "voice" else "[clavier]"
            print(f"\n{current_identity.display_name} {label} > {line}")

            low = line.lower()
            if low in ("/quit", "/exit", "/q"):
                break
            if low == "/who":
                age_str = f", {current_identity.age} ans" if current_identity.age else ""
                print(f"  -> {current_identity.display_name} ({current_identity.user_id}, "
                      f"{current_identity.role}{age_str})")
                continue
            if low == "/users":
                for uid, info in config.USERS.items():
                    print(f"  - [{uid}] {info['display_name']} ({info['role']})")
                print("  - [unknown] voix non identifiee")
                continue
            if low == "/reset":
                brain.reset_history(current_identity.user_id)
                print(f"  -> conv de {current_identity.display_name} reinitialisee")
                continue

            prefix_user, clean_text = parse_prefix(line)
            if prefix_user:
                new_identity = Identity.from_user_id(prefix_user)
                if new_identity.user_id == "unknown" and prefix_user != "unknown":
                    print(f"  -> [{prefix_user}] inconnu, traite comme voix non identifiee")
                current_identity = new_identity
                line = clean_text
                if not line:
                    age_str = f", {current_identity.age} ans" if current_identity.age else ""
                    print(f"  -> locuteur courant : {current_identity.display_name}{age_str}")
                    continue

            brain_in_q.put((current_identity.user_id, line))
            reply_uid, reply = brain_out_q.get()
            print(f"\nWALL-E > {reply}\n")

    except KeyboardInterrupt:
        print("\n[Ctrl+C]")

    print("Arret en cours...")
    stop_event.set()
    brain.join(timeout=3)
    if stt_thread:
        stt_thread.join(timeout=3)
    if vision_thread:
        vision_thread.join(timeout=3)
    print("A bientot !")


if __name__ == "__main__":
    main()
