# concept-script

A structural/craft scriptwriting collaborator. Turns sparse creative seeds or a
verbatim dictation transcript into a single editable `script.md` that
`voiceover-direction direct` consumes unchanged.

## What it is (and isn't)

concept-script proposes **craft scaffolding** — section breakdown, pacing, an
emotional arc, and candidate per-section emotion direction. It **surfaces, never
decides** the creative core (theme, message, which references matter). You own
every decision by editing the file it produces. It is a collaborator, not a
creative automator.

The load-bearing claim: **v1's output is the Voiceover-Direction-ready script, not
an abstract brief you adapt later.** Both input modes converge on the same
editable artifact the next agent ingests directly.

## Two modes, one artifact

```bash
# Generative — sparse seeds (+ optional prior-script reference) -> script.md
concept-script draft --seeds seeds.md -o script.md
concept-script draft --seeds seeds.md --ref prior-script.md -o script.md
concept-script draft "focus, calm, ~2min, video essay"          # inline seeds

# Curation — a verbatim voice-dictation transcript -> script.md
concept-script shape transcript.txt -o script.md
```

Both verbs accept `--max-cost N` and `--dry-run` (plan only; no LLM call, no file
written). Output defaults to `./script.md`.

`cli-prompts/SEEDS_TEMPLATE.md` is a fill-in-the-blanks starting point for the
generative mode — copy it, fill what you know, leave the rest blank.

## The script.md format

The file is plain markdown, dictated by the consumer
(`voiceover_direction.parser.parse_script_text`):

```markdown
A one-line logline capturing intent.

Music: optional style hints for music curation

# Section One
[reflective] Opening prose with emotion direction inline. [pause] Like this.

# Section Two
[building] The next beat.
```

- **Each section is an H1.** The voiceover parser splits at the shallowest heading
  level present and derives each section's id by slugifying its heading.
- **Emotion direction is inline** as literal ElevenLabs-style `[tag]`s in the
  prose — there is no separate voice-direction field. `voiceover-direction direct`
  passes the tags through and refines them.
- **The logline, optional `Music:` hint, and the curation cut-trailer all live in
  the preamble before the first `#`.** The voiceover parser skips everything before
  the first heading (it logs a harmless `"…content before the first heading…
  skipped"` warning), so none of this leaks into narration. That is what lets the
  same file be consumed by `direct` unchanged.

## Curation command channel (`shape`)

The dictation tool captures verbatim; `shape` resolves an in-band channel inside
the transcript:

- **Verbatim content is preserved.** No paraphrasing.
- **Disfluencies are stripped** — uh, um, dead-air, false starts.
- **Natural stumbles and self-corrections are kept as content** (e.g. "you know
  what, I'm wrong about that…"). They are authentic texture — the voiceover agent
  will narrate them. This is intentional.
- **`director note` is the wake phrase** — the one deliberate edit signal. It
  originates from your own dictation, so it is a legitimate instruction:
  `director note, delete that last portion` is executed, and the phrase plus its
  instruction are removed from the script. Nothing else in the transcript is ever
  treated as a command.
- The output carries a **cut trailer** (in the preamble) listing each executed
  `director note` cut, so you can verify the deletions.

## Library API

```python
from concept_script import draft, draft_sync, shape, shape_sync, ConceptResult

result = draft_sync("focus, calm, ~2 min", prior_script=None)   # ConceptResult
result = shape_sync(open("transcript.txt").read())              # ConceptResult

print(result.script_path)   # the written script.md
print(result.brief.logline)
for s in result.brief.sections:
    print(s.heading, s.prose)
print(result.brief.cut_trailer)   # executed director-note cuts (shape only)
```

Public surface: `draft` / `draft_sync` and `shape` / `shape_sync` (entry points),
`VideoBrief` / `BriefSection` / `ConceptResult` (models), and
`to_script_md` / `from_script_md` (serialization).

## Memory model

**v1 is stateless.** concept-script owns no Qdrant collection. There is no
feedback signal that brief quality could be attributed to, so a write-collection
would be storage without learning. Prior work is reused via file reference
(`--ref @prior-script.md`), since outputs are files. Reading `user_knowledge` /
`tutorial_research` to fill a gap is deferred — see
`docs/v2-refinements-concept-script.md`.

## Default budget

```
max_items=1, max_depth=0, max_cost_usd=1.00, max_wall_time_sec=300
```

`max_depth=0` — v1 never delegates. Model: `claude-sonnet-4-6`.

## Integration

`script.md` feeds `voiceover-direction direct script.md` directly (tightest
coupling — the inline emotion-tag format aligns with its parser). The optional
`Music:` hint is for `music-curation`. Downstream `edit-brief` (not built) will
consume an approved brief later.

## Tests

```bash
uv run pytest packages/concept-script/tests/ -v   # 33 tests
```

No test requires real Anthropic or Voyage API keys. The integration test imports
the `voiceover-direction` parser (a test-only dependency) to prove `script.md` is
consumed unchanged.
