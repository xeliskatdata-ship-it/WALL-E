#!/usr/bin/env python3
# walle.py - Orchestrateur WALL-E
# Phase 8.1 multi-user + Phase 8.3 partielle (STT Windows avant deploiement Pi 5)
# user_in_q unifie clavier + micro : source = "keyboard" ou "voice"

import argparse
import logging
import threading
from queue import Queue, Empty

from dotenv import load_dotenv
load_dotenv()

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("walle")

from brain.agent import BrainThread
from brain.identity import Identity, parse_prefix


def print_welcome(current_user, stt_enabled):
    print()
    print("=" * 60)
    title = "  WALL-E reveille - Phase 8.1 (texte, multi-user)"
    if stt_enabled:
        title += " + STT"
    print(title)
    print(f"  Backend : {config.LLM_BACKEND} / {config.ANTHROPIC_MODEL}")
    age_str = f", {current_user.age} ans" if current_user.age else ""
    print(f"  Locuteur courant : {current_user.display_name} ({current_user.role}{age_str})")
    print()
    print("  Commandes (clavier) :")
    print("    [prenom] bonjour...    changer de locuteur et continuer la phrase")
    print("    /who                   qui parle actuellement ?")
    print("    /users                 liste des users connus")
    print("    /reset                 efface la conv du locuteur courant")
    print("    /quit, Ctrl+C          sortir")
    if stt_enabled:
        print("  Micro actif : tu peux aussi parler (FR, pause ~1s pour valider)")
    print("=" * 60)
    print()


def keyboard_worker(user_in_q, stop_event):
    # Thread clavier : input() en boucle -> push ("keyboard", text) dans user_in_q
    # Daemon : meurt avec le main, pas besoin de stop propre
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
    parser = argparse.ArgumentParser(description="WALL-E Phase 8.1 multi-user + STT")
    parser.add_argument(
        "--user", type=str, default="kat",
        help="Locuteur par defaut au demarrage (kat, brice, louis, william, raphael, ambre)",
    )
    parser.add_argument(
        "--no-stt", action="store_true",
        help="Desactive le STT meme si config.STT_ENABLED=True (mode clavier pur)",
    )
    args = parser.parse_args()

    current_identity = Identity.from_user_id(args.user)
    if current_identity.user_id == "unknown":
        print(f"ATTENTION : user '{args.user}' inconnu, fallback sur 'kat'")
        current_identity = Identity.from_user_id("kat")

    brain_in_q = Queue(maxsize=20)
    brain_out_q = Queue(maxsize=20)
    user_in_q = Queue(maxsize=20)   # Unifie clavier + micro
    stop_event = threading.Event()

    # Brain
    brain = BrainThread(brain_in_q, brain_out_q, stop_event)
    brain.start()

    # STT optionnel : fallback gracieux si sounddevice / micro indispo
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

    # Clavier toujours actif (meme quand STT marche, fallback tapage)
    kb_thread = threading.Thread(
        target=keyboard_worker, args=(user_in_q, stop_event),
        daemon=True, name="KeyboardThread",
    )
    kb_thread.start()

    print_welcome(current_identity, stt_enabled)

    try:
        while not stop_event.is_set():
            # Attente entree (clavier ou voix), timeout pour check stop
            try:
                source, line = user_in_q.get(timeout=0.5)
            except Empty:
                continue

            # Affichage de l'entree avec sa source
            label = "[voix]" if source == "voice" else "[clavier]"
            print(f"\n{current_identity.display_name} {label} > {line}")

            # Commandes slash (marchent surtout au clavier, Google ne transcrit pas "/")
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
                print("  - [unknown] voix non identifiee (aucun outil, aucune memoire)")
                continue
            if low == "/reset":
                brain.reset_history(current_identity.user_id)
                print(f"  -> conv de {current_identity.display_name} reinitialisee "
                      f"(memoire long terme preservee)")
                continue

            # Prefix [prenom] pour switch locuteur (fonctionne en clavier)
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

            # Envoi au brain (tuple protocole) et attente reponse bloquante
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
    print("A bientot !")


if __name__ == "__main__":
    main()
