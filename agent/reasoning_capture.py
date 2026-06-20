"""Production reasoning-capture seams (B2). Active only when ECOM_TRACE_REASONING=1.

Wraps the OpenAI-compatible clients (Ollama/OpenRouter), the Anthropic client, and
the claude-code spawn so each LLM call tees its chain-of-thought into a thread-local
sink. `call_llm_raw` pops the capture and folds it into the `llm_call` record.

Best-effort: any provider/parse failure leaves `reasoning_available=false`.
"""
from __future__ import annotations

import json
import os
import re
import threading

_sink = threading.local()
_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)
_installed = False


def enabled() -> bool:
    return os.environ.get("ECOM_TRACE_REASONING") == "1"


def _push(reasoning: str, raw_full: str) -> None:
    items = getattr(_sink, "items", None)
    if items is None:
        items = []
        _sink.items = items
    items.append({"reasoning": reasoning or "", "raw_full": raw_full or ""})


def pop_capture() -> dict:
    """Capture for the just-completed logical LLM call; reset the sink.

    A logical call may issue several spawns/creates (retries/fallback); take the
    last one carrying reasoning, else the last one at all, else empty."""
    items = getattr(_sink, "items", [])
    _sink.items = []
    chosen = None
    for it in items:
        if it["reasoning"]:
            chosen = it
    if chosen is None and items:
        chosen = items[-1]
    return chosen or {"reasoning": "", "raw_full": ""}


def _reasoning_from_openai_resp(resp) -> tuple[str, str]:
    reasoning = full = ""
    try:
        data = resp.model_dump()
    except Exception:
        data = None
    if isinstance(data, dict):
        choices = data.get("choices") or []
        if choices and isinstance(choices[0], dict):
            msg = choices[0].get("message") or {}
            full = msg.get("content") or ""
            reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
            if not reasoning and full:
                m = _THINK_RE.search(full)
                if m:
                    reasoning = m.group(1).strip()
    return (reasoning or ""), (full or "")


def _wrap_openai_client(client) -> None:
    if client is None:
        return
    comp = client.chat.completions
    orig = comp.create

    def wrapped(*a, **k):
        resp = orig(*a, **k)
        try:
            _push(*_reasoning_from_openai_resp(resp))
        except Exception:
            pass
        return resp

    comp.create = wrapped


def _wrap_anthropic_client(client) -> None:
    if client is None:
        return
    orig = client.messages.create

    def wrapped(*a, **k):
        resp = orig(*a, **k)
        try:
            think = "".join(getattr(b, "thinking", "") or ""
                            for b in resp.content if getattr(b, "type", None) == "thinking")
            text = "\n".join(getattr(b, "text", "") or ""
                             for b in resp.content if getattr(b, "type", None) == "text")
            _push(think, text)
        except Exception:
            pass
        return resp

    client.messages.create = wrapped


def _parse_stream_reasoning(lines: list[str]) -> tuple[str, str]:
    parts: list[str] = []
    text_parts: list[str] = []
    for ln in lines:
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            obj = json.loads(ln)
        except (json.JSONDecodeError, ValueError):
            continue
        if obj.get("type") == "assistant":
            for b in (obj.get("message") or {}).get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "thinking":
                    parts.append(b.get("thinking") or "")
                elif b.get("type") == "redacted_thinking":
                    parts.append("[redacted_thinking]")
                elif b.get("type") == "text":
                    text_parts.append(b.get("text") or "")
        elif obj.get("type") == "thinking":
            parts.append(obj.get("thinking") or obj.get("text") or "")
    return "\n".join(p for p in parts if p), "\n".join(t for t in text_parts if t)


def _install_cc_stream_capture() -> None:
    import agent.cc_client as CC
    orig_spawn = CC._spawn_once

    def _spawn(cmd, cwd, env, timeout_s, stdin_data=None):
        cmd = list(cmd)
        if "--output-format" in cmd:
            i = cmd.index("--output-format")
            if i + 1 < len(cmd):
                cmd[i + 1] = "stream-json"
        else:
            cmd += ["--output-format", "stream-json"]
        if "--verbose" not in cmd:  # required with --print --output-format stream-json
            cmd.append("--verbose")
        lines, exit_code, fail = orig_spawn(cmd, cwd, env, timeout_s, stdin_data=stdin_data)
        try:
            _push(*_parse_stream_reasoning(lines))
        except Exception:
            pass
        return lines, exit_code, fail

    CC._spawn_once = _spawn


def install() -> None:
    """Idempotent: wrap every provider seam. Safe to call when disabled (no-op)."""
    global _installed
    if _installed or not enabled():
        return
    _installed = True
    import agent.llm as L
    try:
        _wrap_openai_client(L.ollama_client)
        _wrap_openai_client(L.openrouter_client)
        _wrap_anthropic_client(L.anthropic_client)
        _install_cc_stream_capture()
    except Exception:
        pass
