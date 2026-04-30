# tests/test_brain.py - Tests Phase 8.1 + v2.0 Ollama
# v2.1 : tests refactores pour ne pas dependre des prenoms reels.
# Les tests piochent dynamiquement dans config.USERS pour selectionner
# un parent et un enfant, ce qui les rend independants du foyer configure
# dans family_local.py.

import argparse
import logging
import sys
from pathlib import Path

# Permet d'importer depuis la racine du projet
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_brain")


def _pick_parent_id() -> str:
    """Recupere le user_id du premier parent dans config.USERS."""
    import config
    for uid, info in config.USERS.items():
        if info["role"] == "parent":
            return uid
    raise RuntimeError("Aucun parent dans config.USERS - tests impossibles")


def _pick_child_id() -> str:
    """Recupere le user_id du premier enfant dans config.USERS."""
    import config
    for uid, info in config.USERS.items():
        if info["role"] == "child":
            return uid
    raise RuntimeError("Aucun enfant dans config.USERS - tests impossibles")


def _pick_second_child_id() -> str:
    """Recupere le user_id du second enfant (pour tests cloisonnement)."""
    import config
    children = [uid for uid, info in config.USERS.items() if info["role"] == "child"]
    if len(children) < 2:
        return children[0]
    return children[1]


def _pick_second_parent_id() -> str:
    """Recupere le user_id du second parent."""
    import config
    parents = [uid for uid, info in config.USERS.items() if info["role"] == "parent"]
    if len(parents) < 2:
        return parents[0]
    return parents[1]


# === TESTS DRY-RUN (pas d'appel LLM, pas de hardware) ===

def test_imports():
    logger.info("--- Test imports ---")
    from brain.identity import Identity, parse_prefix
    from brain.memory import MemoryManager
    from brain.tools import TOOLS_ALL, filter_tools_for, execute_tool
    from brain.prompts import build_system_prompt
    from brain.agent import BrainThread
    from brain.llm_client import OllamaClient
    logger.info("Imports OK (identity, memory, tools, prompts, agent, llm_client)")


def test_identity():
    logger.info("--- Test Identity + ACL ---")
    from brain.identity import Identity, parse_prefix

    parent_id = _pick_parent_id()
    child_id = _pick_child_id()

    # Test parent
    p = Identity.from_user_id(parent_id)
    assert p.role == "parent"
    assert p.age and p.age > 0
    assert "search_child_memory" in p.tools_allowed, "Parents doivent avoir search_child_memory"
    assert "save_memory" in p.tools_allowed
    assert p.can_write_family is True
    assert p.is_parent() is True
    logger.info("Identity parent (%s) ......... OK (%d ans, %d outils, family+)",
                p.user_id, p.age, len(p.tools_allowed))

    # Test second parent (intimite couple)
    parent2_id = _pick_second_parent_id()
    p2 = Identity.from_user_id(parent2_id)
    assert "search_child_memory" in p2.tools_allowed
    logger.info("Identity parent2 (%s) ........ OK (%d ans)", p2.user_id, p2.age)

    # Test enfant
    c = Identity.from_user_id(child_id)
    assert c.role == "child"
    assert "search_child_memory" not in c.tools_allowed, "Enfants ne doivent PAS avoir search_child_memory"
    assert "save_memory" in c.tools_allowed
    assert c.can_write_family is False
    assert c.is_parent() is False
    logger.info("Identity enfant (%s) ......... OK (%d ans, %d outils, child, family-)",
                c.user_id, c.age, len(c.tools_allowed))

    # Test unknown
    u = Identity.unknown()
    assert u.role == "unknown"
    assert len(u.tools_allowed) == 0
    logger.info("Identity unknown ............. OK (aucun outil)")

    # Test parse_prefix dynamique
    uid, text = parse_prefix(f"[{child_id}] coucou WALL-E")
    assert uid == child_id and text == "coucou WALL-E"
    uid, text = parse_prefix(f"[{parent_id.upper()}] majuscules")
    assert uid == parent_id
    uid, text = parse_prefix("pas de prefix")
    assert uid is None and text == "pas de prefix"
    logger.info("parse_prefix ................. OK")


def test_prompts():
    logger.info("--- Test prompts ---")
    from brain.identity import Identity
    from brain.prompts import build_system_prompt

    parent_id = _pick_parent_id()
    child_id = _pick_child_id()

    p = Identity.from_user_id(parent_id)
    c = Identity.from_user_id(child_id)

    # Prompt parent : doit contenir search_child_memory + intimite
    sys_prompt_p = build_system_prompt(p, "save_memory, search_memory, search_child_memory", [], [])
    assert "search_child_memory" in sys_prompt_p, "Prompt parent doit mentionner search_child_memory"
    assert "GARDE-FOUS" not in sys_prompt_p, "Prompt parent ne doit pas avoir les garde-fous mineurs"
    logger.info("Prompt parent ................ OK (%d chars)", len(sys_prompt_p))

    # Prompt enfant : doit contenir GARDE-FOUS + display_name
    sys_prompt_c = build_system_prompt(c, "save_memory, search_memory", [], [])
    assert c.display_name in sys_prompt_c, f"Prompt enfant doit mentionner '{c.display_name}'"
    assert "GARDE-FOUS" in sys_prompt_c, "Prompt enfant doit contenir les garde-fous mineurs"
    assert "DETRESSE" in sys_prompt_c
    assert "JAMAIS DE SECRET" in sys_prompt_c
    logger.info("Prompt enfant ................ OK (%d chars, garde-fous + display_name)",
                len(sys_prompt_c))


