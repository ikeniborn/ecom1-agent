from pathlib import Path
from agent.learned_store import load_entries
from agent.oracle_atoms import load_atoms


def test_t01_active_rule_is_method_not_value():
    entries = load_entries("t01")
    text = " ".join((e.get("content") or "") for e in entries).lower()
    assert "normal" in text                 # normalized matching method
    assert "first" in text and "get" in text  # first->get discipline (not column on a row)
    # no baked re-seeded values from the diagnosis
    assert "sto-12jlht7d" not in text and "fst-apsrizjw" not in text


def test_t01_misdirected_format_rule_deactivated():
    # r003 blamed rowset `format` for the F1 interpreter bug — it must be inactive.
    active_ids = {e.get("id") for e in load_entries("t01")}
    assert "r003" not in active_ids


def test_t01_method_rule_is_pinned():
    entries = load_entries("t01")
    pinned = [e for e in entries if e.get("pinned") is True]
    assert pinned, "expected at least one pinned rule in active t01 entries"
    # the pinned rule must carry the fuzzy-match method tokens
    pinned_text = " ".join((e.get("content") or "") for e in pinned).lower()
    assert "normal" in pinned_text
    assert "first" in pinned_text
    assert "get" in pinned_text


def test_oracle_has_normalized_catalogue_atom():
    atoms = load_atoms(Path("data/oracle/atoms.yaml"))
    assert any("normal" in a.content.lower()
               and "catalog" in (" ".join(a.domain) + " " + a.content).lower()
               for a in atoms)
