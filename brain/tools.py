# brain/tools.py - Outils exposes au LLM avec ACL par identite
# v2.0 : web_search retire (mode 100% offline).
# v2.1 : _CHILD_NAMES calcule dynamiquement depuis config.USERS pour pseudonymisation.

import logging

import config

logger = logging.getLogger("walle.tools")


def _get_child_names() -> list:
    """Liste les user_id ayant le role child. Calcul dynamique depuis config.USERS,
    permet de garder ce fichier generique pour le repo public.
    """
    return [uid for uid, info in config.USERS.items() if info.get("role") == "child"]


# Liste calculee au chargement du module
_CHILD_NAMES = _get_child_names()


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
            "OUTIL RESERVE AUX PARENTS. Cherche dans la memoire perso d'un enfant du foyer. "
            "A utiliser quand un parent demande explicitement des nouvelles d'un enfant ou "
            "cherche ce qu'un enfant a partage. Les enfants sont informes que leurs parents "
            "ont ce droit. Principe : transmets les faits factuels (ecole, projets, passions, "
            "amis) librement. Pour les confidences intimes d'ados, resume en termes generaux "
            "et suggere au parent d'en parler directement a l'enfant plutot que de citer "
            "textuellement."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "child_name": {
                    "type": "string",
                    "enum": _CHILD_NAMES,
                    "description": "user_id de l'enfant (en minuscules, defini dans family_local.py)",
                },
                "query": {"type": "string", "description": "Requete semantique"},
                "k": {"type": "integer", "default": 5},
            },
            "required": ["child_name", "query"],
        },
    },
]


def filter_tools_for(identity) -> list:
    return [t for t in TOOLS_ALL if t["name"] in identity.tools_allowed]


def describe_tools(tools: list) -> str:
    if not tools:
        return "(aucun outil disponible pour cet interlocuteur)"
    return "\n".join(f"- {t['name']} : {t['description'].split('.')[0]}." for t in tools)


def execute_tool(name: str, args: dict, identity, memory_mgr) -> dict:
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
            if not identity.is_parent():
                return {"error": "search_child_memory reserve aux parents"}
            child = args["child_name"].lower()
            if child not in _CHILD_NAMES:
                return {"error": f"child_name '{child}' invalide, attendu parmi {_CHILD_NAMES}"}
            docs = memory_mgr.search_perso(child, args["query"], k=args.get("k", 5))
            logger.info("search_child_memory [%s -> %s] : %d resultats",
                        identity.user_id, child, len(docs))
            return {"child": child, "results": docs, "count": len(docs)}

        return {"error": f"outil inconnu : {name}"}

    except Exception as e:
        logger.exception("Erreur execution outil %s : %s", name, e)
        return {"error": f"exception : {type(e).__name__} : {e}"}
