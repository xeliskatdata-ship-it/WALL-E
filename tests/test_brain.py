#!/usr/bin/env python3
# tests/test_brain.py - Test Phase 8.1 multi-user modele B
#
# Usage :
#   python tests/test_brain.py --dry-run   imports + Identity + ACL + cloisonnement memoire
#   python tests/test_brain.py --simulate  mock LLM (a implementer Phase 8.5)
#   python tests/test_brain.py --text      conversation reelle (requiert ANTHROPIC_API_KEY)

import sys
import os
import argparse
import logging
import tempfile
import shutil
import threading
from queue import Queue

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_brain")


def test_dry_run():
    logger.info("=== MODE DRY-RUN (modele B : famille ouverte + intimite couple) ===")

    # --- Imports ---
    from brain.identity import Identity, parse_prefix
    logger.info("Import brain/identity ........ OK")

    from brain.prompts import BASE_PERSONA, OVERLAYS, build_system_prompt
    logger.info("Import brain/prompts ......... OK")

    from brain.tools import TOOLS_ALL, filter_tools_for, describe_tools
    logger.info("Import brain/tools ........... OK")

    from brain.agent import BrainThread
    logger.info("Import brain/agent ........... OK")

    # --- Verifier que tous les users ont un overlay ---
    for uid in config.USERS:
        assert uid in OVERLAYS, f"Overlay manquant pour {uid}"
    assert "unknown" in OVERLAYS, "Overlay 'unknown' manquant"
    logger.info("Overlays persona ............. OK (%d users + unknown)", len(config.USERS))

    # --- Identity : Parents ont search_child_memory, enfants non ---
    kat = Identity.from_user_id("kat")
    assert kat.role == "parent"
    assert kat.age > 40
    assert "web_search" in kat.tools_allowed
    assert "search_child_memory" in kat.tools_allowed, "Modele B : parents doivent avoir search_child_memory"
    assert kat.can_write_family is True
    assert kat.is_parent() is True
    logger.info("Identity Kat ................. OK (%d ans, %d outils, parent, family+)",
                kat.age, len(kat.tools_allowed))

    brice = Identity.from_user_id("brice")
    assert "search_child_memory" in brice.tools_allowed
    logger.info("Identity Brice ............... OK (%d ans, parent, search_child_memory+)", brice.age)

    ambre = Identity.from_user_id("ambre")
    assert ambre.role == "child"
    assert "web_search" not in ambre.tools_allowed
    assert "search_child_memory" not in ambre.tools_allowed, "Enfants ne doivent PAS avoir search_child_memory"
    assert "save_memory" in ambre.tools_allowed
    assert ambre.can_write_family is False
    assert ambre.is_parent() is False
    logger.info("Identity Ambre ............... OK (%d ans, %d outils, child, family-)",
                ambre.age, len(ambre.tools_allowed))

    santa = Identity.from_user_id("santa")
    assert santa.user_id == "unknown"
    assert len(santa.tools_allowed) == 0
    logger.info("Identity inconnu ............. OK (0 outil)")

    # --- parse_prefix ---
    uid, text = parse_prefix("[ambre] coucou WALL-E")
    assert uid == "ambre" and text == "coucou WALL-E"
    uid, text = parse_prefix("[KAT] majuscules")
    assert uid == "kat"
    uid, text = parse_prefix("pas de prefix")
    assert uid is None
    logger.info("parse_prefix ................. OK")

    # --- build_system_prompt : verifie les contenus specifiques au modele B ---
    sys_prompt_kat = build_system_prompt(kat, "save_memory, search_memory, web_search, search_child_memory", [], [])
    assert "search_child_memory" in sys_prompt_kat, "Prompt Kat doit mentionner search_child_memory"
    assert "modele famille ouverte" in sys_prompt_kat, "Prompt Kat doit expliquer l'acces enfants"
    assert "Intimite couple" in sys_prompt_kat, "Prompt Kat doit mentionner l'intimite du couple"
    assert "GARDE-FOUS" not in sys_prompt_kat
    logger.info("Prompt Kat (parent) .......... OK (%d chars, search_child + intimite OK)",
                len(sys_prompt_kat))

    sys_prompt_ambre = build_system_prompt(ambre, "save_memory, search_memory", [], [])
    assert "Ambre" in sys_prompt_ambre
    assert "10 ans" in sys_prompt_ambre
    assert "GARDE-FOUS" in sys_prompt_ambre, "Prompt Ambre doit contenir les garde-fous mineurs"
    assert "DETRESSE" in sys_prompt_ambre
    assert "JAMAIS DE SECRET" in sys_prompt_ambre
    assert "TRANSPARENCE" in sys_prompt_ambre, "Prompt Ambre doit expliquer la transparence memoire"
    logger.info("Prompt Ambre (mineur) ........ OK (%d chars, transparence + garde-fous)",
                len(sys_prompt_ambre))

    # --- ACL : filter_tools_for ---
    kat_tools = filter_tools_for(kat)
    ambre_tools = filter_tools_for(ambre)
    santa_tools = filter_tools_for(santa)

    assert len(kat_tools) == 4, f"Parents doivent avoir 4 outils, Kat en a {len(kat_tools)}"
    assert len(ambre_tools) == 2, f"Enfants doivent avoir 2 outils, Ambre en a {len(ambre_tools)}"
    assert len(santa_tools) == 0
    assert any(t["name"] == "search_child_memory" for t in kat_tools)
    assert not any(t["name"] == "search_child_memory" for t in ambre_tools)
    logger.info("ACL outils ................... OK (Kat=%d | Ambre=%d | Inconnu=%d)",
                len(kat_tools), len(ambre_tools), len(santa_tools))

    # --- MemoryManager : cloisonnement ecriture + lecture parents via search_child_memory ---
    tmp = tempfile.mkdtemp(prefix="walle_test_")
    orig_path = config.CHROMA_PATH
    try:
        config.CHROMA_PATH = tmp
        import importlib
        from brain import memory as memory_module
        importlib.reload(memory_module)

        mgr = memory_module.MemoryManager()
        mgr.save_perso("kat", "Kat aime le dark mode")
        mgr.save_perso("brice", "Brice est passionne de cuisine italienne")
        mgr.save_perso("ambre", "Ambre a un chat qui s'appelle Mistigri")
        mgr.save_perso("louis", "Louis prepare son bac de francais")
        mgr.save_family("kat", "La famille part en Bretagne en juillet")

        # Cloisonnement ecriture : personne n'ecrit dans la collection d'un autre
        # (deja teste implicitement via les save_perso ci-dessus)

        # Cloisonnement lecture perso : Ambre ne voit pas la coll. de Louis
        ambre_perso = mgr.search_perso("ambre", "bac")
        for m in ambre_perso:
            assert "Louis" not in m and "bac" not in m.lower(), \
                f"Fuite memoire Louis dans perso Ambre : {m}"

        # --- Test ACL search_child_memory ---
        from brain.tools import execute_tool

        # Parent (Kat) peut lire mem_louis via search_child_memory
        r = execute_tool("search_child_memory", {"child_name": "louis", "query": "bac"},
                         identity=kat, memory_mgr=mgr)
        assert r.get("child") == "louis", f"search_child_memory Kat KO : {r}"
        assert len(r.get("results", [])) >= 1, "Kat devrait trouver la memoire de Louis"
        logger.info("Kat -> search_child_memory Louis OK (%d resultats)", r.get("count"))

        # Enfant (Ambre) refusee ACL
        r = execute_tool("search_child_memory", {"child_name": "louis", "query": "bac"},
                         identity=ambre, memory_mgr=mgr)
        assert "error" in r, f"ACL devait refuser search_child_memory pour Ambre : {r}"
        logger.info("ACL refus search_child_memory Ambre OK")

        # Parent refuse sur un enfant inexistant
        r = execute_tool("search_child_memory", {"child_name": "jeanne", "query": "test"},
                         identity=kat, memory_mgr=mgr)
        assert "error" in r, "Devrait refuser un nom d'enfant inconnu"
        logger.info("Refus child_name inconnu ..... OK")

        # Ambre refusee sur web_search
        r = execute_tool("web_search", {"query": "test"}, identity=ambre, memory_mgr=mgr)
        assert "error" in r
        logger.info("ACL refus web_search Ambre ... OK")

        # Ambre refusee sur family write
        r = execute_tool("save_memory", {"content": "test", "scope": "family"},
                         identity=ambre, memory_mgr=mgr)
        assert "error" in r
        logger.info("ACL refus family write Ambre . OK")

        # Ambre autorisee sur perso write
        r = execute_tool("save_memory", {"content": "test perso"}, identity=ambre, memory_mgr=mgr)
        assert r.get("status") == "ok"
        logger.info("ACL autorise perso Ambre ..... OK")

        logger.info("Etat final memoire : kat=%d brice=%d louis=%d ambre=%d family=%d",
                    mgr.count_perso("kat"), mgr.count_perso("brice"),
                    mgr.count_perso("louis"), mgr.count_perso("ambre"),
                    mgr.count_family())

        mgr.wipe_all()
    finally:
        config.CHROMA_PATH = orig_path
        shutil.rmtree(tmp, ignore_errors=True)

    logger.info("")
    logger.info("DRY-RUN REUSSI - modele B (famille ouverte + intimite couple) valide.")