def test_tools_acl():
    logger.info("--- Test ACL outils ---")
    from brain.identity import Identity
    from brain.tools import filter_tools_for

    p = Identity.from_user_id(_pick_parent_id())
    c = Identity.from_user_id(_pick_child_id())
    u = Identity.unknown()

    p_tools = filter_tools_for(p)
    c_tools = filter_tools_for(c)
    u_tools = filter_tools_for(u)

    # En v2.0 : 3 outils pour parents (web_search retire), 2 pour enfants, 0 pour unknown
    assert len(p_tools) == 3, f"Parents doivent avoir 3 outils, en a {len(p_tools)}"
    assert len(c_tools) == 2, f"Enfants doivent avoir 2 outils, en a {len(c_tools)}"
    assert len(u_tools) == 0
    assert any(t["name"] == "search_child_memory" for t in p_tools)
    assert not any(t["name"] == "search_child_memory" for t in c_tools)
    logger.info("ACL outils ................... OK (parent=%d | enfant=%d | unknown=%d)",
                len(p_tools), len(c_tools), len(u_tools))


def test_memory():
    logger.info("--- Test memoire (RAM, pas de Chroma persistant) ---")
    import os
    import tempfile

    # Forcer Chroma sur un dossier temporaire pour pas polluer data/
    tmpdir = tempfile.mkdtemp(prefix="walle_test_")
    os.environ["CHROMA_PATH"] = tmpdir

    try:
        from brain.identity import Identity
        from brain.memory import MemoryManager
        from brain.tools import execute_tool

        mgr = MemoryManager()

        parent_id = _pick_parent_id()
        child_id = _pick_child_id()
        child2_id = _pick_second_child_id()

        parent = Identity.from_user_id(parent_id)
        child = Identity.from_user_id(child_id)

        # Saves perso et family
        mgr.save_perso(parent_id, f"{parent_id} aime le dark mode")
        mgr.save_perso(child_id, f"{child_id} a un animal de compagnie")
        if child2_id != child_id:
            mgr.save_perso(child2_id, f"{child2_id} prepare un examen")
        mgr.save_family(parent_id, "La famille part en vacances cet ete")

        # Cloisonnement perso : child ne voit pas mem de child2
        if child2_id != child_id:
            child_perso = mgr.search_perso(child_id, "examen")
            for m in child_perso:
                assert "examen" not in m.lower(), f"Fuite memoire {child2_id} dans perso {child_id} : {m}"
            logger.info("Cloisonnement perso enfant1<-/-enfant2 OK")

        # Family accessible aux deux
        f_p = mgr.search_family("vacances")
        f_c = mgr.search_family("vacances")
        assert any("vacances" in m.lower() for m in f_p), "Parent doit voir mem family"
        assert any("vacances" in m.lower() for m in f_c), "Enfant doit voir mem family"
        logger.info("Memoire family partagee ...... OK")

        # Parent peut lire mem enfant via search_child_memory
        if child2_id != child_id:
            r = execute_tool("search_child_memory",
                            {"child_name": child2_id, "query": "examen"},
                            identity=parent, memory_mgr=mgr)
            assert r.get("child") == child2_id, f"search_child_memory parent KO : {r}"
            logger.info("Parent -> search_child_memory %s OK", child2_id)

        # Enfant refuse ACL search_child_memory
        r = execute_tool("search_child_memory",
                        {"child_name": child_id, "query": "test"},
                        identity=child, memory_mgr=mgr)
        assert "error" in r, f"ACL devait refuser search_child_memory pour enfant : {r}"
        logger.info("ACL refus search_child_memory enfant OK")

        # Enfant refuse sur family write
        r = execute_tool("save_memory",
                        {"content": "tentative", "scope": "family"},
                        identity=child, memory_mgr=mgr)
        assert "error" in r, f"ACL devait refuser family write pour enfant : {r}"
        logger.info("ACL refus family write enfant OK")

        # Enfant autorise sur perso write
        r = execute_tool("save_memory",
                        {"content": "test perso"},
                        identity=child, memory_mgr=mgr)
        assert "error" not in r, f"Enfant doit pouvoir ecrire en perso : {r}"
        logger.info("ACL autorise perso enfant ... OK")

    finally:
        # Cleanup
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


# === TEST LIVE (avec Ollama) ===

def test_live_ollama():
    logger.info("--- Test LIVE Ollama ---")
    logger.info("Verifie que le service Ollama tourne sur OLLAMA_HOST")

    from brain.llm_client import OllamaClient
    import config

    client = OllamaClient()
    resp = client.messages.create(
        model=config.OLLAMA_MODEL,
        max_tokens=100,
        system="Tu es un assistant francais. Reponds en une phrase courte.",
        messages=[{"role": "user", "content": "Dis bonjour"}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    assert text, "Reponse vide"
    logger.info("Ollama repond ................ OK (%d tokens out)", resp.usage.output_tokens)
    logger.info("Reponse : %r", text[:100])


# === MAIN ===

def main():
    parser = argparse.ArgumentParser(description="Tests Brain WALL-E")
    parser.add_argument("--dry-run", action="store_true",
                        help="Tests sans appel LLM (imports, identity, ACL, memoire)")
    parser.add_argument("--text", action="store_true",
                        help="Test live avec Ollama (requiert service actif)")
    args = parser.parse_args()

    if not args.dry_run and not args.text:
        parser.print_help()
        return

    if args.dry_run:
        test_imports()
        test_identity()
        test_prompts()
        test_tools_acl()
        test_memory()
        logger.info("=== TOUS LES TESTS DRY-RUN PASSES ===")

    if args.text:
        test_live_ollama()
        logger.info("=== TEST LIVE OLLAMA PASSE ===")


if __name__ == "__main__":
    main()
