"""quick — one-off image/video generation, bypassing batch/canon/memory.

`quick_generate` builds a single in-memory `VisualSpec`, resolves it against an
already-registered `WorkflowTemplate` — the one piece of infrastructure that
can't be skipped, since the ComfyUI graph itself only exists as a Qdrant-stored
template (see `store.get_template_by_name`) — submits it to a ComfyUI pod, and
saves the result locally. No canon, no batch file, no drafting LLM, and — the
actual "separate from the pipeline" boundary — no `visual_generation_memory`
write of any kind (no `generation` record, no `GpuLedger`, no
`BudgetTracker`/`TracePersister`).

Images and WAN 2.2 video share this one code path. Video is recipe-locked: WAN's
proven 4-step lightx2v settings (steps/cfg/sampler/scheduler/shift/boundary) are
baked into the registered templates and never spec-overridden here — only
prompt, negative prompt, seed, width/height/length/fps, and (I2V) a seed image
are exposed. See `docs/handoffs/visual-generation-video-phase1-research-signals.md`
for the captured recipe this locks to.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_runtime import get_memory_store

from visual_generation.assets import write_asset
from visual_generation.comfyui_client import ComfyUIClient
from visual_generation.constants import (
    DEFAULT_GPU_RATE_USD_PER_HR,
    DEFAULT_POLL_INTERVAL_SEC,
    DEFAULT_POLL_TIMEOUT_SEC,
    DEFAULT_QUICK_IMAGE_TEMPLATE,
    DEFAULT_WAN_FPS,
    DEFAULT_WAN_HEIGHT,
    DEFAULT_WAN_LENGTH,
    DEFAULT_WAN_WIDTH,
    QUICK_PROJECT,
    WAN_I2V_TEMPLATE_NAME,
    WAN_T2V_TEMPLATE_NAME,
)
from visual_generation.generate import _ext_for, _poll_history
from visual_generation.graph_build import (
    apply_source_filenames,
    build_prompt_graph,
    dropped_identity_loras,
    neutralize_unused_loras,
)
from visual_generation.models import LoraRef, VisualSource, VisualSpec, _new_id
from visual_generation.provenance import (
    canonical_json,
    now_iso,
    provenance_record,
    sha256_hex,
    write_provenance,
)
from visual_generation.store import VisualGenerationStore
from visual_generation.validation import validate_spec


class QuickTemplateNotFound(RuntimeError):
    """No registered WorkflowTemplate matches the requested name."""


class QuickSourceError(RuntimeError):
    """A seed image (`--image`) could not be resolved or applied."""


class QuickLoraUnsafe(RuntimeError):
    """The template bakes in a LoRA that cannot be switched off for this render."""


class QuickInvalidSpec(RuntimeError):
    """A value is outside its allowed range."""


class QuickSeedUnmapped(RuntimeError):
    """The template has no seed slot, so the seed that would be reported can't be applied."""


@dataclass
class QuickResult:
    asset_path: Path
    template_name: str
    seed: int | None
    endpoint: str
    elapsed_sec: float
    estimated_cost_usd: float
    video: bool
    # Requested values the template had no slot for — they did not reach the render.
    unmapped: list[str] = field(default_factory=list)
    # The submitted graph and the provenance record saved beside the output.
    graph_path: Path | None = None
    provenance_path: Path | None = None


def _resolve_template_name(
    *, video: bool, image_path: str | Path | None, template_name: str | None
) -> str:
    if template_name:
        return template_name
    if not video:
        return DEFAULT_QUICK_IMAGE_TEMPLATE
    return WAN_I2V_TEMPLATE_NAME if image_path else WAN_T2V_TEMPLATE_NAME


def _registry_identity(store: VisualGenerationStore, name: str) -> bool:
    asset = store.get_model(name)
    return asset is not None and getattr(asset, "identity_bearing", False) is True


