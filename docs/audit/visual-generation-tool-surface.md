# visual-generation tool surface — agent-shell Phase 0

Audited 2026-10-04 against the **working tree** at `f17ae89` (main). No source files were
changed. Paths are relative to `packages/visual-generation/src/visual_generation/` unless
they start with `packages/`.

**HEAD vs uncommitted.** `cli.py` has uncommitted changes and `quick.py` is untracked. The
only command that exists solely in the working tree is `quick` (and its library function).
Everything else in the table is in `HEAD`; `cli.py` line numbers are working-tree numbers.

## 1. Command table

30 leaf commands: 11 top-level plus 19 across 7 groups (the overview's "about 35" is high).
All `*_sync` functions are thin `asyncio.run` wrappers over the async function of the same name.

| Command | `cli.py` | Backing function | Returns | Side effects | Store touched |
|---|---|---|---|---|---|
| `model sync` | 115 | **inline**: `ComfyUIClient.object_info` + `model_sync.parse_object_info` / `reconcile` + `ModelRegistry.replace` | — | HTTP read of the pod; **file write** (`models.json`); prompts | local registry |
| `model list` | 160 | **inline**: `ModelRegistry.list_models` | — | none | local registry |
| `model rm` | 179 | **inline**: `ModelRegistry.remove` | — | **file write**; prompts | local registry |
| `workflow register` | 212 | **inline**: `slot_inference.infer_slots` + `store.upsert_template` | — | **Qdrant write**; embedding spend; prompts | `visual_generation_memory` / `WorkflowTemplate` |
| `workflow list` | 298 | **inline**: `store.search_templates` | — | embedding spend | `WorkflowTemplate` (read) |
| `draft` | 342 | `draft.draft_sync` (`draft.py:389`) | `DraftResult` | **LLM spend**; **file write** (batch file) | reads all three payload types + `user_knowledge` |
| `redraft` | 497 | `draft.redraft_sync` (`draft.py:607`) | `DraftResult` | **LLM spend**; **file write** (batch file) | `VisualGeneration` (read) |
| `generate` | 645 | `generate.plan_generation_sync` (`generate.py:594`) then `generate.spend_generation_sync` (`generate.py:598`) | `GenerationPlan`, `GenerationResult` | **GPU spend**; **Qdrant write**; **file write** (asset, GPU ledger); prompts between plan and spend | `VisualGeneration` |
| `report` | 750 | `report.report_sync` (`report.py:44`) | `VisualGeneration \| None` | **Qdrant write** (payload update, no re-embed) | `VisualGeneration` |
| `quick` *(uncommitted)* | 789 | `quick.quick_generate_sync` (`quick.py:207`) | `QuickResult` | **GPU spend**; **file write** (asset); prompts. No Qdrant write. | `WorkflowTemplate` (read) |
| `knowledge-verify` | 922 | `verify.verify_knowledge` (`verify.py:46`), wrapped inline | report object | embedding spend | reads |
| `digest` | 962 | **inline**: `store.list_generations` / `list_lessons` / `list_pending` | — | none | reads |
| `review-pending` | 1004 | `inspect.list_pending_sync` (`inspect.py:82`) + `render_pending` | `list[VisualGeneration]` | none | reads |
| `chain show` | 1015 | `inspect.get_chain_sync` (`inspect.py:134`) + `render_chain` | `list[VisualGeneration]` | none | reads |
| `recall` | 1022 | `inspect.recall_sync` (`inspect.py:207`) + `render_recall` | 3-tuple of hit lists | embedding spend | reads |
| `batch build` | 1059 | `draft.batch_project_sync` (`draft.py:449`) via `_run_batch` (`cli.py:589`) | `list[DraftResult]` | **LLM spend** per scene; **file write** | reads |
| `batch rebuild` | 1087 | same, `overwrite=True` | `list[DraftResult]` | **LLM spend**; **file overwrite** | reads |
| `batch list` | 1126 | **inline**: `batch_file.read_batch` | — | none | — |
| `batch rm` | 1145 | **inline**: `batch_file.remove_spec` + `write_batch` | — | **file write**; prompts | — |
| `canon set` | 1195 | **inline**: `ProjectCanon.set_subject` | — | **file write** (canon JSON) | — |
| `canon show` | 1266 | **inline**: `ProjectCanon.load` | — | none | — |
| `canon edit` | 1281 | **inline**: `ProjectCanon.update_subject` | — | **file write** | — |
| `canon rm` | 1345 | **inline**: `ProjectCanon.remove` | — | **file write**, no prompt | — |
| `lesson add` | 1366 | **inline**: `store.upsert_lesson` | — | **Qdrant write**; embedding spend | `TechniqueLesson` |
| `lesson list` | 1386 | **inline**: `store.list_lessons` | — | none | reads |
| `lesson rm` | 1413 | **inline**: `store.get_lesson` + `delete_lesson` | — | **Qdrant delete**; prompts | `TechniqueLesson` |
| `fact add` | 1444 | **inline**: `agent_runtime.UserKnowledgeStore.bulk_load_verified` | — | **Qdrant write**; embedding spend | `user_knowledge` |
| `fact ingest-docs` | 1468 | `agent_runtime.ingest_docs_sync` | — | **Qdrant write**; prompts (y/n/edit/defer) | `user_knowledge` |
| `explain` | 1486 | `explain.explain_sync` (`explain.py:213`) + `render_explain` | `ExplainResult` | **LLM spend** | reads |
| `research` | 1496 | `research.research_sync` (`research.py:190`) + `render_research` | `ResearchOutcome` | **LLM spend**; delegates to tutorial-research, which ingests | `tutorial_research` (written by its owner) |

**Inline count: 16 of 30.** The phase doc predicted `model *`, `workflow *`, `lesson *`,
`fact add`, `canon *`, `batch list/rm`, `digest` — all confirmed inline. Two predictions were
wrong: `review-pending` and `chain show` **do** have library functions, and `fact ingest-docs`
is a runtime library call. `knowledge-verify` has a library function but its store setup and
rendering are inline (`cli.py:935-959`).

## 2. Library functions the overview names

All eleven exist.

| Function | Location | Key parameters |
|---|---|---|
| `draft` / `draft_sync` | `draft.py:150` / `:389` | `intent, points, scene, projects_dir, batch_path, template_name, project, source, denoise, model, provider, force_canon, budget` |
| `redraft` / `redraft_sync` | `draft.py:463` / `:607` | `gen_id, change, batch_path, project, model, provider, force_canon, budget` |
| `batch_project` / `_sync` | `draft.py:394` / `:449` | `project, scenes, batch_path, template_name, source, denoise, model, provider, overwrite` |
| `plan_generation` / `_sync` | `generate.py:301` / `:594` | `batch_path, section_id, all_sections, gpu_rate` → `GenerationPlan` (spends nothing) |
| `spend_generation` / `_sync` | `generate.py:358` / `:598` | `plan, endpoint, gpu_rate, max_session_cost, budget` → `GenerationResult` |
| `report` / `report_sync` | `report.py:22` / `:44` | `gen_id, reaction, rating, notes, context` |
| `quick_generate` / `_sync` *(untracked file)* | `quick.py:81` / `:207` | `prompt, endpoint, video, template_name, negative_prompt, seed, width, height, length, fps, image_path, model, settings, …` |
| `explain` / `explain_sync` | `explain.py:139` / `:213` | `concept, level, budget` |
| `research` / `research_sync` | `research.py:105` / `:190` | `topic, dry_run, budget, child_budget` |
| `verify_knowledge` | `verify.py:46` | `query, store, memory_store, project, limit` — async only, stores are required arguments |
| `recall` / `recall_sync` | `inspect.py:141` / `:207` | `query, limit` |

The plan/spend split is real and is the natural approval seam: `cli.py:667` plans,
`cli.py:706-707` confirms, `cli.py:709` spends.

Not exported from `visual_generation/__init__.py` (`:67-121`): `batch_project*`,
`quick_generate*`, `verify_knowledge`. The orchestrator imports `draft`, `recall`,
`render_recall` from the package root.

## 3. Payload models in `visual_generation_memory`

One collection, discriminated by `memory_type` (`store.py:55-56`).

**`VisualGeneration`** (`models.py:76-129`) — `memory_type="generation"`
`entry_id, caption, asset_path, prompt, negative_prompt, settings, model, lora_stack,
workflow_ref, seed, width, height, cost_usd, identity_bearing, reaction, rating, status,
notes, context, project, parent_id, chain_root_id, source_image_path, source_mask_path,
created_at, reacted_at`
- Lineage: `parent_id: str | None` (`:121`); `chain_root_id: str` (`:122`), set to its own
  `entry_id` for a chain root (`:133`).
- `status` is **derived from `reaction`** at write time, not stored independently
  (`models.py:137`).
- There is no field recording which values failed to reach the graph, and no evaluation
  or score fields. A `record_evaluation` path would need new fields or a new payload type.

**`TechniqueLesson`** (`models.py:145-159`) — `memory_type="technique_lesson"`
`entry_id, statement, valence (positive|negative), scope (prompt|settings|workflow|model),
confirmed, derived_from: list[str], created_at`. No `parent_id` / `chain_root_id`;
`derived_from` is its only link to generations.

**`WorkflowTemplate`** (`models.py:169-187`) — `memory_type="workflow_template"`
`entry_id, name, descriptor, graph, slot_map, required_models, created_at`. No lineage fields.

Store write methods: `upsert_generation` (`store.py:81`), `update_generation_reaction` (`:103`),
`upsert_lesson` (`:227`), `delete_lesson` (`:327`), `upsert_template` (`:380`),
`prune_templates_by_name` (`:349`).

## 4. LLM provider seam

Lives in **agent-runtime**, not in visual-generation.

- Interface: `LLMProvider` protocol — `resolve_model(alias)` and
  `complete(system, user_text, image_paths, model, max_tokens)`
  (`packages/agent-runtime/src/agent_runtime/llm/base.py:32-54`).
- Selection: `get_provider(name)` falls back to `config.default_llm_provider`; knows
  `anthropic` and `openai`; anything else raises
  (`packages/agent-runtime/src/agent_runtime/llm/registry.py:13-30`).
- Aliases (Anthropic): `sonnet → claude-sonnet-4-6`, `opus → claude-opus-4-8`; `None` →
  `claude-sonnet-4-6`; an unknown string passes through as a literal model id
  (`llm/providers/anthropic.py:24-28, 62-65`).
- OpenAI today: both methods raise `NotImplementedError("OpenAI provider is not yet
  implemented…")` (`llm/providers/openai.py:26-30, 38-39, 50`).
- CLI exposure: `--provider` on `draft` (`cli.py:365`), `redraft` (`:505`), `batch build`
  (`:1065`), `batch rebuild` (`:1093`).
- **Not on the seam:** `explain` takes an `AsyncAnthropic` client directly (`explain.py:146`).

## 5. Runtime facts

**`AGENT_PROJECTS_DIR` does not exist in `RuntimeConfig`**
(`packages/agent-runtime/src/agent_runtime/config.py:11-32` has `agent_data_dir` and
`agent_reports_vault` only). visual-generation hardcodes `~/agent-projects` at
`discovery.py:29`. The overview's "agent-runtime gains AGENT_PROJECTS_DIR" is still to do.

**`BudgetTracker` pricing** (`packages/agent-runtime/src/agent_runtime/budget.py:14-21`),
USD per 1M tokens, sourced 2026-05-26:

| Model | Input | Output |
|---|---|---|
| `claude-opus-4-8` | 5.00 | 25.00 |
| `claude-opus-4-7` | 15.00 | 75.00 |
| `claude-opus-4-6` | 15.00 | 75.00 |
| `claude-sonnet-4-6` | 3.00 | 15.00 |
| `claude-haiku-4-5` | 0.80 | 4.00 |

**A model not in the table is costed at $0.00, silently** (`budget.py:105`:
`_PRICING.get(model, {"input": 0.0, "output": 0.0})`). Any OpenAI model, and any Claude
model newer than the table, would never count against `max_cost_usd`. The cost cap is
therefore not provider-neutral today.

## Open questions

1. Sixteen commands have their logic inline in `cli.py`. Extract library functions for all of them in Phase 3, or only for the ones the chat tool pack needs first?
2. Unknown models cost $0, which disables the cost cap for an OpenAI engine. Should unknown models raise, or should pricing become part of the `Engine` adapter?
3. `explain` bypasses the provider seam. Leave it Anthropic-only in v1?
4. `VisualGeneration` has no evaluation fields. Should `record_evaluation` extend that model or add a fourth `memory_type`?
5. `quick` and `quick.py` are uncommitted. Should the chat tool pack treat `quick` as part of the surface, and will it be committed before Phase 3?
