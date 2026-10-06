# Visual Agent — ChatGPT project setup

This folder contains the durable setup for the **Visual Agent** project in the ChatGPT desktop app.

Official OpenAI guidance says a local project can attach multiple folders, uses its primary folder for new chats and automatic `AGENTS.md` discovery, and shares project files/context across its chats. Keep separate chats focused on separate outcomes.

## Current primary folder

Use this repository as the primary folder:

`/Users/chrisbryant/dev/agent-stack`

This exposes the implementation, version-controlled workflows, evaluation documents, and root `AGENTS.md`.

## Recommended secondary folders

Attach these only when their evidence is needed:

1. `/Users/chrisbryant/agent-projects/celeste-you-dangerous`
   - Director-owned story, references, audit bundle, batches, and production artifacts.
2. `/Users/chrisbryant/agent-data/visual-generation`
   - Runtime assets, batches, model registry, cost ledger, identity render archive, and LoRA datasets.
3. `/Users/chrisbryant/obsidian/obsidian-vault-personal/production-agents/visual-generation`
   - Historical session summaries and working notes.

Do not attach the whole home folder, all of `Downloads`, or the entire Obsidian vault. The narrow folders above reduce irrelevant retrieval and unnecessary access to personal material.

## Project instructions

Use the contents of:

[`../project-instructions.md`](../project-instructions.md)

as the project's instruction text if the app exposes a Project Instructions field. The root `AGENTS.md` also points future Codex chats to the same setup.

## Shared project sources

The orientation and evidence rules are:

- [`../project-source-manifest.md`](../project-source-manifest.md)
- [`../evaluation-charter.md`](../evaluation-charter.md)
- [`celeste-coraline-failure-analysis-2026-09-22.md`](celeste-coraline-failure-analysis-2026-09-22.md)

The source manifest intentionally uses a small always-read set and task-specific sources. Loading all historical summaries into every chat would make current decisions harder to distinguish from stale ones.

## Recommended chats

Create one chat for each outcome:

| Chat | First objective |
|---|---|
| `01 — Execution truth` | Fix and prove seed/graph/slot provenance before paid agent tests |
| `02 — Character and set authority` | Score and approve heroes and set plates |
| `03 — Editor bake-off` | Complete matched Qwen/Kontext/control tests |
| `04 — Three-frame still proof` | Demonstrate character separation and set continuity |
| `05 — RunPod benchmark` | Measure bootstrap, storage, cold/warm load, teardown, and total cost |
| `06 — Video plumbing` | Prove agent-driven T2V, I2V, FLF2V retrieval and lineage with generic fixtures |
| `07 — Coraline video proof` | Score one clip, then three connected clips from approved boundaries |
| `08 — Cost reconciliation` | Maintain the full compute/storage/training ledger |

## New-chat kickoff template

Use this prompt at the start of an evaluation chat:

```markdown
Evaluation case: <name>
Active phase: <phase/gate>
Question this chat must answer: <one question>
Authoritative inputs: <files/assets/graphs>
Acceptance gate: <rubric and threshold>
Cost cap: <amount or no paid work>
Required artifact: <report, code change, scored sheet, graph, or clip>

Read the Visual Agent project instructions, source manifest, and evaluation charter first. Reconstruct current state from the highest-authority evidence. Distinguish observed, inferred, and unresolved claims. Do not start paid work until the inputs, variables, stop rule, and artifact record are complete.
```

## Immediate first evaluation

Start with **Gate 0 — execution truth** from the evaluation charter. It is the dependency for trusting any new agent-driven image or video comparison:

1. fix random-seed application so the resolved seed is written into the submitted graph;
2. reject required values that lack workflow slots;
3. preserve the submitted graph and hashes with the output;
4. prove two random runs and one explicit fixed-seed run against a neutral fixture;
5. only then proceed to paid editor or video evaluation.

