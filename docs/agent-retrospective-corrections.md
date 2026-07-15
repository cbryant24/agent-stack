# Agent Retrospective Corrections — Coraline / visual-generation

**Written:** 2026-07-15. **Companion to:** [`packages/visual-generation/docs/Consolidated-Coraline-Stop-Motion-Visual-Generation-Audit.md`](../packages/visual-generation/docs/Consolidated-Coraline-Stop-Motion-Visual-Generation-Audit.md) (ground truth; NO-GO on the Z-Image-Turbo + global-character-LoRA + text-canon architecture — root cause is a conditioning/asset-authority gap, not prompt writing).

**What this doc is:** the corrections list for the agent's recorded learnings — the decision timeline with citations, every technique lesson / doc / heuristic that is now known-wrong or category-confused (with one-line replacements), why the training-inputs-as-outputs misread survived, and process guardrails. The KB lesson rewrites (`lesson rm`/`lesson add`) and doc-banner edits listed here are **follow-up actions for their own sessions** — this doc records them; it does not perform them.

**Evidence base:** git history; repo docs; `~/agent-projects/celeste-you-dangerous/`; `~/agent-data/visual-generation/`; full raw scroll of the `visual_generation_memory` Qdrant collection (8 `technique_lesson`, 464 `generation`, 6 `workflow_template` points).

**Investigation caveats:**
- `op run` failed during the retrospective session ("'Personal' isn't a vault in this account"), so Voyage-embedded `recall`/`knowledge-verify` could not run; the KB audit used a direct Qdrant scroll (better for coverage per the coverage-audit convention, but semantic retrieval itself went untested — and the vault issue blocks `recall` generally until fixed).
- The `user_knowledge` collection (`fact` domain) was **not** swept — follow-up item (§B5).
- `fidelity-drift-learnings.md` and `coraline-visual-quality-analysis.md` do not exist in the repo, its git history, `~/agent-projects`, or `~/agent-data`. The content they describe lives in `z-image-turbo-craft.md` (drift learnings) and `~/agent-projects/LLM-implementation-visual-agent-audit/` (quality analyses).

---

## A. Decision timeline (with citations)

### Phase 1 — prompt-and-seed era (06-12 → 06-26)

- 06-12 `aa775a2` "agent stack v1 complete"; first Celeste batch specs 06-14 (`visual-batch.md` spec `562ad75a`, no models registered yet).
- 06-18: settings lessons stored (`2e5fc7ee` cfg 1.0 / 8 steps / res_multistep; `2ed60fc9` 1024×1024). Still valid.
- 06-20 `ee9de6e` video setup: WAN 2.2 T2V/I2V workflows + research-signals handoff. **WAN-only — no edit/reference-model research here.** The base-model commitment is implicit: everything is built around `z_image_turbo_bf16.safetensors`.
- 06-22: visual-batch v1 specs adopt **fixed seed 4471 "for character continuity across the five story beats"** — the seed-as-identity heuristic enters the record.
- 06-26 draft rationale: "Backs-to-camera framing is the deliberate fix for the button-eye dropout… per the no-fight constraint" — staging failures start being 'solved' by prompt-side workarounds.

### Phase 2 — canon + LoRA doubling-down (06-27 → 07-06)

- 06-27 `ceea61d`: `z-image-turbo-craft.md` added. Records: "True identity lock would require a character LoRA (none exists yet — see *Planned durable consistency path*)" (line 188). The LoRA is pre-committed as the identity fix **before any training evidence exists**.
- 06-29 `810fa76`/`aa6c6e7`/`0df8d9b`: the canon system ships — `canon-guide.md` titled "**Canon — locked identity** for characters *and* places", "the **immutable identity** of a named entity", `--lora` = "model-level continuity". Same day `df881e0`: playbook covers "two canon subjects + two LoRAs + forbid-bleed". `character-lora-plan.md` (written 06-29): "Character LoRAs move identity to the model level — consistent look, much leaner prompts… **this is a 'go.'**"
- 07-01 `29e9cb9` narrator LoRA shipped; `39f7971` "canon-pinned LoRA strength overrides the LLM's guess".
- 07-02 `ffd9c42`/`515eb49`/`9d1afca`: Celeste LoRA trained, two-slot template, "**Phase 6 complete — verification passed, two-LoRA shot iterated**". The recorded "verification" is ONE two-shot iterated three times, with residual bleed at every strength tried (2.0/2.0 → sleeve+hair bleed; 1.5/1.5 → "bleed reduced… residual twist in her lower lengths"), graded "**usable for real scenes**" (`character-lora-plan.md` §Phase 6). Same day `7a1dd50` v2 batch plan: "**Proven per-shot recipes (hard-won — follow them)**"; two-shot 1.5/1.5 "renders cleaner (less identity bleed)".
- 07-06 `1de80c7` — **the reinforcement peak**: `lora_guard.py`, commit message "Two model-agnostic guardrails… **because canon owns identity**" — a strength-warning ceiling (1.5) and same-character LoRA dedup, treating identity bleed as an over-strength scalar problem. Same day, 3 of the 8 KB lessons are stored (`7570c0d4`; `6f5638ea` "a two-character two-shot is 1.0 + 1.0"; `878d32da` "let canon, not the drafter, own which file and strength represents a character").

