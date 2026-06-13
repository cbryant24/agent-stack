# voiceover-direction v2 refinements

Items captured during the voiceover-direction Phase 2 build and its first real-use run — real limitations or planned extensions, none of them blocking the MVP. Per the build methodology this file is the durable record of everything captured-but-not-built for the agent; it stays current. Filed for future work, not active.

## Directed-file write-back

**Motivation.** The `generate` fold-in (option B) takes a section's last `report` note, runs a section-scoped re-direction (a Claude call), and shows the revised markup at the gate before any spend. Phase 2 deliberately does *not* write that revised markup back to the `.directed.md` file — no auto-overwrite, so the file stays a stable, hand-editable artifact and is never silently mutated. The consequence: the evolved direction lives only in the new take's text (and compounds across iterations because re-direction bases off the last take, not the file), while the on-disk `.directed.md` drifts stale. A user who opens the file after several `report`→`generate` cycles sees the original direction, not what was actually generated.

**Shape.** An opt-in `--write-back` flag on `generate` (or a separate `voiceover-direction sync-file <script.directed.md>` command) that, after a successful spend, rewrites the affected section's markup + `vo-meta` to match the take that was generated, round-tripping through the existing lossless `write_directed_script` format. Never automatic — preserves the Phase-2 decision that the file isn't mutated behind the user's back.

**Constraints / scope notes.**

- Section-scoped: only generated sections are rewritten; untouched sections stay byte-stable.
- Interacts with `--raw` (the hand-edit branch): write-back of a raw-spoken section is the verbatim file content (a no-op), so write-back only meaningfully applies to fold-in-revised sections.
- Open decision for build: overwrite in place (simpler, matches "the file is the editable artifact," relies on git for history) vs. write a sibling `.directed.vN.md` (avoids clobbering hand edits). Lean in-place; surface at build time.

**Trigger to build.** When iterating across several `report`→`generate` cycles on one script makes the staleness of the on-disk file a recurring friction — i.e., the user wants to resume hand-editing from the evolved direction rather than the original.

---

## Reference-driven direction + on-demand voice/style research

