# AI Music Generation Project

A comprehensive reference for creating AI-generated music using Suno and supporting tools, documenting preferred styles, prompt engineering principles, and production workflows.

---

## Core Musical Styles & Preferences

### Primary Genres

**Lo-Fi Hip-Hop**
- Dusty vinyl crackle and warm tape saturation
- Mellow, downtempo beats (70-90 BPM)
- Jazz-influenced chord progressions
- Atmospheric, contemplative moods
- Nighttime and introspective themes

**Atmospheric Jazz**
- French café jazz with accordion undertones
- Modal jazz: sparse, contemplative, cool-toned
- Smoky, intimate club atmosphere
- Muted trumpet, brushed drums, upright bass
- Cinematic orchestral ballads with lush strings

**Style Characteristics**
- Preference for atmospheric and contemplative over energetic
- Nighttime and Parisian themes in lyrical content
- Instrumental variations preferred
- Warm, analog textures over digital clarity

### Mood & Atmosphere Keywords

| Contemplative | Atmospheric | Textural |
|---------------|-------------|----------|
| Introspective | Smoky | Vinyl warmth |
| Melancholic | Hazy | Tape saturation |
| Wistful | Nocturnal | Lo-fi crackle |
| Reflective | Intimate | Dusty |
| Bittersweet | Dreamlike | Muted |

---

## Prompt Engineering Principles

### Golden Rules

1. **Use Descriptive Language, Not Artist Names**
   - Instead of referencing specific artists, describe the sonic qualities, instrumentation, mood, and era that characterize the desired sound
   - Example: Replace "Miles Davis style" with "sparse modal trumpet lines, cool-toned, contemplative phrasing with space between notes, late-night intimate atmosphere"

2. **Combine Style/Genre and Description**
   - Always merge the Style of Music field with descriptive elements into one cohesive prompt
   - Build comprehensive prompts that include genre tags, instrumental specifications, mood descriptors, and atmospheric elements

3. **Technical Descriptions Over Celebrity Mimicry**
   - Descriptive style elements yield better, more consistent results
   - Focus on instrumentation, tempo, mood, texture, and production style

### Prompt Structure Template

```
[Genre Tags] [Tempo/Feel] [Instrumentation] [Mood/Atmosphere] [Production Texture] [Additional Elements]
```

**Example Combined Prompt:**
```
Lo-fi hip-hop, downtempo jazz fusion, 75 BPM, mellow Rhodes piano chords, 
dusty vinyl crackle, warm tape saturation, muted trumpet accents, 
brushed snare, deep sub-bass, nocturnal atmosphere, introspective, 
Parisian café ambiance, soft rain ambient texture
```

### Suno-Specific Technical Notes

- **Character Limit:** 1000 characters maximum for prompts
- **Track Length:** Determined by AI's perception of compositional completeness, not maximum duration settings
- **Longer Tracks:** Require structural guidance through:
  - Lyrics markers for section breaks
  - Specific duration requests
  - Extend feature to chain sections together
- **Vocal Generation:** Can be inconsistent with specific vocal timbres—expect multiple generations needed
- **Orchestral Backing:** Generates more reliably than specific vocal characteristics

### Custom Mode Interface

Use Suno's Custom mode with separate fields:
- **Style of Music:** Combined genre, instrumentation, and descriptive elements
- **Lyrics:** Structural markers, thematic content, or [Instrumental] tag

---

## Vocal & Language Preferences

### Multilingual Focus
- French lyrics for café jazz and Parisian themes
- Japanese vocals for atmospheric lo-fi tracks
- English for general compositions

### Vocal Style Descriptors

| Style | Description |
|-------|-------------|
| Breathy | Soft, intimate, close-mic feel |
| Smoky | Warm, slightly husky, jazz-influenced |
| Ethereal | Airy, floating, dreamlike quality |
| Warm | Rich, full-bodied, comforting tone |

---

## Production Workflow

### Tool Stack

| Tool | Purpose | Cost |
|------|---------|------|
| **Suno Pro** | AI music generation | $10/month |
| **Moises** | Stem separation | $4/month |
| **iZotope Vinyl** | Lo-fi texturing plugin | Free |
| **GarageBand** | Mixing & arrangement | Free |
| **ChatGPT Pro / Claude Pro** | Lyric generation support | Existing subscriptions |

**Total Monthly Budget:** $14/month

### Workflow Stages

**Generation Phase**
1. Craft combined prompt with all style elements
2. Generate multiple variations in Suno
3. Iterate through stylistic variations (sad versions, lo-fi variants, hip-hop hybrids, upbeat alternatives)

**Processing Phase**
1. Use Moises for stem separation when remixing existing tracks
2. Preserve desired elements (e.g., original vocals) while transforming instrumentals

**Finishing Phase**
1. Apply iZotope Vinyl for additional lo-fi texturing
2. Arrange and mix in GarageBand
3. Final polish and export

---

## Project Goals

### Eight Core Objectives

1. **Instrumental Lo-Fi Tracks** — Create original instrumental lo-fi hip-hop compositions
2. **Multilingual Vocals** — Add vocals in French and Japanese to instrumentals
3. **Style Transformation** — Convert existing music into lo-fi versions
4. **Vocal Preservation** — Transform instrumentals while keeping original vocals intact
5. **French Café Jazz** — Develop atmospheric Parisian-style jazz pieces
6. **Modal Jazz Compositions** — Create sparse, contemplative jazz in the cool-toned tradition
7. **Cinematic Orchestral Ballads** — Compose lush, emotional orchestral pieces
8. **Monetization Exploration** — Explore commercial potential of AI-generated music

---

## Style Variation Templates

### Base Concept Evolution Approach

Start with a core concept and evolve through variations:

```
Base Version → Sad Version → Lo-Fi Variant → Hip-Hop Hybrid → Upbeat Alternative
```

### Quick Reference Prompts

**French Café Jazz:**
```
Intimate French café jazz, accordion undertones, musette waltz influence, 
warm upright bass, brushed drums, smoky atmosphere, Parisian romance, 
vintage recording warmth, 3/4 time signature, nostalgic, bittersweet
```

**Modal Jazz:**
```
Modal jazz, sparse arrangement, cool-toned trumpet, contemplative phrasing, 
space and silence between phrases, late-night intimate atmosphere, 
walking bass, subtle brush work, intellectual restraint, 
blue notes, suspended harmony
```

**Lo-Fi Hip-Hop:**
```
Lo-fi hip-hop, downtempo, 80 BPM, jazzy piano samples, vinyl crackle, 
tape wobble, muted percussion, deep sub-bass, ambient rain texture, 
nighttime study vibes, warm analog saturation, nostalgic
```

**Cinematic Orchestral Ballad:**
```
Cinematic orchestral ballad, lush string ensemble, emotional swells, 
piano-led melody, French horn accents, building dynamics, 
bittersweet atmosphere, film score quality, intimate to grand arc, 
romantic tension
```

---

## Publishing & Rights Notes

- **Publishing on Suno:** Making tracks publicly visible is optional
- **Commercial Use:** Rights for monetization are separate from publishing status
- **Pro Subscription:** Includes commercial use rights for generated content

---

## Iteration Log Template

Use this template to track prompt iterations:

```markdown
### [Track Name]
**Date:** 
**Style Goal:** 
**Prompt Used:**

**Results:**
- Generation 1: 
- Generation 2: 
- Generation 3: 

**Best Version:** 
**Notes for Next Iteration:**
```

---

*Last Updated: January 2025*
