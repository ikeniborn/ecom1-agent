# LLM

The LLM layer (`agent/llm.py`, `agent/cc_client.py`) is the single funnel every phase calls through `call_llm_raw`. It routes a model id to one of four provider transports, resolves a per-phase model tier, retries transient errors, then falls through to `ECOM_MODEL_FALLBACK`. See [[architecture]] for how phases invoke it and [[pipeline]] for the call budget.

## Provider Routing by Prefix

`get_provider(model, cfg)` (`agent/llm.py:308`) picks a transport: explicit `cfg["provider"]` wins over name heuristics. Values: `anthropic` | `claude-code` | `openrouter` | `ollama`. Heuristic fallback: `claude-code/*` → claude-code, name containing `claude` → anthropic, `name:tag` with no slash → ollama, else openrouter.

Transports, all tried in tier order inside `_call_raw_single_model` (`agent/llm.py:325`):

- **`anthropic/`** → Anthropic SDK (`anthropic_client`, `agent/llm.py:113`). Accepts `list[dict]` system blocks with `cache_control` for prompt caching. No `seed` param; `temperature` from cfg is the determinism lever. Alias→API-id mapping in `_ANTHROPIC_MODEL_MAP` (`agent/llm.py:623`) via `get_anthropic_model_id`.
- **`openrouter/`** → OpenRouter OpenAI-compatible client (`agent/llm.py:119`). Skipped for Ollama-format models. Probes structured-output support; forwards `temperature`, `seed`, `logprobs`. Claude-via-OpenRouter also receives cache-control system blocks.
- **`ollama/` or bare name** → local Ollama OpenAI-compat client (`agent/llm.py:134`, default `http://localhost:11434/v1`). `is_ollama_model` (`agent/llm.py:293`) returns true for `name:tag` with no slash, routing it directly to Ollama and skipping OpenRouter.
- **`claude-code`** → `cc_client.cc_complete` subprocess (see [[#Claude Code Subprocess Tier]]). Does NOT cascade into OpenRouter/Ollama on failure — returns `None` so the caller retries the whole step.

## Tier Resolution (`_resolve_model_for_phase`)

`_resolve_model_for_phase(phase, default_model)` (`agent/llm.py:85`) resolves a model id per phase, read live from `os.environ`: `ECOM_MODEL_<PHASE>` → tier env (`ECOM_MODEL_REASON` / `ECOM_MODEL_FAST` / `ECOM_MODEL_EMBED`) → `default_model`. Live reads let a test's `monkeypatch.setenv` apply without reloading the module. With only `ECOM_MODEL` set, every phase resolves to `ECOM_MODEL` (back-compatible).

Phase→tier map `_PHASE_TIER` (`agent/llm.py:69`): reason → `intent`, `plan`, `ilearn`, `learn`, `distill`; fast → `docselect`, `rerank`. `_TIER_ENV` (`agent/llm.py:78`) maps `reason`→`ECOM_MODEL_REASON`, `fast`→`ECOM_MODEL_FAST`, `embed`→`ECOM_MODEL_EMBED`. Phase names are normalised by `_norm_phase` (lowercase, underscores stripped). Any phase not listed defaults to the reason tier for model resolution. See [[data-files]] for `models.json` keys and the phase prompts under `data/prompts/`.

## Reason vs Fast Tier (`think`)

`_think_for_phase(phase)` (`agent/llm.py:103`) sets the `think` flag from tier: reason → `True` (think on), fast → `False` (think off), unlisted → `None` (unchanged, so probe/compaction calls are not perturbed). `call_llm_raw` applies this only when its `think` argument is `None`, deriving it from the `phase` argument (`agent/llm.py:581`).

For Ollama, a `models.json` `ollama_think` value overrides the per-call/tier `think` (`agent/llm.py:481`); otherwise the tier flag is forwarded as `extra_body["think"]`. The Anthropic and OpenRouter tiers do not pass `think` as a request param — the tier instead governs which model is selected and the cfg-level options.

## `ECOM_MODEL_FALLBACK` Fallthrough

`call_llm_raw` (`agent/llm.py:560`) is the single funnel. It runs the primary model through all transport tiers via `_call_raw_single_model`; only if that returns `None` AND `_FALLBACK_MODEL` is set and differs from the primary does it retry once with `ECOM_MODEL_FALLBACK` and an empty cfg, `max_retries=1` (`agent/llm.py:591`). `_FALLBACK_MODEL` reads `ECOM_MODEL_FALLBACK` at import (`agent/llm.py:280`).

Within each tier, errors are classified against `TRANSIENT_KWS` (503/502/429, overloaded, rate limit, timeouts — `agent/llm.py:262`) and `HARD_CONNECTION_KWS` (broken pipe, ECONNRESET, connection refused — `agent/llm.py:273`). Transient errors retry up to `max_retries` (delay 4s); hard connection errors are capped at 1 retry (delay 2s) before falling through. Empty responses fall through to the next tier rather than returning `""`.

## Claude Code Subprocess Tier

`cc_client.cc_complete` (`agent/cc_client.py:193`) runs the `iclaude` CLI as a stateless LLM, gated by `ECOM_CC_ENABLED=1` (`agent/cc_client.py:29`; also re-checked in `llm.py:48`). It is reachable only when a model declares `provider="claude-code"`, and interleaves with the Anthropic tier rather than acting as a downstream fallback. On failure it returns `None`, so the caller retries the whole step.

Isolation flags (`agent/cc_client.py:279`): `--no-save`, `--print`, `--strict-mcp-config`, an empty `--mcp-config`, `--disallowed-tools` banning all built-in tools (`agent/cc_client.py:259`), `--system-prompt-file`, `--output-format json`. The subprocess runs in a temp cwd with `ECOM_ANTHROPIC_API_KEY`/`ECOM_OPENROUTER_API_KEY`/`OPENAI_API_KEY` stripped (`ECOM_CC_STRIP_PROJECT_ENV=1`, `agent/cc_client.py:41`) so it authenticates via OAuth. `cc_model`/`cc_options` (effort, timeout, fallback model, exclude-dynamic) come from `models.json`; the user message is passed via stdin to avoid `E2BIG`. JSON-only output is requested through a system-prompt trailer since the CLI has no `response_format`. `_parse_envelope` (`agent/cc_client.py:75`) scans for the last `type=result` envelope and extracts text plus token usage. Retries: `ECOM_CC_MAX_RETRIES` (default 2), with fail-fast on legitimately-empty `end_turn` generations and on OAuth quota exhaustion.

## HTTP Timeouts

HTTP timeouts (`agent/llm.py:50`) cap how long a stalled request may hang. `ECOM_LLM_HTTP_READ_TIMEOUT_S` (default 180) and `ECOM_LLM_HTTP_CONNECT_TIMEOUT_S` (default 10) build an `httpx.Timeout` applied to the OpenRouter and Ollama clients; the Anthropic SDK uses the read timeout directly. The 180s read timeout keeps requests under the task timeout and lets the `TRANSIENT_KWS` retry loop recover from stalled sockets. The `embed_texts` endpoint (`agent/llm.py:666`) uses a fixed 60s timeout.

## `models.json` Options

`models.json` (template `models.json.example`) holds per-model capability config keyed by the model id used in env vars. `cfg` is threaded into every tier call. Per [[data-files]], recognised keys include `provider`, `response_format_hint` (OpenRouter only), `temperature`, `ollama_think`, `cc_model`, `cc_options`, and `kind` (`embedding` for oracle vectors — see [[oracle]]).

`ollama_options` (`models.json.example:7`) is flattened to top-level request fields because the LiteLLM proxy drops a nested `options` blob. Keys include `num_ctx` (context window, default 2048; set 16384+ for long AGENTS.MD docs), `temperature`, `seed`, `top_k`, `top_p`, `repeat_penalty`, and `num_predict`. The reason-tier Ollama models in the example use `num_ctx: 16384`; the `nomic-embed-text` embedding model uses `num_ctx: 8192`. A `seed` inside `ollama_options` is also forwarded cross-tier to OpenRouter (`agent/llm.py:441`), since the Anthropic SDK has no seed param.

## Structured-Output Capability

`probe_structured_output` (`agent/llm.py:211`) determines whether a model accepts `response_format={"type":"json_object"}`, used by the OpenRouter tier. Resolution order: explicit `cfg` hint → `_STATIC_HINTS` substring table (`agent/llm.py:157`, e.g. `anthropic/claude`, `qwen/qwen`, `openai/gpt` → `json_object`; `perplexity/` → `none`) → a one-off runtime probe. Results are cached per model name, persisted to `.cache/capability_cache.json` with a 7-day TTL (`agent/llm.py:171`), under a double-checked lock so the slow HTTP probe runs outside the lock. The Ollama tier requests `json_object` directly and, on failure, retries once in plain-text mode (`agent/llm.py:535`).
