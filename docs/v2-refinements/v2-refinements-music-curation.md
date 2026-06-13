# music-curation v2 refinements

Items observed during Session 2 build or v1 real-world testing that are real limitations but not blockers. Filed for future work, not active.

## sound-ref add CLI command missing

Observed: the SoundReference memory type exists in code (Pydantic model, MusicCurationStore.upsert_sound_ref()), but there is no user-facing CLI command to create one. The original design called for `sound-ref add` as an interactive command (description, source_track, timestamp_range, qualities, linked_generation_ids, linked_suno_tags).

Impact: None for current seed data — none of the ingested session files contained structured sound references in the form the type expects (verbal description + source track + timestamp + qualities). The capability is built for a future workflow where the user wants to say "give me more of that sound from session X" and have the agent retrieve a previously-defined reference.

Likely fix when built: a thin interactive `music-curation sound-ref add` command that prompts for each field and calls MusicCurationStore.upsert_sound_ref(). Small addition — the underlying type and store method already exist. Trigger to build: the first time the user wants to define and reuse a sound reference during a real session.

---

## Structured reference inputs + on-demand research

Observed during the first real use sessions: the user reports that 95% of their music prompts reference specific artists, songs, albums, or YouTube tracks as inspiration ("in the style of DJ Smokey's slower work", "like Nujabes but darker"). Currently these references live only as prose in the request string. They're not stored as structured data, they're not retrievable as first-class entities across generations, and the agent has no way to deepen its knowledge of a referenced artist beyond whatever incidentally appears in tutorial_research or user_knowledge.

This is three layered features stacked:

### Layer 1: Structured reference inputs at generate time

Add optional list-valued flags to `music-curation generate`:

- `--artist <name>` (repeatable)
- `--song <title>` (repeatable)
- `--album <title>` (repeatable)
- `--youtube <url>` (repeatable)

These get stored on the Generation Pydantic model as `referenced_artists`, `referenced_songs`, `referenced_albums`, `referenced_youtube_urls` — all `list[str]`, default `[]`.

Why lists: a prompt may reference multiple artists ("Nujabes mood, J Dilla rhythmic feel"). Constraining to single values would force the user back to prose for the multi-reference case.

Show references in `review-pending` and `recall` output where applicable. Include them in the formatted retrieval context block so future generations can find prior generations by what they referenced ("show me phonk generations that referenced DJ Smokey").

### Layer 2: On-demand research for references

A new subcommand group: `music-curation research`.

- `music-curation research artist "<name>"`
- `music-curation research song "<title>" [--artist "<artist>"]`
- `music-curation research album "<title>" [--artist "<artist>"]`

Each delegates to `tutorial-research` with a structured query targeting musical theory, mood/sound, story/themes, overall vibe, tempo/groove, and rhythmic feel for the referenced entity. The delegation uses tutorial-research's existing API. If `--youtube <url>` is provided, that URL is passed as a direct ingestion target rather than relying on Tavily discovery (higher quality, faster, more deterministic).

The research output is parsed and structured into a proposed `music_reference` entry (Layer 3 schema). The user reviews — same y/n/edit/defer flow as taste lessons — and the confirmed entry persists to `music_curation_memory`.

Trigger pattern: two-step with implicit fallback.

- **Primary (two-step)**: the user runs `research artist "DJ Smokey"` once. It populates a `music_reference` entry. Future `generate` calls referencing DJ Smokey retrieve from that entry — fast, no delegation cost per generate. This is the expected pattern for artists/songs the user references repeatedly.
- **Implicit fallback**: if `generate` is called with `--artist X` and no stored `music_reference` exists for X, the agent prompts: "You referenced X but I have no stored profile. Run `music-curation research artist '<name>'` first to populate one, or proceed without that context? [y/N]". Default N (proceed without). Don't auto-delegate inline — research is a tutorial-research run, potentially minutes, and `generate` should stay fast.

The research subcommand should respect the standard agent-runtime BudgetEnvelope, with a default appropriate to a tutorial-research delegation (e.g., max_cost_usd=2.50 to allow tutorial-research's ~$2 budget plus music-curation's parsing/structuring overhead).

### Layer 3: The music_reference memory type

A new memory type within `music_curation_memory`. Not a new collection — joins the existing four types (`generation`, `template`, `taste`, `sound_reference`) with `memory_type="music_reference"`.

Rationale for not using `user_knowledge`: `user_knowledge` is for facts the user verified through experience. A research-derived artist profile is agent-researched and user-blessed — different provenance, different confidence semantics. It belongs with the user's personal/music-specific memory, not the cross-agent verified-knowledge pool.

Rationale for not using a separate collection: it's another memory type with similar shape to existing music-curation types. Joining the existing collection means the music-curation retrieval layer surfaces references alongside prior generations and taste lessons in a single retrieval, which is exactly the assembly pattern we want at generate time.

