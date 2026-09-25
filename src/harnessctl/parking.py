"""Disabling items with no native off switch, by parking them under ~/.local/state/harnessctl/disabled/."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from harnessctl.edits import add_plugin_spec_edit, merge_hooks_edit, restore_hook_edit
from harnessctl.jsonio import dumps
from harnessctl.model import InstalledItem, Kind, Scope
from harnessctl.planner import DeletePath, EditJson, MovePath, Step, WriteFile


def park_dir(parking: Path, harness: str, location: str, name: str) -> Path:
    digest = hashlib.sha1(location.encode()).hexdigest()[:10]
    safe = name.replace("/", "_").lstrip("@.")
    return parking / harness / f"{safe}-{digest}"


def park_steps(
    inst: InstalledItem, pdir: Path, scope_dir: Path, restore: dict, first: list[Step]
) -> list[Step]:
    """`first` takes the item out of service; then its metadata is recorded in the parking folder."""
    meta = {
        "name": inst.name,
        "kind": inst.kind.value,
        "scope": inst.scope.value,
        "scope_dir": str(scope_dir),
        "location": inst.location,
        "detail": inst.detail,
        "restore": restore,
        "meta": {k: v for k, v in inst.meta.items() if isinstance(v, (str, int, float, bool, type(None)))},
    }
    return [*first, WriteFile(pdir / "meta.json", dumps(meta).encode())]


def scan_parked(parking: Path, harness: str, scope: Scope, scope_dir: Path) -> list[InstalledItem]:
    items: list[InstalledItem] = []
    for meta_file in sorted((parking / harness).glob("*/meta.json")):
        try:
            meta = json.loads(meta_file.read_text())
        except OSError, json.JSONDecodeError:
            continue
        if meta.get("scope_dir") != str(scope_dir) or meta.get("scope") != scope.value:
            continue
        items.append(
            InstalledItem(
                harness=harness,
                scope=scope,
                kind=Kind(meta["kind"]),
                name=meta["name"],
                location=meta["location"],
                enabled=False,
                detail=meta.get("detail", ""),
                meta={**meta.get("meta", {}), "park_dir": str(meta_file.parent), "restore": meta["restore"]},
            )
        )
    return items


def unpark_steps(inst: InstalledItem) -> list[Step]:
    pdir = Path(inst.meta["park_dir"])
    restore = inst.meta["restore"]
    match restore["type"]:
        case "move":
            steps: list[Step] = [MovePath(pdir / "payload", Path(restore["to"]))]
        case "hook" if "group_index" in restore:
            steps = [
                EditJson(
                    Path(restore["settings"]),
                    restore_hook_edit(
                        restore["event"],
                        restore["group"],
                        restore["hook"],
                        restore["group_index"],
                        restore["hook_index"],
                        restore["alone"],
                    ),
                    f"hooks +1 ({restore['event']}, restored)",
                )
            ]
        case "hook":  # parked before hook positions were recorded
            group = {"hooks": [restore["hook"]]}
            if restore.get("matcher"):
                group = {"matcher": restore["matcher"], **group}
            steps = [
                EditJson(
                    Path(restore["settings"]),
                    merge_hooks_edit({restore["event"]: [group]}),
                    f"hooks +1 ({restore['event']}, restored)",
                )
            ]
        case "npm":
            steps = [
                EditJson(
                    Path(restore["config"]),
                    add_plugin_spec_edit(restore["spec"]),
                    f"plugin +{restore['spec']} (restored)",
                )
            ]
        case other:
            raise ValueError(f"unknown parking type {other!r}")
    return [*steps, DeletePath(pdir)]
