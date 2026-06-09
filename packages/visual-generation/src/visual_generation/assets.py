"""Asset write path + Q8 opsec write-guard.

Generated binaries are disk files referenced by `asset_path`; no bytes go to
Qdrant. Non-identity assets land under the agent's assets dir; identity-bearing
assets land in a secured, isolated dir under `~/agent-data/`. The write-guard
refuses to write an identity-bearing asset anywhere it could leak — under the
obsidian vault, `agent-reports`, or any configured synced location — and refuses
any identity-bearing target that is not under the secured root. This extends the
existing clean-directory-separation rule to the model-output layer.
"""

from __future__ import annotations

from pathlib import Path

from agent_runtime import get_config

from visual_generation.constants import (
    AGENT_SUBDIR,
    ASSETS_SUBDIR,
    DEFAULT_ASSET_EXT,
    IDENTITY_SUBDIR,
)


class OpsecError(RuntimeError):
    """An identity-bearing asset write was refused (leaky or out-of-bounds path)."""


def _agent_root() -> Path:
    return get_config().agent_data_dir / AGENT_SUBDIR


def secured_identity_root() -> Path:
    """The only place identity-bearing assets may be written."""
    return _agent_root() / IDENTITY_SUBDIR


def assets_root(identity_bearing: bool) -> Path:
    return _agent_root() / (IDENTITY_SUBDIR if identity_bearing else ASSETS_SUBDIR)


def _forbidden_roots() -> list[Path]:
    """Locations an identity-bearing asset must never be written under.

    The obsidian vault (the parent of agent-reports) and agent-reports itself are
    the known curated/synced spaces. Additional synced roots can be appended here.
    """
    cfg = get_config()
    vault_reports = cfg.agent_reports_vault.resolve()
    return [vault_reports, vault_reports.parent.resolve()]


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
        return True
    except ValueError:
        return False


def guard_asset_path(path: Path, identity_bearing: bool) -> None:
    """Raise OpsecError if writing `path` would violate identity opsec.

    No-op for non-identity assets. For identity-bearing assets, the target must
    be under the secured identity root AND not under any forbidden/synced root.
    """
    if not identity_bearing:
        return
    resolved = path.resolve()
    for root in _forbidden_roots():
        if _is_within(resolved, root):
            raise OpsecError(
                f"Refusing to write an identity-bearing asset under a synced/curated "
                f"location: {resolved} is within {root}."
            )
    if not _is_within(resolved, secured_identity_root()):
        raise OpsecError(
            f"Identity-bearing assets must be written under the secured root "
            f"{secured_identity_root()}; refusing {resolved}."
        )


def asset_path_for(
    project: str | None, gen_id: str, identity_bearing: bool, ext: str = DEFAULT_ASSET_EXT
) -> Path:
    return assets_root(identity_bearing) / (project or "default") / f"{gen_id}.{ext}"


def write_asset(
    data: bytes,
    *,
    project: str | None,
    gen_id: str,
    identity_bearing: bool,
    ext: str = DEFAULT_ASSET_EXT,
) -> Path:
    """Write asset bytes to the path dictated by `identity_bearing`, guarded."""
    path = asset_path_for(project, gen_id, identity_bearing, ext)
    guard_asset_path(path, identity_bearing)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path
