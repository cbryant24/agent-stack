# Narrator LoRA — asset audit & dataset (celeste-you-dangerous)

**Date:** 2026-06-29 (machine B). **Source:** `~/agent-data/visual-generation/assets/celeste-you-dangerous/` (59 PNGs).
**Method:** 3 parallel vision passes, each judging angle / face-visibility / felt-quality / consistency-vs-favorites.
**Identity anchor (director's favorites):** `0a25cbb2`, `ce0be66f` (felt); `a77c6bb1`, `bfed13d5` (smooth — see style note).

## Decisions (locked)
- **Style target = FELT** (canon-aligned). The smoother/CGI-ish renders are excluded from training, incl. favorites
  `a77c6bb1` & `bfed13d5` (kept as look-reference only, not training data) and the glossy-photoreal storefront cluster.
- **Celeste-bleed = crop**: front frames with Celeste in-frame are cropped to narrator-only before training.
- **Front-on identity is in scope and well-covered** — no face-reference bootstrap needed (unlike Celeste).

## Key findings
- **Coverage:** front/front-¾ (face) well-covered (~13 on-model felt); rear over-covered with near-dupes (~12);
  **profile is the gap** (only `eb9a2fb8`, weak).
- **Style split:** felt vs. smooth-CGI vs. glossy-photoreal vs. clay. Mixing muddies a LoRA → felt-only chosen.
- **Pose monotony (caveat):** front frames are mostly "pointing/celebrating on the couch (with Celeste)"; rears are
  mostly "standing at the storefront." Risk: LoRA overfits to those two compositions. Mitigate by cropping, caption
  variety, and optionally generating a few fresh poses/expressions before training.

## Curated training set (12, felt, deduped, angle-balanced)
Staged in `dataset/`. ⭐ = director favorite. (crop) = remove Celeste before training.

| File | Angle | Face | Role | Note |
|---|---|---|---|---|
| eafde073 | front-¾ | full | face | best felt quality (crop) |
| ce0be66f ⭐ | front-¾ | full | face | favorite, couch (crop) |
| 0a25cbb2 ⭐ | front-¾ | full | face | dynamic cheer pose (crop) |
| 5489cbf7 | front | full | face | close-ish portrait (crop) |
| 51523567 | front | full | face | **narrator solo** (no Celeste) |
| 2d9b11c8 | front-¾ | full | face | calmer seated pose (crop) |
| e9e47555 | rear | none | silhouette | felt stitch detail (best rear) |
| cc8bf89e | rear | none | silhouette | black hoodie standing |
| 4063c282 | rear | none | silhouette | dusk, black hoodie |
| 0bd3354c | rear | none | silhouette | rust hoodie (wardrobe variety) |
| 24df0577 | rear | none | silhouette | sidewalk-seating composition |
| 2331bf13 | rear-¾ | partial | variety | seated jazz club |

**Swaps applied vs. first proposal:** out `966fc7e2`, `c7ae42b8` (redundant couch-pointing); in `2d9b11c8`, `24df0577`.

**Bench (alternates for swaps):** front `504c6cee`, `194df8aa`/`2c2c912e` (dupes), `86cbd66f`, `6959dda3`;
rear `de5b3c7e`, `cefe22ed`, `765ff814`, `8dc68508`, `a03b375e`. Optional profile: `eb9a2fb8` (off-style).

## Full inventory (59)
present=narrator in frame · cand=LoRA candidate (yes/maybe/no)

| file | present | angle | face | felt | consist | cand |
|---|---|---|---|---|---|---|
| 04c0fcbd | y | rear-¾ | partial | minor | low | no — tiny rooftop, off-model |
| 0a25cbb2 ⭐ | y | front-¾ | full | clean | high | yes |
| 0bd3354c | y | rear | none | clean | high | yes |
| 194df8aa | y | front-¾ | full | clean | high | yes (dup 2c2c912e) |
| 2331bf13 | y | rear-¾ | partial | clean | high | yes |
| 24df0577 | y | rear | none | clean | high | yes |
| 255f5d9d | n | — | — | clean | low | no — no narrator |
| 2c2c912e | y | front-¾ | full | clean | high | yes (dup 194df8aa) |
| 2d33b36f | y | rear | none | minor | med | maybe — stitched tee, lanky |
| 2d9b11c8 | y | front-¾ | full | clean | high | yes |
| 30991827 | n | — | — | clean | low | no — no narrator |
| 33407cf3 | y | front-¾ | full | clean | med | maybe — lanky, knit sweater |
| 3784932f | y | front | partial | degraded | low | no — flat 2D red render |
| 4063c282 | y | rear | none | clean | high | yes |
| 42492f93 | y | rear-¾ | partial | minor | med | maybe — small in scene |
| 42b2bcaa | y | front | full | minor | med | maybe — facial hair, older |
| 46302117 | y | rear | none | minor | med | maybe — beaded dreads |
| 504c6cee | y | front-¾ | full | clean | high | yes |
| 51523567 | y | front | full | clean | high | yes — solo |
| 5489cbf7 | y | front | full | clean | high | yes — portrait |
| 5a3f36be | n | — | — | clean | low | no — bartender |
| 612675b2 | y | front | full | minor | med | maybe — cartoon eyes, no AJ1 |
| 63fc0213 | y | front | partial | minor | med | maybe — ragdoll proportions |
| 646e753d | y | rear | none | clean | high | maybe — no face |
| 6959dda3 | y | front-¾ | full | clean | high | yes |
| 73369544 | y | rear | none | clean | med | maybe — red Converse |
| 765ff814 | y | rear | none | clean | high | maybe — no face |
| 7a26a543 | y | rear-¾ | none | minor | low | no — tiny |
| 7a84e76b | y | rear | none | clean | med | maybe — orange hoodie |
| 7d4dde48 | y | rear | none | clean | high | maybe — no face |
| 86cbd66f | y | front-¾ | full | clean | high | yes |
| 8dc68508 | y | rear | none | clean | high | maybe — no face |
| 966fc7e2 | y | front-¾ | full | clean | high | yes |
| a03b375e | y | rear | none | clean | high | maybe — no face |
| a77c6bb1 ⭐ | y | front | full | minor | med | maybe — smooth/CGI render |
| b23b3261 | y | rear | none | minor | low | no — shorts, CGI |
| bd245d93 | y | rear-¾ | none | clean | med | no — tiny in jazz scene |
| bf1f3489 | y | rear | none | clean | med | maybe — orange hoodie |
| bfed13d5 ⭐ | y | front | full | minor | med | maybe — smooth, blue eyes |
| c2557f59 | y | front | full | minor | low | no — clay/Aardman style |
| c396dd48 | y | front | full | clean | med | maybe — stretched shout |
| c7ae42b8 | y | front-¾ | full | clean | high | yes |
| cc8bf89e | y | rear | none | clean | high | yes |
| ccde58c1 | y | rear-¾ | none | clean | med | maybe — small |
| ce0be66f ⭐ | y | front-¾ | full | clean | high | yes |
| cefe22ed | y | rear | none | minor | high | yes |
| d5d91bd2 | y | rear | none | minor | low | no — red Converse, ambiguous |
| de5b3c7e | y | rear | none | minor | high | yes |
| defcf9fa | y | rear-¾ | partial | minor | med | maybe — photoreal |
| e8127d1e | y | rear-¾ | partial | minor | med | maybe — photoreal |
| e9e47555 | y | rear | none | clean | high | yes |
| eafde073 | y | front-¾ | full | clean | high | yes — best |
| eb9a2fb8 | y | profile | partial | clean | med | maybe — only profile |
| ec1c8ba0 | y | rear | none | minor | med | maybe — photoreal |
| ed49b68c | n | front | full | clean | low | no — Celeste |
| edc1cd42 | y | rear | none | clean | med | maybe — small jazz |
| ee7ee937 | y | rear | none | minor | med | maybe — photoreal |
| f4124768 | y | rear | none | minor | med | maybe — photoreal |
| ff05f972 | y | rear | none | minor | med | maybe — photoreal (dup f4124768) |

## Status (dataset ready)
- [x] Cropped the 5 (crop)-tagged fronts to narrator-only (`eafde073`, `ce0be66f`, `0a25cbb2`, `5489cbf7`, `2d9b11c8`).
      Note: `2d9b11c8` & `ce0be66f` retain a tiny Celeste sock sliver in a bottom corner (negligible). `0a25cbb2`
      crop is lower-res/soft (he was the jumping background figure) but on-model — kept for expression variety.
- [x] Captioned all 12 as `.txt` sidecars. **Trigger token = `chrsnrtr`.** Convention: token carries identity;
      captions name angle / framing / pose / wardrobe / setting only.

## Next steps
1. (Optional) generate 2–3 fresh poses/expressions to break pose monotony before training.
2. Phase 3: train on Z-Image-Base (rank 8, ~3k steps) per the plan — needs a separate 24 GB pod (GPU spend).
