# Data Models

All pipeline phase outputs are Pydantic models in `agent/models.py`. Each model maps to one LLM call's parsed JSON response.

## IddOutput

Intent layer output: captures WHAT, WHY, gate decision, and scope estimate.

Fields: `intent_objective` (WHAT+WHY), `reformulated_task` (explicit, no pronouns), `intent_type` (read/write/security_check/compute), `extracted_params`. Gate: `decision` (proceed/hard_stop), `stop_code`, `stop_message`, `stop_refs`. Performance: `scope_estimate` with `files_to_read` and `estimated_cycles`. Expectation contract: `success_criteria`, `stop_rules`, `health_metrics`.

## SddOutput

`spec_goal`: one-line execution objective. `success_criteria`: observable conditions. `plan`: reasoning steps. `actions`: ordered candidate action strings for PLAN. `error_code`: `"DENIED_SECURITY"`, `"UNSUPPORTED"`, or empty.

## PlanOutput

`approach`: reasoning. `steps`: execution steps. `action`: selected action string.

Model validator coerces `action` from list to scalar — guards against LLM returning array.

## ExecuteOutput

`results`: list of dicts with `"output"` key. `action`: executed string. Constructed by pipeline code, not LLM.

## LearnOutput

Encodes rule extraction result. Uses `extra="forbid"` to catch hallucinated fields.

`rule_content`: rule text to persist. `reasoning`: why this rule. `conclusion`: summary. `agents_md_anchor`: if set, triggers vault section lookup. `deactivate`: entry IDs to mark inactive. `skip`/`skip_reason`: signals no new rule needed.

## ConsolidateOutput / ConsolidationItem

`skip`: LLM signals no consolidation needed. `consolidations`: list of `ConsolidationItem`.

Each `ConsolidationItem`: `deactivate` (IDs to remove), `merged_rule` (replacement), `merged_reasoning`.

## AnswerOutput

`reasoning`: internal chain-of-thought. `outcome`: one of `OUTCOME_OK`, `OUTCOME_NONE_CLARIFICATION`, `OUTCOME_NONE_UNSUPPORTED`, `OUTCOME_DENIED_SECURITY`.

`message`: user-facing response. `grounding_refs`: file paths cited as evidence. `completed_steps`: steps executed.

## Learned YAML Format

`data/learned/{task_id}.yaml` stores `task_id`, `last_run` metadata, and `entries` list.

Each entry: `id` (rNNN monotonic), `content`, `status` (active/inactive), `source`, `created`, `reasoning`, `deactivated_reason`. Content under 20 chars or not starting with known action prefixes is rejected by `_apply_learn_diff`.
