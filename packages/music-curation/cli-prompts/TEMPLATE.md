# User Song Prompt for Agent
<!--
  REUSABLE PROMPT TEMPLATE for `music-curation generate`.

  Run with:   uv run music-curation generate "$(cat packages/music-curation/cli-prompts/<file>.md)"

  Copy this file per genre (blues.md, jpop.md, …) and fill it in. Everything in
  HTML comments (like this) is guidance for you and is harmless to leave in — it is
  plain prose to the agent, not a directive. Delete or keep as you like.

  HOW THE AGENT USES THIS: the whole file is sent verbatim as the request. The agent
  turns it into a Suno **style field** (comma-separated sonic descriptors, max 1000
  chars) and an optional **lyrics field** (with [Section] tags). It also pulls your
  saved taste + prior generations from memory and blends them in. Anything you state
  explicitly here OVERRIDES a conflicting saved default for THIS song only — it does
  not change your standing taste (see "Make it stick" at the bottom).

  WHAT ACTUALLY MOVES THE OUTPUT: genre, mood, tempo, instrumentation, vocal character,
  production/era texture, language, length, and explicit section structure. The headers
  below cover each. The more concrete and sensory you are, the closer the result.
-->

## Sound and Style

<!--
  GENRE / VIBE — the anchor. One or two genres + a mood.
    e.g. "heavy delta blues, mournful but warm"
-->

<!--
  REFERENCE ARTIST / SONG (optional but powerful) — name them freely.
  The agent will NOT put an artist name in the Suno style field (Suno strips/!blocks
  these and it can trip the copyright filter). Instead it translates the reference into
  sonic descriptors. If your memory is thin on that artist it may auto-research them.
  Naming a specific SONG ("like Skip James – Hard Time Killin' Floor") is the single
  most effective reference you can give.
-->

<!--
  INSTRUMENTATION — list what you want, and explicitly what you DON'T.
  Negative constraints work ("no electric guitars, acoustic only"). Be specific:
  "fingerpicked resonator guitar, upright bass, brushed kit".
-->

<!--
  VOCALS — gender, age, tone, accent, delivery, and bass/brightness.
    e.g. "calm male vocal, younger, light on the low end, understated (not theatrical)"
  Say "instrumental, no vocals" if you want none — the agent will add [Instrumental].
-->

<!--
  PRODUCTION / ERA TEXTURE — how it should be recorded/mixed.
    e.g. "grainy and old like a dusty 1950s–60s record, mono, tape hiss, warm and lo-fi"
-->

<!--
  TEMPO — words are fine ("slow drag", "mid-tempo"); a number is honoured too
  ("around 70 BPM"). BPM, when given, is parsed and stored on the generation.
-->

<!--
  LANGUAGE (if not English) — goes in the style field. State it plainly
  ("Japanese vocals" / "French lyrics").
-->

<!--
  LENGTH — Suno has NO duration slider; length comes from how many lyric sections there
  are. State a target and the agent maps it to a section count:
     ~1–1.5 min ≈ intro + verse + chorus (+ short outro)
     ~2 min     ≈ intro + verse + chorus + verse/chorus + outro
     ~3 min     ≈ two verse/chorus cycles + bridge
-->

<!--
  STRUCTURE — if you want an exact arrangement, list the sections in order and the agent
  reproduces EXACTLY those, no extras:
     "one intro, chorus, verse, chorus, outro"  ← will not add a second verse
-->


## Lyrics

<!--
  Delete this whole section for an instrumental.

  THEME — what the song is about, in a sentence or two. Name people/places you want
  referenced (these can appear in the lyrics).

  TONE — fun / funny / clever / mournful / sincere. A reference works here too
  ("clever and playful like Lil Dicky").

  POSITIVE REFERENCES — bullet the specifics you want woven in:
    -
    -

  NEGATIVE REFERENCES / things they do that you're poking fun at:
    -
    -

  DO-NOT — call out anything to avoid explicitly ("don't make it romantic",
  "don't say she's funny outright"). The agent honours explicit exclusions.
-->


<!--
  ── Make it stick (turn a one-off into a durable preference) ────────────────────────
  This file is per-song. To teach the agent what you like ACROSS songs, use memory:

  1. After running a prompt in Suno, close the loop:
       music-curation report <gen_id> --reaction loved --rating 5 \
         --context "perfect length — compact single-verse blues, didn't drag"
     The --context note is embedded and resurfaces on similar future requests, so your
     taste emerges from real reactions instead of being re-typed each time.

  2. Or declare a standing preference directly (scope it so it generalises correctly):
       music-curation taste add \
         "Blues feels best compact — ~2 min, single verse, no extended jams" \
         --valence positive --scope arrangement

  Scopes: genre | production | instrumentation | vocal | arrangement | general
    arrangement = length / song structure / section layout.

  A saved taste becomes the DEFAULT; an explicit line in a prompt file still wins for
  that one song. You never need "exceptions" — precedence handles it.
-->
