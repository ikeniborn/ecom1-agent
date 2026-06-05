from agent.oracle_atoms import load_atoms

PATH = "data/oracle/atoms.yaml"


def test_seed_atoms_present_and_valid():
    atoms = load_atoms(PATH)
    ids = {a.id for a in atoms}
    for required in {"fraud-impossible-travel", "sql-no-name-binds",
                     "catalog-price-ex-vat", "never-read-directory"}:
        assert required in ids, f"missing seed atom {required}"
    for a in atoms:
        assert a.content.strip()
        assert a.status in {"active", "candidate"}
        assert "dev_" not in a.content and "cust_" not in a.content


def test_no_task_ids_in_atoms():
    for a in load_atoms(PATH):
        assert "t38" not in a.id and "t51" not in a.id
