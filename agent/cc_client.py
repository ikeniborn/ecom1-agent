"""Claude Code tier — spawn iclaude CLI as stateless LLM.

Bypasses applied (all required to isolate iclaude from the host project):
  - cwd=<tmpdir>        → no project CLAUDE.md auto-discovery
  - --no-save           → no session history written under ~/.claude/projects
  - --strict-mcp-config → block user ~/.claude MCP servers from loading
  - --mcp-config <empty> → no tools exposed to the model (stateless LLM use)
  - --print             → headless non-interactive mode
  - --output-format json → parseable envelope with result + usage
  - env stripped        → ANTHROPIC_API_KEY / OPENROUTER_API_KEY / OPENAI_API_KEY
                          removed when CC_STRIP_PROJECT_ENV=1 so iclaude uses OAuth

The CLI has no --seed and no response_format flag; JSON-only output is requested
via a system-prompt trailer. Caller handles JSON parsing (dispatch / loop).
"""
from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path


_CC_ENABLED = os.environ.get("ECOM_CC_ENABLED") == "1"
_ICLAUDE_CMD = os.environ.get("ECOM_ICLAUDE_CMD", "iclaude")
_CC_STRIP_PROJECT_ENV = os.environ.get("ECOM_CC_STRIP_PROJECT_ENV", "1") == "1"
try:
    _CC_MAX_RETRIES = int(os.environ.get("ECOM_CC_MAX_RETRIES", "2"))
except ValueError:
    _CC_MAX_RETRIES = 2
try:
    _CC_RETRY_DELAY_S = float(os.environ.get("ECOM_CC_RETRY_DELAY_S", "4"))
except ValueError:
    _CC_RETRY_DELAY_S = 4.0

_STRIPPED_ENV_KEYS = frozenset({
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
})


def _build_env() -> dict[str, str]:
    import re as _re
    env = {k: v for k, v in os.environ.items() if k not in _STRIPPED_ENV_KEYS} \
        if _CC_STRIP_PROJECT_ENV else dict(os.environ)
    # Override iclaude.project inside OTEL_RESOURCE_ATTRIBUTES so iclaude wrapper
    # reports ecom1-agent instead of the temp cwd basename (cc_cwd_XXXX).
    # We modify OTEL_RESOURCE_ATTRIBUTES rather than introducing a new env var to
    # avoid inheritance pollution across nested subprocess chains.
    otel = env.get("OTEL_RESOURCE_ATTRIBUTES", "")
    if _re.search(r'iclaude\.project=', otel):
        env["OTEL_RESOURCE_ATTRIBUTES"] = _re.sub(
            r'iclaude\.project=[^,]*', 'iclaude.project=ecom1-agent', otel)
    elif otel:
        env["OTEL_RESOURCE_ATTRIBUTES"] = otel + ",iclaude.project=ecom1-agent"
    else:
        env["OTEL_RESOURCE_ATTRIBUTES"] = "iclaude.project=ecom1-agent"
    return env


def _collect_stdout(pipe, buf: list[str]) -> None:
    try:
        for line in pipe:
            buf.append(line)
    except Exception:
        pass


