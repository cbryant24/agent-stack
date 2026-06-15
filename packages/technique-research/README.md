# technique-research

> "I want to make a video like X — what techniques are involved?"

Technique **discovery**, not clip discovery. Given a creative goal (optionally a reference
image of the look, a reference video URL, or a prior report), the agent reasons to a
**prioritized set of technique domains**, checks what the system already knows, delegates
only the genuine gaps to `tutorial-research`, and curates the result into a director-owned
**TechniqueReport** plus accumulating per-technique findings.

What it owns that `tutorial-research` does not: **(a)** the identification layer (goal →
which techniques matter, and why), **(b)** the control flow *identify → check → delegate →
curate* (the check makes run N+1 cheaper than run N), and **(c)** the curated layer —
relevance *decisions*, not gathered material. It never discovers/ingests tutorials itself;
the moment material needs gathering, that's a delegation.

## CLI

```bash
# invoke via uv (the bare console script isn't exposed by uv run in this workspace)
uv run --package technique-research technique-research identify "<goal>" \
    [--image <path>]... [--url <video-url>] [--ref <report.md>] \
    [--scope editing|generation|both] [--domain "<AMV|game review|…>"] \
    [-o report.md] [--plan-only] [--max-cost N] [-y]

uv run --package technique-research technique-research recall "<query>" [--limit N]
```

- **Interactive gate by default.** After identification you see the technique list + the
  per-gap delegation plan and prune per-domain. `-y` auto-approves; `--plan-only` stops at
  the gate (preview only — no delegation, no writes). Declining all gaps is **not** an
  abort — the run curates from existing knowledge.
- **Scope** is inferred from the goal ("a video like X" → editing; "images like X" →
  generation); the explicit `--scope` flag is authoritative when set.

## How it works (Mode A)

1. **Ground** — yt-dlp metadata for a `--url` (no frame extraction); a conditional,
   Claude-triggered Tavily *reference* search only when a named reference is
   under-specified (a well-specified goal costs zero searches).
2. **Identify** — Sonnet (vision-capable) takes goal + images + grounded context + prior
   findings + the director's toolset and emits prioritized technique domains.
3. **Check** — per domain, query `technique_research_outputs`, `tutorial_research`, and
   `user_knowledge`; any collection clearing its threshold answers locally, else the domain
   is a gap. Every decision is traced via `record_delegation_decision`.
4. **Gate → delegate** — approved gaps each delegate to `tutorial-research` on a child
   budget. `max_items` caps **delegations**, not findings.
5. **Curate → outputs** — findings grounded in the gathered material and the director's
   toolset (with a paid/Studio **upgrade flag** where relevant) → the TechniqueReport
   (`-o`), the `technique_research_outputs` points, and the standard run report.

## Toolset grounding

The director's toolset (DaVinci Resolve free + constraints, ffmpeg, mpv, Topaz Video AI,
etc.) is **never hardcoded**. All how-to-apply grounding and upgrade-flag reasoning comes
from retrieving `user_knowledge` `domain=editing_toolset` at runtime, so it stays current
as the toolset evolves.

## Memory

Owns `technique_research_outputs` (text-embedded, `voyage-3-large`). The stored unit is the
per-technique **finding** (technique → description, why it matters, how to apply, toolset
fit, source refs, goal/domain context). The agent's own `check` step is the retrieval
consumer that earns the collection; the orchestrator reads it as a `search_knowledge`
domain and via the `technique_recall` / `technique_identify` tools.

## Library API

```python
from technique_research import identify, identify_sync, recall, IdentificationInput

result = await identify(IdentificationInput(goal="a punchy AMV"))   # -> TechniqueResult
findings = await recall("speed ramping")                            # -> [(score, TechniqueFinding)]
```

Deferred / V2 items: see `docs/v2-refinements/technique-research-v2-refinements.md`.

## FAQ

Common questions and knowledge gaps. Add entries as they come up.

### Why is the delegation cost estimate so high (e.g. ~$10)?
The gate sums each gap's child delegation at tutorial-research's default per-run cap (~$2 each), so 5 gaps shows ~$10. It's a worst-case "up to" ceiling, not expected spend — most runs finish under cap, and technique-research's own `max_cost_usd` envelope (default $5) clamps the true total below the displayed sum. Decline gaps to trim it.

### How do I actually "use" the TechniqueReport?
Two channels. **Automatic:** findings are written to `technique_research_outputs` (and delegations land in `tutorial_research`), which visual-generation and edit-brief query on their runs — no action needed. **Director-mediated:** the report file seeds `concept-script draft --seeds <report>.md` and gives you intent language for `visual-generation draft`. It cannot be fed to `concept-script shape` (shape takes no `--seeds`).

### Is the report "ingested" separately?
No. Running `identify` ingests findings into the collections as part of the run (you'll see tutorial-research run IDs cited in the report). The `.md` is just your readable copy — there's no separate ingest step.

### Where do this agent's files go?
`-o` outputs are director-owned working files — put them in your per-project folder (`~/agent-projects/<project-slug>/`). Machine-managed outputs (sources, audio, stills, qdrant) go under `~/agent-data/`, and run reports auto-write to `~/obsidian/agent-reports/`. Canonical, single-source-of-truth detail: [File organization](../../README.md#where-should-project-files-live) in the repo root README.
