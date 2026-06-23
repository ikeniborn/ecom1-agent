"""Tests for Phase 2.1 pinned method-rules in t38 and t50 learned stores."""
from agent.learned_store import load_entries


def test_t38_g001_active_and_method_shaped():
    entries = load_entries("t38")
    g = next((e for e in entries if e.get("id") == "g001"), None)
    assert g is not None, "g001 not found in t38 active entries"
    assert g.get("status") == "active"
    assert g.get("surface") == "ir"
    assert g.get("pinned") is True
    content = g.get("content") or ""
    assert "read-only" in content.lower() or "read only" in content.lower()
    assert "mutation" in content.lower()


def test_t50_g001_active_and_method_shaped():
    entries = load_entries("t50")
    g = next((e for e in entries if e.get("id") == "g001"), None)
    assert g is not None, "g001 not found in t50 active entries"
    assert g.get("status") == "active"
    assert g.get("surface") == "ir"
    assert g.get("pinned") is True
    content = g.get("content") or ""
    assert "checkout" in content.lower()
    assert "protected_action" in content


def test_t38_g001_is_no_answer_value():
    """Rule must be method-shaped — no baked task-specific data values."""
    entries = load_entries("t38")
    g = next((e for e in entries if e.get("id") == "g001"), None)
    assert g is not None
    content = (g.get("content") or "").lower()
    # method rule must not contain task-specific record paths or amounts
    assert "/proc/" not in content
    assert "/data/" not in content


def test_t50_g001_is_no_answer_value():
    """Rule must be method-shaped — no baked task-specific data values."""
    entries = load_entries("t50")
    g = next((e for e in entries if e.get("id") == "g001"), None)
    assert g is not None
    content = (g.get("content") or "").lower()
    # method rule must not contain task-specific basket ids or amounts
    assert "basket_" not in content or "basket submission" in content
    assert "/proc/" not in content
