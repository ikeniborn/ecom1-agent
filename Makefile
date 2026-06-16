# AICODE-NOTE: Keep these wrappers aligned with the README commands so the sample
# stays trivial to run from a fresh checkout without inventing parallel workflows.

.PHONY: sync run task graph-health promote

sync:
	uv sync

run:
	uv run python main.py

report:
	uv run python scripts/run_report.py

task:
	@if [ -z "$(TASKS)" ]; then echo "usage: make task TASKS='t01 t03'"; exit 1; fi
	uv run python main.py $(TASKS)

promote:
	uv run python main.py --promote
