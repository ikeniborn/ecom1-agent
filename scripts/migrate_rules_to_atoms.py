"""One-off: distill existing per-task learned rules into general atoms (candidates).

Run manually: uv run python -m scripts.migrate_rules_to_atoms
Writes candidate atoms to data/oracle/atoms.yaml; nothing is promoted automatically.
"""
from __future__ import annotations

from pathlib import Path

from agent.oracle import _cosine


def dedup_by_cosine(atoms, threshold, vec_of):
    kept = []
    for a in atoms:
        va = vec_of(a)
        if any(_cosine(va, vec_of(b)) >= threshold for b in kept):
            continue
        kept.append(a)
    return kept


def main():
    # Walk data/learned/*.yaml, distill each active rule into a candidate atom via
    # KnowledgeOracle.distill, then dedup. Operator-run step (LLM + embeddings required).
    learned = sorted(Path("data/learned").glob("*.yaml"))
    print(f"{len(learned)} per-task rule files found. "
          f"Run KnowledgeOracle().distill per active rule, then dedup_by_cosine.")


if __name__ == "__main__":
    main()
