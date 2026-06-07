# music-curation

A music-theory expert and creative partner with persistent memory for crafting Suno AI prompts. Reusable across video projects, podcasts, and standalone music exploration.

## What it solves

1. **No continuity between sessions** — every fresh conversation started from zero. Prompts that produced loved music weren't retained.
2. **Inconsistent output from drifting prompts** — without a record of what prompt produced which result, good directions couldn't be reproduced.
3. **Misunderstandings about Suno** — conversations sometimes got Suno's interface, features, or syntax wrong.

Persistent memory addresses (1) and (2). Accurate Suno knowledge — kept fresh via `tutorial-research` delegations — addresses (3).

## CLI

```bash
# Generate prompts for a request
music-curation generate "lo-fi hip-hop for late-night studying"
music-curation generate "atmospheric phonk with French vocals" --skip-question
music-curation generate "something dark and heavy" --dry-run

# Close the feedback loop after running in Suno
music-curation report <gen_id> --reaction loved --rating 5
music-curation report <gen_id> --reaction liked_with_changes \
    --notes "slow it down next time" \
    --context "the cowbell placement matches the Memphis tradition I love"
music-curation report <gen_id> --reaction prompt_failed   # Suno didn't render the intent

# Inspect memory
music-curation review-pending               # pending generations awaiting reactions
music-curation recall "heavy Memphis phonk" # search prior generations + taste
music-curation chain show <chain_root_id>   # show evolution chain

# Write memory directly
music-curation taste add "French vocals work well over lo-fi phonk" --valence positive --scope vocal
music-curation taste add "Blues feels best compact — ~2 min, single verse, no extended jams" \
    --valence positive --scope arrangement
music-curation fact add "Memphis phonk cowbell is essential for authentic phonk sound" --domain suno_mechanics

# Seed from session files
music-curation seed ingest ~/path/to/session-files/ --dry-run   # preview
music-curation seed ingest ~/path/to/session-files/             # interactive
music-curation seed ingest ~/path/to/file.md --yes              # no prompts
music-curation seed review-taste                                 # review deferred taste
```

## Reusable prompt files

For repeated, multi-paragraph requests, keep a markdown file per genre and pipe it in:

```bash
uv run music-curation generate "$(cat packages/music-curation/cli-prompts/blues.md)"
```

`cli-prompts/TEMPLATE.md` is a fill-in-the-blanks starting point with inline comments on
every input dimension that actually moves the output — genre, reference artist/song,
instrumentation (including negative constraints like "no electric guitars"), vocal
character, production/era texture, tempo, language, length, and explicit structure. Copy
it per genre. Everything in HTML comments is guidance for you; it reaches the agent as
plain prose, not a directive.

## Controlling length and structure

Suno has **no duration parameter** — song length is an emergent property of the lyrics
field (more/longer sections ⇒ longer song). The generation system prompt (`chains.py`)
carries a length→structure mapping so a request like "around 2 minutes" is translated into
a concrete section count rather than dropped:

| Target | Structure |
|---|---|
| ~1–1.5 min | `[Intro] + [Verse] + [Chorus]` (+ short `[Outro]`) |
| ~2 min | `[Intro] + [Verse] + [Chorus] + [Verse]/[Chorus] + [Outro]` |
| ~3 min | two verse/chorus cycles + `[Bridge]` |

