from __future__ import annotations

import pytest

from agent_runtime import get_config

from visual_generation.assets import (
    OpsecError,
    asset_path_for,
    guard_asset_path,
    secured_identity_root,
    write_asset,
)


def test_non_identity_guard_is_noop(tmp_path) -> None:
    # Any path is fine for a non-identity asset.
    guard_asset_path(tmp_path / "anywhere" / "x.png", identity_bearing=False)


def test_identity_under_secured_root_is_allowed() -> None:
    guard_asset_path(secured_identity_root() / "proj" / "g.png", identity_bearing=True)


def test_identity_under_vault_is_refused() -> None:
    vault = get_config().agent_reports_vault
    with pytest.raises(OpsecError, match="synced/curated"):
        guard_asset_path(vault / "leak" / "g.png", identity_bearing=True)


def test_identity_under_obsidian_vault_parent_is_refused() -> None:
    obsidian = get_config().agent_reports_vault.parent  # the personal vault root
    with pytest.raises(OpsecError, match="synced/curated"):
        guard_asset_path(obsidian / "notes" / "g.png", identity_bearing=True)


def test_identity_outside_secured_root_is_refused(tmp_path) -> None:
    # Not under the vault, but also not under the secured root → still refused.
    with pytest.raises(OpsecError, match="secured root"):
        guard_asset_path(tmp_path / "elsewhere" / "g.png", identity_bearing=True)


def test_write_asset_routes_by_identity() -> None:
    non_id = write_asset(b"\x89PNG", project="proj", gen_id="g1", identity_bearing=False)
    ident = write_asset(b"\x89PNG", project="proj", gen_id="g2", identity_bearing=True)

    assert non_id.exists() and ident.exists()
    assert "/assets/" in str(non_id)
    assert "/identity/" in str(ident)
    # The identity asset is under the secured root.
    assert str(ident).startswith(str(secured_identity_root()))


def test_asset_path_for_uses_default_project() -> None:
    p = asset_path_for(None, "g1", identity_bearing=False)
    assert p.parent.name == "default"
