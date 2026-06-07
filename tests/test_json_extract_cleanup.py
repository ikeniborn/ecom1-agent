import agent.json_extract as je


def test_normalize_parsed_removed():
    assert not hasattr(je, "_normalize_parsed"), "_normalize_parsed should be removed"


def test_extract_json_fenced_block():
    text = '```json\n{"reasoning": "test", "queries": ["SELECT 1"]}\n```'
    result = je._extract_json_from_text(text)
    assert result == {"reasoning": "test", "queries": ["SELECT 1"]}


def test_extract_json_plain_object():
    text = 'Some text {"queries": ["SELECT COUNT(*) FROM products"]} more text'
    result = je._extract_json_from_text(text)
    assert result is not None
    assert "queries" in result


def test_extract_json_mutation_preferred():
    text = '{"tool": "read", "path": "/x"} {"tool": "write", "path": "/y", "content": "z"}'
    result = je._extract_json_from_text(text)
    assert result is not None
    assert result.get("tool") == "write"


def test_extract_json_returns_none_for_no_json():
    result = je._extract_json_from_text("no json here at all")
    assert result is None


def test_extract_script_code_with_braces_in_fenced_json():
    """codegen returns {"script_code": "...python with {dict} braces..."} in a
    ```json fence. Non-greedy level-1 regex truncated at the first inner '}';
    the bracket loop must skip string contents. Regression: t02 cycles 3-4
    'could not parse script_code'."""
    text = (
        '```json\n'
        '{"script_code": "def run(vm, p):\\n    d = {\\"a\\": 1}\\n    return d"}\n'
        '```'
    )
    obj = je._extract_json_from_text(text)
    assert obj is not None
    assert "script_code" in obj
    assert "{" in obj["script_code"] and "}" in obj["script_code"]


def test_extract_object_with_braces_and_close_brace_in_string_unfenced():
    """String-aware depth: a literal '}' inside a quoted value must not close
    the object early (no fence here, so the bracket matcher is exercised)."""
    text = 'noise {"script_code": "x = {1: 2}; y = \\"}\\""} trailing'
    obj = je._extract_json_from_text(text)
    assert obj is not None
    assert obj.get("script_code") == 'x = {1: 2}; y = "}"'
