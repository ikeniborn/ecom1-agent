"""Verify main.py creates/closes TraceLogger and calls log_header + log_task_result."""
import json
from unittest.mock import MagicMock, patch


def test_run_single_task_creates_jsonl_and_removes_log(tmp_path, monkeypatch):
    """After _run_single_task + _finalize_task_trace: .jsonl has header + task_result; no .log file."""
    import main as m

    monkeypatch.setattr(m, "_run_dir", tmp_path)

    fake_trial = MagicMock()
    fake_trial.task_id = "t01"
    fake_trial.trial_id = "trial-1"
    fake_trial.harness_url = "http://x"
    fake_trial.instruction = "find item"

    fake_client = MagicMock()
    fake_client.start_trial.return_value = fake_trial
    fake_client.end_trial.return_value = MagicMock()

    with patch("main.HarnessServiceClientSync", return_value=fake_client), \
         patch("main.run_agent", return_value={"input_tokens": 10, "output_tokens": 5,
                                                "outcome": "OUTCOME_OK", "cycles_used": 1,
                                                "task_type": "lookup", "model_used": "m"}):
        task_id, _trial_id, elapsed, token_stats, trace, filtered = m._run_single_task("trial-1", [])

    assert not filtered
    m._finalize_task_trace(trace, task_id, score=1.0, detail=["ok"], elapsed=elapsed, token_stats=token_stats)

    jsonl_path = tmp_path / "t01.jsonl"
    assert jsonl_path.exists(), "t01.jsonl must be created"
    assert not (tmp_path / "t01.log").exists(), "t01.log must NOT be created"

    records = [json.loads(ln) for ln in jsonl_path.read_text().splitlines() if ln.strip()]
    types = [r["type"] for r in records]
    assert "header" in types
    assert "task_result" in types


def test_main_log_contains_only_stats(tmp_path, monkeypatch):
    """main.log must contain stats rows but NOT pipeline cycle lines."""
    monkeypatch.setenv("ECOM_MODEL", "test-model")
    import main as m
    import io

    stats_buf = io.StringIO()
    monkeypatch.setattr(m, "_run_dir", tmp_path)
    monkeypatch.setattr(m, "_stats_fh", stats_buf)

    # Simulate a table header + one row + summary
    m._print_table_header()
    m._print_table_row("t01", 1.0, [], 12.5, {
        "input_tokens": 100, "output_tokens": 50,
        "task_type": "lookup", "model_used": "anthropic/claude-sonnet-4-6",
    })
    m._write_summary([("t01", 1.0, [], 12.5, {"input_tokens": 100, "output_tokens": 50})], 0.0)

    contents = stats_buf.getvalue()
    assert "ИТОГОВАЯ СТАТИСТИКА" in contents
    assert "t01" in contents
    assert "ИТОГО" in contents
    # Must NOT contain pipeline noise
    assert "[pipeline]" not in contents
    assert "cycle=" not in contents