def _parse_envelope(lines: list[str]) -> tuple[str, int, int, int, int, str]:
    """Extract result text and token usage from iclaude --output-format json.
    Envelope shape: {"type":"result","subtype":"success","result":"...",
                     "usage":{"input_tokens":N,"cache_creation_input_tokens":N,
                              "cache_read_input_tokens":N,"output_tokens":N},
                     "modelUsage":{"<model>":{"inputTokens":N,"outputTokens":N,
                                              "cacheCreationInputTokens":N,
                                              "cacheReadInputTokens":N}}}.
    Returns (text, fresh_in_tok, out_tok, cache_creation, cache_read, stop_reason).
    FIX-N: separates fresh input from cached tokens (Claude API semantics —
    usage.input_tokens is ONLY the non-cached portion of the last message).
    FIX-361: also returns stop_reason to let the caller detect a legitimately
    empty generation (end_turn with result="") and skip pointless retries.
    Scans lines in reverse for the last success envelope."""
    for line in reversed(lines):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if obj.get("type") != "result" or obj.get("subtype") != "success":
            continue
        text = obj.get("result", "")
        if not isinstance(text, str):
            continue
        stop_reason = obj.get("stop_reason") or ""
        if not isinstance(stop_reason, str):
            stop_reason = ""
        in_tok = 0
        out_tok = 0
        cache_cr = 0
        cache_rd = 0
        usage = obj.get("usage")
        if isinstance(usage, dict):
            in_tok = int(usage.get("input_tokens") or 0)
            out_tok = int(usage.get("output_tokens") or 0)
            cache_cr = int(usage.get("cache_creation_input_tokens") or 0)
            cache_rd = int(usage.get("cache_read_input_tokens") or 0)
        if not in_tok and not out_tok and not cache_cr and not cache_rd:
            mu = obj.get("modelUsage")
            if isinstance(mu, dict):
                for per_model in mu.values():
                    if isinstance(per_model, dict):
                        in_tok += int(per_model.get("inputTokens") or 0)
                        out_tok += int(per_model.get("outputTokens") or 0)
                        cache_cr += int(per_model.get("cacheCreationInputTokens") or 0)
                        cache_rd += int(per_model.get("cacheReadInputTokens") or 0)
        return text, in_tok, out_tok, cache_cr, cache_rd, stop_reason
    return "", 0, 0, 0, 0, ""


def _spawn_once(
    cmd: list[str],
    cwd: str,
    env: dict[str, str],
    timeout_s: int,
    stdin_data: str | None = None,
) -> tuple[list[str], int, str]:
    """Spawn iclaude once. Returns (stdout_lines, exit_code, fail_reason).
    fail_reason: 'ok' | 'timeout' | 'error'.
    stdin_data: if provided, written to proc stdin (avoids ARG_MAX / E2BIG)."""
    stdout_lines: list[str] = []
    fail_reason = "ok"
    exit_code = -1
    proc: subprocess.Popen | None = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=cwd,
            env=env,
            start_new_session=True,
        )
        t = threading.Thread(
            target=_collect_stdout,
            args=(proc.stdout, stdout_lines),
            daemon=True,
        )
        t.start()
        if stdin_data is not None and proc.stdin is not None:
            try:
                proc.stdin.write(stdin_data)
                proc.stdin.close()
            except OSError:
                pass
        t.join(timeout=timeout_s)
        if proc.poll() is None:
            fail_reason = "timeout"
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except OSError:
                proc.terminate()
            t.join(timeout=5)
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    proc.kill()
                t.join(timeout=5)
        else:
            t.join(timeout=30)
        exit_code = proc.wait()
    except Exception as e:
        fail_reason = "error"
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
        print(f"[CC] spawn error: {e}")
    return stdout_lines, exit_code, fail_reason