When a request names an explicit section list (e.g. "one intro, chorus, verse, chorus,
outro"), the model reproduces exactly those sections in order — it will not add a second
verse or reorder them.

**Per-song spec vs. standing taste.** An explicit length/structure in the request is the
spec for *that* generation and overrides any conflicting retrieved template or prior
generation — this is **precedence, not an exception**, and it does not change your stored
taste. To express a *durable* length/structure preference across songs, either let it
emerge from `report ... --context "..."` reactions, or declare it with the **`arrangement`**
taste scope (`taste add "..." --scope arrangement`). A saved taste becomes the default for
dimensions a request leaves unspecified; the request always wins when it speaks.

## Library API

```python
from music_curation import curate, curate_sync, MusicResult, SunoPrompt
from agent_runtime import BudgetEnvelope

# Synchronous
result = curate_sync("late-night lo-fi hip-hop, contemplative mood")

# Async
result = await curate("dark phonk with French vocals", skip_question=True)

# Inspect results
for prompt in result.prompts:
    print(f"Style ({len(prompt.style_field)} chars):")
    print(prompt.style_field)
    if prompt.lyrics_field:
        print("\nLyrics:")
        print(prompt.lyrics_field)

print(result.theory_reasoning)    # music-theory reasoning
print(result.cross_references)    # similar prior generations
print(result.generation_ids)      # IDs of pending entries (report reactions with these)
```

Public surface: `curate` / `curate_sync` (entry points), `MusicResult` and `SunoPrompt` (output models), `MusicCurationStore` (the store wrapper over `MemoryStore` that owns `music_curation_memory` — used directly when an embedding host needs to query or write the four memory types outside a `curate()` run).

## Memory model

All memory lives in the `music_curation_memory` Qdrant collection, discriminated by `memory_type`:

| Type | Embedded text | Key payload fields |
|---|---|---|
| `generation` | style_field | reaction, status, chain_root_id, parent_id, bpm, language |
| `template` | descriptor | style_pattern, swap_variables, domain_tags |
| `taste` | statement | valence, scope, confirmed |
| `sound_reference` | description | source_track, qualities, linked_generation_ids |

Suno-mechanics facts live in `user_knowledge` (runtime-owned, `domain=suno_mechanics`).

## Retrieval

On each request the agent issues parallel queries (`asyncio.gather`) across three collections and assembles a weighted context:

- **`music_curation_memory`** — prior generations (pending entries excluded by default), confirmed taste lessons, and templates
- **`user_knowledge`** — `suno_mechanics` facts, scored with a `USER_KNOWLEDGE_SCORE_MULTIPLIER` (1.25×) boost so user-verified facts outrank tutorial-derived hits
- **`tutorial_research`** — read-only music-theory / Suno-feature knowledge

Each leg degrades silently if its collection is missing or Qdrant is unreachable. Retrieved items are formatted with source-tagged prefixes (`[PRIOR GENERATION: reaction=LOVED]`, `[USER FACT: suno_mechanics]`, `[TASTE: positive/genre]`, `[TUTORIAL KNOWLEDGE]`) so the generation model can weight and cite them correctly. When local memory is thin, a `DelegationTrigger` may route to `tutorial-research` (see the architecture doc for the three trigger rules and thresholds).

## Curated writes

Three write paths, matching the nature of the data:

- **Automatic (events)** — generated prompts are logged immediately as pending generations (`status="pending"`). A prompt is a fact about what was emitted, not an inference, so it needs no confirmation.
- **Confirmation (inferences)** — taste lessons and inferred templates parsed from seed files are interpretations, so they go through a y/n/edit/defer confirmation before being written. Deferred items queue under `~/agent-data/drafts/music-curation/taste-pending/` for later `seed review-taste`.
- **Explicit (direct commands)** — `taste add`, `fact add` write exactly what the user states, confirmed by the act of running the command.

## Pending-generation handling

A generation is written with `status="pending"` at emit time and a `suggested_track_title` (a memorable 3–5 word handle for re-finding the track in Suno — required in the model's structured output; the agent retries rather than substituting a generic default). Pending entries are excluded from taste/quality retrieval by default. After running a prompt in Suno, `report <gen_id> --reaction <X>` records the reaction and flips status to `complete`; `review-pending` lists everything still awaiting a reaction.

`report` also accepts an optional `--rating <1-5>` (intensity within a reaction tier — two `loved` tracks can differ; used as a retrieval tiebreaker after similarity score) and two distinct free-text fields:

- **`--notes`** — *action-oriented*: what to change or do differently next time. Informs the next generation in a chain; not surfaced as standing retrieval context.
- **`--context`** — *reasoning-oriented*: why you reacted the way you did. Becomes part of the retrievable signal — when the agent pulls a similar prior generation, the `context` is included in the formatted block (e.g. `[PRIOR GENERATION: reaction=loved, rating=5, context="..."]`) so the model sees *why*, not just *that*, you reacted.

`--rating` is meaningful for positive reactions (`loved`, `liked`, `liked_with_changes`); pairing it with a negative reaction is accepted but warns.

## Seed ingestion

`seed ingest <path>` parses Suno session-summary markdown into the four memory types plus `user_knowledge` suno_facts (via `UserKnowledgeStore.bulk_load_verified`). Generations and explicit taste/templates are written automatically; inferred taste/templates go through interactive confirmation (the curated-write flow above). `--dry-run` previews counts without writing; `--yes` writes everything without prompts.

A non-interactive `--decisions <file>` mode (with a companion `--dry-run --emit-decisions <file>` to generate the template) is **specified but not yet implemented** — see `.decisions-mode-spec.md` at the workspace root. Until it lands, interactive mode is the only confirmation path.

## Reaction vocabulary

| Value | Meaning |
|---|---|
| `pending` | Generated but not yet run in Suno |
| `loved` | Produced something loved |
| `liked` | Kept, would use |
| `liked_with_changes` | Direction good, wanted adjustments |
| `disliked` | Suno rendered the prompt correctly but the result isn't to taste (aesthetic feedback) |
| `prompt_failed` | Suno didn't render the prompt's intent correctly (prompt-engineering issue, not aesthetic) |
| `copyright_blocked` | Tripped Suno's copyright filter |
| `never_ran` | Prompt written, never executed in Suno |
| `lost_track` | Was run, reaction not recorded |

`disliked` and `prompt_failed` have opposite implications for future generations: `disliked` weighs against the *territory* (avoid this aesthetic next time); `prompt_failed` leaves the territory open and surfaces the prior prompt as a structure to learn from (the intent didn't render — revise the prompt, don't abandon the direction).

## Default budget

```
max_items=1, max_depth=2, max_cost_usd=1.50, max_wall_time_sec=300
```

`max_depth=2` allows music-curation → tutorial-research → further delegation.

## Tests

```bash
uv run pytest packages/music-curation/tests/ -v   # 213 tests
```

No tests require real Anthropic or Voyage API keys. Tests requiring Qdrant are skipped automatically if not running.
