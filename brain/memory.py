# brain/memory.py - Memoire long terme multi-utilisateur
# Une collection ChromaDB par user + une collection partagee "family"
# Cloisonnement strict : personne ne voit la memoire perso d'un autre

import logging
from datetime import datetime
from pathlib import Path

import chromadb
from chromadb.config import Settings

import config

logger = logging.getLogger("walle.memory")

_PROJECT_ROOT = Path(config.__file__).parent
DB_PATH = _PROJECT_ROOT / config.CHROMA_PATH
DB_PATH.mkdir(parents=True, exist_ok=True)

FAMILY_COLLECTION = "family"


class MemoryManager:
    """Gere les collections : une par user (mem_kat, mem_brice, ...) + mem_family.

    Regles :
    - save_perso(user_id, text)     : ecrit sur la collection perso du user
    - save_family(author, text)     : ecrit sur mem_family (reserve parents via ACL tools.py)
    - search_perso(user_id, query)  : cherche UNIQUEMENT dans la collection du user
    - search_family(query)          : cherche dans mem_family
    - search_combined(user_id, q)   : perso + family (utilise par le RAG)
    """

    def __init__(self):
        self.client = chromadb.PersistentClient(
            path=str(DB_PATH),
            settings=Settings(anonymized_telemetry=False),
        )
        self._cols = {}  # cache collections
        logger.info("MemoryManager initialise (path=%s)", DB_PATH)

    def _get_collection(self, name: str):
        if name not in self._cols:
            self._cols[name] = self.client.get_or_create_collection(
                name=f"mem_{name}",
                metadata={"hnsw:space": "cosine"},
            )
        return self._cols[name]

    # --- Ecriture ---
    def save_perso(self, user_id: str, text: str, source: str = "conversation") -> str:
        col = self._get_collection(user_id)
        mid = f"{user_id}_{datetime.utcnow().isoformat()}"
        col.add(
            documents=[text],
            metadatas=[{"source": source, "ts": datetime.utcnow().isoformat(), "scope": "perso"}],
            ids=[mid],
        )
        logger.debug("Memoire perso [%s] : %s", user_id, text[:60])
        return mid

    def save_family(self, author: str, text: str, source: str = "conversation") -> str:
        # author trace dans les metadatas, mais le contenu est dans la collection family
        col = self._get_collection(FAMILY_COLLECTION)
        mid = f"family_{datetime.utcnow().isoformat()}"
        col.add(
            documents=[text],
            metadatas=[{
                "source": source,
                "ts": datetime.utcnow().isoformat(),
                "scope": "family",
                "author": author,
            }],
            ids=[mid],
        )
        logger.debug("Memoire family (par %s) : %s", author, text[:60])
        return mid

    # --- Lecture ---
    def search_perso(self, user_id: str, query: str, k: int = 5) -> list[str]:
        col = self._get_collection(user_id)
        if col.count() == 0 or not query:
            return []
        res = col.query(query_texts=[query], n_results=min(k, col.count()))
        return res["documents"][0] if res["documents"] else []

    def search_family(self, query: str, k: int = 5) -> list[str]:
        col = self._get_collection(FAMILY_COLLECTION)
        if col.count() == 0 or not query:
            return []
        res = col.query(query_texts=[query], n_results=min(k, col.count()))
        return res["documents"][0] if res["documents"] else []

    def search_combined(self, user_id: str, query: str, k: int = 5) -> dict:
        # Pour le tool search_memory : perso + family en deux listes separees
        return {
            "perso": self.search_perso(user_id, query, k=k),
            "family": self.search_family(query, k=k),
        }

    # --- Meta ---
    def count_perso(self, user_id: str) -> int:
        return self._get_collection(user_id).count()

    def count_family(self) -> int:
        return self._get_collection(FAMILY_COLLECTION).count()

    def counts_summary(self) -> dict:
        # Pour affichage au demarrage
        summary = {}
        for uid in config.USERS:
            summary[uid] = self.count_perso(uid)
        summary["family"] = self.count_family()
        return summary

    def wipe_all(self):
        # TESTS UNIQUEMENT - reset complet
        for uid in list(config.USERS.keys()) + [FAMILY_COLLECTION]:
            try:
                self.client.delete_collection(name=f"mem_{uid}")
            except Exception:
                pass
        self._cols = {}
        logger.warning("MemoryManager : toutes collections wipees")
