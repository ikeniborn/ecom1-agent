from agent.resolve import normalize_value, sql_quote, relax_sql, literal_from_prose


def test_normalize_strips_unit_suffix_and_case():
    assert normalize_value("8 l") == "8"
    assert normalize_value("1000 ml") == "1000"
    assert normalize_value("900 mm") == "900"
    assert normalize_value("  Gray ") == "gray"
    assert normalize_value("Tool   Bag") == "tool bag"
    assert normalize_value("20 V") == "20"
    assert normalize_value("hybrid sealant") == "hybrid sealant"


def test_sql_quote_escapes():
    assert sql_quote("a'b") == "'a''b'"


def test_literal_from_prose():
    assert literal_from_prose("literal 'Sika' from instruction") == "Sika"
    assert literal_from_prose("literal '100 ml' from instruction") == "100 ml"
    assert literal_from_prose("Vienna") == "Vienna"


def test_relax_sql_text_predicate():
    out = relax_sql("SELECT 1 WHERE pv.color_family = 'Gray'")
    assert "lower(trim(pv.color_family))" in out.lower()
    assert "'gray'" in out.lower()


def test_relax_sql_numeric_fallback_on_property_value_text():
    out = relax_sql("SELECT 1 WHERE p0.property_value_text = '8 l'").lower()
    assert "p0.property_value_number = 8" in out
    assert "lower(trim(p0.property_value_text))" in out


def test_relax_sql_noop_without_equality():
    sql = "SELECT count(*) FROM stores"
    assert relax_sql(sql) == sql


from agent.resolve import resolve_product


class _FakeVM:
    def __init__(self): self.calls = []
    def exec(self, path=None, stdin=None, **kw):
        self.calls.append(stdin or "")
        class R: pass
        r = R()
        r.stdout = ("product_sku,record_path\nSKU-1,/proc/products/sku-1.json\n"
                    if "lower(" in (stdin or "").lower()
                    else "product_sku,record_path\n")
        return r


def test_resolve_product_falls_through_to_relaxed():
    vm = _FakeVM()
    rows = resolve_product(vm, columns={"brand": "Milwaukee"}, properties={"volume": "8 l"})
    assert rows == [{"product_sku": "SKU-1", "record_path": "/proc/products/sku-1.json"}]
    assert len(vm.calls) >= 2