async def quick_generate(
    prompt: str,
    *,
    endpoint: str,
    video: bool = False,
    template_name: str | None = None,
    negative_prompt: str | None = None,
    seed: int | None = None,
    width: int | None = None,
    height: int | None = None,
    length: int | None = None,
    fps: int | None = None,
    image_path: str | Path | None = None,
    model: str | None = None,
    settings: dict[str, Any] | None = None,
    lora_stack: list[LoraRef] | None = None,
    out_path: str | Path | None = None,
    gpu_rate: float = DEFAULT_GPU_RATE_USD_PER_HR,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SEC,
    poll_timeout: float = DEFAULT_POLL_TIMEOUT_SEC,
    store: VisualGenerationStore | None = None,
    client: ComfyUIClient | None = None,
) -> QuickResult:
    """Generate one image or WAN video from a raw prompt straight to ComfyUI.

    Writes nothing to `visual_generation_memory` — the only Qdrant touch-point is
    the read-only template lookup. Raises `QuickTemplateNotFound` /
    `QuickSourceError` / `QuickSeedUnmapped` / `ComfyUIError` on failure; callers
    (the CLI) render these. Other values the template has no slot for are returned
    on `QuickResult.unmapped` for the caller to surface.
    """
    resolved_template = _resolve_template_name(
        video=video, image_path=image_path, template_name=template_name
    )

    store = store or VisualGenerationStore(get_memory_store())
    await store.ensure_collection()
    template = await store.get_template_by_name(resolved_template)
    if template is None:
        raise QuickTemplateNotFound(
            f"No workflow template named {resolved_template!r} is registered. "
            f"Run `workflow register <exported-api.json> --name {resolved_template}` first."
        )

    resolved_settings = dict(settings or {})
    resolved_width, resolved_height = width, height
    if video:
        resolved_settings.setdefault(
            "length", length if length is not None else DEFAULT_WAN_LENGTH
        )
        resolved_settings.setdefault("fps", fps if fps is not None else DEFAULT_WAN_FPS)
        resolved_width = width if width is not None else DEFAULT_WAN_WIDTH
        resolved_height = height if height is not None else DEFAULT_WAN_HEIGHT

    source = VisualSource(image_path=str(image_path)) if image_path else None
    resolved_seed = seed if seed is not None else random.randint(0, 2**32 - 1)

    spec = VisualSpec(
        prompt=prompt,
        negative_prompt=negative_prompt,
        settings=resolved_settings,
        model=model,
        seed=resolved_seed,
        seed_strategy="fixed",
        width=resolved_width,
        height=resolved_height,
        lora_stack=list(lora_stack or []),
        workflow_ref=resolved_template,
        source=source,
        project=QUICK_PROJECT,
    )

    problems = validate_spec(spec, effective=True)
    if problems:
        raise QuickInvalidSpec("; ".join(problems))

    graph, unmapped = build_prompt_graph(spec, template)
    if "seed" in unmapped:
        raise QuickSeedUnmapped(
            f"template {resolved_template!r} has no seed slot, so seed {resolved_seed} "
            "can't be applied — the render would ignore it."
        )

    dropped = dropped_identity_loras(spec, unmapped, lambda n: _registry_identity(store, n))
    if dropped:
        raise QuickLoraUnsafe(
            f"template {resolved_template!r} has no loader for identity LoRA "
            f"{', '.join(repr(n) for n in dropped)}, so the render would ignore that identity."
        )
    neutralized, stuck = neutralize_unused_loras(graph, template.slot_map, len(spec.lora_stack))
    if stuck:
        raise QuickLoraUnsafe(
            f"template {resolved_template!r} bakes in LoRA {', '.join(repr(n) for n in stuck)} and "
            "has no strength slot to switch it off — it would apply although none was requested."
        )

    client = client or ComfyUIClient(endpoint)
    t0 = time.monotonic()
    quick_sources: list[dict[str, Any]] = []

    if source is not None:
        local = Path(image_path)  # type: ignore[arg-type]
        if not local.exists():
            raise QuickSourceError(f"seed image not found: {local}")
        if "init_image" not in template.slot_map:
            raise QuickSourceError(
                f"template {resolved_template!r} has no init_image slot — it can't take a seed image."
            )
        seed_bytes = local.read_bytes()
        pod_name = await client.upload_image(seed_bytes, f"quick_{local.name}")
        quick_sources.append({
            "role": "init_image", "local_path": str(local), "sha256": sha256_hex(seed_bytes),
            "uploaded_as": pod_name,
        })
        source_unmapped = apply_source_filenames(graph, template.slot_map, init_image=pod_name)
        if "init_image" in source_unmapped:
            raise QuickSourceError(
                f"template {resolved_template!r} could not accept the seed image."
            )

    graph_json = canonical_json(graph)          # the bytes that get hashed and saved
    started_at = now_iso()
    prompt_id = await client.submit(graph)
    record = await _poll_history(client, prompt_id, poll_interval, poll_timeout, time.monotonic)
    media = client.videos_from_history(record) if video else client.images_from_history(record)
    if not media:
        raise RuntimeError("the pod produced no output — re-run, or check the graph/endpoint.")

    item = media[0]
    data = await client.view(
        item["filename"], subfolder=item.get("subfolder", ""), type=item.get("type", "output")
    )
    elapsed = time.monotonic() - t0

    if out_path is not None:
        asset_path = Path(out_path)
        asset_path.parent.mkdir(parents=True, exist_ok=True)
        asset_path.write_bytes(data)
    else:
        asset_path = write_asset(
            data,
            project=QUICK_PROJECT,
            gen_id=_new_id(),
            identity_bearing=False,
            ext=_ext_for(item["filename"]),
        )

    files = write_provenance(
        asset_path,
        identity_bearing=False,
        guard=out_path is None,             # a path the caller chose is theirs; the default is guarded
        graph_json=graph_json,
        record=provenance_record(
            generation_id=asset_path.stem, spec=spec, template=template, graph_json=graph_json,
            prompt_id=prompt_id, endpoint=endpoint, resolved_seed=resolved_seed,
            effective_settings=dict(spec.settings), sources=quick_sources,
            outputs=[{"path": str(asset_path), "sha256": sha256_hex(data)}],
            unmapped=unmapped, neutralized_loras=neutralized, started_at=started_at,
            completed_at=now_iso(), seconds=elapsed, identity_bearing=False,
        ),
    )

    return QuickResult(
        asset_path=asset_path,
        template_name=resolved_template,
        seed=resolved_seed,
        endpoint=endpoint,
        elapsed_sec=elapsed,
        estimated_cost_usd=elapsed / 3600 * gpu_rate,
        video=video,
        unmapped=unmapped,
        graph_path=files.graph_path,
        provenance_path=files.provenance_path,
    )


def quick_generate_sync(prompt: str, **kwargs: Any) -> QuickResult:
    return asyncio.run(quick_generate(prompt, **kwargs))
