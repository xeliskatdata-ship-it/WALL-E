# brain/llm_client.py - Wrapper LLM Ollama avec interface compatible Anthropic
# Phase 8.5 v2.0 : migration full Ollama. Ce wrapper expose une methode
# messages.create() identique a Anthropic SDK, ce qui permet de garder
# brain/agent.py quasi intact.
#
# En interne :
#   - traduit l'historique Claude (blocs typed) -> format Ollama (role/content/tool_calls)
#   - traduit les tools Claude (input_schema) -> format Ollama (parameters style OpenAI)
#   - reconvertit la reponse Ollama en blocs Claude (.content, .stop_reason, .usage)

import json
import logging
import uuid
from types import SimpleNamespace

import ollama

import config

logger = logging.getLogger("walle.llm")


# --- Types compatibles Anthropic SDK ---

class _Block:
    # Bloc generique : .type + champs selon le type
    # type='text'      -> .text
    # type='tool_use'  -> .id, .name, .input
    def __init__(self, type, **kwargs):
        self.type = type
        for k, v in kwargs.items():
            setattr(self, k, v)


class _Response:
    # Imite Anthropic.messages.create() return value
    def __init__(self, content, stop_reason, input_tokens=0, output_tokens=0):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


# --- Conversion outils Claude -> Ollama (style OpenAI function calling) ---

def _claude_tools_to_ollama(tools):
    if not tools:
        return None
    out = []
    for t in tools:
        out.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],   # le schema JSON est compatible
            },
        })
    return out


# --- Conversion historique Claude -> Ollama ---

def _claude_messages_to_ollama(system, messages):
    """Convertit l'historique format Claude vers format Ollama.

    Claude utilise des blocs typed dans content (TextBlock, ToolUseBlock).
    Ollama utilise un content str + tool_calls separe + role 'tool' pour les results.
    """
    out = [{"role": "system", "content": system}]

    # Map tool_use_id -> tool_name (Ollama n'a pas d'id, on doit retrouver le name)
    tool_use_id_to_name = {}

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if role == "user":
            # Cas 1 : user a tape du texte
            if isinstance(content, str):
                out.append({"role": "user", "content": content})

            # Cas 2 : retour d'outils -> liste de tool_result dicts
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "tool_result":
                        tname = tool_use_id_to_name.get(item.get("tool_use_id"), "unknown")
                        out.append({
                            "role": "tool",
                            "content": item.get("content", ""),
                            "name": tname,
                        })

        elif role == "assistant":
            # content est une liste de _Block (text + tool_use)
            text_parts = []
            tool_calls = []
            for block in content:
                btype = getattr(block, "type", None)
                if btype == "text":
                    text_parts.append(getattr(block, "text", ""))
                elif btype == "tool_use":
                    tname = getattr(block, "name", "")
                    targs = getattr(block, "input", {})
                    tid = getattr(block, "id", "")
                    tool_use_id_to_name[tid] = tname
                    tool_calls.append({
                        "function": {"name": tname, "arguments": targs}
                    })

            ollama_msg = {"role": "assistant", "content": "".join(text_parts)}
            if tool_calls:
                ollama_msg["tool_calls"] = tool_calls
            out.append(ollama_msg)

    return out


# --- Conversion reponse Ollama -> blocs Claude ---

def _ollama_msg_to_blocks(message):
    blocks = []

    # Texte (si non vide)
    text = getattr(message, "content", "") or ""
    if isinstance(message, dict):
        text = message.get("content", "") or ""
    if text.strip():
        blocks.append(_Block(type="text", text=text))

    # Tool calls
    tool_calls = getattr(message, "tool_calls", None)
    if isinstance(message, dict):
        tool_calls = message.get("tool_calls", None)
    if not tool_calls:
        return blocks

    for tc in tool_calls:
        # Selon version : tc peut etre objet ou dict
        if isinstance(tc, dict):
            fn = tc.get("function", {})
            name = fn.get("name", "")
            args = fn.get("arguments", {})
        else:
            fn = getattr(tc, "function", None)
            name = getattr(fn, "name", "") if fn else ""
            args = getattr(fn, "arguments", {}) if fn else {}

        # Args peut etre str (JSON) ou dict selon version
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                logger.warning("Tool args non parsables : %r", args)
                args = {}

        blocks.append(_Block(
            type="tool_use",
            id=f"toolu_{uuid.uuid4().hex[:12]}",
            name=name,
            input=args,
        ))

    return blocks


# --- API publique : imite Anthropic SDK ---

class _MessagesAPI:
    def __init__(self, parent):
        self._parent = parent

    def create(self, model=None, max_tokens=1024, system="", tools=None, messages=None):
        return self._parent._create(model, max_tokens, system, tools, messages or [])


class OllamaClient:
    """Drop-in replacement pour anthropic.Anthropic.

    Usage identique :
        client = OllamaClient()
        resp = client.messages.create(model='qwen2.5:3b', max_tokens=1024,
                                      system='...', tools=[...], messages=[...])
        resp.content       # liste de _Block
        resp.stop_reason   # 'end_turn' ou 'tool_use'
        resp.usage.output_tokens
    """

    def __init__(self, host=None, default_model=None, timeout=120):
        host = host or getattr(config, "OLLAMA_HOST", "http://localhost:11434")
        self._client = ollama.Client(host=host, timeout=timeout)
        self._default_model = default_model or getattr(config, "OLLAMA_MODEL", "qwen2.5:3b")
        self.messages = _MessagesAPI(self)
        logger.info("OllamaClient initialise (host=%s, model=%s)", host, self._default_model)

    def _create(self, model, max_tokens, system, tools, messages):
        model = model or self._default_model
        ollama_msgs = _claude_messages_to_ollama(system, messages)
        ollama_tools = _claude_tools_to_ollama(tools)

        try:
            response = self._client.chat(
                model=model,
                messages=ollama_msgs,
                tools=ollama_tools,
                options={"num_predict": max_tokens},
            )
        except Exception as e:
            # Erreur reseau, modele non charge, etc. -> on remonte au caller (agent.py)
            logger.exception("Erreur appel Ollama : %s", e)
            raise

        # response.message peut etre objet ou dict selon version ollama-python
        msg = getattr(response, "message", None)
        if msg is None and isinstance(response, dict):
            msg = response.get("message", {})

        blocks = _ollama_msg_to_blocks(msg)

        # Filet : si Ollama renvoie tool_calls inutilisables (parfois sur petits modeles)
        # mais pas de texte non plus, on remonte un texte vide pour eviter le KO complet
        if not blocks:
            blocks = [_Block(type="text", text="...")]

        # stop_reason : si on a un tool_use -> il faut boucler dans agent.py
        has_tool_use = any(b.type == "tool_use" for b in blocks)
        stop_reason = "tool_use" if has_tool_use else "end_turn"

        # Usage approximatif depuis les compteurs Ollama
        if isinstance(response, dict):
            in_tok = response.get("prompt_eval_count", 0) or 0
            out_tok = response.get("eval_count", 0) or 0
        else:
            in_tok = getattr(response, "prompt_eval_count", 0) or 0
            out_tok = getattr(response, "eval_count", 0) or 0

        return _Response(blocks, stop_reason, in_tok, out_tok)