**Motivation.** The voice analog of music-curation's reference layer, inverted. Direction today is driven by the script text plus retrieval; the user can't hand the agent a *delivery reference* ("narrate like a nature documentary," "the gravelly noir read," a specific narrator's style) as structured input, and the agent has no way to deepen its knowledge of a referenced style beyond whatever incidentally sits in `tutorial_research` / `user_knowledge`. The voice registry (`voice sync`) tells the agent *which voices exist*, not *how a referenced style maps onto them*. This is three layered features, parallel to music-curation's `music_reference` work.

### Layer 1 — structured delivery-reference inputs at direct time

Repeatable flags on `direct` (e.g. `--style "noir narrator"`, `--reference "Attenborough-like"`), stored on the take / direction model so prior takes become retrievable by what they referenced ("show me takes directed toward a documentary read"). Surface them in `recall` output and in the formatted retrieval context.

### Layer 2 — on-demand research for references

A `voiceover-direction research` subcommand group that delegates to `tutorial-research` for delivery-technique knowledge (pacing, breath, emphasis, register for a referenced style) and, where useful, ElevenLabs-specific technique (which voices/settings approximate a target style). Trigger pattern mirrors music-curation: two-step with implicit fallback — `research style "<name>"` once populates an entry that future `direct` calls retrieve cheaply; if `direct --style X` finds no stored profile, prompt rather than auto-delegate inline (a research run is a tutorial-research delegation, potentially minutes; `direct` should stay fast). Research respects a `BudgetEnvelope` sized for a tutorial-research delegation.

### Layer 3 — a `voice_style_reference` memory type

A new `memory_type` within `voiceover_direction_memory` (not a new collection): name, `reference_type`, the per-axis research output (register, pacing, emotional range, texture), source URLs, `research_run_id`, `confidence`, `user_confirmed`, `superseded_by`. Agent-researched and user-blessed — different provenance from `user_knowledge` (verified facts) and from the concrete voice registry, so it belongs with the agent's own voice memory. `user_confirmed` gates retrieval; unconfirmed entries aren't surfaced in `direct` context.

**Constraints / scope notes.**

- Distinct from the local voice registry: the registry holds concrete vendor voices (JSON, looked up by `voice_id`, never semantically searched); a style reference is a semantic delivery profile that *informs* voice selection + settings, not a voice itself.
- The harder sub-problem is the "reference → concrete voice" mapping: which stock `voices.json` entry best approximates a researched style. Could start advisory (surface candidate `voice_id`s with reasoning) before any automation.
- Composes upward into the persona type below — a confirmed style reference can be promoted into a persona.

**Trigger to build.** When real direction work repeatedly starts from "make it sound like X" and the prose-only path proves lossy — the same signal that drove the music-curation reference layer.

---

## `persona` memory type

**Motivation.** v1 is deliberately single-narrator with no persona: a take carries voice + settings + emotion tags, but there's no first-class notion of a reusable *character/persona* — a named identity with a default voice, baseline settings, and a delivery signature — that persists across scripts and projects. Two workflows want it: multi-speaker dialogue (ElevenLabs v3 supports it; the spec notes it) and a recurring narrator identity (a channel's consistent VO voice the user doesn't want to re-specify every script).

**Shape.** A `persona` `memory_type` within `voiceover_direction_memory`: name, default `voice_id`, baseline settings (stability mode, etc.), a prose delivery signature the direction chain conditions on, and optionally the exemplar takes the persona was learned from. `direct --persona "narrator-1"` seeds the direction chain with the persona's defaults; the chain may still deviate per section, but the persona is the baseline.

**Constraints / scope notes.**

- Doesn't belong in `user_knowledge` — it's voice-specific memory, not cross-agent verified fact (same provenance reasoning as music-curation's `music_reference`).
- Minimal version: a single recurring narrator persona (the likely first build). Larger version: multi-speaker, where a script's per-section speakers each map to a persona and the directed-script `vo-meta` gains a `persona` field.
- Composes with the reference-research layer above.

**Trigger to build.** When the user works on multi-speaker scripts, or maintains a recurring narrator identity across projects and re-specifying voice + settings + delivery each time becomes friction.

---

## Conversational chat mode (agent-runtime dependency)

**Motivation.** The `direct` loop is single-shot CLI: one invocation, one directed-script file. Real direction is conversational ("make the intro punchier," "drop the whisper tag on line 3," "try a warmer voice") — a back-and-forth that today means re-running `direct` or hand-editing the file. This is not voiceover-specific; it's a shared interaction mode that belongs in `agent-runtime` and is tracked in `v2-refinements-agent-runtime.md`. It's listed here as a dependent consumer, not as voiceover-direction-owned work.

**Shape.** An interactive REPL/chat surface (agent-runtime-provided) that voiceover-direction plugs into: the direction chain runs turn-by-turn against an in-memory working directed-script, the user refines in natural language, and the file/takes are written only on an explicit commit.

**Constraints / scope notes.**

- Owned by agent-runtime; voiceover-direction is one consumer (music-curation is another). Cross-agent, not a voiceover-direction-only build.
- Must preserve the cost inversion: chat refines *direction* (free); `generate` stays the deliberate paid commitment. Nothing in chat mode should make generation feel incidental.

**Trigger to build.** When agent-runtime's conversational mode lands (driven from `v2-refinements-agent-runtime.md`); voiceover-direction adopts it as a direction surface at that point.

---

## `--decisions` batch mode for `knowledge ingest-docs`

**Motivation.** `ingest-docs` is interactive (y/n/edit/defer per candidate), and the docs folder is the durable queue — deferred/skipped sections reappear on the next run, and a re-run dedups against existing entries so nothing double-writes. What's missing is a non-interactive *replay*: re-running the same folder after adding a doc still re-prompts every previously-decided candidate. A saved decisions record would apply prior choices automatically and prompt only on genuinely new candidates.

**Shape.** Mirror music-curation's deferred `seed ingest --decisions`: `ingest-docs --decisions <file>` reads/writes a decisions manifest (candidate key → confirm/skip/edit + edited text). The first interactive run can emit the manifest; subsequent runs replay it and prompt only on candidates absent from it. Key on the same dedup tuple already in use (`source_ref` + `topic_tags` + `statement`).

**Constraints / scope notes.**

- The existing dedup pre-check already makes re-runs *safe* (no double-write); `--decisions` makes them *fast* (no re-answering). Distinct concerns.
- Pairs naturally with URL-fetch ingest below — a scripted or scheduled refresh wants both non-interactive flags.

**Trigger to build.** When the ElevenLabs docs folder is re-ingested often enough (docs updates, added pages) that re-answering the confirmation flow becomes the friction.

---

## URL-fetch ingest (`--url`) for `knowledge ingest-docs`

**Motivation.** `ingest-docs` is local-file only by design — the user saves docs as markdown locally and the agent never fetches. Same deferral reasoning as music-curation's URL-fetch defer: fetching introduces parse complexity tied to the vendor's docs format, which can change, whereas local files are deterministic and keep curation in the user's hands. One ElevenLabs-specific note that lowers the risk here: appending `.md` to an indexed docs URL yields a clean markdown export (the convention used to gather the seed corpus), so the parse surface is more stable for this vendor than it was for Suno.

**Shape.** `knowledge ingest-docs --url <elevenlabs-docs-url>` (repeatable) fetches the page (preferring the `.md` export where available), runs it through the same heading→candidate parser and the same y/n/edit/defer confirmation flow, and routes confirmed entries through `UserKnowledgeStore.bulk_load_verified` with `source_ref` recording the URL (`url://<url>` — the schema already accommodates a URL source). No new write mechanism; only a new acquisition front-end on the existing path.

**Constraints / scope notes.**

- Lower risk than the Suno case because of the `.md`-export convention, but still deferred until local-file ingestion has proven the parser against more pages.
- Pairs with `--decisions` for a fully scripted refresh of the ElevenLabs knowledge.

**Trigger to build.** When the user wants to pull ElevenLabs docs without the manual save step — most likely once docs ingestion is a recurring maintenance task rather than a one-time seed.
