# music-curation — tool surface audit

Written 2026-10-07 for Phase 6 (`docs/agent-shell/phase-6-onboard-other-agents.md`), before the chat
module. Read from `packages/music-curation/src/music_curation/` at commit `7de4539`: `cli.py`, `agent.py`,
`seed_ingestion.py`, `store.py`, `retrieval.py`.

## Commands

| Command | Backing code | Side effects | Collection |
|---|---|---|---|
| `generate "<request>"` | `agent.curate_sync` → `curate` | LLM spend (Sonnet: question check, then generation). May delegate to tutorial-research (child budget at most $0.50). **Writes pending generations automatically.** Run report and notification. `--dry-run` retrieves only. | `music_curation_memory` (write); `user_knowledge`, `tutorial_research` (read) |
| `report <id> --reaction` | **inline**: `store.get_generation` + `store.update_generation_reaction`; the rating warning is inline too | Qdrant payload write | `music_curation_memory` |
| `review-pending` | **inline**: `store.list_pending` | none | read |
| `recall "<query>"` | **inline** rendering over `retrieval.retrieve_context` | embedding call | three collections, read |
| `taste add` | **inline**: `TasteLesson(confirmed=True)` + `store.upsert_taste` | Qdrant write | `music_curation_memory` |
| `fact add` | **inline**: `UserKnowledgeStore.bulk_load_verified(source_ref="manual:cli")` | Qdrant write | `user_knowledge` |
| `chain show <root>` | **inline**: `store.get_chain` | none | read |
| `seed ingest <path>` | `seed_ingestion.ingest_seed(path, dry_run, auto_confirm)` | Terminal prompts: `click.confirm` for facts and for each inferred template, `click.prompt` y/n/e/d for each inferred taste lesson. Writes facts, taste lessons, templates and generations. Deferred taste lessons become JSON files under `drafts/music-curation/taste-pending/`. | `music_curation_memory`, `user_knowledge` |
| `seed review-taste` | `seed_ingestion.review_taste_queue()` | Terminal prompts y/n/e/x per deferred draft. Writes taste lessons; deletes draft files. | `music_curation_memory` |

## Findings

1. Six of the nine commands are implemented inline in `cli.py`. There was no library function for a chat
   tool to call.
2. `curate` returned its clarifying question by writing `result.__dict__["_pending_question"]`. It asks and
   generates in the same call, so the question is advisory: prompts are produced either way.
3. `ingest_seed` returned `None` and reported only through `click.echo`.
4. `ingest_seed` writes generations without a confirmation (by design: they are facts, not
   interpretations), and writes explicit taste lessons and explicit templates without one as well. Only
   facts (one yes/no per file), inferred taste lessons and inferred templates are confirmed.
5. There is no project concept. A generation is found by id, by pending status, or by search; the store
   has no list-all method.
6. Not exposed by the CLI and left out of the chat: `store.remediate` (the orchestrator's remediation
   handler), `store.migrate_approved_to_liked`, `store.upsert_sound_ref`.
7. The package had no import-linter contract and no optional extras.

## What the chat needs from the library

| Need | Seam |
|---|---|
| Record a reaction | `curation.record_reaction` |
| Add a taste lesson / a fact | `curation.add_taste`, `curation.add_fact` |
| Pending list, chain, recall output | `reads.render_pending`, `reads.render_chain`, `reads.render_recall`, `reads.render_result` |
| The clarifying question | `MusicResult.pending_question` (a real field) |
| Seed ingest without a terminal | `ingest_seed(..., decisions=)`: the answers come from a decision source; the write path is the same one the terminal uses (`docs/decisions-mode-spec.md`) |
| Seed preview | `seed_ingestion.plan_seed` (parse only) |
| The deferred taste queue | `list_taste_queue`, `review_taste_queue(decisions=)` |

## Effect classes for the chat

| Tool | Effect |
|---|---|
| `recall`, `review_pending`, `chain_show`, `seed_preview`, `taste_queue` | READ |
| `generate` | LLM_SPEND (also writes pending generations, stated in its description and preview) |
| `propose_reaction` | NONE |
| `report`, `taste_add`, `fact_add`, `seed_ingest`, `taste_queue_decide` | MEMORY_WRITE |

No external metered spend: Suno has no API, so nothing here is `GPU_SPEND`.
