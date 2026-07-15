# Canon — subject registry: cast naming, LoRA pinning, asset references

> **Rewritten 2026-07-15** per the consolidated Coraline audit (§5/§11) and
> `docs/agent-retrospective-corrections.md` §B3. The B3 row proposed retitling this doc
> "deterministic prompt-macro + LoRA-pinning layer"; since the prompt-macro mechanism itself
> (locked-text injection, `@token` expansion, blind `--forbid` substring stripping) has now
> been **deleted from the code**, that title would describe a removed mechanism — B3's intent
> is honored by this body rewrite instead. What canon is NOT: an identity authority. Text
> descriptors were a prompt macro — they raised the probability of broad semantic traits and
> could not pin geometry, materials, camera, or region assignment. Identity and set authority
> are **versioned reference images and approved plates** (audit §17, plate-first).

Canon is `visual-generation`'s per-project **subject registry**. A subject is a named,
recurring entity (a character or a place) with:

- **aliases** — the names the subject is called by (cast detection + LoRA pinning key);
- an optional pinned **character LoRA** — the deprecated single-LoRA ideation path
  (model-level character-class prior, pinned deterministically on every scene that names
  the subject);
- **asset references** aligned with [`docs/shared-shot-schema.md`](../../../docs/shared-shot-schema.md):
  `id` (e.g. `celeste_v1`), `reference_pack`, `wardrobe`, `hair`, `region` — pipeline
  metadata for the plate-first production path, never prompt prose.

> **Where it lives:** `~/agent-data/visual-generation/canon/<project>.json`, one file per
> project, `{"subjects": [ … ]}`. **This is outside the git repo** (`agent-data/`), so it does
> **not** sync between machines. Legacy files carrying `locked`/`forbid` fields still load and
> round-trip untouched — those fields are ignored (`canon show` flags them).

---

## 1. What canon does now (the mechanics)

1. **Cast-weaving (composition input).** `draft --scene` scans the scene text for subject
   aliases and hands the named subjects to the craft step as the scene's cast — by **name
   and asset id only**, never an appearance descriptor. The LLM is instructed to render each
   cast character by name and to place/pose them, not describe them: identity is carried at
   the model/asset level.
2. **Deterministic LoRA pinning.** After the prompt is crafted, every subject the prompt
   names by alias gets its registered character LoRA pinned into the spec's `lora_stack`
   (`── Canon applied (LoRA pins) ──` in the output). Canon owns the pinned strength value —
   if the LLM guessed a different strength for the same file, the canon value overrides it.
   Duplicate checkpoints of the same character are pruned (`lora_guard`).
3. **Absent-cast advisory.** If a scene-named subject is missing from the composed prompt,
   you get a non-blocking `⚠ … ABSENT` advisory — a dropped lead is visible, not silent.
4. **`draft --canon "<subject>"` (force).** Alias matching misses when the LLM names a
   subject by other words. `--canon` (repeatable; also on `redraft`) forces the subject into
   the compose-time cast **and** forces its LoRA pin even when the prompt never names it.

**What was removed** (audit §11 — delete, not deprecate): locked-descriptor injection,
`@token` expansion, and the blind `forbid` substring strip. Appearance consistency is not a
prompt-layer problem; see the audit's plate-first architecture (§17).

---

## 2. Where does each change go? (the cheat-sheet)

| Home | Use it for | How it's applied |
|------|------------|------------------|
| **Canon subject** — `canon set` / `canon edit` | A recurring entity's aliases, asset references, pinned LoRA | Cast naming + deterministic LoRA pin on every scene that names it |
| **`--points`** — per `draft` | This-shot creative choices (clothing, framing, time of day, mood) | Composed into the prompt by the LLM (advisory) |
| **`draft --from <gen_id>`** — refine | Iterating on a render you mostly like | img2img/inpaint on the source frame |
| **`settings`** — on the spec | Engine knobs (`steps`, `cfg`, `denoise`, dims) | Mapped through the template slot map at `generate` |
| **Reference packs / plates** (plate-first path) | Identity and set authority | Versioned image assets + masks — see the consolidated audit §10/§17 |

---

## 3. Subjects — characters *and* recurring places

A subject is `aliases` + optional asset references + optional `lora`. In
`celeste-you-dangerous` there are four: the narrator, Celeste, the bar exterior, the bar
interior.

### Alias disambiguation — still the most important rule

Aliases decide which subject a scene names (cast + LoRA pin). If two subjects share an
alias, the wrong subject fires. **Aliases must be unambiguous and non-overlapping** — e.g.
exterior → `"the storefront"`, `"outside the bar"`; interior → `"inside the bar"`,
`"the bar counter"`. Never name both in one draft.

---

## 4. Command reference

All canon commands are **free** (no LLM, no GPU) and file-backed. `<project>` is the slug;
`<subject>` selects a subject by **any** of its aliases.