def test_simulate():
    logger.info("=== MODE SIMULATION ===")
    logger.info("Mock LLM a implementer. Pour l'instant, valide avec --text.")


def test_text():
    logger.info("=== MODE TEXT (API Claude reelle) ===")
    logger.info("Requiert ANTHROPIC_API_KEY dans .env")
    print()

    from dotenv import load_dotenv
    load_dotenv()

    from brain.agent import BrainThread
    from brain.identity import Identity, parse_prefix

    current = Identity.from_user_id("kat")
    brain_in_q = Queue()
    brain_out_q = Queue()
    stop_event = threading.Event()

    brain = BrainThread(brain_in_q, brain_out_q, stop_event)
    brain.start()

    print(f"Locuteur : {current.display_name}. Prefix [nom] pour switch, 'quit' pour sortir.")

    try:
        while not stop_event.is_set():
            try:
                line = input(f"\n{current.display_name} > ").strip()
            except EOFError:
                break
            if line.lower() in ("quit", "q"):
                break
            if not line:
                continue

            prefix_user, clean = parse_prefix(line)
            if prefix_user:
                current = Identity.from_user_id(prefix_user)
                line = clean
                if not line:
                    print(f"  -> {current.display_name}")
                    continue

            brain_in_q.put((current.user_id, line))
            uid, reply = brain_out_q.get()
            print(f"\nWALL-E > {reply}")
    except KeyboardInterrupt:
        print()
    finally:
        stop_event.set()
        brain.join(timeout=3)


def main():
    parser = argparse.ArgumentParser(description="Test Phase 8.1 Brain multi-user modele B")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--text", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        test_dry_run()
    elif args.simulate:
        test_simulate()
    elif args.text:
        test_text()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
