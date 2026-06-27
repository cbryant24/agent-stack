# Naming & folder conventions

**Canonical, single source of truth** for where files go and what they're named across the
agent-stack runtime trees. The README FAQ entries ("How should I name files…", "Where should
project files live?") are friendly entry points; **this doc is authoritative**. Grounded in what
the code actually writes — paths here match `agent-runtime` config and each agent's CLI defaults.

---

## Cheat sheet — "where does this file go?"

| You have… | It goes… | Named… |
|---|---|---|
| A throwaway intermediate (one session) | **session scratchpad dir** (auto-isolated) | anything; it's ephemeral |
| A director-owned artifact you'll keep | `~/agent-projects/<slug>/` | **type-only** (`script.md`, `directed.md`, …) |
| A reference image for a project | `~/agent-projects/<slug>/refs/` | descriptive kebab (`jazz-club.jpg`) |
| A ComfyUI workflow for a project | `~/agent-projects/<slug>/workflows/` | kebab purpose (`img2img.json`) |
| Agent-managed data / state | `~/agent-data/<code-owned subdir>/` | **let the code name it** |
| A finished run report | `~/obsidian/agent-reports/<agent>/` | auto-written by the agent |
| Anything, into repo `tmp/` | ❌ **don't** | — (`tmp/` is not an artifact store) |

---

## The three trees

- **`~/agent-data/`** — agent-managed data & state. **Code owns this layout** (`agent_data_dir`,
  default `~/agent-data`, in `packages/agent-runtime/src/agent_runtime/config.py`). Don't
  reorganize it by hand or invent ad-hoc subdirs.
- **`~/agent-projects/<slug>/`** — director-owned working artifacts for one piece of work. The
  folder namespaces the project; you control the filenames (rules below).
- **`~/obsidian/agent-reports/`** — run reports, auto-written by agents (`tutorial-research/`,
  `music-curation/`, `system/` auto-created).
- **repo `tmp/`** — gitignored, and **not an artifact store**. See "Ephemeral / scratch policy".

---

## Global naming rules (apply everywhere)

1. **lowercase `kebab-case`** for every file and directory. **No spaces**, no `CamelCase`, no
   `snake_case`. (e.g. `visual generation course docs/` → `visual-generation-course/`;
   `lefttv_basketball_mask.png` → `left-tv-basketball-mask.png`; `14B` → `14b`.)
2. **One stable `<slug>` per project** — lowercase-hyphenated, matching the work's identity,
   threaded across agents via `--project-id` / `--project` so assets auto-discover downstream.
   The slug names the **folder**, never the files inside it.
3. **No `.bak` / `.orig` / dated-copy files** in project folders. Use git or the scratchpad.
4. **Qualifiers append in a fixed order, hyphen-separated** (`visual-batch-thumbnails.md`),
   and qualify the **role**, never the project.

---

## `~/agent-projects/<slug>/` — director artifacts

**Folder = project slug; filename = artifact type only.** The folder already namespaces the
project, so do **not** repeat the slug in filenames (`celeste-you-dangerous-visual-batch.md` is
wrong → `visual-batch.md`).

| Artifact | Canonical file |
|---|---|
| Creative brief | `brief.md` |
| Source story / dictation | `story.md` |
| Technique report | `techniques.md` |
| Script | `script.md` |
| Directed script | `directed.md` |
| Visual batch | `visual-batch.md` |
| Edit brief | `edit-brief.md` |
| Reference images | `refs/<descriptive-kebab>.{png,jpg}` (not raw `IMG_####`) |
| ComfyUI workflows | `workflows/<purpose>.json` (e.g. `t2v-wan2-2-14b.json`, `img2img.json`) |

If a project genuinely needs two of one type, qualify the role: `visual-batch-thumbnails.md`.

### Type-only (canonical) vs stem-derived (default)

Type-only names are **canonical** — produce them by passing `-o <type>.md`. Without `-o`, several
CLIs emit **stem-derived double-extension** defaults derived from the input filename:

- `voiceover-direction direct script.md` → `script.directed.md` (default)
- `edit-brief draft script.md` → `script.edit-brief.md` (default)
- `visual-generation draft …` → `<project>.batch.md` under agent-data (default)

These defaults are valid, but **prefer `-o directed.md` / `-o edit-brief.md` / `-o visual-batch.md`**
for clean, stable project folders that match the table above.

---

## `~/agent-data/` — code-owned subdir map

This tree is **owned by the code**. Document it; don't redesign it. If you need a new location,
add it to `config.py` or the owning agent — don't hand-create ad-hoc dirs.

| Subdir | Owner / written by | Notes |
|---|---|---|
| `sources/<source-set>/` | ingestion | source docs grouped by set; auto-created |
| `runs/<YYYY-MM-DD>/<agent>/<run_id>/trace.jsonl` | tracing | run traces; auto-created |
| `qdrant/` | Qdrant | vector storage; auto-created |
| `drafts/user_knowledge/`, `drafts/<agent>/` | knowledge / agents | pending drafts; auto-created |
| `technique-reports/` | technique-research | `TechniqueReport` outputs |
| `visual-generation/{batches,assets,masks}/` | visual-generation | batches, generated assets, masks |
| `voiceover/`, `concept-script/` | those agents | per-agent working data |
| root state files | runtime | `agent-stack.db*`, `youtube-cookies.txt`, `*.json` ledgers |

---

## Ephemeral / scratch policy (the `tmp/` fix)

- **Throwaway, single-session work → the session scratchpad dir** (per-session, auto-isolated).
  Claude Code should write intermediate files there, **never** to repo `tmp/`.
- Repo **`tmp/` is gitignored and not an artifact store.** Anything worth keeping belongs in
  `~/agent-projects/<slug>/`.
- Cross-session keepers always land in the project folder or the code-owned `agent-data` path.

---

## Appendix — known drift to clean up (reviewable, NOT yet executed)

Offenders found on disk and the cleanup applied. **DONE** rows were executed (2026-06-27).
**LEAVE** rows are code-owned / identifier-based and were intentionally not touched.

### `~/agent-projects/celeste-you-dangerous/` — DONE (verified not code-referenced)

| Was | Now | Action |
|---|---|---|
| `content.md` | `story.md` | ✅ renamed to canonical type-only name |
| `visual-batch.md.bak` | — | ✅ deleted (no `.bak` in project folders) |
| `refs/IMG_5518.jpg` | `refs/sports-bar-interior-crowd.jpg` | ✅ renamed (content-described kebab) |
| `refs/IMG_5519.jpg` | `refs/sports-bar-storefront-day.jpg` | ✅ renamed |
| `refs/IMG_5520.jpg` | `refs/sports-bar-exterior-night.jpg` | ✅ renamed |
| `visual-workflow*.json` (×4, project root) | `workflows/visual-workflow*.json` (×4, **same names**) | ✅ relocated into `workflows/`, names **kept** |

> ⚠️ **Why the workflow JSONs were relocated but NOT renamed:** verification showed their basenames
> mirror *registered template names* — `visual-batch.md` specs carry `workflow_ref: "visual-workflow"`,
> `"visual-workflow-img2img"`, `"visual-workflow-inpaint"`. Renaming the files would sever that link.
> They are therefore an **accepted exception to pure-kebab** (the `14B` casing stays): the filename
> is the template identity. `indoor-photo.jpg` / `classic-sports-bar.png` were left as-is — already
> well-named **and** referenced by absolute path in the batch specs.

### `~/agent-data/` — DONE (human/reference clutter, not code-written)

| Was | Now | Action |
|---|---|---|
| `visual generation course docs/` (202 files, spaces) | `sources/visual-generation-course/` | ✅ moved into `sources/`; all 202 inner filenames kebab-normalized (spaces/parens/commas/`CamelCase`/trailing `..md`) |
| `z-image-reference/` | `sources/z-image-turbo/` | ✅ **decision resolved** — folded into `sources/` |
| `docs-staging/comfyui_md`, `runpod_md` | `docs-staging/comfyui-md`, `runpod-md` | ✅ dir names kebab'd (inner `__` page files left — see exception below) |
| `visual-generation/masks/lefttv_basketball_{mask,glass}.png` | `left-tv-basketball-{mask,glass}.png` | ✅ renamed to kebab |

### LEAVE — code-owned, identifier-based, or accepted internal conventions (verified)

| Path / pattern | Why left alone |
|---|---|
| `agent-stack.db`, `-wal`, `-shm`, `youtube-cookies.txt` | root state files written by code (`agent_runtime/youtube.py`) |
| `visual-generation/batches/batch.batch.md` | redundant double-suffix is a known code artifact (see `visual-generation/README.md`) |
| `runs/`, `qdrant/`, `drafts/user_knowledge/`, `technique-reports/`, `*.json` ledgers (`models.json`, `gpu_ledger.json`, `voices.json`) | code-owned; document, don't touch |
| `sources/youtube-tutorials/<VIDEO_ID>/` | YouTube IDs are **case-sensitive identifiers** (e.g. `HAtynUpVM1A`); must keep exact case |
| `sources/langgraph-docs/SqliteSaver.md`, `ChatAnthropic.md`, … | scraped doc pages mirroring API **class names** — meaningful as-is |
| `docs-staging/*/​*__*.md` (double-underscore) | docs_ingest staging: `__` encodes the source URL hierarchy (`pods__troubleshooting__…`); internally consistent |
| ComfyUI outputs (`Wan2.2_i2v_00003_.mp4`, `masks/mask.png`) | tool-generated filenames |
