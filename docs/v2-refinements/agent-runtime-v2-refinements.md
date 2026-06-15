# agent-runtime v2 refinements

Items observed during real-world use that are real limitations or anticipated capabilities but not blockers. Filed for future work, not active.

## Conversational query mode

**Motivation.** Current agents (music-curation, tutorial-research) interact via one-shot CLI invocations. This works well for generation and ingestion flows where each invocation is self-contained. It works less well for exploratory querying — questions about an agent's memory, follow-ups, drill-downs — where each turn naturally builds on the prior. The one-shot pattern forces the user to either repeat context every invocation or rely on the agent to re-retrieve everything, which is friction for fundamentally exploratory interactions.

This pattern is anticipated to recur across agents. Music-curation is the first consumer; davinci-color-grading (planned future agent) is the second confirmed consumer; further domain agents are likely. Building chat mode into music-curation as a one-off would commit to a migration later when the second consumer arrives. Building it in the runtime once, with each agent opting in, is the right call now.

This reverses the original system-spec decision to use one-shot CLI for all interactions. The original argument (continuity comes from memory, not session state) holds for generation/ingestion flows but doesn't hold for query/exploration flows. Both modes can coexist per agent — generation/ingestion subcommands stay one-shot; chat is its own mode.

**Shape.** A runtime-layer capability that any agent can compose with. The runtime provides:

- A REPL loop with session-scoped conversation history (in-memory, not persisted across sessions)
- Per-turn retrieval orchestration against agent-supplied collections
- A conversation-shape Sonnet chain (vs. the generation-shape chains in `agent_runtime.chains`) — answer-focused, with citation requirements
- An end-of-session memory proposal flow — at session close, the agent proposes any writes that emerged from the conversation (taste lessons, sound references, knowledge entries, agent-specific types) and the user confirms via the standard y/n/edit/defer flow
- Trace events for chat turns (same observability story as existing record_* helpers)

Agents supply:

- The system prompt that scopes the conversation to their domain
- Which collections to query each turn
- Which memory types are proposable at session end (and the proposal/confirmation logic for each — likely a small typed interface the agent implements)
- Domain-specific output formatting

**Composition pattern.** Mirrors the UserKnowledgeStore pattern: the runtime owns the generic shape; the agent supplies the domain-specific bits via composition or interface. Sketch:

```python
from agent_runtime.chat import ConversationalSession, ConversationConfig

config = ConversationConfig(
    system_prompt=MUSIC_CURATION_CHAT_PROMPT,
    collections=["music_curation_memory", "user_knowledge", "tutorial_research"],
    proposable_memory_types=[
        TasteProposal(store=music_curation_store),
        SoundReferenceProposal(store=music_curation_store),
        FactProposal(store=user_knowledge_store),
    ],
    model=MODEL_GENERATOR,
)

async with ConversationalSession(config) as session:
    await session.run_repl()  # blocks until user exits
    # On exit: end-of-session proposals fire, user walks through y/n/edit/defer
```

CLI surface per agent (music-curation as the example):

```
music-curation chat
```

Opens the REPL. Existing subcommands (generate, report, recall, etc.) stay one-shot. Chat is its own mode, not a replacement.

**Design questions resolved during this conversation.**

- Runtime-layer capability vs. agent-specific: runtime. Music-curation is the first consumer; davinci-color-grading anticipated as the second.
- REPL vs. richer one-shot: REPL. Follow-up questions and drill-downs are central to the exploratory mode, and the one-shot pattern can't carry session state cleanly.
- Session persistence: not persisted across REPL invocations. Within a session, history accumulates; close the REPL and start fresh next time. The end-of-session proposal flow is what makes the session durable in memory terms — the *conclusions* persist, not the conversation transcript.
- Memory writes: never silent. End-of-session proposal flow with explicit user confirmation per item, same pattern as taste-lesson confirmation in seed ingest.

**Constraints / scope notes.**

- Should not be built until the structured-references-and-research feature in docs/v2-refinements/music-curation-v2-refinements.md is either landed or explicitly deferred, since they likely share retrieval and confirmation infrastructure.
- The end-of-session proposal flow is the design piece most likely to need refinement after real use. The basic shape (propose batched, confirm individually) is right; what's uncertain is how the conversation's content gets *decomposed* into proposals — that requires real conversation logs to design against.
- The system-spec doc (docs/ai-director-agent-system.md) should be updated when this lands to reflect that conversational mode is a supported runtime capability and to document the agent-side interface for opting in.

**Trigger to build.** When the user wants to ask exploratory questions about their music memory or about Suno mechanics, finds the existing `recall` subcommand insufficient (it returns hits, not answers), and the friction of one-shot interaction for exploration becomes a recurring annoyance. Anticipated to happen once the structured-references feature lands and the user starts exploring "what do I know about this artist" / "what mechanics matter for this feature" questions across the populated knowledge base.

## `AGENT_PROJECTS_DIR` — config-owned project working directory (deferred)

Today the per-project working folder (`~/agent-projects/<slug>/` holding `brief.md`, `script.md`, `directed.md`, the visual batch, `edit-brief.md`) is a **documentation convention only** — no agent reads it. The director passes `-o <path>` manually and the runtime never sees the project dir. The runtime-managed paths (`agent_data_dir`, the agent-reports vault) are already centralized in `RuntimeConfig`; the project working dir is the one location convention that lives only in prose (root README "File organization", referenced by the project-plan template and each package README).

**The refinement:** add `AGENT_PROJECTS_DIR` (default `~/agent-projects`) to `RuntimeConfig`, plus a small path helper (e.g. `project_dir(project_id) -> agent_projects_dir / project_id`, created on demand like the other config dirs). Agents that take `-o` and a `--project-id` could then **default their output into `AGENT_PROJECTS_DIR/<project_id>/`** when `-o` is omitted, instead of the cwd. This makes the convention enforceable from one place: change the base dir in `.env`/config and every agent follows, the same way `agent_data_dir` works today.

**Why deferred:** it only earns its place once we want tooling to *auto-place* outputs; until then the doc convention is sufficient and agents stay explicit about `-o`. Scope when built: the config field + helper here, then each agent's CLI opts into the default. No behavior change for explicit `-o` paths.
