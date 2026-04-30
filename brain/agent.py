# brain/agent.py - BrainThread multi-utilisateur
# v2.0 : migration full Ollama via brain/llm_client.py
# v2.2 : integration de la couche safety deterministe (Phase 8.6)
# v2.3 : injection de l'emotion detectee dans le system prompt (Phase 8.4)

import json
import logging
import threading
from queue import Empty, Queue

from brain.llm_client import OllamaClient

import config
from brain.identity import Identity
from brain.memory import MemoryManager
from brain.tools import filter_tools_for, describe_tools, execute_tool
from brain.prompts import build_system_prompt
from brain.safety import SafetyFilter

logger = logging.getLogger("walle.brain")

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OllamaClient()
    return _client


def _get_latest_face(face_q):
    """v2.3 : helper qui vide face_q et garde uniquement la derniere FaceData.

    Le brain n'est pas synchronise avec le rythme de VisionThread, donc on
    drain la queue (non-bloquant) pour avoir la lecture la plus recente.
    """
    if face_q is None:
        return None
    latest = None
    while True:
        try:
            latest = face_q.get_nowait()
        except Empty:
            break
    return latest


class BrainThread(threading.Thread):
    """Thread brain multi-user."""

    def __init__(self, brain_in_q, brain_out_q, stop_event=None,
                 motor_q=None, face_q=None, motors_thread=None):
        super().__init__(name="BrainThread", daemon=True)
        self.brain_in_q = brain_in_q
        self.brain_out_q = brain_out_q
        self.stop_event = stop_event or threading.Event()

        self.motor_q = motor_q
        self.face_q = face_q                    # v2.3 : utilise pour lire l'emotion
        self.motors_thread = motors_thread

        self.memory_mgr = MemoryManager()
        self.safety = SafetyFilter()
        self.histories = {}

    def _get_history(self, user_id: str):
        if user_id not in self.histories:
            self.histories[user_id] = []
        return self.histories[user_id]

    def _build_system(self, identity: Identity, query_hint: str, emotion_data=None) -> str:
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
            emotion_data=emotion_data,         # v2.3 Phase 8.4
        )

    def _handle_turn(self, identity: Identity, user_input: str) -> str:
        # Safety niveau 2 : detresse sur input
        in_check = self.safety.check_input(user_input, identity)
        if not in_check.passed:
            logger.warning("Safety [%s] input bloque : %s",
                           identity.user_id, in_check.reason)
            return in_check.replacement

        history = self._get_history(identity.user_id)
        history.append({"role": "user", "content": user_input})

        # v2.3 Phase 8.4 : recupere la derniere emotion vue par VisionThread
        emotion_data = _get_latest_face(self.face_q)
        if emotion_data is not None:
            logger.debug("Emotion detectee pour [%s] : %s (conf=%.2f)",
                         identity.user_id,
                         getattr(emotion_data, "emotion", "?"),
                         getattr(emotion_data, "confidence", 0.0))

        system = self._build_system(identity, query_hint=user_input,
                                    emotion_data=emotion_data)
        tools = filter_tools_for(identity)

        collected_text = []

        for iteration in range(config.BRAIN_MAX_TOOL_ITERATIONS):
            try:
                resp = _get_client().messages.create(
                    model=config.OLLAMA_MODEL,
                    max_tokens=config.BRAIN_MAX_TOKENS,
                    system=system,
                    tools=tools,
                    messages=history,
                )
            except Exception as e:
                logger.exception("Erreur appel LLM : %s", e)
                history.pop()
                return (f"Oups, j'arrive pas a joindre mon cerveau local "
                        f"(Ollama). Verifie que le service tourne. ({e})")

            history.append({"role": "assistant", "content": resp.content})

            iteration_text = "".join(
                b.text for b in resp.content if b.type == "text"
            ).strip()
            if iteration_text:
                collected_text.append(iteration_text)

            logger.debug("Tour [%s] iter %d : stop=%s, texte=%r, tokens_out=%d",
                         identity.user_id, iteration + 1, resp.stop_reason,
                         iteration_text[:80], resp.usage.output_tokens)

            if resp.stop_reason != "tool_use":
                final = " ".join(collected_text).strip()
                if not final:
                    final = "C'est note !"

                # Safety niveau 1 : check output (mineurs uniquement)
                out_check = self.safety.check_output(final, identity)
                if not out_check.passed:
                    logger.warning("Safety [%s] output bloque : %s",
                                   identity.user_id, out_check.reason)
                    if len(history) >= 2:
                        history.pop()
                        history.pop()
                    return out_check.replacement

                return final

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

        fallback = " ".join(collected_text).strip()
        if fallback:
            out_check = self.safety.check_output(fallback, identity)
            if not out_check.passed:
                return out_check.replacement
            return fallback + " (j'ai un peu bugge, mais j'ai retenu l'essentiel)"
        return "Desole, j'ai boucle trop longtemps sur mes outils. Reformule ?"

    def run(self):
        logger.info("Demarrage BrainThread (backend=%s, model=%s, host=%s)",
                    config.LLM_BACKEND, config.OLLAMA_MODEL,
                    getattr(config, "OLLAMA_HOST", "http://localhost:11434"))
        logger.info("Safety filter actif (Phase 8.6)")
        if self.face_q is not None:
            logger.info("Emotion injection active (Phase 8.4)")
        summary = self.memory_mgr.counts_summary()
        logger.info("Memoires au demarrage : %s",
                    ", ".join(f"{k}={v}" for k, v in summary.items()))

        while not self.stop_event.is_set():
            try:
                item = self.brain_in_q.get(timeout=0.1)
            except Empty:
                continue

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
        if user_id is None:
            self.histories = {}
            logger.info("Toutes les conversations reinitialisees")
        else:
            self.histories.pop(user_id, None)
            logger.info("Conversation reinitialisee pour %s", user_id)
