# Visual Agent — project source manifest

This manifest tells future Visual Agent chats what to read, which source wins when records conflict, and which material should be loaded only for a specific task.

## Authority order

| Rank | Source | Establishes | Limits |
|---|---|---|---|
| 1 | Current code; exact submitted ComfyUI API graph; model/source hashes; image/video metadata; live service response | What was implemented or executed | Current code may differ from historical execution; embedded metadata may omit human decisions |
| 2 | Signed director gate; current target document; approved asset manifest | What visual result is accepted | A design target is not approval; a rating is not necessarily a formal gate |
| 3 | Machine-readable `vg-spec`, sequence spec, workflow slot map | What was requested | A value may be dropped or overwritten before submission |
| 4 | Session log and cost ledger | Operator actions, chronology, review, spend | Can be incomplete or contain stale summaries |
| 5 | Batch rationale, README status prose, handoff | Intent and context | May describe a value that did not run or a state that later changed |
| 6 | Retrospective, audit synthesis, chat summary | Interpretation | Must be reconciled with dates and primary artifacts |

If rank 1 conflicts with rank 3, report **execution mismatch**. If rank 2 conflicts with an older design note, the latest recorded director decision wins. If two sources at the same rank conflict, retain both and mark the question unresolved until a stronger source settles it.

## Always-read orientation set

Use this small set at the start of a new Visual Agent evaluation chat:

1. [`project-instructions.md`](project-instructions.md) — operating rules.
2. [`evaluation-charter.md`](evaluation-charter.md) — what the project evaluates and how progression works.
3. [`chatgpt/celeste-coraline-failure-analysis-2026-09-22.md`](chatgpt/celeste-coraline-failure-analysis-2026-09-22.md) — verified baseline and unresolved questions.
4. [`../README.md`](../README.md) — current implemented agent surface; verify status claims against code.
5. [`../../../docs/visual-generation-known-issues.md`](../../../docs/visual-generation-known-issues.md) — open and resolved technical issues.

Do not preload every historical summary into every chat. Retrieve the additional set below based on the evaluation question.

## Task-specific sources

### Character, set, and editor work

- [`bakeoff/celeste-v2-design-TARGET.md`](bakeoff/celeste-v2-design-TARGET.md)
- [`bakeoff/sheet-1-hero-approval-gate.md`](bakeoff/sheet-1-hero-approval-gate.md)
- [`bakeoff/sheet-2-bakeoff-score-sheets.md`](bakeoff/sheet-2-bakeoff-score-sheets.md)
- [`bakeoff/sheet-3-derivation-instructions.md`](bakeoff/sheet-3-derivation-instructions.md)
- [`bakeoff/session-log.md`](bakeoff/session-log.md)
- `bakeoff/outputs/` and embedded PNG ComfyUI graphs
- [`Consolidated-Coraline-Stop-Motion-Visual-Generation-Audit.md`](Consolidated-Coraline-Stop-Motion-Visual-Generation-Audit.md)

### Prompt, LoRA, and historical failure analysis

- [`coraline-failure-conclusions.md`](coraline-failure-conclusions.md)
- [`coraline-prompt-to-image-evidence.md`](coraline-prompt-to-image-evidence.md)
- [`character-lora-narrator-audit.md`](character-lora-narrator-audit.md)
- [`fidelity-drift-learnings.md`](fidelity-drift-learnings.md)
- Current and historical source, plus the embedded graphs in `~/agent-data/visual-generation/identity/celeste-you-dangerous/`

Historical chat summaries live at:

`~/obsidian/obsidian-vault-personal/production-agents/visual-generation/chat-summaries/`

Use them to reconstruct decisions and acceptance standards. They do not override graphs, code, or current director targets.

### RunPod operations

- [`../runpod-setup-context.md`](../runpod-setup-context.md)
- [`../../../scripts/README.md`](../../../scripts/README.md)
- [`../../../docs/handoffs/visual-generation-2026-09-20-runpod-global-volume-handoff.md`](../../../docs/handoffs/visual-generation-2026-09-20-runpod-global-volume-handoff.md)
- `scripts/pod`, `scripts/comfyui-bootstrap`, and `scripts/stage-models`
- Current RunPod and ComfyUI primary documentation for upstream behavior and pricing

The handoff is historical context. The current scripts and setup context control present operation.

### Video implementation and evaluation

- [`video-generation-implementation-guide.md`](video-generation-implementation-guide.md)
- [`video-generation-research.md`](video-generation-research.md)
- [`video-generation-doc-references.md`](video-generation-doc-references.md)
- [`../workflows/README.md`](../workflows/README.md)
- `workflows/wan2.2-t2v-14B-lightx2v-api.json`
- `workflows/wan2.2-i2v-14B-lightx2v-api.json`
- [`../../../docs/handoffs/visual-generation-video-phase1-handoff.md`](../../../docs/handoffs/visual-generation-video-phase1-handoff.md)

The implementation guide describes a target state as well as existing behavior. Verify every claimed feature in current code before calling it implemented.

## External runtime sources

These are not fully represented in Git and should be attached as additional local-project folders only when the work needs them:

| Folder | Use | Handling |
|---|---|---|
| `~/agent-projects/celeste-you-dangerous/` | Director-owned story, reference, batch, audit, and production artifacts | Recommended secondary folder for the project |
| `~/agent-data/visual-generation/` | Code-owned batches, assets, registries, ledger, identity renders, datasets | Attach/read when auditing execution or runtime state; avoid manual reorganization |
| `~/obsidian/obsidian-vault-personal/production-agents/visual-generation/` | Historical chat summaries and working notes | Attach/read for chronology; treat as secondary evidence |

Do not add all of `~/Downloads` or an entire personal vault. Attach the smallest relevant folder. Real photographs and other personal material stay local and are not used outside the authorized project task.

## Known superseded or disputed claims

- Older clay/felt/fingerprint material descriptions are superseded by the August 1 painted-resin target.
- The claim that the historical canon cleanup is still pending is stale; the deterministic append/strip path was removed.
- The strongest v2 Celeste pose examples were training inputs, not proof renders from the trained LoRA.
- The shipped LoRA training base is unresolved where Base and Turbo records conflict.
- The back-view narrator solo cannot prove facial consistency.
- A `$100+` overall cost is reported, not audited; local ledgers cover narrower scopes.
- Attempts 11–13 have embedded graph evidence but no located formal human gate record.
- Project READMEs may say video is “set up” while referring to manual ComfyUI execution. Verify whether the agent CLI can provision sources, retrieve MP4s, record lineage, enforce approvals, and render sequences before calling video integration complete.

## Freshness check

At the start of work that may spend money or change architecture, record:

- Git commit and working-tree state;
- current date;
- current code paths used;
- ComfyUI commit/version and custom nodes;
- workflow filename and content hash;
- model filenames and hashes;
- live RunPod GPU, volume, rate, and pod ID;
- whether Qdrant is reachable;
- whether the claimed source assets are formally approved.
