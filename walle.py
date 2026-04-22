#!/usr/bin/env python3
# walle.py - Orchestrateur principal WALL-E
# Phase 8.1 multi-user : text-only, identification par --user ou prefix [nom]
# Phase 8.3 : remplacera le prefix par reconnaissance vocale Resemblyzer

import argparse
import logging
import threading
from queue import Queue

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


def print_welcome(current_user):
    print()
    print("=" * 60)
    print("  WALL-E reveille - Phase 8.1 (texte, multi-user)")
    print(f"  Backend : {config.LLM_BACKEND} / {config.ANTHROPIC_MODEL}")
    print(f"  Locuteur courant : {current_user.display_name} "
          f"({current_user.role}, {current_user.age} ans)"
          if current_user.age else
          f"  Locuteur courant : {current_user.display_name} ({current_user.role})")
    print()
    print("  Commandes :")
    print("    [prenom] bonjour...    changer de locuteur et continuer la phrase")
    print("    /who                   qui parle actuellement ?")
    print("    /users                 liste des users connus")
    print("    /reset                 efface la conv du locuteur courant")
    print("    /quit, Ctrl+C          sortir")
    print("=" * 60)
    print()


def main():
    parser = argparse.ArgumentParser(description="WALL-E Phase 8.1 multi-user")
    parser.add_argument(
        "--user", type=str, default="kat",
        help="Locuteur par defaut au demarrage (kat, brice, louis, william, raphael, ambre)",
    )
    args = parser.parse_args()

    current_identity = Identity.from_user_id(args.user)
    if current_identity.user_id == "unknown":
        print(f"ATTENTION : user '{args.user}' inconnu, fallback sur 'kat'")
        current_identity = Identity.from_user_id("kat")

    brain_in_q = Queue(maxsize=20)
    brain_out_q = Queue(maxsize=20)
    stop_event = threading.Event()

    brain = BrainThread(brain_in_q, brain_out_q, stop_event)
    brain.start()

    print_welcome(current_identity)

    try:
        while not stop_event.is_set():
            try:
                line = input(f"{current_identity.display_name} > ").strip()
            except EOFError:
                break

            if not line:
                continue

            # Commandes slash
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

            # Prefix [prenom] pour switch de locuteur
            prefix_user, clean_text = parse_prefix(line)
            if prefix_user:
                new_identity = Identity.from_user_id(prefix_user)
                if new_identity.user_id == "unknown" and prefix_user != "unknown":
                    print(f"  -> [{prefix_user}] inconnu, traite comme voix non identifiee")
                current_identity = new_identity
                line = clean_text
                if not line:
                    # Switch sans phrase : on confirme et on attend le prochain input
                    age_str = f", {current_identity.age} ans" if current_identity.age else ""
                    print(f"  -> locuteur courant : {current_identity.display_name}{age_str}")
                    continue

            # Envoi dans brain_in_q et attente de la reponse (bloquant)
            brain_in_q.put((current_identity.user_id, line))
            reply_uid, reply = brain_out_q.get()
            print(f"\nWALL-E > {reply}\n")

    except KeyboardInterrupt:
        print("\n[Ctrl+C]")

    print("Arret en cours...")
    stop_event.set()
    brain.join(timeout=3)
    print("A bientot !")


if __name__ == "__main__":
    main()
