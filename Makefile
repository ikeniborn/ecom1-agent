# AICODE-NOTE: Keep these wrappers aligned with the README commands so the sample
# stays trivial to run from a fresh checkout without inventing parallel workflows.

.PHONY: sync run task graph-health promote

sync:
	uv sync

# FIX-388: graph health gate. Set GRAPH_HEALTH=0 to skip (e.g. CI rebuilding from scratch).
graph-health:
	uv run python scripts/check_graph_health.py

run:
	uv run python main.py

task:
	@if [ -z "$(TASKS)" ]; then echo "usage: make task TASKS='t01 t03'"; exit 1; fi
	uv run python main.py $(TASKS)

promote:
	uv run python main.py --promote
