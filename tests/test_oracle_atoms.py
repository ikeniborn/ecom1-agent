import textwrap
from agent.oracle_atoms import Atom, load_atoms, save_atoms, content_hash, build_oracle_block


def test_load_parses_atoms(tmp_path):
    p = tmp_path / "atoms.yaml"
    p.write_text(textwrap.dedent("""
        - id: sql-no-name-binds
          description: "no :name binds"
          domain: [sql, vm-io]
          content: "inline literals"
          source: investigation
          validated_by: manual
          validated_at: '2026-06-05'
          status: active
          embedding_hash: deadbeef
    """))
    atoms = load_atoms(p)
    assert len(atoms) == 1
    a = atoms[0]
    assert a.id == "sql-no-name-binds"
    assert a.domain == ["sql", "vm-io"]
    assert a.status == "active"


def test_content_hash_changes_with_content():
    assert content_hash("a") != content_hash("b")
    assert content_hash("a") == content_hash("a")


def test_active_filter():
    atoms = [
        Atom(id="x", description="d", domain=[], content="c", source="s",
             validated_by="manual", validated_at="2026-06-05", status="active",
             embedding_hash=""),
        Atom(id="y", description="d", domain=[], content="c", source="s",
             validated_by="manual", validated_at="2026-06-05", status="candidate",
             embedding_hash=""),
    ]
    assert [a.id for a in atoms if a.status == "active"] == ["x"]


def test_save_roundtrip(tmp_path):
    p = tmp_path / "atoms.yaml"
    atoms = [Atom(id="x", description="d", domain=["sql"], content="c", source="s",
                  validated_by="manual", validated_at="2026-06-05", status="active",
                  embedding_hash="h")]
    save_atoms(p, atoms)
    again = load_atoms(p)
    assert again[0].id == "x" and again[0].domain == ["sql"]


def _atom():
    return Atom(id="sql-no-name-binds", description="d", domain=["sql"],
                content="inline quoted literals in IN()", source="s",
                validated_by="grader", validated_at="d", status="active",
                embedding_hash="")


def test_block_lists_atom_content():
    block = build_oracle_block([_atom()])
    assert "VALIDATED KNOWLEDGE" in block
    assert "inline quoted literals" in block


def test_empty_atoms_yields_empty_block():
    assert build_oracle_block([]) == ""


def test_codegen_v2_reexports_build_oracle_block():
    # design.py imports it from codegen_v2 until Task 5; the re-export must hold.
    from agent.codegen_v2 import build_oracle_block as via_codegen
    assert via_codegen([]) == ""
