"""Stage-2 LLM re-rank of cosine candidate atoms."""
from __future__ import annotations

import os

from .llm import call_llm_json

_SYS = (
    "You select which knowledge snippets are RELEVANT to a coding task. "
    "Return JSON {\"keep\": [ids]} listing only the ids whose content would help "
    "write the task's script, most relevant first."
)


def llm_rerank(task_text, candidates, k):
    catalog = "\n".join(f"- {a.id}: {a.description}" for a in candidates)
    user = (f"TASK:\n{task_text}\n\nCANDIDATE KNOWLEDGE:\n{catalog}\n\n"
            f"Return at most {k} ids in JSON {{\"keep\": [...]}}.")
    model = os.environ.get("MODEL_RANK") or os.environ.get("MODEL", "")
    out = call_llm_json(_SYS, user, model)
    keep = list(out.get("keep", [])) if isinstance(out, dict) else []
    by_id = {a.id: a for a in candidates}
    return [by_id[i] for i in keep if i in by_id]
