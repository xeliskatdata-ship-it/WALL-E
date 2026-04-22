# brain/identity.py - Identites des utilisateurs + ACL outils
# Phase 8.1 modele B : famille ouverte + intimite couple
# Phase 8.3 : remplacement de la detection par reconnaissance vocale

import re
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import config

logger = logging.getLogger("walle.identity")


# Mapping role -> outils autorises
# Modele B : parents ont search_child_memory pour consulter la memoire perso des enfants
# Ecriture reste cloisonnee : personne n'ecrit dans la memoire d'un autre
_TOOLS_BY_ROLE = {
    "parent":  {"save_memory", "search_memory", "web_search", "search_child_memory"},
    "child":   {"save_memory", "search_memory"},    # pas de web_search, ni acces aux autres
    "unknown": set(),                                # aucun outil
}


@dataclass
class Identity:
    user_id: str
    display_name: str
    role: str                           # "parent" / "child" / "unknown"
    age: Optional[int] = None
    tools_allowed: set = field(default_factory=set)
    can_write_family: bool = False

    @classmethod
    def from_user_id(cls, user_id: str) -> "Identity":
        if not user_id:
            return cls.unknown()
        uid = user_id.lower().strip()
        if uid not in config.USERS:
            logger.info("User_id inconnu : '%s' -> fallback unknown", user_id)
            return cls.unknown()

        info = config.USERS[uid]
        role = info["role"]
        return cls(
            user_id=uid,
            display_name=info["display_name"],
            role=role,
            age=_compute_age(info["dob"]),
            tools_allowed=_TOOLS_BY_ROLE[role],
            can_write_family=(role == "parent"),
        )

    @classmethod
    def unknown(cls) -> "Identity":
        return cls(
            user_id="unknown",
            display_name="Inconnu",
            role="unknown",
            age=None,
            tools_allowed=_TOOLS_BY_ROLE["unknown"],
            can_write_family=False,
        )

    def can_use_tool(self, tool_name: str) -> bool:
        return tool_name in self.tools_allowed

    def is_parent(self) -> bool:
        return self.role == "parent"


def _compute_age(dob_iso: str) -> int:
    dob = date.fromisoformat(dob_iso)
    today = date.today()
    age = today.year - dob.year
    if (today.month, today.day) < (dob.month, dob.day):
        age -= 1
    return age


# Regex prefix : [prenom] reste du message
_PREFIX_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(.*)$", re.DOTALL)


def parse_prefix(text: str) -> tuple[Optional[str], str]:
    """Extrait un prefix [prenom] si present.
    Retourne (user_id | None, texte_nettoye).
    """
    m = _PREFIX_RE.match(text)
    if not m:
        return None, text
    return m.group(1).lower().strip(), m.group(2).strip()
