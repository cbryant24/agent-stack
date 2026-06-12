---
project_id: script-draft
version: 1
date: 2026-06-12
agent: edit-brief
inputs:
  vo_takes: 0 of 7 sections
  music_file: none
  music_duration_sec: none
  bpm: none (none)
  assets: 0
---

# Edit Brief — script-draft

> **Missing inputs / notes**

> - No voiceover takes discovered for this project — ALL section timestamps are word-count ESTIMATES, not measured durations. Run `voiceover-direction` and regenerate the brief for exact timing.
> - No music track provided (`--music FILE`) — no track on the timeline.
> - No BPM available — beat grid omitted. Pass `--bpm N`, or log the track in music-curation, to get beat-aligned cut proposals.
> - No generated assets or `--footage` discovered — footage sourcing is unaddressed.
> - ALL TIMESTAMPS ARE ESTIMATED — no VO take exists for any section. Every section boundary and duration is approximate. The entire edit structure is provisional until real footage and/or VO recordings are placed.
> - NO ASSETS DISCOVERED — every section requires footage. The brief contains no clips, media files, or generated assets to place. Director must supply footage for all seven sections before a functional edit can begin.
> - NO BPM / BEAT GRID — beat-aligned steps have been omitted throughout per instructions. If music is added later and a beat grid is generated, speed ramp points, transition triggers, and effect keyframes will need to be revisited.
> - RECURRING 0.500s INTER-SECTION GAPS — every section pair has a 0.500s gap between the estimated end of one section and the estimated start of the next (8.400→8.900, 24.100→24.600, 40.200→40.700, 57.500→58.000, 73.200→73.700, 88.500→89.000). These may be intentional (breathing room) or artifacts of estimation. Director must decide: black slug, extend adjacent clips, or eliminate once real footage defines actual durations.
> - NO VO PIPELINE — no VO take exists for any section. When VO is recorded, it should be placed on Audio Track 1 at each section's start timestamp. The Fairlight page should be used for audio cleanup and mixing at that time.
> - TOPAZ / FFMPEG PIPELINE NOTE — if footage passes through Topaz Video AI denoising, use Proteus (prob-4) as the reliable model on M1. Nyx crashes on M1 due to Apple Neural Engine / CoreML cache corruption (clear cache: `rm -rf "/Applications/Topaz Video.app/Contents/Resources/models/coreMLCache"` if testing). After Topaz, transcode output via ffmpeg with `-vsync vfr` before importing into Resolve to avoid VFR/CFR mismatch corrupting retime calculations.
> - STUDIO-ONLY FEATURES FLAGGED — the following techniques are NOT available in the free tier and have been noted where relevant: Speed Warp retiming (⬆ Studio), Color page Blur/Mist (⬆ Studio), Film Grain effect in Effects Library (⬆ Studio), Noise Reduction panel on Color page (⬆ Studio), RGB Shift effect in Effects Library (⬆ Studio). Free workarounds via Fusion page have been noted where findings provide them.
> - TUTORIAL MATERIAL (orchestra/piano) — the supplied tutorial material is not applicable to any editing step in this project and has not been used.
> - DIRECTOR PREFERENCE — SUNO MUSIC: if background music is generated via Suno for any section, apply all explicit negation descriptors ('no drums, no percussion, no rhythm section, no bass') and target 60–75 BPM solo synthesizer framing with 'unaccompanied' and 'isolated keyboard voice' language. This affects music generation, not Resolve editing steps directly.
> - GAP: no color grading intent specified per section — Hue vs. Saturation, halation/bloom, and softness steps have been written as conditional ('if intended'). Director should confirm which sections receive which grade treatments before Color page work begins.
> - GAP: no transition style specified between sections — only placeholder cuts and a fade-to-black on the close have been written. If cross-dissolves, whip-pan smears, or other transitions are intended, run technique-research or confirm intent per section.
> - GAP: no Deliver/export settings provided — no export steps written. Director must configure output format, codec, and resolution on the Deliver page before final export.

