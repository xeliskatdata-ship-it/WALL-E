# brain/tools.py - Outils exposes au LLM avec ACL par identite
# Phase 8.1 modele B : save, search, web (parents), search_child_memory (parents uniquement)

import logging
from duckduckgo_search import DDGS

logger = logging.getLogger("walle.tools")


# Liste des enfants autorises comme cible de search_child_memory
# Synchronise avec config.USERS (role=child). Hardcode ici pour limite dure.
_CHILD_NAMES = ["louis", "william", "raphael", "ambre"]


TOOLS_ALL = [
    {
        "name": "save_memory",
        "description": (
            "Sauvegarde un fait important sur le long terme. Par defaut ecriture sur ta "
            "memoire perso avec l'interlocuteur courant. Option scope='family' reservee "
            "aux parents pour les infos qui concernent toute la famille."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Contenu a memoriser, affirmation courte et autosuffisante",
                },
                "scope": {
                    "type": "string",
                    "enum": ["perso", "family"],
                    "default": "perso",
                    "description": "perso (default) = coll. de l'interlocuteur | family = partage (parents uniquement)",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "search_memory",
        "description": (
            "Recherche semantique dans ta memoire long terme. Retourne deux listes : "
            "tes souvenirs perso avec cet interlocuteur, et les souvenirs partages famille."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Requete semantique"},
                "k": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_child_memory",
        "description": (
            "OUTIL RESERVE AUX PARENTS (Kat et Brice). Cherche dans la memoire perso d'un "
            "de leurs enfants (Louis, William, Raphael, Ambre). A utiliser quand un parent "
            "demande explicitement des nouvelles d'un enfant ou cherche ce qu'un enfant a "
            "partage. Les enfants sont informes que leurs parents ont ce droit. "
            "Principe : transmets les faits factuels (ecole, projets, passions, amis) "
            "librement. Pour les confidences intimes d'ados (attirances, doutes sur soi, "
            "conflits amicaux), resume en termes generaux et suggere au parent d'en "
            "parler directement a l'enfant plutot que de citer textuellement."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "child_name": {
                    "type": "string",
                    "enum": _CHILD_NAMES,
                    "description": "Prenom de l'enfant en minuscules",
                },
                "query": {"type": "string", "description": "Requete semantique"},
                "k": {"type": "integer", "default": 5},
            },
            "required": ["child_name", "query"],
        },
    },
    {
        "name": "web_search",
        "description": (
            "Recherche web via DuckDuckGo pour les faits recents ou d'actualite. "
            "Reserve aux parents (Kat et Brice). Non disponible pour les enfants."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
]


def filter_tools_for(identity) -> list:
    return [t for t in TOOLS_ALL if t["name"] in identity.tools_allowed]


def describe_tools(tools: list) -> str:
    if not tools:
        return "(aucun outil disponible pour cet interlocuteur)"
    # On prend juste la premiere ligne de la description pour le system prompt
    return "\n".join(f"- {t['name']} : {t['description'].split('.')[0]}." for t in tools)


def execute_tool(name: str, args: dict, identity, memory_mgr) -> dict:
    # Check ACL strict (double defense avec le filtrage cote LLM)
    if name not in identity.tools_allowed:
        logger.warning("ACL refus : user=%s tente %s", identity.user_id, name)
        return {
            "error": f"Outil '{name}' non autorise pour {identity.display_name}. "
                     f"Cet outil est reserve aux parents."
        }

    try:
        if name == "save_memory":
            scope = args.get("scope", "perso")
            if scope == "family":
                if not identity.can_write_family:
                    logger.warning("ACL refus family write : %s", identity.user_id)
                    return {"error": "Ecriture dans la memoire famille reservee aux parents."}
                mid = memory_mgr.save_family(identity.user_id, args["content"])
                return {"status": "ok", "scope": "family", "id": mid}
            mid = memory_mgr.save_perso(identity.user_id, args["content"])
            return {"status": "ok", "scope": "perso", "id": mid}

        if name == "search_memory":
            return memory_mgr.search_combined(
                identity.user_id, args["query"], k=args.get("k", 5)
            )

        if name == "search_child_memory":
            # Double check : seul un parent peut acceder (l'ACL l'a deja fait, on re-valide)
            if not identity.is_parent():
                return {"error": "search_child_memory reserve aux parents"}
            child = args["child_name"].lower()
            if child not in _CHILD_NAMES:
                return {"error": f"child_name '{child}' invalide, attendu parmi {_CHILD_NAMES}"}
            docs = memory_mgr.search_perso(child, args["query"], k=args.get("k", 5))
            logger.info("search_child_memory [%s -> %s] : %d resultats",
                        identity.user_id, child, len(docs))
            return {"child": child, "results": docs, "count": len(docs)}

        if name == "web_search":
            with DDGS() as ddgs:
                raw = list(ddgs.text(args["query"], max_results=args.get("max_results", 5)))
            return {
                "results": [
                    {"title": r["title"], "snippet": r["body"], "url": r["href"]}
                    for r in raw
                ]
            }

        return {"error": f"outil inconnu : {name}"}

    except Exception as e:
        logger.exception("Erreur execution outil %s : %s", name, e)
        return {"error": f"exception : {type(e).__name__} : {e}"}
