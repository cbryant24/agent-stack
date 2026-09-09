"""`clip explain <question>` — Phase 2 grounded semantic-search tutor."""

from __future__ import annotations

import asyncio

import click

from video_clipping.constants import (
    EXPLAIN_INCLUDE_TYPES_DEFAULT,
    EXPLAIN_MAX_USD_DEFAULT,
    EXPLAIN_TOP_K_DEFAULT,
)


@click.command("explain")
@click.argument("question", type=str)
@click.option(
    "--max-usd",
    type=float,
    default=EXPLAIN_MAX_USD_DEFAULT,
    show_default=True,
    help="Per-invocation cost cap. Preflight refusal if the projected cost exceeds this.",
)
@click.option(
    "--top-k",
    type=int,
    default=EXPLAIN_TOP_K_DEFAULT,
    show_default=True,
    help="Total hits pulled from Qdrant (across --include-types, merged and reranked).",
)
@click.option(
    "--include-types",
    type=str,
    default=EXPLAIN_INCLUDE_TYPES_DEFAULT,
    show_default=True,
    help="Comma-separated memory_types to query. Valid: segment, run, lesson.",
)
def explain_command(
    question: str, max_usd: float, top_k: int, include_types: str
) -> None:
    """Grounded semantic-search tutor over video_clipping_memory."""
    from video_clipping.explain import (
        PreflightCostRefusal,
        QdrantUnavailable,
        explain_sync,
        render_explain,
    )

    try:
        result = asyncio.run(
            explain_sync(
                question,
                max_usd=max_usd,
                top_k=top_k,
                include_types=include_types,
            )
        )
    except PreflightCostRefusal as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(2) from exc
    except QdrantUnavailable as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(2) from exc

    click.echo(render_explain(result))
