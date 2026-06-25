"""visual-generation agent — ComfyUI-backed diffusion generation.

Exposes the memory store, the model/LoRA registry, the three-collection
retrieval, the ComfyUI backend, and the draft → generate → report turn.
"""

from __future__ import annotations

from visual_generation.assets import OpsecError, guard_asset_path, write_asset
from visual_generation.batch_file import read_batch, write_batch
from visual_generation.draft import draft, draft_sync, redraft, redraft_sync
from visual_generation.explain import (
    ExplainResult,
    explain,
    explain_sync,
    render_explain,
)
from visual_generation.generate import (
    generate,
    generate_sync,
    plan_generation,
    plan_generation_sync,
    spend_generation,
    spend_generation_sync,
)
from visual_generation.gpu_tracker import GpuLedger, SessionMeter, estimate_per_run_cost
from visual_generation.graph_build import build_prompt_graph
from visual_generation.identity import derive_identity_bearing
from visual_generation.inspect import (
    get_chain,
    get_chain_sync,
    list_pending,
    list_pending_sync,
    recall,
    recall_sync,
    render_chain,
    render_pending,
    render_recall,
)
from visual_generation.model_registry import ModelRegistry
from visual_generation.models import (
    DraftResult,
    GenerationBatch,
    GenerationResult,
    ModelAsset,
    TechniqueLesson,
    VisualGeneration,
    VisualResult,
    VisualSpec,
    WorkflowTemplate,
)
from visual_generation.report import report, report_sync
from visual_generation.research import (
    ResearchOutcome,
    register_delegate_handlers,
    render_research,
    research,
    research_sync,
)
from visual_generation.retrieval import (
    RetrievedContext,
    build_context_prompt,
    retrieve_context,
)
from visual_generation.store import VisualGenerationStore

__all__ = [
    "DraftResult",
    "ExplainResult",
    "GenerationBatch",
    "GenerationResult",
    "GpuLedger",
    "ModelAsset",
    "ModelRegistry",
    "OpsecError",
    "ResearchOutcome",
    "RetrievedContext",
    "SessionMeter",
    "TechniqueLesson",
    "VisualGeneration",
    "VisualGenerationStore",
    "VisualResult",
    "VisualSpec",
    "WorkflowTemplate",
    "build_context_prompt",
    "build_prompt_graph",
    "derive_identity_bearing",
    "draft",
    "draft_sync",
    "estimate_per_run_cost",
    "explain",
    "explain_sync",
    "generate",
    "generate_sync",
    "get_chain",
    "get_chain_sync",
    "guard_asset_path",
    "list_pending",
    "list_pending_sync",
    "plan_generation",
    "plan_generation_sync",
    "read_batch",
    "recall",
    "recall_sync",
    "redraft",
    "redraft_sync",
    "register_delegate_handlers",
    "render_chain",
    "render_explain",
    "render_pending",
    "render_recall",
    "render_research",
    "report",
    "report_sync",
    "research",
    "research_sync",
    "retrieve_context",
    "spend_generation",
    "spend_generation_sync",
    "write_asset",
    "write_batch",
]
