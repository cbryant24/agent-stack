#!/usr/bin/env python
"""Ingest a folder of local markdown docs into verified `user_knowledge` under a given domain.

General-purpose wrapper over `agent_runtime.ingest_docs_sync` — the runtime function takes an
arbitrary `domain`, but the only CLI that exposes it (`voiceover-direction knowledge ingest-docs`)
is hard-wired to `elevenlabs_mechanics`. This script is the domain-arbitrary entry point.

Parser contract (see agent_runtime/knowledge/docs_ingest.py):
  - One `.md` file per source page in FOLDER.
  - Optional frontmatter `source_url:` (or `url:`) -> recorded as the entry's source_ref (`url://...`);
    without it the source_ref is the local file path.
  - Each H2+ heading becomes one verified statement; the heading hierarchy becomes its topic_tags.
    H1 is treated as the page title only.
  - Re-runnable: entries already present (same source_ref + tags + statement) are skipped, so the
    folder is a durable queue you can re-ingest after editing.

Confirmation is interactive (y/n/edit/defer per section) unless --yes is passed.

Run on the machine that hosts Qdrant (the original Mac) so writes land in the authoritative store;
there it reads the default QDRANT_URL (localhost:6333) and the existing .env keys. No QDRANT_URL
needed for this step.

Examples:
  uv run python scripts/ingest_user_knowledge.py ~/agent-data/sources/langgraph-docs --domain langgraph_mechanics
  uv run python scripts/ingest_user_knowledge.py ./some-docs --domain langgraph_mechanics --dry-run
"""

from __future__ import annotations

from pathlib import Path

import click

from agent_runtime import ingest_docs_sync


@click.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--domain", required=True, help="user_knowledge domain tag, e.g. langgraph_mechanics")
@click.option("--dry-run", is_flag=True, help="Parse and report counts only; write nothing.")
@click.option("--yes", "auto_confirm", is_flag=True, help="Skip the per-section confirm prompt.")
def main(folder: Path, domain: str, dry_run: bool, auto_confirm: bool) -> None:
    """Parse local markdown docs in FOLDER into verified user_knowledge under --domain."""
    ingest_docs_sync(
        str(folder.expanduser()),
        domain=domain,
        dry_run=dry_run,
        auto_confirm=auto_confirm,
    )


if __name__ == "__main__":
    main()