Schema for a `music_reference` entry:

| Field | Type | Notes |
|---|---|---|
| Embed target | Combined description (synthesis of mood + sound + vibe) | The vector other generations match against when semantic-retrieving by similarity |
| `reference_type` | `artist` \| `song` \| `album` | Discriminator within the memory type |
| `name` | str | "DJ Smokey", "Throwed N Choppped", etc. |
| `artist` | str \| None | For songs/albums — who's the artist |
| `mood_sound` | str | Per-field research output |
| `story_themes` | str | Per-field research output |
| `overall_vibe` | str | Per-field research output |
| `tempo_groove` | str | Per-field research output |
| `rhythmic_feel` | str | Per-field research output |
| `youtube_urls` | list[str] | Source URLs used in research |
| `research_run_id` | str \| None | Links to the tutorial-research run that produced this |
| `confidence` | `high` \| `medium` \| `low` | Based on depth of research available |
| `user_confirmed` | bool | Did the user review and approve the research output |
| `created_at`, `updated_at` | datetime | Standard |
| `superseded_by` | str \| None | If research is later re-run with better data, link to the new version (mirrors UserKnowledgeStore pattern) |

The `user_confirmed` field gates retrieval — by default, unconfirmed entries aren't surfaced in `generate` context. This mirrors the curated-write principle: research outputs are inferences, not facts. The confirmation flow proposes the structured entry, the user accepts/edits/rejects per field if desired.

### How it composes at generate time

When `generate` is called with reference flags:

1. For each referenced entity, look up the corresponding `music_reference` in `music_curation_memory` filtered by `reference_type` and `name`.
2. If found and `user_confirmed=True`, inject the structured fields directly into the generation context with high weight (explicit reference > similarity-based retrieval).
3. If not found, apply the implicit-fallback prompt described in Layer 2.
4. The generation chain's theory_reasoning can cite reference fields by content ("Drawing on DJ Smokey's stored profile: dragging-behind-the-beat pocket, heavy 808 reliance, raw Memphis aesthetic...").

This makes future generations stronger by accumulation: research an artist once, benefit from the structured knowledge across every future generation that references them. No re-research, no re-elicitation.

### CLI subcommand surface (post-implementation)
music-curation research artist "DJ Smokey"
music-curation research song "Throwed N Choppped" --artist "DJ Smokey"
music-curation research album "Phonk Tape Vol. 1" --artist "DJ Smokey" --youtube "https://..."
music-curation research list [--type artist|song|album]
music-curation research show "<name>"
music-curation research review-pending          # confirm proposed entries that weren't confirmed inline

`generate` gains:
--artist <name>      (repeatable)
--song <title>       (repeatable)
--album <title>      (repeatable)
--youtube <url>      (repeatable)

### Design questions resolved during this conversation

- **Lists vs. single values for references**: lists, because multi-reference is common.
- **Trigger for research (implicit vs. explicit vs. two-step)**: two-step primary, implicit-fallback with confirmation prompt. Generation stays fast; research is a deliberate prior step.
- **Where the music_reference memory type lives**: `music_curation_memory`, as a new `memory_type` discriminator value alongside the existing four. Not `user_knowledge` (different provenance), not a separate collection (unnecessary overhead).
- **Structured fields**: mood_sound, story_themes, overall_vibe, tempo_groove, rhythmic_feel — per user's request. These map to what tutorial-research can extract from artist/song/album research.
- **Confirmation flow**: same y/n/edit/defer pattern as taste lessons. Research outputs are inferences requiring user blessing before becoming retrieval-visible.

### Constraints / scope notes

- This is a substantial build. Roughly: new memory type + schema + store methods, new CLI subcommand group with confirmation flow, new retrieval path for explicit-reference lookup, new flags on generate, integration with tutorial-research's delegation API, and the confirmation-flow interactive logic.
- Should not be built until Groups A and B have landed and the user has accumulated enough real-use signal to confirm the structured-field set is right. The five fields listed are the user's initial proposal — real use may show some are unused or that an additional field is needed.
- The implicit-fallback prompt during `generate` is the one piece that could cause UX friction — getting prompted to research mid-flow when in a creative groove might be annoying. Worth a `--no-research-prompt` flag if it proves intrusive, but don't pre-add it; wait for the friction to surface.
- A re-research-and-supersede flow exists in spec via the `superseded_by` field, but the CLI command to trigger it (`research artist "X" --refresh` or similar) is a deferred sub-feature — basic research is the v1.

### Trigger to build

The next time the user wants to research a specific artist/song they reference repeatedly, and finds the lack of structured storage painful — e.g., they're explaining DJ Smokey's style for the fourth time in four generate calls. Or the next time a generate call would have benefited from depth on an artist the agent doesn't know. That's the friction signal; until then, this stays specified-but-not-built.

