#!/usr/bin/env python3
"""Synthesize eval_log optimization entries into candidate files."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date
from pathlib import Path

import yaml
from dotenv import load_dotenv

os.environ["EVAL_ENABLED"] = "0"   # must be before agent imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import knowledge_loader
from agent.llm import call_llm_raw

call_llm_raw_cluster = call_llm_raw  # alias — allows patch in tests without affecting call_llm_raw

_ROOT = Path(__file__).parent.parent
_EVAL_LOG = _ROOT / "data" / "eval_log.jsonl"
_RULES_DIR = _ROOT / "data" / "rules"
_SECURITY_DIR = _ROOT / "data" / "security"
_PROMPTS_DIR = _ROOT / "data" / "prompts"
_PROMPTS_OPTIMIZED_DIR = _PROMPTS_DIR / "optimized"
_PROCESSED_FILE = _ROOT / "data" / ".eval_optimizations_processed"
_MODELS_JSON = _ROOT / "models.json"
_BITGN_URL = os.getenv("BENCHMARK_HOST") or "https://api.bitgn.com"
_BENCHMARK_ID = os.getenv("BENCHMARK_ID") or "bitgn/pac1-dev"
_BITGN_API_KEY = os.getenv("BITGN_API_KEY") or ""
_LOGS_DIR = _ROOT / "logs"

for _d in (_RULES_DIR, _SECURITY_DIR, _PROMPTS_OPTIMIZED_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def read_original_score(task_id: str, logs_dir: Path | None = None) -> float | None:
    """Return task_result.score from latest non-validate run for task_id, or None."""
    if logs_dir is None:
        logs_dir = _LOGS_DIR
    if not logs_dir.exists():
        return None
    dirs = [d for d in logs_dir.iterdir() if d.is_dir() and not d.name.startswith("validate-")]
    if not dirs:
        return None
    latest = max(dirs, key=lambda d: d.stat().st_mtime)
    task_file = latest / f"{task_id}.jsonl"
    if not task_file.exists():
        return None
    for line in task_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
            if ev.get("type") == "task_result":
                return float(ev["score"])
        except Exception:
            continue
    return None


def validate_recommendation(
    task_id: str,
    *,
    injected_session_rules: list[str] | None = None,
    injected_prompt_addendum: str = "",
    injected_security_gates: list[dict] | None = None,
) -> tuple[float | None, float | None]:
    """Re-run task_id with recommendation injected. Returns (original_score, validation_score).

    Either may be None: original if no baseline; validation if task not found in trials.
    """
    import datetime
    from bitgn.harness_connect import HarnessServiceClientSync
    from bitgn.harness_pb2 import StartRunRequest, StartTrialRequest, EndTrialRequest, SubmitRunRequest
    from agent import run_agent

    original_score = read_original_score(task_id)

    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    client = HarnessServiceClientSync(_BITGN_URL)
    run = client.start_run(StartRunRequest(
        name=f"validate-{timestamp}",
        benchmark_id=_BENCHMARK_ID,
        api_key=_BITGN_API_KEY,
    ))

    validation_score: float | None = None
    for trial_id in run.trial_ids:
        trial = client.start_trial(StartTrialRequest(trial_id=trial_id))
        if trial.task_id != task_id:
            client.end_trial(EndTrialRequest(trial_id=trial.trial_id))
            continue
        run_agent(
            model_configs={},
            harness_url=trial.harness_url,
            task_text=trial.instruction,
            task_id=trial.task_id,
            injected_session_rules=injected_session_rules or [],
            injected_prompt_addendum=injected_prompt_addendum,
            injected_security_gates=injected_security_gates or [],
        )
        result = client.end_trial(EndTrialRequest(trial_id=trial.trial_id))
        validation_score = float(result.score)
        break

    client.submit_run(SubmitRunRequest(run_id=run.run_id, force=True))

    if validation_score is None:
        print(f"[validate] WARNING: task_id={task_id!r} not found in trial_ids — skipping")

    return original_score, validation_score


def _load_model_cfg(model: str) -> dict:
    raw = json.loads(_MODELS_JSON.read_text())
    profiles = raw.get("_profiles", {})
    cfg = dict(raw.get(model, {}))
    for fname in ("ollama_options", "ollama_options_evaluator"):
        if isinstance(cfg.get(fname), str):
            cfg[fname] = profiles.get(cfg[fname], {})
    return cfg


def _load_processed() -> set[str]:
    if _PROCESSED_FILE.exists():
        return set(line for line in _PROCESSED_FILE.read_text().splitlines() if line)
    return set()


def _save_processed(hashes: set[str]) -> None:
    _PROCESSED_FILE.write_text("\n".join(sorted(hashes)) + "\n")


def _entry_hash(task_text: str, channel: str, rec: str) -> str:
    return hashlib.sha256(f"{channel}|{task_text}|{rec}".encode()).hexdigest()[:16]


def _cluster_recs(
    items: list[tuple[str, dict, str]],
    existing_md: str,
    model: str,
    cfg: dict,
) -> list[tuple[str, dict, list[str]]]:
    """Cluster semantically equivalent recs into representatives via one LLM call.

    Returns list of (representative_rec, first_entry, all_original_hashes).
    Falls back to singleton tuples on LLM failure.
    """
    if not items:
        return []

    from agent.json_extract import _extract_json_from_text

    recs = [rec for rec, _, _ in items]
    system = (
        "You will receive a JSON array of raw optimization recommendations and (optionally) existing content.\n"
        "Return a JSON array of unique, non-redundant recommendations.\n"
        "Merge semantically equivalent items into one. Drop items already covered by existing content.\n"
        "Keep the most specific/actionable wording. Return only the merged array, no other text."
        + (f"\n\nExisting content:\n{existing_md}" if existing_md else "")
    )
    user_msg = json.dumps(recs, ensure_ascii=False)
    raw = call_llm_raw_cluster(system, user_msg, model, cfg, max_tokens=1024)

    if not raw:
        return [(rec, entry, [h]) for rec, entry, h in items]

    parsed = None
    try:
        parsed = json.loads(raw.strip())
    except (json.JSONDecodeError, ValueError):
        parsed = _extract_json_from_text(raw)
    if not isinstance(parsed, list):
        return [(rec, entry, [h]) for rec, entry, h in items]

    result = []
    remaining_items = list(items)
    for rep_rec in parsed:
        if not isinstance(rep_rec, str):
            continue
        matched_hashes = []
        matched_entry = None
        for orig_rec, orig_entry, orig_hash in remaining_items:
            if orig_rec in rep_rec or rep_rec in orig_rec or orig_rec == rep_rec:
                matched_hashes.append(orig_hash)
                if matched_entry is None:
                    matched_entry = orig_entry
        if not matched_hashes:
            # representative is new wording — assign all remaining originals
            matched_hashes = [h for _, _, h in remaining_items]
            matched_entry = remaining_items[0][1] if remaining_items else {}
        result.append((rep_rec, matched_entry or {}, matched_hashes))
        remaining_items = [it for it in remaining_items if it[2] not in matched_hashes]
        if not remaining_items:
            break

    if not result:
        return [(rec, entry, [h]) for rec, entry, h in items]
    return result


def _check_contradiction(
    new_content: str,
    existing_md: str,
    model: str,
    cfg: dict,
) -> str | None:
    """Returns None if no conflict, or 'CONFLICT: <id> — <reason>' string."""
    if not existing_md:
        return None

    system = (
        "Check if the new content contradicts any existing item.\n"
        "A contradiction means opposite instructions for the same scenario.\n"
        "If found: respond with exactly: CONFLICT: <id> — <reason>\n"
        "If not found: respond with exactly: OK"
    )
    user_msg = f"Existing:\n{existing_md}\n\nNew content:\n{new_content}"
    raw = call_llm_raw_cluster(system, user_msg, model, cfg, max_tokens=128, plain_text=True)
    if not raw:
        return None
    raw = raw.strip()
    if raw.upper().startswith("CONFLICT"):
        return raw
    return None


def _next_num(directory: Path, prefix: str) -> int:
    existing = []
    for f in directory.glob("*.yaml"):
        try:
            r = yaml.safe_load(f.read_text(encoding="utf-8"))
            rid = r.get("id", "")
            if rid.startswith(prefix):
                num_part = rid[len(prefix):].split("-")[0]
                if num_part.isdigit():
                    existing.append(int(num_part))
        except Exception:
            pass
    return max(existing, default=0) + 1


def _synthesize_rule(raw_rec: str, existing_rules_md: str, model: str, cfg: dict) -> str | None:
    from agent.llm import call_llm_raw

    system = (
        "Convert the raw recommendation into a concise, actionable SQL planning rule. "
        "Start with 'Never', 'Always', or 'Use'. One self-contained paragraph. "
        "Include a concrete SQL example if helpful. "
        "If the recommendation is already fully covered by an existing rule, respond with exactly: null\n\n"
        f"Existing rules:\n{existing_rules_md}"
    )
    result = call_llm_raw(system, f"Raw recommendation:\n{raw_rec}",
                          model, cfg, max_tokens=512, plain_text=True)
    if not result:
        return None
    result = result.strip()
    return None if result.lower() == "null" else result


def _synthesize_security_gate(raw_rec: str, existing_security_md: str, model: str, cfg: dict) -> dict | None:
    from agent.llm import call_llm_raw
    from agent.json_extract import _extract_json_from_text

    system = (
        "If the recommendation is already fully covered by an existing gate, respond with exactly: null\n\n"
        f"Existing gates:\n{existing_security_md}\n\n"
        "Otherwise, convert the security recommendation into a gate spec. "
        "Return JSON: {\"pattern\": \"<regex or null>\", \"check\": \"<name or null>\", \"message\": \"<block reason>\"}. "
        "Exactly one of pattern or check must be non-null. "
        "If not blockable as a regex/check, return exactly: null"
    )
    result = call_llm_raw(system, f"Security recommendation:\n{raw_rec}",
                          model, cfg, max_tokens=256)
    if not result:
        return None
    result = result.strip()
    if result.lower() == "null":
        return None
    parsed = _extract_json_from_text(result)
    if not isinstance(parsed, dict) or not parsed.get("message"):
        return None
    if not parsed.get("pattern") and not parsed.get("check"):
        return None
    return parsed


def _synthesize_prompt_patch(raw_rec: str, existing_prompts_md: str, model: str, cfg: dict) -> dict | None:
    from agent.llm import call_llm_raw
    from agent.json_extract import _extract_json_from_text

    system = (
        "If the recommendation is already present in the existing prompt content, respond with exactly: null\n\n"
        f"Existing prompt files:\n{existing_prompts_md}\n\n"
        "Otherwise, convert the prompt optimization recommendation into a markdown rule block. "
        "Return JSON: {\"target_file\": \"<basename e.g. answer.md>\", \"content\": \"<markdown section starting with ## heading>\"}. "
        "If too vague to produce a concrete rule, return exactly: null"
    )
    result = call_llm_raw(system, f"Prompt recommendation:\n{raw_rec}",
                          model, cfg, max_tokens=512)
    if not result:
        return None
    result = result.strip()
    if result.lower() == "null":
        return None
    parsed = _extract_json_from_text(result)
    if not isinstance(parsed, dict):
        return None
    if not parsed.get("target_file") or not parsed.get("content"):
        return None
    return parsed


def _write_rule(num: int, content: str, entry: dict, raw_rec: str) -> Path:
    rule_id = f"sql-{num:03d}"
    dest = _RULES_DIR / f"{rule_id}.yaml"
    with open(dest, "w", encoding="utf-8") as f:
        yaml.dump({
            "id": rule_id, "phase": "sql_plan", "verified": True, "source": "eval",
            "content": content, "created": date.today().isoformat(),
            "eval_score": entry.get("score"),
            "raw_recommendation": raw_rec,
        }, f, allow_unicode=True, default_flow_style=False)
    print(f"[propose] created {dest.name}")
    return dest


def _write_security(num: int, gate_spec: dict, entry: dict, raw_rec: str) -> Path:
    gate_id = f"sec-{num:03d}"
    dest = _SECURITY_DIR / f"{gate_id}.yaml"
    record: dict = {
        "id": gate_id, "action": "block", "message": gate_spec["message"],
        "verified": True, "source": "eval", "created": date.today().isoformat(),
        "task_text": entry["task_text"][:120],
        "eval_score": entry.get("score"),
        "raw_recommendation": raw_rec,
    }
    if gate_spec.get("pattern"):
        record["pattern"] = gate_spec["pattern"]
    if gate_spec.get("check"):
        record["check"] = gate_spec["check"]
    with open(dest, "w", encoding="utf-8") as f:
        yaml.dump(record, f, allow_unicode=True, default_flow_style=False)
    print(f"[propose] created {dest.name}")
    return dest


def _write_prompt(patch_result: dict, entry: dict, raw_rec: str) -> Path:
    target = patch_result["target_file"]
    dest = _PROMPTS_DIR / target
    content = patch_result["content"]
    action = "updated"
    if dest.exists():
        existing = dest.read_text(encoding="utf-8")
        if content.strip() in existing:
            print(f"[propose] skipped {target} (already present)")
            return dest
        dest.write_text(existing.rstrip() + "\n\n" + content + "\n", encoding="utf-8")
    else:
        dest.write_text(content + "\n", encoding="utf-8")
        action = "created"
    print(f"[propose] {action} {target}")
    return dest


def _flatten_recs(
    entries: list[dict],
    channel: str,
    processed: set[str],
) -> list[dict]:
    """Flatten entries to dicts with (entry, rec) pairs, only processing outcome=ok entries.

    Returns list of entry dicts that have unprocessed recs in the given channel.
    """
    result = []
    for entry in entries:
        if entry.get("outcome") != "ok":
            continue
        # Collect entries that have recs in this channel and aren't fully processed
        if entry.get(channel, []):
            result.append(entry)
    return result


def _dedup_by_content_per_task(
    items: list[tuple[str, dict, str]],
) -> tuple[list[tuple[str, dict, str]], list[str]]:
    """Remove exact-duplicate recs within the same task_id. Returns (deduped, skipped_hashes)."""
    seen: set[tuple[str, str]] = set()
    result = []
    skipped: list[str] = []
    for rec, entry, h in items:
        key = (entry.get("task_id", ""), rec)
        if key in seen:
            skipped.append(h)
        else:
            seen.add(key)
            result.append((rec, entry, h))
    return result, skipped


def main(dry_run: bool = False) -> None:
    load_dotenv()
    model = os.environ.get("MODEL_EVALUATOR", "")
    if not model:
        print("ERROR: MODEL_EVALUATOR not set", file=sys.stderr)
        sys.exit(1)
    cfg = _load_model_cfg(model)

    if not _EVAL_LOG.exists():
        print(f"No eval log at {_EVAL_LOG}")
        return

    entries = [json.loads(l) for l in _EVAL_LOG.read_text().splitlines() if l.strip()]
    processed = _load_processed()
    rules_md = knowledge_loader.existing_rules_text()
    security_md = knowledge_loader.existing_security_text()
    prompts_md = knowledge_loader.existing_prompts_text()
    new_processed = set(processed)
    written = 0

    # --- Flatten per channel (skips success entries without evaluator) ---
    flattened_rules = _flatten_recs(entries, "rule_optimization", processed)
    flattened_security = _flatten_recs(entries, "security_optimization", processed)
    flattened_prompts = _flatten_recs(entries, "prompt_optimization", processed)

    rule_items: list[tuple[str, dict, str]] = [
        (rec, entry, _entry_hash(entry["task_text"], "rule", rec))
        for entry in flattened_rules
        for rec in entry.get("rule_optimization", [])
        if _entry_hash(entry["task_text"], "rule", rec) not in processed
    ]
    security_items: list[tuple[str, dict, str]] = [
        (rec, entry, _entry_hash(entry["task_text"], "security", rec))
        for entry in flattened_security
        for rec in entry.get("security_optimization", [])
        if _entry_hash(entry["task_text"], "security", rec) not in processed
    ]
    prompt_items: list[tuple[str, dict, str]] = [
        (rec, entry, _entry_hash(entry["task_text"], "prompt", rec))
        for entry in flattened_prompts
        for rec in entry.get("prompt_optimization", [])
        if _entry_hash(entry["task_text"], "prompt", rec) not in processed
    ]

    # Content-hash dedup: within same task_id, identical recs validated once
    rule_items, rule_dup_hashes = _dedup_by_content_per_task(rule_items)
    new_processed.update(rule_dup_hashes)
    security_items, sec_dup_hashes = _dedup_by_content_per_task(security_items)
    new_processed.update(sec_dup_hashes)
    prompt_items, prompt_dup_hashes = _dedup_by_content_per_task(prompt_items)
    new_processed.update(prompt_dup_hashes)

    # --- Pre-cluster per channel ---
    rule_clusters = _cluster_recs(rule_items, rules_md, model, cfg) if rule_items else []
    security_clusters = _cluster_recs(security_items, security_md, model, cfg) if security_items else []
    prompt_clusters = _cluster_recs(prompt_items, prompts_md, model, cfg) if prompt_items else []

    # --- Process representatives ---
    for raw_rec, entry, all_hashes in rule_clusters:
        print(f"[rule] {raw_rec[:80]}...")
        content = _synthesize_rule(raw_rec, rules_md, model, cfg)
        if content is None:
            new_processed.update(all_hashes)
            print("  → skip (null/duplicate)")
            continue
        conflict = _check_contradiction(content, rules_md, model, cfg)
        if conflict:
            print(f"  → skip (contradiction: {conflict})")
            continue
        num = _next_num(_RULES_DIR, "sql-")
        if dry_run:
            print(f"  → [DRY RUN] sql-{num:03d}.yaml: {content[:100]}")
        else:
            dest = _write_rule(num, content, entry, raw_rec)
            new_processed.update(all_hashes)
            written += 1
            rules_md = knowledge_loader.existing_rules_text()

    for raw_rec, entry, all_hashes in security_clusters:
        print(f"[security] {raw_rec[:80]}...")
        gate_spec = _synthesize_security_gate(raw_rec, security_md, model, cfg)
        if gate_spec is None:
            new_processed.update(all_hashes)
            print("  → skip (null/not-applicable)")
            continue
        conflict = _check_contradiction(gate_spec.get("message", ""), security_md, model, cfg)
        if conflict:
            print(f"  → skip (contradiction: {conflict})")
            continue
        num = _next_num(_SECURITY_DIR, "sec-")
        if dry_run:
            print(f"  → [DRY RUN] sec-{num:03d}.yaml: {gate_spec.get('message', '')}")
        else:
            dest = _write_security(num, gate_spec, entry, raw_rec)
            new_processed.update(all_hashes)
            written += 1
            security_md = knowledge_loader.existing_security_text()

    for raw_rec, entry, all_hashes in prompt_clusters:
        print(f"[prompt] {raw_rec[:80]}...")
        patch_result = _synthesize_prompt_patch(raw_rec, prompts_md, model, cfg)
        if patch_result is None:
            new_processed.update(all_hashes)
            print("  → skip (null/vague)")
            continue
        conflict = _check_contradiction(patch_result.get("content", ""), prompts_md, model, cfg)
        if conflict:
            print(f"  → skip (contradiction: {conflict})")
            continue
        if dry_run:
            print(f"  → [DRY RUN] {patch_result['target_file']}: {patch_result['content'][:80]}")
        else:
            dest = _write_prompt(patch_result, entry, raw_rec)
            new_processed.update(all_hashes)
            written += 1
            prompts_md = knowledge_loader.existing_prompts_text()

    if not dry_run:
        _save_processed(new_processed)
        print(f"\nDone. {written} candidate(s) written.")
    else:
        total = len(rule_items) + len(security_items) + len(prompt_items)
        print(f"\n[DRY RUN] {total} entry(ies) would be processed (before clustering).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