def cc_complete(
    system: str,
    user_msg: str,
    *,
    cfg: dict,
    max_tokens: int,
    plain_text: bool = False,
    token_out: dict | None = None,
) -> str | None:
    """Stateless LLM call via iclaude subprocess.

    Returns assistant text (JSON string when plain_text=False; freeform otherwise),
    or None after CC_MAX_RETRIES+1 failed attempts. The caller parses JSON.

    max_tokens is ignored — iclaude has no equivalent flag; CC stops naturally.
    """
    if not _CC_ENABLED:
        return None

    cc_model = cfg.get("cc_model") or os.environ.get("ECOM_CC_DEFAULT_MODEL", "")
    cc_opts = cfg.get("cc_options") or {}
    if isinstance(cc_opts, str):
        cc_opts = {}
    cc_effort = cc_opts.get("cc_effort") or os.environ.get("ECOM_CC_DEFAULT_EFFORT", "")
    try:
        cc_timeout = int(cc_opts.get("cc_timeout_s") or os.environ.get("ECOM_CC_DEFAULT_TIMEOUT_S", "180"))
    except (TypeError, ValueError):
        cc_timeout = 180

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, prefix="cc_mcp_"
    ) as f:
        json.dump({"mcpServers": {}}, f)
        cfg_path = f.name

    cwd = tempfile.mkdtemp(prefix="cc_cwd_")

    sys_prompt = system or ""
    if not plain_text:
        sys_prompt += (
            "\n\n# Output format\n"
            "Return ONLY a valid JSON object. "
            "No preamble, no code fences, no commentary.\n"
            "\n# Execution model (FIX-340)\n"
            "CRITICAL: DO NOT call any tools, functions, or actions. "
            "DO NOT use Bash, Read, Glob, Grep, Write, or any other tool. "
            "This is a PURE JSON ANALYSIS task — the JSON output IS the complete "
            "answer. Generate the JSON schema immediately based ONLY on the text "
            "provided in the user message. No tool calls are needed or permitted.\n"
            "You are a PURE LLM text generator. You have NO local tools: NO "
            "Bash, NO Glob, NO Grep, NO Read, NO Write — they are disabled. "
            "Your subprocess cwd is an empty tmpdir and is irrelevant. The "
            "vault lives in the PCM harness — your JSON `function` field "
            "describes the NEXT PCM tool call; the host agent dispatches it "
            "and returns the result in the NEXT user message.\n"
            "Do NOT claim 'vault not mounted', 'filesystem unmounted', or "
            "'file not found' unless a PCM tool call in THIS conversation "
            "returned such an error. Observations from your own environment "
            "(ls, glob, cwd) are hallucinations and must be ignored."
        )

    # FIX-340 / FIX-BANLIST: ban ALL user-visible CC built-in tools so the model
    # cannot call them, while preserving the internal --json-schema tool-forcing
    # mechanism (which --tools "" would break). Opus-class models trigger newer
    # tools (Agent, TaskCreate, Skill, ScheduleWakeup, LSP, EnterPlanMode, etc.)
    # that were not in the original ban list, producing result="" after strip.
    _CC_BUILTIN_TOOLS_BAN = (
        "Bash BashOutput KillShell KillBash Glob Grep Read Write Edit MultiEdit "
        "NotebookEdit NotebookRead TodoWrite Task WebFetch WebSearch "
        "SlashCommand ExitPlanMode AskUserQuestion "
        "Agent SendMessage ScheduleWakeup "
        "CronCreate CronDelete CronList "
        "LSP Skill "
        "EnterPlanMode EnterWorktree ExitWorktree "
        "TaskCreate TaskGet TaskList TaskUpdate TaskOutput TaskStop"
    )

    # FIX-E2BIG: write system prompt to a file to avoid ARG_MAX / E2BIG when
    # the assembled context is large. kernel enforces a per-execve limit on
    # argv+envp tighter than the reported ARG_MAX (~2MB nominal).
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, prefix="cc_sys_"
    ) as sf:
        sf.write(sys_prompt)
        sys_prompt_path = sf.name

    cmd = [
        *shlex.split(_ICLAUDE_CMD),
        "--no-save",
        "--print",
        "--strict-mcp-config",
        "--mcp-config", cfg_path,
        "--disallowed-tools", _CC_BUILTIN_TOOLS_BAN,
        "--system-prompt-file", sys_prompt_path,
        "--output-format", "json",
    ]
    if cc_model:
        cmd.extend(["--model", cc_model])
    if cc_effort:
        cmd.extend(["--effort", cc_effort])

    # FIX-N+1: pass-through CC flags from cc_options (OAuth-compatible only;
    # --bare is intentionally NOT supported — it forces ANTHROPIC_API_KEY/apiKeyHelper
    # and disables OAuth / keychain reads, breaking iclaude's auth model).
    cc_fallback = cc_opts.get("cc_fallback_model") or os.environ.get("ECOM_CC_DEFAULT_FALLBACK_MODEL", "")
    if cc_fallback:
        cmd.extend(["--fallback-model", cc_fallback])

    _exclude_dyn = cc_opts.get("cc_exclude_dynamic")
    if _exclude_dyn is None:
        _exclude_dyn = os.environ.get("ECOM_CC_DEFAULT_EXCLUDE_DYNAMIC") == "1"
    if _exclude_dyn:
        cmd.append("--exclude-dynamic-system-prompt-sections")

    # FIX-SCHEMA: --json-schema combined with --disallowed-tools causes empty
    # result for complex Pydantic schemas (IddOutput, SddOutput etc.) — the
    # internal schema-tool conflicts with the ban list on some model versions.
    # CC provider relies solely on the system-prompt JSON instruction instead.

    # FIX-E2BIG: user_msg passed via stdin, not as a positional CLI arg.
    # Combined sys_prompt (~10-150 KB) + user_msg as CLI args triggered E2BIG
    # even well under getconf ARG_MAX, because the kernel enforces a per-execve
    # limit on the argv+envp region that is tighter than the reported ARG_MAX.

    env = _build_env()

    try:
        for attempt in range(_CC_MAX_RETRIES + 1):
            stdout_lines, exit_code, fail_reason = _spawn_once(cmd, cwd, env, cc_timeout, stdin_data=user_msg)
            text, in_tok, out_tok, cache_cr, cache_rd, stop_reason = _parse_envelope(stdout_lines)
            if text:
                if token_out is not None:
                    token_out["input"] = in_tok
                    token_out["output"] = out_tok
                    token_out["cache_creation"] = cache_cr  # FIX-N
                    token_out["cache_read"] = cache_rd      # FIX-N
                return text

            # FIX-361: legitimately empty generation — model produced output
            # tokens but result="" (likely a banned built-in tool_use stripped
            # by iclaude). Retry cannot fix this; fail fast to skip the 4s×N
            # backoff and let the caller fall back.
            legitimately_empty = (
                stop_reason == "end_turn" and out_tok > 0 and fail_reason == "ok"
            )

            # FIX-390: fail-fast on OAuth quota exhaustion. Without this, the
            # caller burns _CC_MAX_RETRIES × _CC_RETRY_DELAY_S waiting for a
            # limit that won't lift for hours, masking the real failure mode
            # behind generic "empty/error" messages and silently killing
            # downstream work (post-run wiki-lint observed dying mid-loop).
            tail_text = "".join(stdout_lines[-12:]).lower()
            quota_exhausted = any(
                marker in tail_text
                for marker in (
                    "hit your limit",
                    "claude usage limit",
                    "you have reached",
                    "rate limit",
                    "too many requests",
                )
            )
            if quota_exhausted:
                tail_print = "".join(stdout_lines[-8:]).rstrip()[:800] or "<empty>"
                print(
                    f"[CC] OAuth quota exhausted — aborting retries to avoid "
                    f"{_CC_MAX_RETRIES * _CC_RETRY_DELAY_S}s of useless backoff. "
                    f"Stdout tail:\n{tail_print}"
                )
                break

            # FIX-N+4: diagnostic — dump tail of stdout so we can distinguish
            # "iclaude crashed silently" vs "envelope parse failed" vs "rate-limited".
            _debug = os.environ.get("ECOM_CC_DEBUG_EMPTY") == "1"
            if _debug or attempt >= _CC_MAX_RETRIES or legitimately_empty:
                tail = "".join(stdout_lines[-8:]).rstrip()[:800] or "<empty>"
                print(f"[CC] stdout tail (last {min(8, len(stdout_lines))} lines):\n{tail}")
            if legitimately_empty:
                print(
                    f"[CC] empty result with stop_reason=end_turn, output_tokens={out_tok} "
                    f"— not retrying (likely banned tool_use stripped)"
                )
                break
            if attempt < _CC_MAX_RETRIES:
                print(
                    f"[CC] {fail_reason} or empty "
                    f"(attempt {attempt + 1}/{_CC_MAX_RETRIES + 1}, exit={exit_code}) "
                    f"— retrying in {_CC_RETRY_DELAY_S}s"
                )
                time.sleep(_CC_RETRY_DELAY_S)
            else:
                print(
                    f"[CC] Failed after {_CC_MAX_RETRIES + 1} attempts "
                    f"(last fail_reason={fail_reason}, exit={exit_code})"
                )
    finally:
        Path(cfg_path).unlink(missing_ok=True)
        Path(sys_prompt_path).unlink(missing_ok=True)
        try:
            Path(cwd).rmdir()
        except OSError:
            pass

    return None