---

## Pre-existing ruff issues in music-curation package

Observed during the Group A reaction-feedback work (2026-06-01): `ruff check packages/music-curation/src/music_curation/` reports 22 lint issues. All predate the Group A changes and sit in code the reaction work did not modify, so they were left untouched per the no-drive-by-fixes constraint. All are `--fix`-able except the `E741` ambiguous-name cases (which need a manual rename of the loop variable). Tracked here so they're addressed deliberately rather than living only in chat.

Full list (line numbers as of 2026-06-01; may drift):

**`agent.py`**
- `:7` F401 — `datetime.UTC` imported but unused
- `:7` F401 — `datetime.datetime` imported but unused
- `:23` F401 — `agent_runtime.record_llm_call` imported but unused
- `:29` F401 — `music_curation.constants.MODEL_GENERATOR` imported but unused
- `:76` F841 — local variable `start_time` assigned but never used
- `:214` F401 — `tutorial_research.research` imported but unused
- `:225` F841 — local variable `result` assigned but never used

**`chains.py`**
- `:24` F401 — `music_curation.models.GenerationRef` imported but unused
- `:24` F401 — `music_curation.models.MusicResult` imported but unused

**`cli.py`**
- `:17` F401 — `json` imported but unused
- `:20` F401 — `typing.Any` imported but unused
- `:84` F541 — f-string without any placeholders (the "Theory Reasoning" divider echo in `generate`)

**`retrieval.py`**
- `:18` F401 — `music_curation.models.GenerationRef` imported but unused

**`seed_ingestion.py`**
- `:14` F401 — `asyncio` imported but unused
- `:80`, `:216`, `:327`, `:331` E741 — ambiguous variable name `l` (loop vars; rename to `lesson`/`ln`)

**`store.py`**
- `:8` F401 — `agent_runtime.tracing.decorators.record_memory_write` imported but unused
- `:16` F401 — `music_curation.constants.REACTION_PENDING` imported but unused
- `:106`, `:109` E741 — ambiguous variable name `l` (in `upsert_taste_bulk`)

Likely fix: `uv run ruff check --fix packages/music-curation/` clears the F401/F541/F841 set automatically; the six `E741` cases need a one-line manual rename each. Low risk — none affect behavior. Trigger to build: whenever the workspace adopts a ruff gate in CI, or a cleanup pass is wanted. Note: this is a music-curation-package observation; a parallel sweep of the other packages would tell whether it's workspace-wide.

---

## Suno documentation ingestion

**Motivation.** The user_knowledge collection currently holds Suno-mechanics facts derived from the user's session files (during seed ingest). Suno itself publishes documentation at help.suno.com covering features, workflows, and capabilities — particularly the post-generation track-action features (Cover, Extend, Crop, Cut, Adjust Speed, Fade In/Out, Replace Section, Get Stems, Remaster, Open in Studio, Open in Editor). None of this content is currently accessible to the agent.

This documentation is high-quality, structured, factual, and exactly what user_knowledge was designed for. Ingesting it grounds the agent in Suno's own definitions rather than third-party interpretations from YouTube tutorials.

**Shape.** New CLI subcommand:

```
music-curation knowledge ingest-docs <path-to-directory>
```

