# Data Models

Pipeline models are Pydantic. IR models (`agent/ir_models.py`) define the interpreter contract; `agent/models.py` holds the LEARN and answer outputs. All IR models use `extra="forbid"`.

## IntentSpec (`ir_models.py`)

Frozen INTENT output.

Fields: `objective`, `desired_outcome`, `params`, `outcome_space` (allowed outcomes), `constraints` (list of `Constraint`), `success_criteria` (list of `PredExpr`), `answer_shape` (`AnswerShape.msg_skeleton`), `required_refs` (dict keyed by outcome → list of `RefSpec`).

- `Constraint` — `anchor`, `rule`, `security` flag, `deny_when` (`PredExpr`; True ⇒ I3 deny, security only).
- `RefSpec` — `kind` (`policy_doc` literal `path` | `record_path` runtime `source`).

## PlanIR (`ir_models.py`)

Per-cycle PLAN output.

Fields: `discovery` (list of `Step`), `rowsets` (list of `RowSet`), `compute` (list of `ComputeStep`), `decision` (`DecisionTree`), `ops` (list of `GuardedOp`), `answer` (dict outcome → `AnswerTemplateIR`), `custom_extract` (list of `CustomExtract`).

- `Step` / `GuardedOp` — `rpc`, `args`, `bind`; `GuardedOp` adds `guard_label` + `outcome_from_exit` (`OutcomeFromExit`: `ok_outcome` + `keyword_buckets` + `default_outcome`).
- `RowSet` — `from` / `format` / `into` + `columns` (`ColResolve`: alias first present header from `candidates`).
- `ComputeStep` — `prim`, `args`, `into`. `CustomExtract` — `name`, `input`, `into`.
- `DecisionTree` — `branches` (`Branch`: `when` PredExpr + `label`) + `default_label`.

## PredExpr (`ir_models.py`)

Single predicate language shared by `decision`, `success_criteria`, and security `deny_when`.

Leaf ops: `eq/ne/lt/le/gt/ge`, `nonempty/isnull`, `contains_any/in_set/startswith/endswith/regex_match`. Bool ops: `and/or/not`. A string starting with `$` is a ref into `env`; anything else is a literal.

## LearnConsolidateOutput (`models.py`)

LEARN output. Fields: `rule_content?`, `agents_md_anchor?`, `reasoning`, `deactivate_ids`, `deactivate_reason?`, `skip`, `skip_reason?`, `prephase_deep_read`. Null `rule_content` allowed when `skip=True` or only deactivating prior rules.

## AnswerOutput (`models.py`)

`message`, `outcome` (one of `OUTCOME_OK` / `OUTCOME_NONE_CLARIFICATION` / `OUTCOME_NONE_UNSUPPORTED` / `OUTCOME_DENIED_SECURITY`), `grounding_refs`.

## Learned YAML

`data/learned/{task_id}.yaml` stores active/inactive rule entries, a `last_run` block (`status` / `outcome` / `cycles_used` / `date`), and `prephase_deep_read`. Managed by `learned_store.py`. See [[constraints]].

Each entry: `id` (`rNNN` / `vNNN`), `content`, `status`, `source`, `reasoning`. Content under `_MIN_CONTENT_LEN` chars or not starting with a `_VALID_RULE_STARTS` prefix is rejected by `apply_learn_diff`.