### `canon show <project>`

Print every subject (aliases, asset references, lora). Subjects whose stored JSON still
carries legacy fields print `(legacy locked/forbid present — ignored)`.

### `canon set <project> --alias … [asset options] [--lora NAME[:STRENGTH]]`

**Create or fully REPLACE** a subject, keyed by its first alias (case-insensitive).

| Option | Repeatable | Meaning |
|---|---|---|
| `--alias` | ✅ (≥1 required) | A name the subject is called by. `aliases[0]` is the key. |
| `--id` | — | Versioned asset id (e.g. `celeste_v1`) — shared-shot-schema aligned. |
| `--reference-pack` | — | Versioned reference bundle id (e.g. `celeste_refs_v1`). |
| `--wardrobe` | — | Versioned wardrobe asset id (e.g. `black_bar_uniform_v1`). |
| `--hair` | — | Versioned hair asset id (e.g. `bun_front_curl_v1`). |
| `--region` | — | Named region mask (e.g. `celeste_mask`). |
| `--lora` | — | `NAME[:STRENGTH]` character LoRA pinned whenever the subject appears. `NAME` must key into the model registry; strength defaults to `1.0`. |

⚠ **`set` replaces the *whole* subject** — including dropping any legacy `locked`/`forbid`
still in the stored JSON. Use **`canon edit`** to change one field while preserving the rest.

### `canon edit <project> <subject> [--add-alias …] [--rm-alias …] [asset options] [--lora …] [--clear-lora]`

**Surgically edit** an existing subject in place. Prints **Before / After**. Everything you
don't name — untouched aliases, the LoRA, legacy fields — is preserved.

| Option | Meaning |
|---|---|
| `--add-alias` / `--rm-alias` | Add/remove an alias (repeatable; refuses to remove the last one). |
| `--id` / `--reference-pack` / `--wardrobe` / `--hair` / `--region` | Set the field; **pass an empty string to clear it**. |
| `--lora` | Set/replace the pinned character LoRA (`NAME[:STRENGTH]`). |
| `--clear-lora` | Remove the pinned LoRA (mutually exclusive with `--lora`). |

```bash
agent visual-generation canon edit celeste-you-dangerous "the narrator" \
  --id narrator_v1 --reference-pack narrator_refs_v1
```

### `canon rm <project> <alias>`

Remove the whole subject any of whose aliases match `<alias>`.

---

## 5. Recipes

- **A character's look must hold across shots.** Not a canon-text job — build a versioned
  **reference pack** (audit §7: hero + multi-view bundle) and record it: `canon edit …
  --reference-pack <id>`. The plate-first pipeline consumes it.
- **Pin a character LoRA for the ideation path.** Register the LoRA (`model sync`, flagged
  `identity_bearing`), then `canon edit … --lora NAME:STRENGTH`. Deprecated ideation aid: a
  LoRA is a character-class prior, not a locked identity. Never stack two identities in one
  pass — the CLI warns (dual-identity stacking is deprecated, audit §6).
- **Change clothing for one shot.** Per-scene → `--points`.
- **Iterate on a render you like.** `draft --from <gen_id> --points "<the change>"`.

---

## 6. Gotchas (consolidated)

| Symptom | Cause | Fix |
|---|---|---|
| Editing canon wiped the LoRA/asset ids | `canon set` **replaces** the whole subject | Use `canon edit` for one-field changes |
| Wrong subject fired (exterior LoRA/cast in an interior shot) | Two subjects share an alias | Non-overlapping aliases; don't name both in one draft (§3) |
| Canon change didn't affect an existing render | Canon runs at `draft`/`redraft`, not `generate` | Re-`draft` the scene |
| A subject didn't fire (no `Canon applied` line) | The LLM named it by other words, not an exact alias | `draft --canon "<subject>"` to force it; or add a matching (non-overlapping) alias |
| A "solo" shot pulls in the other character's LoRA | Subject-detection matches *negated* mentions ("no Celeste in this shot" counts as naming her) | Don't name absent characters in points/prompts |
| Canon set on machine A, missing on machine B | `canon/*.json` lives in `~/agent-data`, outside git | Set canon on each machine, or copy the JSON |
| `canon show` prints "(legacy locked/forbid present — ignored)" | The stored JSON predates the audit cleanup | Harmless; `canon set` on that subject drops the legacy fields |

---

## 7. Verifying canon is working

- **`canon show <project>`** — the subjects on disk.
- **`draft` output** — `── Canon applied (LoRA pins) ──` lists the pins/overrides/prunes;
  `⚠ … ABSENT` flags a scene-named subject the prompt dropped.
- **`knowledge-verify "<query>" --project <slug>`** — proves the surrounding knowledge is
  reachable, with per-leg scores and gap flags.