Local-file-based, mirroring the seed ingest pattern. The user saves Suno docs as markdown locally (manually, via copy-paste, or via a separate scrape tool — the agent doesn't fetch); the command parses the markdown files in the directory, extracts structured entries, and routes them to user_knowledge via UserKnowledgeStore.bulk_load_verified with source_type="documentation" and source_ref pointing to the local file path or original URL if recorded in a frontmatter field.

A future URL-based ingestion (`--url <suno-docs-url>`) is a possible follow-up but not v1 — it introduces fetch and parse complexity tied to Suno's specific docs format, which could change. Local-file ingestion is more deterministic and gives the user control over what's curated in.

**Parsing approach.** Mirror seed-ingest's pattern: regex + section heuristics, no LLM extraction (the docs are structured, parseable, and small enough that LLM parsing would be unnecessary overhead). Each H2/H3 section becomes a candidate entry; the section heading becomes the topic_tag; the body becomes the statement. Confirmation flow at end of run (the same y/n/edit/defer pattern as taste lessons), since not every doc section will be worth storing as a discrete fact.

**Schema mapping to user_knowledge.** Per existing UserKnowledgeStore schema:

- `statement` — the parsed fact/explanation text
- `domain` — `suno_mechanics`
- `topic_tags` — derived from heading hierarchy (e.g., `["track_actions", "cover"]` for a section about Cover)
- `source_type` — `documentation`
- `source_ref` — `file://<path>` or `url://<url>` if recorded
- `confidence` — `high` (it's Suno's own docs)

**Design questions resolved during this conversation.**

- Local-file vs. URL fetch: local-file for v1. URL fetch deferred until v1 proves valuable and Suno's docs structure proves stable.
- Where docs live in the collection model: user_knowledge with source_type="documentation". Not a separate collection; the existing schema accommodates this.
- Parsing approach: regex + section heuristics, same as seed ingest. No LLM extraction.
- Confirmation flow: yes, end-of-run y/n/edit/defer. Not every doc section warrants a stored entry; the user curates which become facts.

**Constraints / scope notes.**

- Independent of the conversational chat mode spec (v2-refinements-agent-runtime). Either can land first; chat mode benefits from this work if it lands first but doesn't require it.
- The retrieval-side already handles user_knowledge entries with source_type="documentation" — no retrieval changes needed; this is purely a write-path addition.
- Future agents writing documentation entries to user_knowledge would use the same UserKnowledgeStore.bulk_load_verified path; this CLI command is music-curation's surface to that path, not a new write mechanism.

**Trigger to build.** When the user has Suno documentation they want to ingest — most likely when working with post-generation features (Cover, Stems, Extend, etc.) and finding the agent's knowledge of those features insufficient. The trigger is the user collecting the docs locally and wanting a path to ingest them; until that need is concrete, this stays specified-but-not-built.

---

## Variant divergence — anchor + explore

**Motivation.** Real use of music-curation surfaces that the current two-variant default produces prompts that are too similar — both anchored close to retrieved precedent. The user can end up with two good tracks that sound alike. Wants one variant as the anchor (close to retrieved precedent) and one as the explore (deliberately diverges along musical-theoretic axes while preserving the request's core intent).

**Shape.** Prompt-level change to the generation chain. When N > 1, the system prompt instructs Sonnet that prompt 1 is the anchor (close to retrieved precedent) and prompts 2+ are progressively more exploratory — varying along axes like rhythm, instrumentation, structural unconventionality, or genre-blending. The exploratory prompt cites *which axes* it diverged on in its theory_reasoning.

Good divergence requires informed variation, not random variation. The exploratory variant's prompt construction should explicitly retrieve relevant music-theory knowledge from `tutorial_research` about how to vary the genre/style/structure at hand. This makes divergence music-theoretically motivated, not stylistically arbitrary.

**Constraints / scope notes.**

- Single LLM call with differentiated prompts in the system message, not a separate call per variant. (Two calls would give explicit control but cost more; start with one and escalate only if divergence still feels timid.)
- The N-prompt instruction should generalize beyond 2 — N=3 means anchor + two exploratory variants progressively more divergent.
- A `--variants 1` invocation should bypass divergence entirely and produce a single anchor-style prompt (the existing flag already supports this).

**Trigger to build.** When the user finds the two-variant output continues to feel timid after a few more real generations, or when they want to deliberately use the divergence as a creative tool ("give me an anchor I trust and an explore I might love").

---

## `--continue` flag for iterating from most recent generation

**Motivation.** Iterating from a specific prior generation currently requires describing it in prose (which relies on semantic retrieval to surface the right entry) or pasting a UUID. Neither is ergonomic for the most common case: continuing from the most recent generation just made. The seed-ingested data preserves evolution chains (`parent_id`, `chain_root_id`), but new generations all become orphan chain-roots because there's no CLI surface for marking a new entry as a child of a prior one.

**Shape.** A new `--continue` flag on `generate`. When passed:

1. Look up the most recent generation by `created_at` (regardless of status — pending or complete both qualify).
2. Treat it as the primary retrieval context (higher weight than ordinary similarity-retrieved hits).
3. Set the new entry's `parent_id` to that prior entry's id.
4. Set `chain_root_id` to the prior entry's `chain_root_id` (so the new entry joins the existing chain rather than starting a new one).
5. Pre-populate `change_summary` with `"iterated from {parent_id}: <user's request>"` as a starting point — the actual summary is generated by Sonnet during the prompt construction.

Also add an explicit form: `--iterate-from <gen_id>` for cases where the user wants to extend a specific older chain rather than the most recent one. This is the same machinery with a different lookup.

**Constraints / scope notes.**

- "Most recent" = most recent by `created_at`, regardless of whether the user has reacted to it. Reaction is not a precondition for iteration — if a prompt was just generated and the user wants to iterate before running it in Suno, that should work.
- The retrieval weight bump (primary context > similarity hits) is the key design piece: without it, `--continue` is just a flag that sets `parent_id` but doesn't actually change generation behavior. The whole point is to make the agent build on the specific prior, not search for it.
- The `notes` field (action-oriented, from `report`) on the parent generation, if present, should be included in the prompt construction context — that's the user's stated direction for what to change.

**Trigger to build.** When the user finds themselves wanting to extend a chain explicitly and the lack of a flag becomes recurring friction, or when iteration-and-refinement becomes a primary workflow pattern.