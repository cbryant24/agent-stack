# Suno.ai Prompt Engineering Summary

## Key Learnings

### Golden Rule: Descriptive Language Over Artist Names
**Never reference specific artists, musicians, or bands by name in Suno prompts.** Instead, translate their artistic qualities into descriptive language.

| ❌ Don't Use | ✅ Use Instead |
|-------------|----------------|
| "Miles Davis style" | "sparse modal trumpet lines, cool-toned, contemplative phrasing with deliberate space between notes, late-night intimate atmosphere, intellectual restraint" |
| "Nujabes style lo-fi" | "jazzy piano samples over downtempo hip-hop beats, vinyl warmth, nostalgic melancholy, introspective atmosphere, warm analog textures" |

### Always Combine Style + Description
Never separate genre tags from descriptive elements. Suno's "Style of Music" field should contain one cohesive, flowing prompt that merges:
- Genre tags
- Tempo/BPM
- Instrumentation
- Production texture
- Mood/atmosphere
- Additional sonic details

### Technical Constraints
- **Character limit:** 1000 characters maximum
- **Track length:** Determined by AI's perception of compositional completeness
- **Longer tracks:** Use lyrics markers for section breaks or the Extend feature
- **Vocal generation:** Can be inconsistent—expect multiple generations needed

---

## Ready-to-Use Prompt Templates

### Lo-Fi Hip-Hop
```
Lo-fi hip-hop, downtempo, 80 BPM, jazzy piano samples, vinyl crackle, 
tape wobble, muted percussion, deep sub-bass, ambient rain texture, 
nighttime study vibes, warm analog saturation, nostalgic, 
dusty vinyl warmth, contemplative, introspective
```

### French Café Jazz
```
Intimate French café jazz, accordion undertones, musette waltz influence, 
warm upright bass, brushed drums, smoky atmosphere, Parisian romance, 
vintage recording warmth, 3/4 time signature, nostalgic, bittersweet,
muted trumpet, intimate club atmosphere
```

### Modal Jazz
```
Modal jazz, sparse arrangement, cool-toned trumpet, contemplative phrasing, 
space and silence between phrases, late-night intimate atmosphere, 
walking bass, subtle brush work, intellectual restraint, 
blue notes, suspended harmony, muted dynamics
```

### Atmospheric Jazz
```
Atmospheric jazz, smoky intimate club feel, muted trumpet phrases,
brushed snare patterns, upright bass warmth, French café undertones,
nocturnal mood, cinematic quality, lush strings optional,
contemplative, wistful, melancholic beauty
```

### Cinematic Orchestral Ballad
```
Cinematic orchestral ballad, lush string ensemble, emotional swells, 
piano-led melody, French horn accents, building dynamics, 
bittersweet atmosphere, film score quality, intimate to grand arc, 
romantic tension, sweeping crescendos
```

---

## Mood & Atmosphere Vocabulary

### Contemplative Keywords
- Introspective
- Melancholic
- Wistful
- Reflective
- Bittersweet

### Atmospheric Keywords
- Smoky
- Hazy
- Nocturnal
- Intimate
- Dreamlike

### Textural Keywords
- Vinyl warmth
- Tape saturation
- Lo-fi crackle
- Dusty
- Muted

---

## Vocal Style Descriptors

| Style | Description | Best For |
|-------|-------------|----------|
| Breathy | Soft, intimate, close-mic feel | Intimate ballads |
| Smoky | Warm, slightly husky, jazz-influenced | Café jazz, late-night |
| Ethereal | Airy, floating, dreamlike quality | Atmospheric pieces |
| Warm | Rich, full-bodied, comforting tone | Emotional compositions |

---

## Prompt Structure Formula

```
[Genre Tags] + [Tempo/Feel] + [Instrumentation] + [Mood/Atmosphere] + [Production Texture] + [Additional Elements]
```

**Example breakdown:**
```
Lo-fi hip-hop,          ← Genre tag
downtempo, 80 BPM,      ← Tempo/Feel
jazzy piano samples,    ← Instrumentation
vinyl crackle,          ← Production texture
tape wobble,            ← Production texture
muted percussion,       ← Instrumentation
deep sub-bass,          ← Instrumentation
ambient rain texture,   ← Additional element
nighttime study vibes,  ← Mood/Atmosphere
warm analog saturation, ← Production texture
nostalgic,              ← Mood
contemplative           ← Mood
```

---

## Style Variation Workflow

Evolve a base concept through variations to explore creative possibilities:

```
Base Version → Sad Version → Lo-Fi Variant → Hip-Hop Hybrid → Upbeat Alternative
```

This approach helps iterate on a core idea while discovering unexpected directions.

---

## Multilingual Considerations

- **French lyrics** — Best for café jazz, Parisian themes
- **Japanese vocals** — Best for atmospheric lo-fi tracks
- **English** — General purpose compositions

---

## Production Tool Stack

| Tool | Purpose | Cost |
|------|---------|------|
| Suno Pro | AI music generation | $10/month |
| Moises | Stem separation | $4/month |
| iZotope Vinyl | Lo-fi texturing plugin | Free |
| GarageBand | Mixing & arrangement | Free |

**Total monthly budget:** $14/month

---

## Quick Checklist Before Generating

- [ ] No artist names in the prompt
- [ ] Style and description combined (not separated)
- [ ] Under 1000 characters
- [ ] Tempo/BPM specified if relevant
- [ ] Key instrumentation included
- [ ] Mood/atmosphere keywords present
- [ ] Production texture described (vinyl, tape, etc.)

---

*Generated from AI Prompt Generation Hub project conversation*