## Timeline

| Section | Start | End | VO | Timing |
|---|---|---|---|---|
| [Opening image](#opening-image) | 00:00.000 | 00:08.400 | — | estimate |
| [The problem we don't name](#the-problem-we-don-t-name) | 00:08.900 | 00:24.100 | — | estimate |
| [What focus actually is](#what-focus-actually-is) | 00:24.600 | 00:40.200 | — | estimate |
| [The calm underneath](#the-calm-underneath) | 00:40.700 | 00:57.500 | — | estimate |
| [A different way to work](#a-different-way-to-work) | 00:58.000 | 01:13.200 | — | estimate |
| [What you get back](#what-you-get-back) | 01:13.700 | 01:28.500 | — | estimate |
| [Close](#close) | 01:29.000 | 01:36.200 | — | estimate |

## Beat grid

_No beat grid — no BPM available. See missing-inputs above._

## Sections

<a id="opening-image"></a>
### Opening image — 00:00.000 → 00:08.400

- [ ] 1. On the Edit page, create a new timeline named 'script-draft' with a frame rate matching your intended output (e.g. 24fps) and a resolution appropriate to your footage — set this before placing any clips.
- [ ] 2. Since no VO take exists and the timestamp is ESTIMATED, place a placeholder title clip (use 'Text+' from the Effects Library > Titles on the Edit page) at 0.000s spanning the full section duration (0.000s → 8.400s, duration = 8.400s). Label it 'PLACEHOLDER: opening-image footage needed'.
- [ ] 3. If director footage candidates for this section are available in the future, surface them here for director selection — do NOT auto-assign any clip.
- [ ] 4. If a generated visual asset exists for the opening image (prompt/intent provided), place it on Video Track 1 at 0.000s, trimmed to end at 8.400s.
- [ ] 5. Leave the audio track empty for this section (no VO). If background music is later added, it will begin here — note the entry point as 0.000s.
- [ ] 6. On the Edit page, right-click the placeholder clip → Flag it (e.g. yellow) to mark it as 'needs footage'.

> ⚠ TIMESTAMP ESTIMATED — no VO take recorded. All cuts in this section are provisional until real footage is placed.
> ⚠ No assets discovered — footage needed for opening image. Director must supply or select from candidates.
> ⚠ No BPM/beat grid — omit all beat-aligned steps per instructions.
> ⚠ No VO file to place. If VO is recorded later, it should be placed on Audio Track 1 starting at 0.000s.
> ⚠ Tutorial material (orchestra/piano) is not relevant to this section's editing steps.
> ⚠ Director preference: if background music is being generated via Suno, apply explicit negation descriptors ('no drums, no percussion, no rhythm section') and target 60–75 BPM solo synthesizer framing.

<a id="the-problem-we-don-t-name"></a>
### The problem we don't name — 00:08.900 → 00:24.100

- [ ] 1. On the Edit page, move the playhead to 8.900s (the section start).
- [ ] 2. Place a placeholder Text+ title clip on Video Track 1 at 8.900s, trimmed to end at 24.100s (duration = 15.200s). Label it 'PLACEHOLDER: the-problem-we-don-t-name footage needed'.
- [ ] 3. Right-click the placeholder clip → Flag it (e.g. yellow) to mark it as 'needs footage'.
- [ ] 4. If director footage candidates exist for this section, surface them as ranked candidates for the director to review — do NOT decide the final pick.
- [ ] 5. If a generated visual asset (with prompt/intent) has been produced for this section, place it on Video Track 1 at 8.900s, trimmed to 24.100s.
- [ ] 6. Leave Audio Track 1 empty in this range (no VO take).
- [ ] 7. Ensure there is a clean cut (no transition) between the previous section's clip end at 8.400s and this section's clip start at 8.900s — the 0.500s gap (8.400s→8.900s) should be noted as a potential black frame gap; decide whether to extend the previous clip, add a black slug, or trim once real footage is in place.

> ⚠ TIMESTAMP ESTIMATED — no VO take. All cuts provisional.
> ⚠ 0.500s gap between previous section end (8.400s) and this section start (8.900s) — director must decide how to handle (black slug, extend prior clip, or trim). Cannot resolve without real footage.
> ⚠ No assets discovered — footage needed. Director must supply or select.
> ⚠ No BPM/beat grid — omit all beat-aligned steps.
> ⚠ No VO file to place.

<a id="what-focus-actually-is"></a>
### What focus actually is — 00:24.600 → 00:40.200

- [ ] 1. On the Edit page, move the playhead to 24.600s (the section start).
- [ ] 2. Place a placeholder Text+ title clip on Video Track 1 at 24.600s, trimmed to end at 40.200s (duration = 15.600s). Label it 'PLACEHOLDER: what-focus-actually-is footage needed'.
- [ ] 3. Right-click the placeholder clip → Flag it (e.g. yellow) to mark it as 'needs footage'.
- [ ] 4. If director footage candidates exist for this section, surface them as ranked candidates for the director to review — do NOT decide the final pick.
- [ ] 5. If a generated visual asset (with prompt/intent) has been produced for this section, place it on Video Track 1 at 24.600s, trimmed to 40.200s.
- [ ] 6. Leave Audio Track 1 empty in this range (no VO take).
- [ ] 7. Note the 0.500s gap between the previous section end (24.100s) and this section start (24.600s) — same gap-handling decision required as noted in the previous section.

> ⚠ TIMESTAMP ESTIMATED — no VO take. All cuts provisional.
> ⚠ 0.500s gap between previous section end (24.100s) and this section start (24.600s) — director must decide handling.
> ⚠ No assets discovered — footage needed. Director must supply or select.
> ⚠ No BPM/beat grid — omit all beat-aligned steps.
> ⚠ No VO file to place.

<a id="the-calm-underneath"></a>
### The calm underneath — 00:40.700 → 00:57.500

- [ ] 1. On the Edit page, move the playhead to 40.700s (the section start).
- [ ] 2. Place a placeholder Text+ title clip on Video Track 1 at 40.700s, trimmed to end at 57.500s (duration = 16.800s). Label it 'PLACEHOLDER: the-calm-underneath footage needed'.
- [ ] 3. Right-click the placeholder clip → Flag it (e.g. yellow) to mark it as 'needs footage'.
- [ ] 4. If director footage candidates exist for this section, surface them as ranked candidates for the director to review — do NOT decide the final pick.
- [ ] 5. If a generated visual asset (with prompt/intent) has been produced for this section, place it on Video Track 1 at 40.700s, trimmed to 57.500s.
- [ ] 6. Leave Audio Track 1 empty in this range (no VO take).
- [ ] 7. Note the 0.500s gap between the previous section end (40.200s) and this section start (40.700s) — same gap-handling decision required.
- [ ] 8. If a soft visual treatment (diffusion/glow) is desired for this section's 'calm' aesthetic: the Color page Blur and Mist tools are Studio-only and NOT available in the free version. Use the Fusion-based blur approach instead — on the Edit page, right-click the clip → 'Open in Fusion Page'; add a Blur node between MediaIn and MediaOut (Gaussian, adjust radius to taste). Alternatively, bake softness into an exported LUT applied via ffmpeg. (See toolset fact: 'The Blur and Mist tools on the Color page are Studio-only.')

> ⚠ TIMESTAMP ESTIMATED — no VO take. All cuts provisional.
> ⚠ 0.500s gap between previous section end (40.200s) and this section start (40.700s) — director must decide handling.
> ⚠ No assets discovered — footage needed. Director must supply or select.
> ⚠ No BPM/beat grid — omit all beat-aligned steps.
> ⚠ No VO file to place.
> ⚠ Diffusion/softness effect: Blur and Mist on Color page are Studio-only (⬆ paid/Studio). Fusion-based Blur node is the confirmed free workaround — complex to set up. ffmpeg LUT bake is the lower-overhead alternative.

<a id="a-different-way-to-work"></a>
### A different way to work — 00:58.000 → 01:13.200

- [ ] 1. On the Edit page, move the playhead to 58.000s (the section start).
- [ ] 2. Place a placeholder Text+ title clip on Video Track 1 at 58.000s, trimmed to end at 73.200s (duration = 15.200s). Label it 'PLACEHOLDER: a-different-way-to-work footage needed'.
- [ ] 3. Right-click the placeholder clip → Flag it (e.g. yellow) to mark it as 'needs footage'.
- [ ] 4. If director footage candidates exist for this section, surface them as ranked candidates for the director to review — do NOT decide the final pick.
- [ ] 5. If a generated visual asset (with prompt/intent) has been produced for this section, place it on Video Track 1 at 58.000s, trimmed to 73.200s.
- [ ] 6. Leave Audio Track 1 empty in this range (no VO take).
- [ ] 7. Note the 0.500s gap between the previous section end (57.500s) and this section start (58.000s) — same gap-handling decision required.
- [ ] 8. If speed ramping is intended for this section: before importing any footage into Resolve, transcode Topaz output via ffmpeg with '-vsync vfr' to avoid duplicated frames that would corrupt retime calculations: `ffmpeg -i topaz_output.mp4 -vsync vfr -c:v libx264 -crf 18 proxy.mp4`. Then in Resolve, right-click the clip on the Edit page → Retime Controls. Set clip properties → Retime Process → Optical Flow. (Note: Speed Warp is Studio-only and produces materially better results on fast motion — ⬆ paid/Studio.)

> ⚠ TIMESTAMP ESTIMATED — no VO take. All cuts provisional.
> ⚠ 0.500s gap between previous section end (57.500s) and this section start (58.000s) — director must decide handling.
> ⚠ No assets discovered — footage needed. Director must supply or select.
> ⚠ No BPM/beat grid — omit all beat-aligned steps. Speed ramp points cannot be beat-aligned without BPM data.
> ⚠ No VO file to place.
> ⚠ Speed Warp retiming is Studio-only (⬆ paid/Studio). Standard Optical Flow is free. VFR pre-transcode via ffmpeg required before Resolve import if Topaz output is used.

<a id="what-you-get-back"></a>
### What you get back — 01:13.700 → 01:28.500

- [ ] 1. On the Edit page, move the playhead to 73.700s (the section start).
- [ ] 2. Place a placeholder Text+ title clip on Video Track 1 at 73.700s, trimmed to end at 88.500s (duration = 14.800s). Label it 'PLACEHOLDER: what-you-get-back footage needed'.
- [ ] 3. Right-click the placeholder clip → Flag it (e.g. yellow) to mark it as 'needs footage'.
- [ ] 4. If director footage candidates exist for this section, surface them as ranked candidates for the director to review — do NOT decide the final pick.
- [ ] 5. If a generated visual asset (with prompt/intent) has been produced for this section, place it on Video Track 1 at 73.700s, trimmed to 88.500s.
- [ ] 6. Leave Audio Track 1 empty in this range (no VO take).
- [ ] 7. Note the 0.500s gap between the previous section end (73.200s) and this section start (73.700s) — same gap-handling decision required.
- [ ] 8. If a neon/selective saturation grade is intended for this section: go to the Color page. In Curves, select 'Hue vs. Saturation'. Add control points to: (a) pull green and cyan-green band toward zero saturation; (b) pull orange-red midpoint down slightly; (c) boost magenta-purple band sharply; (d) boost yellow-amber band sharply. Then open 'Luminance vs. Saturation' curve and drop saturation in the shadow range to zero so crushed blacks stay neutral. This is available in the free tier. (See finding: 'Selective Saturation — Boost Neon Hues, Desaturate Neutrals' — toolset fit: DaVinci Resolve free Color page.)
- [ ] 9. If a halation/bloom effect is intended: on the Edit page, right-click the clip → 'Open in Fusion Page'. Build the node chain: MediaIn → Brightness/Contrast node (crush to isolate brightest highlights) → Blur node (Gaussian, radius ~30–50px, tinted toward dominant neon hue) → Merge node back over unblurred MediaIn using Add blend mode at ~20–35% opacity. (See finding: 'Halation / Neon Bloom via Fusion Highlight Blur' — toolset fit: DaVinci Resolve free Fusion page. ⬆ paid/Studio: Color page Blur and Mist tools would achieve this faster but are Studio-only.)

> ⚠ TIMESTAMP ESTIMATED — no VO take. All cuts provisional.
> ⚠ 0.500s gap between previous section end (73.200s) and this section start (73.700s) — director must decide handling.
> ⚠ No assets discovered — footage needed. Director must supply or select.
> ⚠ No BPM/beat grid — omit all beat-aligned steps.
> ⚠ No VO file to place.
> ⚠ Halation/bloom via Fusion is confirmed free workaround but complex to set up. Color page Blur/Mist is Studio-only (⬆ paid/Studio).
> ⚠ Selective saturation Hue vs. Saturation and Luminance vs. Saturation curves are both available free.

<a id="close"></a>
### Close — 01:29.000 → 01:36.200

- [ ] 1. On the Edit page, move the playhead to 89.000s (the section start).
- [ ] 2. Place a placeholder Text+ title clip on Video Track 1 at 89.000s, trimmed to end at 96.200s (duration = 7.200s). Label it 'PLACEHOLDER: close footage needed'.
- [ ] 3. Right-click the placeholder clip → Flag it (e.g. yellow) to mark it as 'needs footage'.
- [ ] 4. If director footage candidates exist for this section, surface them as ranked candidates for the director to review — do NOT decide the final pick.
- [ ] 5. If a generated visual asset (with prompt/intent) has been produced for this section (e.g. a closing title card or end graphic), place it on Video Track 1 at 89.000s, trimmed to 96.200s.
- [ ] 6. Leave Audio Track 1 empty in this range (no VO take).
- [ ] 7. Note the 0.500s gap between the previous section end (88.500s) and this section start (89.000s) — same gap-handling decision required.
- [ ] 8. For a clean out on the final frame, add a Fade to Black: on the Edit page, in the Inspector panel with the final clip selected, use 'Composite' settings or manually add a Cross Dissolve to black at the tail — right-click the clip's end handle → Add Transition → Cross Dissolve, or drag a 'Dip to Color Dissolve' (black) from Effects Library > Video Transitions onto the clip's out point. Set duration to taste (e.g. 1.0s ending at 96.200s). Both transitions are available in the free tier.
- [ ] 9. Once all placeholder clips are eventually replaced with real footage, review the full timeline from 0.000s → 96.200s on the Edit page for continuity of the 0.500s inter-section gaps and resolve them consistently.

> ⚠ TIMESTAMP ESTIMATED — no VO take. All cuts provisional.
> ⚠ 0.500s gap between previous section end (88.500s) and this section start (89.000s) — director must decide handling.
> ⚠ No assets discovered — footage needed. Director must supply or select.
> ⚠ No BPM/beat grid — omit all beat-aligned steps.
> ⚠ No VO file to place.
> ⚠ Film Grain effect is locked in the free version. If grain is needed on the close, use a Fusion composition node as per toolset fact: 'The director's workaround for grain is a Fusion composition node, which is free but not the straightforward tool.' No step written here — run technique-research for Fusion grain node setup if needed.
> ⚠ Deliver page / export settings not specified in the brief — no Deliver steps written. Director should configure output format before final export.