### Phase 3 — migration researched, then scoped away from the failure (07-07 → 07-15)

- 07-07 `060f0ae`: `video-generation-research.md` lands. Recommendation 2: "**Migrate keyframe generation to Qwen-Image-Edit 2511.**" Recommendation 3: "**Keep Z-Image Turbo for ideation only… Retire it from the consistency-critical path.**" The implementation guide (same commit) encodes it: "Keyframe generation migrates to Qwen-Image-Edit 2511… which Z-Image Turbo (pure t2i) cannot do. Identity comes from reference images… **Z-Image Turbo stays for ideation and scene-opening drafts.**"
- **No revert commit exists.** What the record shows instead: the migration was scoped to *future video keyframes*; the still pipeline — the thing actually failing — was grandfathered via "scene-opening drafts," and 07-07 → 07-09 engineering went into WAN FLF2V plumbing (`039e079`, `a82efc9`, `ff34a39`, `41aec04`, `ec79052`), not a Qwen bake-off. No Qwen edit graph was stood up; no reference packs were built. Two-LoRA two-shot generation continued (generation records using `narrator-…-turbo @1.2` + `celeste-…-v2 @0.85` with the "Two clearly different people in frame… they must not look alike" prompt prefix postdate the 07-06 Turbo retrain).
- **Note on the premise:** git records the Qwen/FLF2V research at 07-07 — 8 days before the audit, not weeks. The 06-20 research was WAN-only. If the Qwen research existed earlier off-git, the repo never saw it. Within the record, the honest finding is not "returned to Z-Image after the research" but "**the research was adopted for video and never allowed to touch the stills path**" — there is no recorded decision point that weighed moving stills to an edit model. The question was never asked in writing.
- 07-14/15: three external LLM audits (`~/agent-projects/LLM-implementation-visual-agent-audit/`). The Claude one initially advised "**Do what you already validated: freeze the winning solo recipe**" and "Frozen solo recipe holds identity across 8+ shots (**already true for 5**)" — built on the five training INPUTS misread as outputs. 07-15 `4c9d4fb`: the consolidated audit corrects the misread (§1) and issues the NO-GO.

**Spend note:** the local GPU ledger records only ~$0.80 cumulative inference (`~/agent-data/visual-generation/gpu_ledger.json`); LoRA-training pods, idle pod time, and per-machine sessions are not in any repo ledger. The $100+ figure cannot be reconstructed from the record — itself a finding (audit §16, Cost Controls).

---

## B. Corrections — technique lessons, docs, heuristics

### B1. Qdrant `visual_generation_memory` technique_lessons (8 total)

