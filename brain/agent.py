# brain/agent.py - BrainThread multi-utilisateur
# brain_in_q recoit (user_id: str, text: str), brain_out_q emet (user_id, reply)
# Une conversation courte distincte par user_id (self.histories)

import json
import logging
import threading
from queue import Empty

from anthropic import Anthropic

import config
from brain.identity import Identity
from brain.memory import MemoryManager
from brain.tools import filter_tools_for, describe_tools, execute_tool
from brain.prompts import build_system_prompt

logger = logging.getLogger("walle.brain")

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = Anthropic()  # lit ANTHROPIC_API_KEY
    return _client


class BrainThread(threading.Thread):
    """Thread brain multi-user.

    Entree : brain_in_q recoit des tuples (user_id: str, text: str)
    Sortie : brain_out_q emet (user_id: str, reply: str)

    Chaque user a sa propre conversation courte dans self.histories[user_id].
    La memoire long terme est geree centralement par MemoryManager.
    Les personas et ACL sont resolues via Identity.from_user_id().
    """

    def __init__(self, brain_in_q, brain_out_q, stop_event=None,
                 motor_q=None, face_q=None, motors_thread=None):
        super().__init__(name="BrainThread", daemon=True)
        self.brain_in_q = brain_in_q
        self.brain_out_q = brain_out_q
        self.stop_event = stop_event or threading.Event()

        # Reserves Phases 8.2+
        self.motor_q = motor_q
        self.face_q = face_q
        self.motors_thread = motors_thread

        self.memory_mgr = MemoryManager()
        self.histories = {}  # user_id -> liste messages court terme

    def _get_history(self, user_id: str):
        if user_id not in self.histories:
            self.histories[user_id] = []
        return self.histories[user_id]

    def _build_system(self, identity: Identity, query_hint: str) -> str:
        perso_mems, family_mems = [], []
        if identity.user_id != "unknown" and query_hint:
            perso_mems = self.memory_mgr.search_perso(
                identity.user_id, query_hint, k=config.BRAIN_MEMORY_TOP_K
            )
            family_mems = self.memory_mgr.search_family(
                query_hint, k=config.BRAIN_MEMORY_TOP_K
            )

        allowed = filter_tools_for(identity)
        tools_desc = describe_tools(allowed)

        return build_system_prompt(
            identity=identity,
            allowed_tools_desc=tools_desc,
            perso_mems=perso_mems,
            family_mems=family_mems,
        )

    def _handle_turn(self, identity: Identity, user_input: str) -> str:
        history = self._get_history(identity.user_id)
        history.append({"role": "user", "content": user_input})

        system = self._build_system(identity, query_hint=user_input)
        tools = filter_tools_for(identity)

        for iteration in range(config.BRAIN_MAX_TOOL_ITERATIONS):
            try:
                resp = _get_client().messages.create(
                    model=config.ANTHROPIC_MODEL,
                    max_tokens=config.BRAIN_MAX_TOKENS,
                    system=system,
                    tools=tools,
                    messages=history,
                )
            except Exception as e:
                logger.exception("Erreur API Claude : %s", e)
                history.pop()  # on retire le dernier user pour eviter d'accumuler
                return f"Oups, j'ai eu un souci technique : {e}"

            history.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason != "tool_use":
                text = "".join(b.text for b in resp.content if b.type == "text")
                logger.debug("Tour [%s] en %d iter, tokens=%d",
                             identity.user_id, iteration + 1, resp.usage.output_tokens)
                return text

            # Tool use : execute avec ACL
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    logger.info("Tool [%s] : %s(%s)",
                                identity.user_id, block.name, block.input)
                    out = execute_tool(
                        name=block.name,
                        args=block.input,
                        identity=identity,
                        memory_mgr=self.memory_mgr,
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(out, ensure_ascii=False),
                    })

            history.append({"role": "user", "content": tool_results})

        return "Desole, j'ai boucle trop longtemps sur mes outils. Reformule ?"

    def run(self):
        logger.info("Demarrage BrainThread (backend=%s, model=%s)",
                    config.LLM_BACKEND, config.ANTHROPIC_MODEL)
        summary = self.memory_mgr.counts_summary()
        logger.info("Memoires au demarrage : %s",
                    ", ".join(f"{k}={v}" for k, v in summary.items()))

        while not self.stop_event.is_set():
            try:
                item = self.brain_in_q.get(timeout=0.1)
            except Empty:
                continue

            # Format attendu : (user_id, text)
            if not isinstance(item, tuple) or len(item) != 2:
                logger.warning("Item invalide dans brain_in_q : %s", item)
                continue

            user_id, user_input = item
            if not isinstance(user_input, str) or not user_input.strip():
                continue

            identity = Identity.from_user_id(user_id)

            try:
                reply = self._handle_turn(identity, user_input)
                self.brain_out_q.put((user_id, reply))
            except Exception as e:
                logger.exception("Erreur traitement tour : %s", e)
                self.brain_out_q.put((user_id, f"[Erreur brain : {e}]"))

        logger.info("BrainThread arrete")

    def reset_history(self, user_id: str = None):
        # Reset la conv courte d'un user (ou de tous si None)
        if user_id is None:
            self.histories = {}
            logger.info("Toutes les conversations reinitialisees")
        else:
            self.histories.pop(user_id, None)
            logger.info("Conversation reinitialisee pour %s", user_id)
