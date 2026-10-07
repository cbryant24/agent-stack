# Phase 4 — `visual-generation chat`: evaluation records and memory writes

**Goal:** your reactions and evaluations become structured, lineage-linked records in `visual_generation_memory`, written only after you confirm each one.

**Depends on:** Phase 3. **Spends GPU:** no. **LLM spend:** REPL turns.

## Ownership rule

Repo rule: only the owning agent writes to its own collection, and only `UserKnowledgeStore` writes to `user_knowledge`. So every new write path is a function on the `visual-generation` store. The chat tools call those functions and add the gate. `visual_generation/chat/` contains no Qdrant client code.

## Schemas

These follow `evaluation-charter.md` (three score layers, status vocabulary, attempt record) and the guardrails in `agent-retrospective-corrections.md` §D. They replace the simpler prompt / implementation / outcome split from the first report.

```python
class Layer(str, Enum):
    PLATFORM = "platform"                      # pod, volume, model load, retrieval of outputs
    AGENT_CORRECTNESS = "agent_correctness"    # submitted graph vs spec: seed, slots, LoRAs, sources
    CONDITIONING_ASSET = "conditioning_asset"  # identity, staging, set: references, plates, masks
    PROMPT = "prompt"                          # wording, negations, length
    OUTCOME = "outcome"                        # rendered faithfully, misses a stated requirement or taste

class Evidence(str, Enum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    UNRESOLVED = "unresolved"

class Finding(BaseModel):
    layer: Layer
    evidence: Evidence
    statement: str
    basis: str                 # what was looked at: graph path, record field, image region
    suggested_action: str | None

class KeepConstraint(BaseModel):
    attribute: str             # "jaw"
    source_gen_id: str         # resolved from "attempt-07"

class EvaluationRecord(BaseModel):
    kind: Literal["evaluation"] = "evaluation"
    eval_id: str
    gen_id: str
    chain_root_id: str
    project: str
    question: str | None            # the single question this attempt was meant to answer
    reaction: str                   # existing REACTIONS vocabulary
    rating: int | None
    raw_feedback: str               # verbatim
    keep: list[KeepConstraint]
    change: list[str]
    findings: list[Finding]
    required_outcomes: list[str]
    infrastructure_status: str | None   # charter status vocabulary
    agent_status: str | None
    visual_status: str | None
    director_signoff: bool = False
    strike_class: str | None        # fix class this attempt belongs to, for three-strikes counting
    session_id: str
    engine_provider: str
    engine_model: str
    created_at: datetime

class LessonCandidate(BaseModel):
    statement: str
    scope: str                      # existing lesson scopes
    valence: Literal["positive", "negative"]
    layer: Layer
    source_eval_ids: list[str]
    evidence_n: int
    falsification_test: str | None  # required when layer is PROMPT and the topic is identity, staging or set
    claim_level: Literal["tuned", "validated"] = "tuned"   # "validated" needs held-out evidence

class RevisedSpecProposal(BaseModel):
    base_gen_id: str
    mode: Literal["redraft", "refine_img2img", "inpaint", "new_draft"]
    locked: list[str]
    changes: list[str]
    open_parameters: list[str]      # things the director must decide; the model does not invent numbers

class FeedbackInterpretation(BaseModel):
    evaluation: EvaluationRecord
    revised_spec: RevisedSpecProposal
    lessons: list[LessonCandidate]
    open_questions: list[str]
```

Rules enforced in code, not left to the prompt:

- A `LessonCandidate` at `PROMPT` layer about identity, staging or set geometry is rejected without a `falsification_test`.
- `claim_level="validated"` is rejected unless `evidence_n >= 5` and a held-out evaluation id is cited.
- When three evaluations in one chain share a `strike_class` with a negative reaction, the next proposal must include an architecture question naming the layer blamed and the alternative layer. The tool refuses a fourth same-class `redraft` proposal until that question is recorded.
- Numeric settings come from the record or from you. The model does not emit new numeric values in a proposal.

## New library functions in `visual-generation`

| Function | Does |
|---|---|
| `record_evaluation(record)` | Upserts an `evaluation` point linked to `gen_id` / `chain_root_id`, and calls `report_sync` for the reaction so existing retrieval and `review-pending` keep working. |
| `add_lesson(...)`, `add_fact(...)` | Extracted from the inline CLI logic. Lessons gain optional `layer`, `evidence_n`, `falsification_test`, `claim_level`. |
| `remove_lesson(...)`, `remove_batch_spec(...)` | Extracted. |
| `register_workflow(...)`, `sync_models(...)` | Extracted, keeping their propose then confirm shape. |
| `list_evaluations(gen_id | chain_root_id | project)` | Read path; `recall` returns evaluations as a fourth kind. |

Before adding payload fields, align names with the existing models found in Phase 0. Add the `evaluation` kind additively; existing points are untouched.

## Tools

| Tool | Effect | Gate shows |
|---|---|---|
| `report` | MEMORY_WRITE | gen id, reaction, rating, notes |
| `record_evaluation` | MEMORY_WRITE | the full record, rendered |
| `add_lesson`, `add_fact` | MEMORY_WRITE | statement, scope, layer, claim level |
| `lesson_rm`, `batch_rm`, `model_rm`, `canon_rm` | DESTRUCTIVE_LOCAL | the exact item |
| `canon_set`, `canon_edit` | MEMORY_WRITE | the diff |
| `workflow_register` | MEMORY_WRITE | proposed slot map |
| `list_evaluations` | READ | — |

