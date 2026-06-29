# Canon — locked identity for characters *and* places

Canon is the one channel in `visual-generation` that does **not** depend on the model's
discretion. A retrieved fact can be ignored by the LLM; a **canon lock is enforced in code**
on every `draft`/`redraft`. Use it for anything whose look must be **identical across every
image** — a character, or a **recurring place** (a bar, a room, a street). This guide is the
full reference: the mental model, every command and option, the gotchas we hit building the
`celeste-you-dangerous` canon, and the cheat-sheet for where each kind of change belongs.

> **Where it lives:** `~/agent-data/visual-generation/canon/<project>.json`, one file per
> project, `{"subjects": [ … ]}`. **This is outside the git repo** (`agent-data/`), so it does
> **not** sync between machines — set canon up on each box, or copy the JSON across. (Canon
> survives across sessions on the *same* machine; it's the cross-machine sync that git doesn't
> cover.)

---

## 1. Where does each change go? (the cheat-sheet)

The single deciding question for any change: **does this persist across *every* image of this
thing, or is it just this shot?**

| Home | Use it for | Persists across | How it's applied | Examples |
|------|------------|-----------------|------------------|----------|
| **Canon `locked`** — `canon set` / `canon edit` | The **immutable identity** of a named entity — a character **or a recurring place** | **Every** image that names the entity | Locked text is injected into the prompt deterministically wherever an alias appears | Narrator's dreadlocks & stocky build; the bar's 55″ flat-screen TVs; the terracotta facade |
| **Canon `forbid`** — `canon set` / `canon edit` | Wrong words that keep creeping back in | Same as above (only while that subject is named) | The phrasing is stripped from the whole prompt | strip `CRT`, `lanky`, `chalkboard`, `antenna` |
| **`--points`** — per `draft` | **This-shot** creative choices that **vary** scene to scene | Just that one render | Composed into the prompt by the LLM (advisory, not guaranteed) | Clothing, camera framing, time of day, what's in/out of frame, mood |
| **`draft --from <gen_id>`** — refine | Iterating on a render you **mostly like** | Builds on one good frame (img2img) | The change rides on top of the source frame | "take this frame, pull the camera back, make it night, drop the tables" |
| **`settings`** — on the spec | Engine knobs | The spec | Mapped through the template slot map at `generate` | `steps`, `cfg`, `denoise`, `width`/`height` |

