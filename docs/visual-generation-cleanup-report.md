# visual-generation cleanup — execution report

**Date:** 2026-07-15. **Executes:** consolidated audit §11/§12 (delete-vs-deprecate split) +
[`docs/agent-retrospective-corrections.md`](agent-retrospective-corrections.md) §B1/§B3/§B5.
**Commits:** (a) `93b8b56` code + tests + workflow JSON removal; (b) `f6f8729` docs; (c) this
report. The knowledge-base operations below leave no repo diff — this report is their record.

## What was done

1. **Deleted from the production path** (commit a): `enforce_canon` (locked-text injection,
   `@token` expansion, blind `forbid` substring strip) + `_tidy`/`_dedupe_locked`; the cast
   block's locked-descriptor emission; the two-LoRA workflow
   (`workflows/z-image-turbo-lora2-api.json`); the identity-sum strength threshold (replaced
   by an unconditional 2+-identity-LoRA deprecation advisory). No negative-phrasing helpers
   existed beyond the forbid-strip itself (grep-verified).
2. **Canon transformed to an asset-reference subject registry** (audit §5, field names
   aligned with `docs/shared-shot-schema.md`): `CanonSubject{aliases, lora, id,
   reference_pack, wardrobe, hair, region}`; `locked`/`forbid` dropped from the active
   schema; legacy JSON (e.g. `~/agent-data/visual-generation/canon/celeste-you-dangerous.json`)
   loads and round-trips those fields untouched. Presence is alias-only; `--canon` force =
   compose-time cast + forced LoRA pin. `identity_bearing` opsec untouched.
3. **Deprecated, not deleted** (commit b): single-LoRA Z-Image workflows and craft notes are
   labeled ideation-only/non-canonical; all generation records and prior outputs untouched.
4. **Docs**: every B3 row executed (canon-guide retitled per the approved variant "Canon —
   subject registry: cast naming, LoRA pinning, asset references"; README LoRA/continuity/
   troubleshooting rewrites; craft-doc small-n demotions; supersede + provenance banners;
   playbook Workflow 5–6 deprecation + mechanics-changed banner; video-doc one-clause
   amendments; external Claude-audit correction note in
   `~/agent-projects/LLM-implementation-visual-agent-audit/`, outside git).
5. **Tests**: 310 passed; ruff clean; mypy baseline unchanged (50 pre-existing errors).

## KB lesson operations (B1) — old → new entry_id mapping

All eight operations ran add-first, rm-second; final state = **11 lessons** (verified by
`lesson list`; `recall "identity bleed two characters"` surfaces the new structural lesson
as the top hit at 0.581).

| # | Operation | Old ID | New ID |
|---|---|---|---|
| 1 | Rewrite (KNOWN-WRONG: "a two-shot is 1.0 + 1.0") | `6f5638ea-3640-4d33-aa5b-96cd5ad2337a` | `3f415090-251a-4f32-aa42-e0b85a57c49c` |
| 2 | Rewrite (CATEGORY-CONFUSED: retrain-fix over-claim) | `7570c0d4-8f82-4958-b6d0-44c16219b0e0` | `68cb1908-36f0-4174-bd2b-eb0364cf3a23` |
| 3 | Rewrite (CATEGORY-CONFUSED: "canon owns identity") | `878d32da-aca3-45d3-ad90-2ecd967137a7` | `fe55484b-4520-418b-98db-285b7dc6c26f` |
| 4 | Scope-label "(Z-Image ideation path)" ('waving') | `87dd8981-93d0-4ec0-a335-67fd213b25df` | `8ccc6ade-388c-4dce-a398-a29fc647494c` |
| 5 | Scope-label "(Z-Image ideation path)" (settings recipe) | `2e5fc7ee-7dde-40b4-886d-008423618a86` | `2beece8c-ec72-41b3-bda8-a197d7e582e8` |
| 6 | NEW: structural identity bleed (negative/model) | — | `c3baf0b5-b7d2-424d-aaa4-0f8c01f1372a` |
| 7 | NEW: text canon is a prompt macro (negative/workflow) | — | `66991fba-2e1c-4008-a9a8-e23465253f60` |
| 8 | NEW: validated two-shot path, gen `359471ab` (positive/workflow) | — | `17fa44e8-a577-4c62-808c-440556eb4464` |

Unchanged (still valid): `2ed60fc9` (1024×1024), `6ea3619d` (glass-only masks),
`a3528547` (tight inpaint masks). Old lesson texts are preserved verbatim in
`agent-retrospective-corrections.md` §B1 and git history.

## Qdrant `visual-workflow-lora2` registration — deleted (user-approved)

- **Point ID:** `909f07c3-4ddf-4373-962b-ac447aeb28a2` (collection
  `visual_generation_memory`, `memory_type=workflow_template`, created 2026-07-02).
- **Payload summary:** name `visual-workflow-lora2`; descriptor "z-image turbo text2img with
  TWO chained character-LoRA slots (lora_0 + lora_1) for two-character shots"; 14-slot
  slot_map (seed/steps/cfg/sampler/scheduler/denoise/positive/width/height/unet/lora_0(+str)/
  lora_1(+str)); required_models: z_image_turbo_bf16, ae, narrator-zimage,
  celeste-zimage, qwen_3_4b.
- **Recovery:** re-register from the JSON in git history (`git show
  93b8b56^:packages/visual-generation/workflows/z-image-turbo-lora2-api.json`).
- Remaining templates (5): `visual-workflow`, `visual-workflow-img2img`,
  `visual-workflow-inpaint`, `visual-workflow-inpaint-lora`, `visual-workflow-lora`.

## user_knowledge sweep (B5) — findings, nothing changed

- **`visual_generation_canon` domain: EMPTY (0 facts).** The `[PROJECT CANON]` retrieval
  advisory channel never had content behind it — the craft-prompt instruction about it was
  aspirational. Domain census (832 facts): runpod_mechanics 253, comfyui_mechanics 251,
  langgraph_mechanics 227, elevenlabs_mechanics 48, suno_mechanics 37, editing_toolset 16.
- Keyword scan (canon / locked identity / character lora / identity bleed / two-shot /
  durable fix / solo recipe) over all 832: **1 match** — `61e05f90…` (comfyui_mechanics), an
  accurate Z-Image Turbo settings fact. **No fact asserts text-canon or LoRA identity
  authority; nothing to rm/rewrite.**
- Optional later: ingest plate-first canon facts into `visual_generation_canon` once
  reference packs/plates exist, so the retrieval channel carries the corrected doctrine.

## Flags

- **Behavioral cliff (intended — audit Phase 0):** with locked-text injection gone,
  single-pass renders hold identity strictly worse than before until the reference/plate
  pipeline exists; the `⚠ ABSENT` cast advisory is now the only dropped-character guard
  (test coverage kept).
- **Negated-mention bug remains open** (blast radius reduced to the LoRA pin only).
- **Video primer** (`video-generation-primer.md`, B3 row) exists only in git at `d37805b`,
  not the working tree — its one-clause amendment was skipped.

## Follow-ups

1. `store.delete_template()` + a `workflow rm <name>` CLI with confirmation (this session
   deleted the lora2 point via a raw Qdrant call by explicit approval; don't repeat that
   pattern).
2. Fix `_subject_present` negated-mention matching (`no/without/not <subject>`).
3. Ingest plate-first canon facts into the empty `visual_generation_canon` domain when
   reference packs/plates exist.
4. The plate-first implementation itself (audit §14 Phases 1–3) — outside this cleanup.
