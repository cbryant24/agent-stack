# shared-shot-schema.md — the neutral shot contract

The single schema both the film's plate pipeline (visual-generation) and Scene-Forge consume.
**Neither implementation imports the other; both consume this schema.** It is the architectural
seam that lets Scene-Forge become a Test D arm — or a full escalation backend — without ever
being a film dependency.

## Fields

```yaml
shot_id:          # unique, stable, human-readable (bar_05_toast)
set_asset:        # versioned set reference (see mappings)
framing_asset:    # versioned framing reference (see mappings)
characters:       # ordered list — order is edit-pass order
  - character_id:     # versioned character asset (narrator_v1)
    reference_pack:   # versioned reference bundle (narrator_refs_v1)
    pose_guide:       # versioned pose/blocking reference (narrator_toast_v1)
    region:           # named region mask (narrator_mask)
pose_guides:      # optional shot-level blocking references
regions:          # named masks beyond per-character (background_protect, contact bands)
props:            # deterministic prop list (composited conventionally where possible)
lighting_intent:  # named preset/intent (amber_night_v1) — an intent, not a light rig
outputs:          # required artifacts (final_frame, character_masks, validation_report,
                  #   pass_stack, …)
```

## Identity & version rules

- Every `*_asset`, `*_id`, `*_pack`, and `*_guide` value is `name_vN` — immutable once approved.
- A consumer that cannot resolve the exact pinned version **fails loudly**; it never silently
  substitutes a newer version (`supersedes` + `migration_notes` in the asset manifest point
  forward, a human moves the pin).
- Schema evolution: this file carries a `schema_version`; both consumers validate against it and
  reject specs from a newer schema than they support.

## Mappings

| Field | Film / plate pipeline | Scene-Forge |
|---|---|---|
| `set_asset` | approved master plate (image + manifest) | versioned `.blend` set |
| `framing_asset` | approved framing plate + framing metadata (shot size, estimated focal character, horizon/perspective notes) | named camera asset (`CAM_*`) with lens/sensor metadata |
| `characters[].region` | mask image aligned to the framing plate | Cryptomatte/collection-derived mask from proxy objects (`ANCHOR_*`) |
| `pose_guide` | pose reference image / blocking sketch | proxy placement at named empties |
| `lighting_intent` | baked into the approved plate; graded in finishing | lighting preset collection (`COLL_LIGHT_*`) |
| `outputs: pass_stack` | plate-derived depth/segmentation (soft guides) | rendered beauty/depth/normals/masks/grounding passes (deterministic) |

## Required validation outputs

Every executed shot, on either backend, must emit a `validation_report` containing: resolved
asset versions (full pin list), protected-region result (Gate 2A zones: protected-background
score + method, integration-band approval status, diff image path), identity check status per
character, and the producing backend + tool versions.

## Compatibility policy

- The schema is additive-only within a major `schema_version`; renames/removals bump the major.
- Fields a backend cannot honor must be rejected at `shot validate` time, not ignored (a plate
  backend receiving a physically-impossible `framing_asset` for its plates says so; it does not
  guess).

## Example — the same shot, resolved two ways

`bar_05_toast` with `set_asset: sports_bar_v1`, `framing_asset: bar_counter_two_shot_01`:

- **Plate resolution:** `sports_bar_v1` → `plates/sports-bar/master_v1.png`;
  `bar_counter_two_shot_01` → `plates/sports-bar/framings/counter_two_shot_v1.png` + framing
  metadata JSON; regions resolve to mask PNGs aligned to that plate; execution is sequential
  masked Qwen-Edit insertions with Gate 2A validation.
- **Scene-Forge resolution:** `sports_bar_v1` → `sets/sports-bar-v1.blend`;
  `bar_counter_two_shot_01` → camera object `CAM_COUNTER_TWO_SHOT` in that file; regions resolve
  to Cryptomatte IDs of `ANCHOR_NARRATOR`/`ANCHOR_CELESTE` proxies; execution is a headless
  pass-stack render whose masks and depth feed the same downstream edit flow.
