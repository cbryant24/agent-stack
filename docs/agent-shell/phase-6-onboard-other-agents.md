# Phase 6 — Onboard the other agents, then an optional router

**Goal:** repeat the `visual-generation chat` pattern for the remaining agents, in an order that matches their value and risk.

**Depends on:** Phase 4 (reads, crafting and gated writes proven once). Does not need Phase 5.

Per-agent notes below come from each package README in the bundle. The surface audit in step 1 reads the source and overrides them where they differ.

## Recipe per agent

1. **Surface audit.** `docs/audit/<agent>-tool-surface.md`: every CLI command, its backing library function or "inline", side effects, collection touched.
2. **Library seams.** Extract inline CLI logic into functions in the agent's own package. Interactive confirm flows get a decision-source parameter (see below).
3. **`chat/` module** in the agent's package: `tool_pack()`, `ChatConfig`, `prompts/system.md`, and a `<agent> chat` command.
4. **Effect classes** per tool. Any metered spend outside the LLM is `GPU_SPEND`.
5. **Golden tests** for whatever interpretation the agent does.
6. **README** section in the package and a line in the root README.

If onboarding needs a change in `agent-shell`, stop and review the core design.

### Interactive flows

Several agents confirm writes at a terminal prompt (music-curation `seed ingest`, technique-research's gap gate, `ingest-docs`). `docs/decisions-mode-spec.md` already sets the rule: a non-interactive path must use the same write code path, with only the decision source changing. Apply it here: each flow takes a decision source, and the chat gate is one such source. Do not write a parallel direct-write path.

## Shared tool pack: `knowledge`

Build once, in `agent-shell` or `agent-runtime`'s chat support, and include it in every agent's chat:

| Tool | Wraps | Effect |
|---|---|---|
| `knowledge_drafts` | `UserKnowledgeStore` drafts (7-day expiry) | READ |
| `knowledge_confirm` / `knowledge_reject` | propose then confirm workflow | MEMORY_WRITE |
| `knowledge_search` | `user_knowledge` with the 1.25x boost | READ |

feedback-iteration proposes `editing_preference` lessons that wait for a confirm. Today nothing surfaces them conversationally.

## Order and notes

### 1. music-curation

- **Library:** `curate` / `curate_sync`, `MusicCurationStore`.
- **Tools:** `generate` (LLM_SPEND; writes a pending generation automatically, which the README classes as an event, not an inference), `report` (MEMORY_WRITE), `review_pending`, `recall`, `chain_show` (READ), `taste_add`, `fact_add` (MEMORY_WRITE), `seed_ingest` (MEMORY_WRITE, via the decision-source seam), `seed_review_taste`.
- **No external spend:** Suno has no API; you run prompts by hand.
- **Interpretation:** reactions distinguish `disliked` (taste) from `prompt_failed` (prompt engineering). Map feedback to that vocabulary, the same shape as visual's layers.
- This is the agent the runtime v2-refinement named as the first chat consumer, and it already has the one remediation handler.

### 2. voiceover-direction

- **Library:** `direct_sync`, `plan_generation_sync`, `spend_generation_sync`, `read_directed_script`, `write_directed_script`, `ingest_docs_sync`.
- **Same plan/spend split as visual-generation.** `plan` is LLM_SPEND (it may run a re-direction pass); `spend` is `GPU_SPEND` (ElevenLabs characters). Do not wrap `generate_sync`: it plans and spends with no gate.
- **Gate shows:** per-section character count, total, vendor remaining (queried live), re-direction cost.
- **Other tools:** `report`, `lesson_add`, `fact_add`, `voice_sync` (writes the local registry), `review_pending`, `recall`, and a `voice_list` READ tool (the README notes there is no such command today).

### 3. concept-script

- **Library:** `draft_sync`, `shape_sync`, `to_script_md`, `from_script_md`.
- Stateless, owns no collection. Tools write `script.md` into the project directory; `--dry-run` exists.
- Rule to carry into the prompt: it surfaces and never decides the creative core, and in `shape` only a `director note` phrase is ever treated as an instruction.

### 4. edit-brief + feedback-iteration (one chat)

- **edit-brief:** `draft` with `--dry-run` discovery (free). Stateless. All timing is computed in code.
- **feedback-iteration:** `revise` patches the brief in place after snapshotting to `versions/`; `--dry-run` is free. The LLM never emits a number; a numberless timing request is returned as unresolved.
- `revise` is `DESTRUCTIVE_LOCAL` on a director-owned file: the gate shows the anchors touched and any checked steps that will be invalidated.
- feedback-iteration imports only `agent-runtime`, never `edit-brief`. Keep that: the combined chat lives in one of the two packages and calls the other through its library API, or lives in the router.

### 5. technique-research + tutorial-research

- **technique-research:** `identify`, `recall`. Already has a gate, `--plan-only` and `-y`. `plan` maps to an LLM_SPEND tool; delegation is a gated tool showing the per-gap ceiling (about $2 each at tutorial-research's default cap).
- **tutorial-research:** `research_sync` with `dry_run`; modes research / ingest / retrieve; `ingest-docs`. Ingestion is MEMORY_WRITE plus Tavily spend.
- tutorial-research is the one agent others delegate to. Its chat is mostly `retrieve`.

### 6. video-clipping

- Console script `clip`: `spec init`, `draft` (free pre-pass with projected cost), `generate` (Claude vision spend, preflight cap `--max-usd`), `report`, `explain`.
- `generate` also writes run, segment and auto-accrued lesson points. The gate shows projected cost and that lessons are written automatically.
- Not wrapped by the orchestrator today.

### 7. yt-intelligence-pipeline

- `process_video` / `process_video_sync`. Ingestion writes to `tutorial_research` or a named collection.
- Requires `LANGSMITH_API_KEY` and uses LangChain. Low value as a chat on its own; expose it as tools inside tutorial-research's chat.

## Outside agent-stack

### diffusion-prompter (the repo you linked as wan-prompter)

Its README confirms: three local Ollama writers (`wan-cinematic`, `wan-animate`, `zimage-turbo`) on one base model, run with `ollama run <model> "<idea>"`, a `./log` JSONL journal with a mandatory rating and `what_was_missing`, and `./build`. No Python API.

Two integrations, both optional, both inside `visual-generation chat`:

| Tool | Does | Effect |
|---|---|---|
| `local_prompt(model, idea)` | Calls the local Ollama HTTP API for one of the three writers | NONE (local, free, private) |
| `prompter_review(model)` | Runs the README's improvement loop step 4: reads that model's `log.jsonl` lines and its Modelfile, proposes a rewritten `SYSTEM` and few-shots | LLM_SPEND |
| `prompter_apply(model)` | Writes the Modelfile and runs `./build <model>` | DESTRUCTIVE_LOCAL |

Rules from the README to enforce in the tools: 3-5 few-shot examples per model (adding one prunes one), one model per target, and review only after about 20 rated entries for that model.

Ollama stays out of the REPL engine. `zimage-turbo` overlaps `visual-generation draft`: `draft` is the memory-grounded path; `local_prompt` is the private, free one. The repo path is a config value. `prompter_review` sends log content to a cloud model, which the README's own loop already does; the gate says so.

### Flight tracker, photo tagging

Not workspace members. Out of scope until you decide whether they join.

## Optional router: `stack`

Build only after at least three agents have chat, and only for cross-agent flows keyed by `project_id` (script, voiceover, visuals, edit brief).

- A small package that imports each agent's `chat.tool_pack()` and namespaces tool names (`visual.draft`, `music.recall`).
- Loads tool packs on demand so the tool list stays small.
- Takes over the orchestrator's `search_knowledge` and vector-DB diagnostics (Phase 7).
- No `read_file` / `grep` over the repo. A READ tool returns the relevant package README section.
- No agent depends on it, matching the design docs' rule for the orchestrator.

## Acceptance (per agent)

- Surface audit committed.
- `chat/` contains no store-write code; interactive flows share one write path.
- Every paid or writing tool shows a confirm panel; dry-run works.
- Contract tests pass under both engines.
- The agent's one-shot CLI and library API work without the engine SDK extras.
- No change was needed in `agent-shell`, or the change was reviewed as a core design issue.

## Claude Code prompt (template, per agent)

1. **Goal:** add chat to `<agent>`.
2. **Mode:** plan mode first, then direct.
3. **Files:** `@docs/agent-shell/phase-6-onboard-other-agents.md @docs/decisions-mode-spec.md @packages/agent-shell/README.md @packages/visual-generation/src/visual_generation/chat/ @packages/<agent>/`
4. **Prompt:**

```
Add chat to packages/<agent> following the recipe in
docs/agent-shell/phase-6-onboard-other-agents.md, using visual_generation/chat/ as the
reference implementation.

1. Write docs/audit/<agent>-tool-surface.md: every CLI command -> library function or
   "inline" -> side effects -> collection touched. Stop and show me this before any code.
2. Extract inline CLI logic into library functions. No behavior change. Where a flow confirms
   at a terminal prompt, add a decision-source parameter so the chat gate and the terminal
   prompt share one write path, per docs/decisions-mode-spec.md.
3. Create <package>/chat/ with tool_pack(), a ChatConfig, prompts/system.md and a `chat`
   Click command. Assign effect classes per the audit. Include the shared knowledge pack.
4. Tests: argument mapping, effect classes, no store-write code in chat/, confirm / edit /
   defer / dry-run paths, contract tests under the fake engine, and the one-shot CLI running
   without the engine SDK extras.

If you find you need to change packages/agent-shell, stop and explain why instead of
changing it.
```