Flow: you give feedback, the model calls `propose_interpretation`, you see the rendered proposal and choose y/n/edit/defer. On accept, `record_evaluation` runs through the gate. Lessons are offered one at a time and are never auto-confirmed. Anything still unwritten at `/exit` is offered again by the end-of-session proposal flow; deferred items queue under `~/agent-data/drafts/visual-generation/`.

`fact add` writes to `user_knowledge`, which only `UserKnowledgeStore` may write, through its propose then confirm workflow. The `add_fact` tool uses that path; the chat gate is the confirm step.

## First job for this phase

The retrospective §B1 lists three lessons to rewrite and three to add, and says those are "follow-up actions for their own sessions". Doing them through the new tools is the acceptance exercise for this phase.

## What was built (and where it differs from the plan above)

- **Names.** The persisted model is `EvaluationEntry` in the library (`memory_type="evaluation"`, `entry_id` = the eval id), not `kind`/`eval_id`, to match every other payload. It lives in `visual_generation.models` because the library cannot import `chat/`. Added to `TechniqueLesson`: optional `layer`, `evidence_n`, `falsification_test`, `claim_level` (lessons stored before load unchanged). Added to the evaluation: `architecture_question`, so "recorded" has somewhere to live.
- **Layers.** The five-valued `Layer` replaces Phase 3's score-layer + attribution pair; the prompt still quotes the three score layers and maps `outcome` to production quality.
- **`record_evaluation`** takes the full record as its arguments (not a proposal id) so a deferred record is self-contained and the gate shows exactly what will be written. It calls the async `report()` (not `report_sync`, which uses `asyncio.run`), writes the evaluation first, and its id is `uuid5(gen, reaction, feedback)` so a retry or re-confirm never duplicates. A failure of the second step is reported as a partial write.
- **Rules in code**, in the library so no caller can skip them: prompt-layer conditioning lessons need a falsification test; "validated" needs `evidence_n >= 5` and an existing held-out evaluation; a fourth same-class redraft needs an architecture question (enforced in `propose_interpretation` and in the `redraft` tool); numbers in a proposal must be grounded in the director's words or the attempt's recipe. Each has tests, including the fourth (numbers), which the doc lists as a bullet but not among the "three".
- **agent-shell additions** the phase needed: async `preview`, `precheck` (refuse before asking), `Proposal.tool` + `Session.apply_proposal` so accepted end-of-session proposals are actually written, and `result_data`/`artifacts` in the audit record.
- **`fact add`** now calls `add_fact` (propose then confirm); a test proves the stored payload equals what `bulk_load_verified` stored, and the one CLI test that pinned the old call was updated.
- **Not extracted or exposed:** `sync_models` (needs the ComfyUI client and a pod). `recall` in the CLI still returns three kinds; the chat's `recall` returns evaluations too (`recall_all`).
- **Pre-fix marking** uses the environment variable `EXECUTION_TRUTH_VERIFIED_SINCE` (an ISO date). Unset means nothing is trusted yet.
- **Tests against a real Qdrant** use a throwaway collection per test and faked embeddings; skipped with a visible note when Qdrant is down.
- The §B1 lesson corrections are a work list for you (`docs/agent-shell/phase-4-b1-lessons.md`); they need your keys and Qdrant.

## Acceptance

- Every write shows a confirm panel; rejecting leaves Qdrant point counts unchanged (test compares counts). Edit and defer paths are tested.
- Dry-run performs no writes.
- An evaluation is retrievable by `gen_id`, by chain and through `recall`.
- The three code-enforced rules above each have a test.
- The audit log alone is enough to reconstruct what was written and why.
- The §B1 lesson corrections are applied through the REPL.

## Risks

- **Schema drift with existing payloads.** Mitigated by the Phase 0 dump and additive-only changes.
- **Evaluations about untrustworthy records.** Until Gate 0 passes (Phase 5), every `EvaluationRecord` for a generation made before the seed fix gets `agent_status = "unresolved"` automatically, with a finding that the recorded seed may not match the submitted graph.

## Claude Code prompt

1. **Goal:** structured evaluation and lesson writes behind confirmation.
2. **Mode:** plan mode first, then direct.
3. **Files:** `@docs/agent-shell/phase-4-evaluation-and-memory-writes.md @docs/audit/visual-generation-tool-surface.md @packages/agent-shell/README.md @packages/visual-generation/src/visual_generation/ @packages/visual-generation/docs/evaluation-charter.md @docs/agent-retrospective-corrections.md`
4. **Prompt:**

```
Implement docs/agent-shell/phase-4-evaluation-and-memory-writes.md.

Part A - packages/visual-generation (owner of the collection):
- Add the library functions listed in the phase doc. Extract existing inline CLI logic rather
  than duplicating it; Click commands must call the new functions.
- Add the `evaluation` point kind additively. Show me the proposed payload next to the
  existing VisualGeneration and TechniqueLesson payloads before writing the store code, and
  flag any field-name conflict.
- record_evaluation must also call report_sync so the generation's reaction is set.

Part B - visual_generation/chat/:
- Finalize schemas.py as specified, including the three code-enforced rules. Each rule gets
  a test.
- Add the write tools with the effect classes in the phase doc. chat/ must contain no Qdrant
  client code; it calls store functions. add_fact goes through UserKnowledgeStore's
  propose -> confirm path.
- Register an on_session_end hook that returns unwritten proposals.
- Until a config flag `execution_truth_verified_since` is set, mark agent_status as
  "unresolved" for evaluations of generations created before that date and add the finding
  described in the phase doc.

Tests: confirm and reject paths compare Qdrant point counts (skip when Qdrant is down, and
say so in the output), dry-run, retrieval of an evaluation by gen id and by chain.
Do not touch generate.py, graph_build.py or the ComfyUI client in this phase.
```
