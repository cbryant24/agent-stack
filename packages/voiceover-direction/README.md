# voiceover-direction

Director for ElevenLabs voiceover work. The cost structure inverts music-curation:
*direction* (choosing text, emotion tags, voice, pacing) is free LLM iteration, while
*generation* (the ElevenLabs call) burns a scarce monthly character budget. So you direct
freely until a section is settled, then spend characters on generation as a deliberate
commitment; the reaction is recorded later by a separate command.

**Status: Phase 2 complete (MVP).** 145 tests passing. The full loop — `direct` → `generate`
→ `report` — is live, plus the inspect (`review-pending`, `recall`), direct-write
(`lesson add`, `fact add`), and knowledge/voice commands (`knowledge ingest-docs`,
`voice sync`).

## The turn

ElevenLabs inverts music-curation's cost structure. There, emitting the prompt was free and
the scarce step was running it in Suno. Here it's reversed:

- **Direction** (text, emotion tags, voice, pacing) is LLM-only — cheap, infinitely iterable.
- **Generation** (the ElevenLabs call) burns the monthly character budget — scarce.

So a turn is: **direct freely until the direction is settled, then spend characters on
generation as a deliberate commitment.** Iteration lives in direction, never in generation.
The lifecycle is split — `generate` produces audio + a pending take and exits; you go listen,
then `report` your reaction (the API is synchronous, but the human listening step isn't).

## Commands

**Direct a script** (free, re-runnable — no API cost):
```bash
voiceover-direction direct script.md [-o out.directed.md] [--project-id ID] [--dry-run]
```
Parses the markdown into sections — section boundaries are the shallowest heading level
present, so a script written with `#` H1s and one written with `##` H2s both split correctly
(deeper headings stay within a section's body) — composes retrieval across the three
collections, runs the whole-script direction chain (Sonnet), and writes an editable
*directed-script* file — headings preserved, audio tags inline, per-section metadata
(voice, model, settings, notes) in invisible HTML-comment JSON that round-trips losslessly.

**Generate audio** (spends ElevenLabs characters):
```bash
voiceover-direction generate script.directed.md (--section <id> | --all) [--raw] [-y] [--max-cost N]
```
Runs in two phases so the cost gate can show the *revised* markup before any spend:
- **plan** — resolves each target section. If a section's last take carries a `report` note
  (and not `--raw`), the note is folded into a section-scoped re-direction (a Claude call,
  option B) and the revised markup is shown. This phase carries the Claude cost (capped).
- **gate** — soft-inform: per-section char count, total to spend, vendor remaining (queried
  live, not cached), re-direction cost. `--yes` skips the confirm.
- **spend** — TTS → audio file + a `pending` take. Characters are recorded as a span
  attribute, **never** in `BudgetEnvelope`.

`--raw` speaks the file's section markup verbatim (the hand-edit branch — skips the fold-in).

**React** (after listening — flips the take `pending` → `complete`):
```bash
voiceover-direction report <take_id> --reaction <X> [--rating 1-5] [--notes "..."] [--context "..."]
```
Reaction vocabulary: `loved`, `liked`, `liked_with_changes`, `disliked`, `render_failed`.
The load-bearing distinction: `disliked` = rendered faithfully but not to taste (aesthetic —
weighs against the direction/territory); `render_failed` = ElevenLabs didn't render the intent
(tags ignored, mispronunciation — the direction was fine, the territory stays open, the prior
take surfaces as structure to learn from). `--rating` is meaningful only for positive reactions.

**Inspect:**
```bash
voiceover-direction review-pending          # takes awaiting a reaction
voiceover-direction recall "<query>" [--limit N]   # search prior takes + direction lessons
```

**Direct writes:**
```bash
voiceover-direction lesson add "<statement>" [--valence positive|negative] [--scope voice|pacing|tone|general]
voiceover-direction fact add "<statement>" [--domain elevenlabs_mechanics] [--confidence high|medium|low]
```

**Knowledge + voices:**
```bash
voiceover-direction knowledge ingest-docs <folder> [--dry-run] [--yes]   # local ElevenLabs docs → user_knowledge
voiceover-direction voice sync                                            # pull voices from ElevenLabs into the registry
```
`ingest-docs` parses each `##`+ heading into a candidate (heading hierarchy → `topic_tags`,
body → `statement`), runs a y/n/edit/defer confirmation (no LLM), and loads confirmed entries
via `UserKnowledgeStore.bulk_load_verified` (`domain=elevenlabs_mechanics`,
`source_type=documentation`, `confidence=high`). The docs folder is the durable queue — deferred
or skipped sections reappear on the next run, and a re-run dedups against existing entries.

## Memory model

All vectors live in `voiceover_direction_memory`, discriminated by `memory_type`:

| Type | Embedded text | Key payload |
|---|---|---|
| `take` | the section text sent to ElevenLabs | voice_id, model, settings, emotion_tags, character_count, audio_path, reaction, rating, status, section_id, project_id, domain, parent_take_id, chain_root_id |
| `direction_lesson` | the statement | valence, scope (voice/pacing/tone/general), confirmed |

**Voice registry** — a local JSON file (`<agent_data_dir>/voiceover/voices.json`), not a vector
type. Voices are enumerated/looked-up by `voice_id`, never semantically searched. Rewritten
wholesale on each `voice sync`. **ElevenLabs mechanics facts** live in the runtime-owned
`user_knowledge` collection (`domain=elevenlabs_mechanics`).

Retrieval (`retrieve_context`) composes three collections in parallel —
`voiceover_direction_memory` (prior takes + direction lessons), `user_knowledge`
(`elevenlabs_mechanics`, 1.25× score-boosted), and `tutorial_research`. Each leg degrades
silently, so `direct` is useful from a cold start with every collection empty.

## Two budgets

The per-run Claude cost (for `direct` and the `generate` fold-in) stays in agent-runtime's
`BudgetEnvelope`. The monthly ElevenLabs character budget is orthogonal — queried from the
vendor at generation time, never cached locally, never routed through `BudgetEnvelope`.
ElevenLabs already hard-enforces the quota, so the agent informs rather than gatekeeps.

## eleven_v3 stability — mode vs. float

`eleven_v3` expresses stability as a discrete *mode* (`creative` / `natural` / `robust`), which
the direction chain emits and the directed-script `settings` dict carries. The API's
`voice_settings.stability`, however, is a float (0.0–1.0): lower = broader emotional range,
higher = more consistent/monotonous. The ElevenLabs client translates the mode to its float at
the vendor boundary only — `creative → 0.0`, `natural → 0.5`, `robust → 1.0`. A numeric
stability passes through unchanged (v2-style settings stay valid); an unknown mode string raises
a clear `ValueError` naming the valid modes rather than re-triggering the opaque 422. The chain
output and directed-script format are unchanged — only the client adapter coerces.

## Library API

```python
from voiceover_direction import (
    direct_sync, generate_sync, plan_generation_sync, spend_generation_sync,
    read_directed_script, write_directed_script, ingest_docs_sync,
)

result = direct_sync("script.md")            # DirectionResult: directed_script, output_path, cost_usd, ...
result = generate_sync("script.directed.md", all_sections=True)  # GenerationResult (plan + auto-spend, no gate)
```

`generate` is the prompt-free combined entry (plan + auto-spend) for library use; the CLI runs
plan → interactive gate → spend.

## Testing

```bash
uv run pytest packages/voiceover-direction -q
```

Store tests that touch Qdrant skip automatically when it isn't running at `localhost:6333`
(`@requires_qdrant`). The ElevenLabs client is tested fully mocked — no live key, no characters
consumed.
