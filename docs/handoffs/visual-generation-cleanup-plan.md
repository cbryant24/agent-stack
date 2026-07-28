# visual-generation cleanup — execute audit §11/§12 + corrections B3 (B1/B5 deferred)

> **Handoff note (2026-07-28):** approved Claude Code implementation plan, copied verbatim from a machine-local plans directory so either machine can execute it. Not yet executed. Despite the title, the plan's preflight passed and steps 5 (B1 lesson corrections) and 6 (B5 user_knowledge sweep, propose-only) are IN scope — see "Preflight result" below. Source strategy: `packages/visual-generation/docs/Consolidated-Coraline-Stop-Motion-Visual-Generation-Audit.md` §11/§12 + `docs/agent-retrospective-corrections.md`.

## Context

The consolidated audit (NO-GO, conditioning/asset-authority gap) and `docs/agent-retrospective-corrections.md` prescribe: delete the forbid-strip, canon locked-text prompt injection, and the dual-LoRA workflow from the production path; deprecate (not delete) single-LoRA Z-Image workflows; transform canon to an asset-reference schema (audit §5, field names aligned with `docs/shared-shot-schema.md`); execute the B3 doc-action table verbatim. History and reusable infrastructure stay.

**Preflight result: PASS** (after the user's vault fix — op now reads the `Claude` vault). `op run -- true` OK; `lesson list` returns the 8 known lessons (IDs match B1); `recall` works, proving the Voyage embedding path `lesson add` needs. **Steps 5–6 are in scope**: step 5 executes B1; step 6 is propose-only ("show me before changing").

## Execution order

1. Code: canon.py → lora_guard.py → chains.py → draft.py → cli.py → models.py comment → `git rm` lora2 JSON.
2. Tests (step 7): update per plan; `uv run pytest` (package) + `uv run ruff check` + `uv run mypy` green.
3. Docs (step 4): B3 table verbatim + package README plate-first sections.
4. KB step 5 (op verified working): B1 lesson rm/add per the list below; verify 11 lessons.
5. Qdrant lora2 registration: record point ID + payload, then delete (user-approved).
6. KB step 6: user_knowledge sweep — PROPOSE-ONLY, present findings, change nothing.
7. Final report incl. flags: behavioral cliff, primer skipped (git-only), follow-ups (`workflow rm` CLI + `delete_template`).

## Do NOT touch (step 8)

plan/spend separation, identity.py, assets.py, model_sync reconcile, ComfyUI client, workflow registration/slot inference code, store/retrieval (incl. the retrieval.py `[PROJECT CANON]` user_knowledge advisory channel), gpu_tracker, report/reaction, other packages, generation records/prior outputs.

## Known so far (from direct reads)

- `canon.py`: `CanonSubject{aliases, locked, forbid, lora}`; `enforce_canon` (inject locked + strip forbid + @alias expansion + `_dedupe_locked`/`_tidy`); `subjects_matching`, `scene_cast`, `canon_loras_for` (presence = locked-text OR alias match); `ProjectCanon` JSON store keyed by primary alias.
- `draft.py`: `enforce_canon` called in `draft()` (line ~284) and `redraft()` (~566); `_pin_canon_loras` pins canon LoRA + "canon owns identity" framing + `prune_noncanon_identity`; `canon_absent` advisory via `scene_cast`.
- `lora_guard.py`: `strength_warnings` (per-entry ceiling 1.5 — KEEP; identity-sum ceiling 2.5 across 2+ identity LoRAs — dual-identity-stacking logic, to replace/delete); `prune_noncanon_identity` (same-character dedup — KEEP); module docstring frames bleed as over-strength + "Canon owns identity" (docstring correction per B3).
- `workflows/`: `z-image-turbo-lora2-api.json` (delete), `z-image-turbo-lora-api.json` (deprecate label only), wan2.2 t2v/i2v (untouched).
- Negative-phrasing helpers: grep of src found none beyond the forbid-strip itself (chains.py "NOT/do not" hits are craft-prompt instructions, not prompt-content writers). Deleting forbid-strip closes audit §11 "negative-word lists used as positive text" unless Explore finds more.
- lora2 references live only in docs (character-lora-plan.md:211, celeste-visual-batch-v2-plan.md:30/42/66/68/71) + the workflow JSON + (presumably) a Qdrant workflow_template registration named `visual-workflow-lora2` (NOT git-recoverable — user decision required).

## File-by-file plan

### Code (steps 1–3) — settled design

**Design decisions:**
- **Legacy round-trip:** `CanonSubject` gets `model_config = ConfigDict(extra="allow")` — legacy `locked`/`forbid` keys load as pydantic extras and survive `model_dump()` → `_write` byte-for-byte. `update_subject` is rewritten to `s.model_copy(update={...})` so edits preserve extras. `canon set` (full replace by design) intentionally drops them — stated in its help text.
- **`--canon` force flag survives** with new semantics: force-include the subject in the compose-time cast + force its LoRA pin even when the prompt doesn't name it. Hook: `canon_loras_for` gains `force: Sequence[str] = ()`; `_pin_canon_loras(spec, project, store, forced=())` passes it through. `_subject_present` becomes alias-only (keeps `@`-stripping for legacy alias lists).
- **Identity-sum warning replaced, not just deleted:** a threshold implies sub-threshold dual-identity stacking works. New rule in `strength_warnings`: any 2+ identity LoRAs → one unconditional advisory ("dual-identity stacking is deprecated (audit §6) — no strength pair isolates identities in a single pass… use sequential masked single-identity edits"). When `is_identity is None`, the stacking check is skipped entirely (old all-are-identity fallback would misfire).
- **`canon_applied` field name kept** (public-ish surface); CLI header "── Canon enforced (deterministic) ──" → "── Canon applied (LoRA pins) ──".
- **Cast block emits no descriptors:** `_format_cast` → `- "the narrator" (also called: narrator, Chris) [asset: narrator_v1]` (asset suffix only when `id` set; reference_pack/wardrobe/hair/region never leak into prompts — they're pipeline references, not prose).

**File-by-file (ordered):**

1. **`src/visual_generation/canon.py`** — `CanonSubject`: drop `locked`/`forbid`; add `id`, `reference_pack`, `wardrobe`, `hair`, `region` (all `str | None = None`); keep `aliases`, `lora`; `extra="allow"`. DELETE `enforce_canon`, `_tidy`, `_dedupe_locked`. `set_subject`/`update_subject` new signatures (string fields: `None`=untouched, `""`=clear; `update_subject` via `model_copy`). `_subject_present` alias-only. `canon_loras_for(+force=)`. `subjects_matching`/`scene_cast`/`_alias_set` kept. Module docstring rewritten (asset-reference registry; pins LoRAs + surfaces cast; does not rewrite prompt text; legacy files round-trip).
2. **`src/visual_generation/lora_guard.py`** — delete `DEFAULT_IDENTITY_SUM_WARN` + sum logic; add unconditional ≥2-identity advisory; module + `prune_noncanon_identity` docstrings rewritten per B3 (mitigates over-strength/duplication artifacts, does NOT provide identity isolation; all "canon owns identity" phrasing removed; prune note text keeps "canon pins another checkpoint of the same character" so existing test assertions survive).
3. **`src/visual_generation/chains.py`** — `_format_cast`/`_cast_block` per design (identity carried at model level; name/place/pose, don't invent physical descriptions). System-prompt `[PROJECT CANON]` bullet reworded (retrieval advisory channel stays; "locked descriptor is injected deterministically" promise removed). Revise-mode "Preserve every locked descriptor block…" → "Preserve all unchanged composition/style/lighting and character language VERBATIM" (both sites, ~92-95 and ~194).
4. **`src/visual_generation/draft.py`** — drop `enforce_canon` import + both call sites (draft ~284, redraft ~566); `canon_applied` now comes solely from `_pin_canon_loras(..., forced=...)`; docstrings/comments lose "canon owns identity"/"locked text" framing; `canon_absent` recheck unchanged (alias-based).
5. **`src/visual_generation/cli.py`** — `canon set`: drop `--locked`(required)/`--forbid`; add `--id/--reference-pack/--wardrobe/--hair/--region`; help notes full-replace drops legacy fields + schema alignment with `docs/shared-shot-schema.md`. `canon edit`: drop `--locked/--add-forbid/--rm-forbid`; add the five (empty string clears; "nothing to edit" check uses `is not None`). `_echo_subject`/`canon show`: print set fields + `(legacy locked/forbid present — ignored)` when extras exist; `canon show` reuses `_echo_subject`. `--canon` help texts updated (draft: cast + pin; redraft: pin only — no cast in revise mode). Headers at 457/547. `_parse_lora` untouched.
6. **`src/visual_generation/models.py`** — comment-only on `canon_applied`.
7. **`git rm workflows/z-image-turbo-lora2-api.json`** (no code references it; workflows/README.md doesn't mention it — verified).

**Step 7 — tests:**
- `test_canon.py`: delete 13 enforce/forbid/dedupe/token tests (lines 53–176); rewrite seeds (asset fields instead of locked/forbid) + 6 tests (round-trip, presence-by-alias, update_subject variants); keep 14 alias/cast/lora tests; ADD 5: legacy-JSON load+round-trip, legacy-survives-update_subject, empty-string-clears, presence-is-alias-only (prompt containing legacy locked text but no alias pins nothing), force-pins-unnamed-subject (incl. `@narrator` without `@`).
- `test_lora_guard.py`: delete 4 identity-sum tests + import; ADD 3 (two identities @1.0 → one "deprecated…sequential masked" advisory; identity+detail → no advisory; `is_identity=None` → no stacking check). Per-entry ceiling + prune tests unchanged.
- `test_chains.py`: rewrite 2 (cast block asserts name+alias+asset-id, and `"locked" not in block`), keep 2, ADD omits-asset-suffix-when-no-id.
- `test_draft.py`: delete 2 enforce-stub tests; ADD force-canon-pins-lora passthrough test (fake `canon_loras_for` asserting `force=` kwarg); `_patch_cast` loses `locked=` + stray `enforce_canon` setattrs; keep LoRA-pin/absent/strength-override tests.
- `test_cli_turn.py` (passthrough), `test_cli_step5.py` (`_parse_lora`), `test_redraft.py`: unchanged.
- ADD CLI round-trip test: `canon set/edit/show` with asset fields + legacy-note rendering (monkeypatched canon dir).

**Known behavioral cliff (intended, flag in final report):** with locked-text injection gone, single-pass renders hold identity strictly worse than before until the reference/plate pipeline exists — this is the audit's Phase-0 "stop structurally doomed spend" intent, and `canon_absent` becomes the only dropped-character guard (its tests are kept).

### Step 4 — DOCS (B3 verbatim; insertion points verified)

All paths relative to `packages/visual-generation/` unless noted.

1. **`docs/canon-guide.md`** — rewrite/retitle. New title: "Canon — deterministic prompt-macro + LoRA-pinning layer" (was "locked identity"). Rework §2 (enforcement mechanics: locked injection/@token expansion/forbid strip all deleted → describe what remains: cast naming + LoRA pinning), delete §on `--forbid` and `--locked` from §5 command reference (lines 163–204) replacing with the new asset-reference options, drop "immutable identity"/"guaranteed" wording (lines 25, 82), add a header note pointing to audit §5 and the asset-reference schema. @token docs (48–49, 169) removed with the mechanism.
2. **`README.md` (package)** —
   - "Character LoRA (model-level continuity)" (line 697–705): rewrite — remove "This is the durable fix for cross-scene character drift"; LoRA = character-class prior for the deprecated ideation path; durable identity = reference packs + masked edits (plate-first).
   - Troubleshooting 811–820: rewrite the "Fix: … a two-shot is 1.0 + 1.0" ending to match corrected lesson `6f5638ea` (strength never isolates identities; two-character frames = sequential masked edits).
   - 370–381 ("validate the two-shot itself … which held" + "character LoRA … the durable fix"): rewrite per audit §1/§11 (claims withdrawn; strongest→weakest list ends at "deprecated ideation aids").
   - Gaps 229–236 (negated-mention canon bug): rewrite/remove — with locked-injection deleted the bug's blast radius is now only LoRA pinning; keep as a smaller note.
   - Canon section 650–705: rewrite to the new asset-reference canon (metadata layer, not identity authority).
   - lora_guard section (488): correct per B3 — mitigates over-strength artifacts, does not provide identity isolation.
   - Video section (78+): plate-first framing; Z-Image = ideation-only, non-canonical (remove any solo-path-validated implication; 221–226 refinement/inpaint "proven end-to-end" claims are about infrastructure and stay).
3. **`docs/z-image-turbo-craft.md`** — insert ideation-only banner after line 1 (doc leaves the continuity path per audit §17; craft notes remain valid as model-specific ideation guidance per audit §12). Demote SUPPORTED→"small-n observation" at lines 422, 543, 544, 550, 1096 (and audit the other SUPPORTED hits at 42, 85, 103, 196, 256, 272, 345, 368, 441, 463, 476, 505, 517, 525 — same demotion where the verdict concerns identity/continuity; leave pure settings/craft verdicts).
4. **`docs/character-lora-plan.md`** — superseded banner after line 1 (audit §7: dataset = agent's own synthetic outputs, no hero geometry, no held-out views; "Phase 6 verification passed"/"usable for real scenes" (219) withdrawn — one tuned two-shot is not validation; RunPod/ai-toolkit ops gotchas remain valid). lora2 references (211–220) remain as history under the banner.
5. **`docs/celeste-visual-batch-v2-plan.md`** — superseded banner after line 1 ("Proven per-shot recipes" withdrawn; 1.5/1.5 recipe deprecated — strength balancing ≠ isolation; lora2 template deleted).
6. **`docs/production-testing-playbook.md`** — deprecation note under `## Workflow 5` (line 378) and `## Workflow 6` (line 422): harness structure kept; anchor-img2img continuity and character-LoRA continuity are off the continuity path (audit §11); Workflow 6's "the durable fix" subtitle corrected.
7. **`docs/character-lora-explainer.md`** + **`docs/character-lora-narrator-audit.md`** — provenance banner after line 1: training dataset = agent-generated synthetic frames (gen-ids in filenames); images shown are INPUTS unless a gen-id proves otherwise.
8. **`docs/video-generation-research.md`** (line 45 rec 3) + **`docs/video-generation-implementation-guide.md`** (line 27 "Z-Image Turbo stays for ideation and scene-opening drafts"; also line 271 scene-opening keyframe) — one-clause amendment: non-canonical ideation only; keyframe/still authority is plate-first. (The primer exists only in git at `d37805b`, not in the working tree — skipped, noted in report.)
9. **`~/agent-projects/LLM-implementation-visual-agent-audit/Claude - Audit: Coraline Stop-Motion Visual-Gen.md`** — header note: "'already validated solo recipe' claims herein were built on training inputs misread as outputs — corrected by Consolidated Audit §1."

### Step 5 — KB lesson corrections (B1; op preflight passed)

There is no `lesson edit` — every rewrite/scope-label is `lesson rm <id> --yes` + `lesson add "<new text>" --scope <s> --valence <v>` (new entry_id; the old text is preserved verbatim in `docs/agent-retrospective-corrections.md` §B1 and in git, so this is recoverable-by-record). All commands under `op run --env-file=.env --`.

Rewrites (rm + add):
1. `6f5638ea` → add (positive/model): "Character LoRAs trained on Z-Image Turbo (Ostris de-distill adapter) apply at ~1.0; a LoRA that only takes at 2.0+ is base-trained — retrain it on Turbo. Strength does NOT isolate identities in multi-character frames: two-shots require per-region conditioning (sequential masked insertion), not strength pairs. (Z-Image ideation path)"
2. `7570c0d4` → add (negative/model): "A character LoRA trained on Z-Image Base under-applies on Z-Image Turbo: it only registers around 2.0+, where it overrides prompt adherence and bleeds onto other figures. Retraining on Turbo restores prompt adherence at ~1.0; it does not prevent cross-figure identity bleed in shared frames — that is a conditioning/routing gap no strength value fixes."
3. `878d32da` → add (negative/model): "Never stack two LoRA files for one character in a generation (muddy likeness, worse bleed). One pinned file per character prevents muddiness only — canon pinning is bookkeeping, not an identity authority."

Scope-labels (rm + add, text otherwise verbatim + suffix "(Z-Image ideation path)"):
4. `87dd8981` (negative/prompt) — 'waving' lesson.
5. `2e5fc7ee` (positive/settings) — cfg 1.0 / 8 steps / res_multistep / simple recipe.

Unchanged: `2ed60fc9`, `6ea3619d`, `a3528547`.

New adds (B1 "Lessons to ADD"):
6. (negative/model) "Identity bleed between two globally-applied character LoRAs is structural — no spatial routing exists; prompt phrasing ('left/right', 'must not look alike'), strength balancing, and seed sweeps cannot fix it. Two-character frames use sequential masked single-identity edits on a locked plate."
7. (negative/workflow) "Text canon is a prompt macro: it raises the probability of broad semantic traits and cannot pin geometry, materials, camera, or region assignment. Identity and set authority are versioned reference images and approved plates."
8. (positive/workflow) "Validated two-shot path: solo base frame + masked inpaint insertion of the second character (gen 359471ab, Phase-E shot 5 final); whole-frame two-LoRA generation is deprecated."

Verify after: `lesson list` shows 11 lessons, none of the 5 removed IDs remain; `recall "identity bleed two characters"` surfaces the new structural lesson.

### Step 6 — user_knowledge sweep (B5; PROPOSE-ONLY)

Scroll `user_knowledge` (raw Qdrant scroll, read-only) for canon/identity-domain facts (retrieval.py `CANON_DOMAINS` feeds the `[PROJECT CANON]` advisory channel). List any fact asserting text-canon or LoRA identity authority with id + full text + proposed rm/rewrite — **present to the user, change nothing**.

### Qdrant `visual-workflow-lora2` registration (user decided: DELETE)

Delete the workflow_template point via raw Qdrant API (scroll filtered on `memory_type=workflow_template` + name `visual-workflow-lora2`; **record the point ID + payload summary in the final report BEFORE deleting**; recovery = re-register from the JSON in git history). Rationale (user's): draft surfaces templates via retrieval, so leaving it registered keeps a known-broken production path as a live drafter candidate — the stale-authority pattern the retrospective documented.

Do NOT build a `workflow rm` command this session — **follow-ups list**: `delete_template` in store.py + `workflow rm <name>` CLI with confirmation.

## Verification

- `uv run pytest` (visual-generation package) green; `uv run ruff check` clean; `uv run mypy` for the package clean.
- Grep-verify: no remaining references to `forbid`, `enforce_canon`, `locked` (active schema), `lora2` in src/ or active docs sections (except history/superseded banners).
- Manual: `uv run visual-generation canon show <project>` still loads legacy JSON (ignored legacy fields), `draft --help` reflects removed/added options.
