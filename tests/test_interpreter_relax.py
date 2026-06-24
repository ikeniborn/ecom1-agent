# tests/test_interpreter_relax.py
from agent.ir_models import PlanIR, IntentSpec, AnswerShape
from agent import interpreter


class _RelaxVM:
    """Exact query (no LOWER) → 0 rows; relaxed query (has LOWER) → 1 row."""
    def __init__(self):
        self.sqls = []

    def exec(self, path=None, stdin=None, **kw):
        self.sqls.append(stdin or "")
        class R:
            pass
        r = R()
        if "lower(" in (stdin or "").lower():
            r.stdout = "product_sku,record_path\nSKU-7,/proc/products/sku-7.json\n"
        else:
            r.stdout = "product_sku,record_path\n"
        r.exit_code = 0
        return r


def _plan(sql):
    return PlanIR.model_validate({
        "discovery": [{"rpc": "Exec", "args": {"path": "/bin/sql", "stdin": sql}, "bind": "res"}],
        "rowsets": [], "compute": [], "custom_extract": [],
        "decision": {"branches": [], "default_label": "ok"},
        "ops": [],
        "answer": {"ok": {"message": "done", "outcome": "OUTCOME_OK", "refs": []}},
    })


def _intent():
    return IntentSpec(objective="x", desired_outcome="OUTCOME_OK",
                      outcome_space=["OUTCOME_OK"], answer_shape=AnswerShape(msg_skeleton="x"))


def test_zero_row_resolving_step_is_retried_relaxed():
    vm = _RelaxVM()
    sql = "SELECT product_sku, record_path FROM product_variants pv WHERE pv.brand = 'Sika'"
    res = interpreter.interpret(_plan(sql), _intent(), vm)
    assert any("lower(" in s.lower() for s in vm.sqls), "relaxed retry was issued"
    assert "SKU-7" in interpreter._payload(res.env["res"]), "relaxed result rebound into env"