**Rules of thumb:**
- Identity that never changes (a character, or a recurring place's look) → **canon `locked`**.
- A trait the model keeps getting *wrong* in words → reinforce with **canon `forbid`**.
- Anything that legitimately changes per scene (clothing, time, framing, props that come and go)
  → **`--points`**, never canon. If you lock it, it's forced into *every* shot.
- A render whose composition you already like → **`draft --from`**, don't re-roll from scratch.

---

## 2. How enforcement actually works (the mechanics)

Knowing these four mechanics explains every behavior — and every gotcha:

1. **Whole-descriptor injection on any alias.** When **any** of a subject's aliases appears in
   the composed prompt (word-boundary, case-insensitive), the **entire** `locked` descriptor is
   injected. → *Corollary:* don't stuff exterior **and** interior into one lock, or an exterior
   shot gets interior bric-a-brac forced in. Keep each lock **lean** (§4).
2. **`@token` aliases expand in place.** An alias beginning with `@` (e.g. `@narrator`) is a
   token: wherever it appears it's **replaced** by the locked descriptor, rather than triggering
   an append. Plain aliases ("the narrator") trigger an append if the locked text isn't already
   present.
3. **`forbid` is a raw substring strip** — case-insensitive, **no word boundary**. → *Gotcha:*
   `--forbid "tall"` also guts `me`**`tall`**`ic`, `in`**`stall`**. Forbid **multi-word phrases**
   or words that aren't substrings of common words (`lanky`, `skinny`, `chalkboard`), and lean on
   the **positive** locked text instead of forbidding bare words.
4. **Deterministic, at compose-time, on `draft`/`redraft` only.** Canon runs **after** the LLM
   writes the prompt and **before** the spec is saved. `generate` renders the stored prompt
   **verbatim — it does NOT re-enforce canon.** → *Corollary:* if you hand-edit a batch spec and
   delete the locked text, `generate` won't put it back. Re-`draft` to re-apply.

### Cast-weaving (canon as a *composition input*, not just a filter)

Because injection only fires on an alias that's *already in the prompt*, a scene could silently
drop its own lead (the LLM writes a characterless shot → no alias → nothing to enforce). To
close that, `draft --scene` now **feeds the scene's canon cast into composition**: subjects the
scene **names** are handed to the LLM with their locked look so it writes them in *by name* —
and then enforcement fires on the alias as usual.

If a scene-named subject is **still** missing from the composed prompt, you get a non-blocking
advisory:

```
⚠ Canon character(s) named in this scene but ABSENT from the prompt:
  • 'the narrator' is named in scene 'Arrival' but absent from the drafted prompt —
    re-draft with a point naming them, or proceed if this shot intentionally omits them.
```

This makes a dropped lead **visible** instead of silent. An intentional establishing shot with
no figure is fine — the advisory is informational.

---

## 3. Subjects — characters *and* recurring places

A **subject** is one locked entity: `aliases` + `locked` + optional `forbid` + optional `lora`.
Subjects are **not** only characters — any named, recurring thing whose look should be
consistent is a subject. In `celeste-you-dangerous` there are four:

| Subject | Kind | Why it's canon |
|---|---|---|
| **the narrator** (Chris) | character | Hair length, build, skin must never drift |
| **Celeste** | character | The waitress / love interest, recurring across scenes 2–4 |
| **the bar exterior** | place | Recurring storefront — facade, plain entrance, exterior TVs |
| **inside the bar** | place | Recurring interior — bar counter, seating, wall TVs |

### Alias disambiguation — the most important place-canon rule

The alias is **what decides which lock fires.** If two subjects share an alias, the wrong lock
can fire. Real example we hit: giving the **exterior** the bare alias `"the bar"` collides with
the interior — an interior scene narrating *"he sat at the bar"* would inject the **storefront
facade** into an **interior** shot.

**Rule: aliases must be unambiguous and non-overlapping.** For the bar:

- **Exterior** → `"the storefront"`, `"outside the bar"`, `"the bar exterior"`, `"the sports bar"`
- **Interior** → `"inside the bar"`, `"the bar interior"`, `"the bar counter"`

Then steer which fires by how you name it in `--points`/scene text: *"the storefront at night"*
(exterior) vs *"inside the bar, at the counter"* (interior). **Never name both in one draft** —
both locks would inject.

---

## 4. The lean-lock principle

Put in `locked` **only** the invariants that (a) must be identical every appearance **and**
(b) are actually visible in the shots where the subject appears. Everything else is `--points`.

- ✅ In the lock: the narrator's dreadlocks + build; the bar's flat-screen TVs, terracotta
  facade, warm-wood palette.
- ❌ Not in the lock: clothing (varies), the crowd (varies), sidewalk tables (you remove them in
  some shots), time of day (unless it's *always* night) — these are `--points`.

A bloated lock (every interior prop + every exterior detail in one descriptor) makes the prompt
long, forces irrelevant detail into the wrong frame, and dilutes Z-Image at 8 steps. Split a
place into **exterior** and **interior** subjects when each is a distinct, recurring frame.

---

## 5. Command reference

All canon commands are **free** (no LLM, no GPU) and file-backed. `<project>` is the slug
(e.g. `celeste-you-dangerous`); `<subject>` selects a subject by **any** of its aliases.

### `canon show <project>`

Print every locked subject (aliases, locked, forbid, lora). Run it first — `edit` works from
what you see here.

### `canon set <project> --alias … --locked … [--forbid …] [--lora NAME[:STRENGTH]]`

**Create or fully REPLACE** a subject, keyed by its first alias (`aliases[0]`, case-insensitive).

| Option | Repeatable | Meaning |
|---|---|---|
| `--alias` | ✅ (≥1 required) | A name the subject is called by. `aliases[0]` is the key. Prefix `@` for a token that **expands in place**. |
| `--locked` | required | The canonical descriptor injected whenever the subject is named. |
| `--forbid` | ✅ | A phrasing to strip from the prompt (raw substring — see §2.3). |
| `--lora` | — | `NAME[:STRENGTH]` character LoRA pinned whenever the subject appears (model-level continuity). `NAME` must key into the model registry; strength defaults to `1.0`. |

⚠ **`set` replaces the *whole* subject.** Omitting `--forbid`/`--lora` **drops** them. To change
just one field without restating everything, use **`canon edit`**. (`set` now prints a reminder
to this effect when it replaces an existing subject.)

### `canon edit <project> <subject> [--add-alias …] [--rm-alias …] [--add-forbid …] [--rm-forbid …] [--locked …]`

**Surgically edit** an existing subject in place — the safe alternative to `set` when you only
want to tweak one thing. Prints **Before / After** so you can see exactly what changed.

| Option | Repeatable | Meaning |
|---|---|---|
| `--add-alias` | ✅ | Add an alias (deduped case-insensitively). |
| `--rm-alias` | ✅ | Remove an alias (refuses to remove the **last** one). |
| `--add-forbid` | ✅ | Add a forbidden phrase. Prefer multi-word phrases over bare words (§2.3). |
| `--rm-forbid` | ✅ | Remove a forbidden phrase. |
| `--locked` | — | Replace the locked descriptor (the one field that *is* a full overwrite). |
| `--lora` | — | Set/replace the pinned character LoRA as `NAME[:STRENGTH]` (registry name). |
| `--clear-lora` | — | Remove the pinned character LoRA (mutually exclusive with `--lora`). |

At least one edit option is required. `<subject>` may be **any** current alias. Everything you
don't name — the LoRA, untouched aliases/forbids, the descriptor if you don't pass `--locked` —
is preserved.

```bash
# Add a build trait + new forbids without restating the aliases or existing forbids:
agent visual-generation canon edit celeste-you-dangerous "the narrator" \
  --locked "a felt-and-clay stop-motion puppet of a young Black man, short and stocky with a compact broad-shouldered build and a large head-to-body ratio, deep caramel-brown felt skin, long black yarn dreadlocks falling to mid-back" \
  --add-forbid "lanky" --add-forbid "skinny" --add-forbid "slender"
```

### `canon rm <project> <alias>`

Remove the whole subject any of whose aliases match `<alias>`.

---

## 6. Worked example — `celeste-you-dangerous`

The four `canon set` commands that build the project's canon. Phrased in the **felt-and-clay
stop-motion idiom** so each lock reinforces the Coraline aesthetic rather than fighting it.

```bash
# 1 — the narrator (character): build + hair locked; substring-safe forbids
agent visual-generation canon set celeste-you-dangerous \
  --alias "the narrator" --alias "narrator" --alias "@narrator" \
  --alias "Chris" --alias "the man" \
  --locked "a felt-and-clay stop-motion puppet of a young Black man, short and stocky with a compact broad-shouldered build and a large head-to-body ratio, deep caramel-brown felt skin, long black yarn dreadlocks falling to mid-back" \
  --forbid "short hair" --forbid "shoulder-length" --forbid "buzz cut" \
  --forbid "lanky" --forbid "skinny" --forbid "slender"

# 2 — Celeste (character)
agent visual-generation canon set celeste-you-dangerous \
  --alias "Celeste" --alias "the waitress" \
  --locked "a felt-and-clay stop-motion puppet of a young woman, smooth matte felt skin, long black yarn hair falling just past her shoulders, bare felt face with no makeup, glossy black stitched sewing-button eyes"

# 3 — the bar EXTERIOR (place): plain entrance + two exterior TVs (non-overlapping aliases)
agent visual-generation canon set celeste-you-dangerous \
  --alias "the storefront" --alias "outside the bar" --alias "the bar exterior" --alias "the sports bar" \
  --locked "a felt-and-clay stop-motion model of a modern Buenos Aires corner sports bar at street level, burnt-orange terracotta painted facade above a full-width black steel-framed folding glass storefront, plain uncluttered entrance with clean glass doors and bare facade, warm amber wood-panelled interior glowing through the glass, two 55-inch flat-screen televisions mounted on the exterior facade one on each side of the entrance, both facing the sidewalk and showing the Lakers basketball game, grey hexagonal Buenos Aires pavement tiles in front" \
  --forbid "chalkboard" --forbid "chalk art" --forbid "league decals" \
  --forbid "sports stickers" --forbid "posters" \
  --forbid "CRT" --forbid "tube television" --forbid "antenna"

# 4 — inside the bar INTERIOR (place): seating locked to the reference
agent visual-generation canon set celeste-you-dangerous \
  --alias "inside the bar" --alias "the bar interior" --alias "the bar counter" \
  --locked "a felt-and-clay stop-motion model of the cozy warm interior of a modern Buenos Aires sports bar, burnt-orange terracotta painted walls and ceiling, honey-toned wood plank floor with wood-panelled wainscoting, a long polished wood bar counter backed by warm backlit shelves of liquor bottles, wooden ladder-back bar stools at the counter, round high-top wood tables with tall teal blue-green upholstered cushioned bar chairs, clusters of warm Edison-bulb cage pendant lights, several 55-inch wall-mounted flat-screen televisions showing the Lakers basketball game, framed sports memorabilia on the walls, warm amber lighting" \
  --forbid "CRT" --forbid "tube television" --forbid "antenna"
```

Note the **shared invariant** across the two place-subjects — *55″ flat-screens showing the
Lakers, terracotta + warm-wood palette* — so inside and outside read as the same building. The
**`CRT`/`tube television`/`antenna` forbids** appear wherever TVs do, to hold the flat-screen
look. Seating, crowd, and clothing are deliberately **not** locked (they're per-scene `--points`).

---

## 7. Recipes (common tasks → the right home)

- **Give a character a permanent trait (height/build).** It's identity → `canon edit … --locked`.
  Use **proportion** language ("short and stocky, large head-to-body ratio"), not an absolute
  height — a single frame has no scale reference, so "5′7″" can't render; proportions do.
- **Change clothing for one shot.** Per-scene → `--points`. If the garment can cover the hair,
  **state the occlusion**: *"hood down, long dreadlocks falling freely over the collar to
  mid-back."* Canon locks the *length*; it can't fix a *visual* occlusion — that's prompt craft,
  and a front/¾ view shows hair far better than a dead-rear view with the hood up.
- **A recurring place keeps drifting (e.g. TVs).** Stop re-describing it per draft — make it a
  **place-subject** (§3) and lock the invariant once.
- **Lock a character at the model level (not just text).** Train a Z-Image character LoRA, register
  it (`model sync`, flagged `identity_bearing`), then `canon set … --lora NAME:STRENGTH`. The LoRA
  is pinned on *every* scene the subject appears in; pinning dedupes if the LLM already picked it.
  A pinned LoRA on a template with no loader slot is surfaced as a "won't apply" advisory, never
  silently dropped.
- **Iterate on a render you like.** `draft --from <gen_id> --points "<the change>"` — img2img off
  the good frame, preserving composition.

---

## 8. Gotchas (consolidated)

| Symptom | Cause | Fix |
|---|---|---|
| Editing canon wiped the forbids/LoRA | `canon set` **replaces** the whole subject | Use `canon edit` for one-field changes |
| `--forbid "tall"` mangled unrelated words | `forbid` is a raw substring strip | Forbid multi-word phrases / non-substring words; lean on positive locked text |
| Wrong lock fired (exterior look in an interior shot) | Two subjects share an alias | Non-overlapping aliases; don't name both in one draft (§3) |
| Canon change didn't affect an existing render | Canon runs at `draft`/`redraft`, not `generate` | Re-`draft` (or `batch rebuild`) the scene |
| Scene's lead missing, no `Canon enforced` block | LLM composed a characterless prompt → no alias to enforce | Cast-weaving now writes them in; if still absent you get the `⚠ ABSENT` advisory — add a `--points` naming them |
| Canon set on machine A, missing on machine B | `canon/*.json` lives in `~/agent-data`, outside git | Set canon on each machine, or copy the JSON |
| Long lock, diluted output | Exterior + interior crammed into one subject | Split into place-subjects; keep each lean (§4) |

---

## 9. Verifying canon is working

- **`canon show <project>`** — the subjects on disk.
- **`draft` output** — `── Canon enforced (deterministic) ──` lists exactly what was injected /
  expanded / stripped; `⚠ … ABSENT` flags a scene-named subject the prompt dropped.
- **`knowledge-verify "<query>" --project <slug>`** — proves the surrounding knowledge (incl.
  ingested canon docs) is reachable, with per-leg scores and gap flags.