| ID | Verdict | Correction (one line) |
|---|---|---|
| `6f5638ea` "Run each character LoRA near 1.0; a two-character two-shot is 1.0 + 1.0" | **KNOWN-WRONG** (as an isolation recipe) | Rewrite: "Turbo-trained LoRAs apply at ~1.0 (2.0+ take = base-trained, retrain); strength does NOT isolate identities in multi-character frames — two-shots require per-region conditioning (sequential masked insertion), not strength pairs." |
| `7570c0d4` base-on-Turbo bleeds at 2.0+; "Fix: retrain on Turbo so it applies near 1.0" | **CATEGORY-CONFUSED** (right observation, fix over-claims) | Rewrite: "…Retraining on Turbo restores prompt adherence at ~1.0; it does not prevent cross-figure identity bleed in shared frames — that is a conditioning/routing gap no strength value fixes." |
| `878d32da` don't stack same-character LoRAs; "let canon… own which file and strength represents a character" | **CATEGORY-CONFUSED** | Rewrite: "Never stack two LoRA files for one character (muddy likeness). One pinned file per character prevents muddiness only — canon pinning is bookkeeping, not an identity authority." |
| `87dd8981` 'waving' reverses blocking | STILL-VALID | Keep; scope-label "Z-Image ideation path". |
| `2e5fc7ee` cfg 1.0 / 8 steps / res_multistep / simple | STILL-VALID | Keep; scope-label "Z-Image ideation path". |
| `2ed60fc9` 1152×896 stalls; use 1024×1024 | STILL-VALID | Keep. |
| `6ea3619d` mask glass-only, not bezel | STILL-VALID | Keep — consistent with plate-first masked editing. |
| `a3528547` tight region-only inpaint masks tolerate denoise ~0.8 | STILL-VALID | Keep — this is the corrected architecture in embryo. |

**Lessons to ADD (new):**

1. "Identity bleed between two globally-applied character LoRAs is structural — no spatial routing exists; prompt phrasing ('left/right', 'must not look alike'), strength balancing, and seed sweeps cannot fix it. Two-character frames use sequential masked single-identity edits on a locked plate." (negative/model)
2. "Text canon is a prompt macro: it raises the probability of broad semantic traits and cannot pin geometry, materials, camera, or region assignment. Identity and set authority are versioned reference images and approved plates." (negative/workflow)
3. "Validated two-shot path: solo base frame + masked inpaint insertion of the second character (gen `359471ab`, Phase-E shot 5 final); whole-frame two-LoRA generation is deprecated." (positive/workflow)

### B2. Generation-record notes encoding wrong-layer 'lessons'

History records can't be rewritten; the correcting lessons above supersede them. Affected examples:

- `1699c58a`: "Naming 'the narrator'… pulled his figure in — describe the shadow anonymously" — prompt-macro workaround for a canon presence-detection misfire.
- `0646f23c` / `20eb448f` / `2130ba6a` / `426a2094` / `4979a702` (+1): the "Two clearly different people in frame… they must not look alike" prefix — the audit's textbook "weak semantic guidance, not spatial routing."
- `42b2bcaa` / `33407cf3`: "button eyes are unreliable in multi-character face-forward prompts" — right observation, prompt-layer conclusion; the fix that finally worked was the masked eye-inpaint (`0a25cbb2`: "stop trying to prompt around it"), i.e. a conditioning-layer move the record itself contains.
- visual-batch v1 specs (6×): "fixed seed 4471 for character continuity" — seed-as-identity, explicitly deprecated by audit §11.

### B3. Docs

| Doc | Action | Replacement one-liner |
|---|---|---|
| `packages/visual-generation/docs/canon-guide.md` | **Rewrite/retitle** | "Canon — deterministic prompt-macro + LoRA-pinning layer" — remove "locked identity" / "immutable identity" / "guaranteed"; delete blind `--forbid` substring-strip entirely (audit §5: actively harmful). |
| `packages/visual-generation/README.md` "Character LoRA (model-level continuity)" | **Rewrite** | Remove "This is the durable fix for cross-scene character drift"; LoRA = character-class prior for ideation; durable identity = reference packs + masked edits. |
| README troubleshooting "a two-shot is 1.0 + 1.0" | **Rewrite** | Match corrected lesson `6f5638ea`. |
| `packages/visual-generation/docs/z-image-turbo-craft.md` | **Banner: ideation-only** | Composition-Ledger "SUPPORTED" verdicts (e.g. same-plane two-shot, n=2: `5489cbf7`, `c7ae42b8`) demoted to small-n observations; the doc leaves the continuity path per audit §17. |
| `packages/visual-generation/docs/character-lora-plan.md` | **Mark superseded** (keep as history) | Superseded by audit §7: dataset = ~12 of the agent's own synthetic outputs, no hero geometry, no held-out views; "Phase 6 verification passed" withdrawn — one tuned two-shot is not validation. RunPod/ai-toolkit ops gotchas remain valid. |
| `packages/visual-generation/docs/celeste-visual-batch-v2-plan.md` | **Mark superseded** | "Proven per-shot recipes" withdrawn; the 1.5/1.5 two-shot recipe deprecated (strength balancing ≠ isolation). |
| `packages/visual-generation/docs/production-testing-playbook.md` Workflows 5–6 (anchor img2img, LoRA training, forbid-bleed) | **Mark deprecated paths** | Keep the harness structure; the covered paths are off the continuity path. |
| `packages/visual-generation/docs/character-lora-explainer.md`, `character-lora-narrator-audit.md` | **Add provenance banner** | "Training dataset = agent-generated synthetic frames (gen-ids in filenames); images shown are INPUTS unless a gen-id proves otherwise." |
| `video-generation-research.md` / `video-generation-implementation-guide.md` / primer (in git at `d37805b`) | **Amend one clause** | "Z-Image Turbo stays for… scene-opening drafts" → non-canonical ideation only; keyframe/still authority is plate-first (audit amendment + §17). |
| `~/agent-projects/LLM-implementation-visual-agent-audit/Claude - Audit…` | **Mark corrected** | Header note: "'already validated solo recipe' claims herein were built on training inputs misread as outputs — corrected by Consolidated Audit §1." |
| `lora_guard.py` docstrings / `1de80c7` framing | **Doc-level note only** (code change out of scope) | The strength ceiling stays as a useful warning; the rationale "because canon owns identity" is wrong — note in README that lora_guard mitigates over-strength artifacts, it does not provide identity isolation. |

