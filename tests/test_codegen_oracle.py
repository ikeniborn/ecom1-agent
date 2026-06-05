from agent.codegen_v2 import build_oracle_block
from agent.oracle_atoms import Atom


def test_block_lists_atom_content():
    atoms = [Atom(id="sql-no-name-binds", description="d", domain=["sql"],
                  content="inline quoted literals in IN()", source="s",
                  validated_by="grader", validated_at="d", status="active",
                  embedding_hash="")]
    block = build_oracle_block(atoms)
    assert "VALIDATED KNOWLEDGE" in block
    assert "inline quoted literals" in block


def test_empty_atoms_yields_empty_block():
    assert build_oracle_block([]) == ""
