from agent.investigate import descriptors_from_intent, run_resolution_probe, Brief
from agent.ir_models import IntentSpec, AnswerShape, RefSpec


def _intent():
    return IntentSpec(
        objective="count units",
        desired_outcome="OUTCOME_OK",
        params={"product_brand": "literal 'Sika' from instruction",
                "volume": "literal '100 ml' from instruction"},
        outcome_space=["OUTCOME_OK", "OUTCOME_NONE_UNSUPPORTED"],
        answer_shape=AnswerShape(msg_skeleton="count: %d"),
        required_refs={"OUTCOME_OK": [RefSpec(kind="record_path", source="$product.record_path")]},
    )


class _VM:
    def exec(self, path=None, stdin=None, **kw):
        class R: stdout = "product_sku,record_path\nSKU-9,/proc/products/sku-9.json\n"
        return R()


def test_descriptors_parse_prose_params():
    cols, props = descriptors_from_intent(_intent())
    assert cols.get("brand") == "Sika"
    assert props.get("volume") == "100 ml"


def test_probe_binds_resolved_record_path():
    brief = Brief()
    run_resolution_probe(_VM(), _intent(), brief)
    assert brief.env.get("resolved_product_record_path") == "/proc/products/sku-9.json"
    assert brief.env.get("resolved:$product.record_path") == "/proc/products/sku-9.json"