### B4. Not found (named in the retrospective request)

`fidelity-drift-learnings.md`, `coraline-visual-quality-analysis.md` — no file, no git history, not in `~/agent-projects` or `~/agent-data`. Nearest equivalents already covered above.

### B5. Unswept

`user_knowledge` collection (`fact` domain, comfyui_mechanics etc.) — not audited this session (op vault unavailable); sweep for canon-related facts before trusting `fact` retrieval on identity topics.

---

## C. Why the misread survived (mechanisms to fix)

1. **No input/output provenance labeling.** LoRA dataset files are named by generation-id and sit beside `.txt` caption sidecars (`~/agent-data/visual-generation/lora/narrator/dataset/`) — visually identical to output+caption evidence. Five Celeste training inputs read as the recipe's best outputs.
2. **No held-out identity check.** "Phase 6 verification passed" = the same two-shot iterated until "usable." Training-adjacent images validated a training-derived recipe — circular.
3. **Confirmation-only lesson pipeline.** `lesson add` requires "CONFIRMED", but confirmation = it worked once; no falsification protocol; craft-doc verdicts promoted to SUPPORTED at n=2.
4. **Layer-blind escalation ladder.** 2.0 → restatement points → 1.5/1.5 → lora_guard ceiling → retrain-on-Turbo → 1.0+1.0 → 1.2/0.85 + "must not look alike" prefix: seven attempts at one failure class, every one at the prompt/strength layer, no recorded architecture question until three external audits forced it.
5. **Docs compound without re-testing upstream assumptions.** Craft doc ("true identity lock would require a LoRA") → canon-guide ("locked identity") → lora-plan ("go") → v2 plan ("proven, hard-won — follow them") → lora_guard ("canon owns identity"). Each layer cites the previous as settled.

---

## D. Process guardrails

1. **Conditioning-first attribution:** identity, staging, and set-geometry failures are conditioning/asset problems until proven otherwise. A prompt-layer lesson about them may only be stored with a falsification test attached (a defined counter-case that would disprove it).
2. **Provenance labels on all evidence:** every image cited in any doc, report, or audit is labeled `input` or `output` with lineage (gen-id or dataset path). An unlabeled image supports no claim.
3. **Three-strikes architecture trigger:** 3+ failed attempts at one fix class (e.g. bleed via strength/wording) triggers a written architecture question naming the layer being blamed and the alternative layer that could be at fault — before a 4th attempt is paid for.
4. **"Validated" requires held-out evidence:** an identity/continuity claim needs a test the tuning loop never saw (new pose/view/scene) scored against pre-defined criteria; until then docs say "tuned," never "proven/validated." SUPPORTED verdicts need n≥5 plus a counter-case search.
5. **Paid-run question discipline** (audit §16, promoted to standing rule): every GPU batch states, before generation, the single question it answers and its pass/fail criteria; reactions/taste memory are preference data, not validation data.
