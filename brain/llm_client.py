# brain/llm_client.py - wrapper Ollama qui expose une API style SDK Anthropic
# (objets attribues, pas dicts) pour ne PAS toucher a agent.py.
#
# Usage cote agent :
#   client = OllamaClient()
#   resp = client.messages.create(model=..., max_tokens=..., system=..., tools=..., messages=...)
#   resp.content      -> list[TextBlock | ToolUseBlock]
#   resp.stop_reason  -> "end_turn" | "tool_use" | "error"
#   resp.usage.input_tokens, .output_tokens
#
# v2.4 : timeout 60s + num_thread + num_ctx pour qwen2.5:7b sur Pi 5.

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field

import ollama

import config

logger = logging.getLogger("walle.llm")


# ===== Types de blocs (style SDK Anthropic) =====

@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict
    type: str = "tool_use"


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class MessageResponse:
    id: str
    model: str
    role: str
    content: list                  # list[TextBlock | ToolUseBlock]
    stop_reason: str               # "end_turn" / "tool_use" / "error"
    usage: Usage = field(default_factory=Usage)


# ===== Client =====

class _MessagesAPI:
    # Sous-objet pour exposer .messages.create (mimic SDK Anthropic)
    def __init__(self, parent):
        self._parent = parent

    def create(self, model=None, max_tokens=None, system=None, tools=None, messages=None):
        return self._parent._chat(
            model=model, max_tokens=max_tokens,
            system=system, tools=tools, messages=messages,
        )


class OllamaClient:

    def __init__(self):
        self._client = ollama.Client(host=config.OLLAMA_HOST, timeout=config.OLLAMA_TIMEOUT)
        self.messages = _MessagesAPI(self)

    def _chat(self, model=None, max_tokens=None, system=None, tools=None, messages=None):
        # Construit la liste pour Ollama : system(s) + historique aplati
        ollama_msgs = []
        if system:
            ollama_msgs.append({"role": "system", "content": system})
        if tools:
            # Ollama (qwen2.5) ne consomme pas un schema tool API,
            # on lui injecte la liste en JSON dans un 2e system + format de sortie attendu.
            tools_brief = json.dumps(tools, ensure_ascii=False, indent=2)
            ollama_msgs.append({
                "role": "system",
                "content": (
                    "Outils disponibles (JSON Anthropic) :\n"
                    f"{tools_brief}\n\n"
                    "Pour appeler un outil, reponds UNIQUEMENT avec un bloc JSON delimite "
                    "par ```json {\"name\": \"...\", \"arguments\": {...}} ```.\n"
                    "Sinon, reponds en texte libre."
                ),
            })
        for m in messages or []:
            ollama_msgs.append({
                "role":    m["role"],
                "content": _flatten_content(m["content"]),
            })

        t0 = time.perf_counter()
        try:
            resp = self._client.chat(
                model=model or config.OLLAMA_MODEL,
                messages=ollama_msgs,
                options={
                    "num_ctx":     config.OLLAMA_NUM_CTX,
                    "num_thread":  config.OLLAMA_NUM_THREAD,
                    "num_predict": max_tokens or config.BRAIN_MAX_TOKENS,
                    "temperature": 0.7,
                },
            )
        except Exception as e:
            # remontee a l'agent qui choisira son fallback (mode degrade)
            logger.error("Ollama chat KO (%s) : %s", type(e).__name__, e)
            raise

        dt = time.perf_counter() - t0
        text = resp["message"]["content"]
        in_t  = int(resp.get("prompt_eval_count", 0) or 0)
        out_t = int(resp.get("eval_count", 0) or 0)
        logger.info("Ollama OK : %.2fs in=%d out=%d", dt, in_t, out_t)

        return _to_response(text, model or config.OLLAMA_MODEL, in_t, out_t)


# ===== Helpers serialisation/parsing =====

def _attr(obj, name, default):
    # acces uniforme sur dict ou dataclass
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _flatten_content(content):
    # str ou liste de blocks (dataclass ou dict) -> string pour Ollama
    if isinstance(content, str):
        return content
    parts = []
    for blk in content:
        t = _attr(blk, "type", None)
        if t == "text":
            parts.append(_attr(blk, "text", ""))
        elif t == "tool_use":
            name = _attr(blk, "name", "")
            inp = _attr(blk, "input", {})
            parts.append(f"[tool_use {name} {json.dumps(inp, ensure_ascii=False)}]")
        elif t == "tool_result":
            tu_id = _attr(blk, "tool_use_id", "")
            data  = _attr(blk, "content", "")
            if not isinstance(data, str):
                data = json.dumps(data, ensure_ascii=False)
            parts.append(f"[tool_result id={tu_id} {data}]")
    return "\n".join(parts)


_TOOL_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _to_response(text, model, in_t, out_t):
    # Detecte un appel d'outil JSON. Preserve TOUJOURS la preface texte (bug fix v2.1).
    m = _TOOL_BLOCK_RE.search(text)
    blocks = []
    stop_reason = "end_turn"

    if m:
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and "name" in data:
            preface = text[:m.start()].strip()
            if preface:
                blocks.append(TextBlock(text=preface))
            args = data.get("arguments") or data.get("input") or {}
            blocks.append(ToolUseBlock(
                id="toolu_" + uuid.uuid4().hex[:12],
                name=data["name"],
                input=args if isinstance(args, dict) else {},
            ))
            stop_reason = "tool_use"
            # postface eventuelle ignoree (rare, generalement bavardage post-tool)

    if not blocks:
        # pas de tool call detecte : reponse texte simple
        blocks = [TextBlock(text=text or "")]
        stop_reason = "end_turn"

    return MessageResponse(
        id="msg_" + uuid.uuid4().hex[:12],
        model=model,
        role="assistant",
        content=blocks,
        stop_reason=stop_reason,
        usage=Usage(input_tokens=in_t, output_tokens=out_t),
    )