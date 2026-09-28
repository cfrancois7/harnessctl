"""The adapter contract and helpers shared by the Claude Code and opencode adapters."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from harnessctl.jsonio import JsonFileError, has_comments, read_json, sha256_bytes
from harnessctl.model import CatalogItem, InstalledItem, Kind, Scope, Variant
from harnessctl.planner import PlanError, Step, WriteFile
from harnessctl.sources.formats import read_frontmatter
from harnessctl.validate import links_leaving


@dataclass
class Install:
    steps: list[Step]
    locations: list[str]  # InstalledItem.location values the install creates
    files: dict[str, str]  # absolute path → sha256 of the content written
    settings: dict = field(default_factory=dict)


class Adapter(Protocol):
    id: str
    label: str
    reload_hint: str

    def detect(self) -> bool: ...
    def scope_dir(self, scope: Scope, project: Path | None) -> Path: ...
    def scan(self, scope: Scope, project: Path | None) -> list[InstalledItem]: ...
    def watched_paths(self, project: Path | None) -> list[Path]: ...
    def unavailable_reason(self, variant: Variant) -> str | None: ...
    def plan_install(
        self, item: CatalogItem, scope: Scope, project: Path | None, replace: bool = False
    ) -> Install: ...
    def plan_remove(self, inst: InstalledItem, project: Path | None) -> list[Step]: ...
    def plan_toggle(self, inst: InstalledItem, project: Path | None) -> list[Step]: ...


def safe_join(root: Path, rel: str) -> Path:
    target = Path(os.path.normpath(root / rel))
    if Path(rel).is_absolute() or not target.is_relative_to(root):
        raise PlanError(f"{rel!r} would be written outside {root}")
    return target


def ensure_json_writable(path: Path, manual: str = "") -> None:
    """Refuse to plan an edit of a file harnessctl must not rewrite."""
    if not path.exists():
        return
    hint = f" Make the change by hand: {manual}." if manual else ""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PlanError(f"{path}: {exc}. Fix the file first.") from exc
    if has_comments(text):
        raise PlanError(f"{path} contains comments, which harnessctl will not rewrite.{hint}")
    try:
        read_json(path)
    except JsonFileError as exc:
        raise PlanError(f"{exc}. Fix the file first.") from exc


def require_writable(inst: InstalledItem) -> None:
    if inst.readonly:
        raise PlanError(f"{inst.name}: {inst.readonly}")


def write_payload_files(
    files: list[tuple[Path, str]], scope_dir: Path, replace: bool, within: Path | None = None
) -> tuple[list[Step], dict[str, str]]:
    """Steps copying each source file to its destination. With `within`, a source that resolves
    outside that folder (a symlink to e.g. ~/.ssh/id_rsa) refuses the plan."""
    steps: list[Step] = []
    hashes: dict[str, str] = {}
    for src, dest in files:
        if within is not None and links_leaving(src, within):
            raise PlanError(f"{src} is a symlink leading outside {within}; refusing to install it")
        target = safe_join(scope_dir, dest)
        if (target.exists() or target.is_symlink()) and not replace:
            raise PlanError(f"{target} already exists")
        data = src.read_bytes()
        steps.append(WriteFile(target, data, executable=os.access(src, os.X_OK)))
        hashes[str(target)] = sha256_bytes(data)
    return steps, hashes


def install_skill(src: Path, dest: Path, replace: bool = False) -> Install:
    if (dest.exists() or dest.is_symlink()) and not replace:
        raise PlanError(f"{dest} already exists")
    files = [(f, f.relative_to(src).as_posix()) for f in sorted(src.rglob("*")) if f.is_file()]
    steps, hashes = write_payload_files(files, dest, replace=True, within=src)
    return Install(steps, [str(dest)], hashes)


def scan_skill_dirs(
    folder: Path, harness: str, scope: Scope, readonly: str | None = None
) -> list[InstalledItem]:
    """One item per `<folder>/<name>/SKILL.md`. Unreadable frontmatter never hides a skill."""
    if not folder.is_dir():
        return []
    items: list[InstalledItem] = []
    for d in sorted(folder.iterdir()):
        md = d / "SKILL.md"
        if not md.is_file():
            continue
        front, body = read_frontmatter(md)
        description = str(front.get("description") or "(no description)")
        items.append(
            InstalledItem(
                harness=harness,
                scope=scope,
                kind=Kind.SKILL,
                name=d.name,
                location=str(d),
                detail=body,
                readonly=readonly,
                meta={"description": description, "symlink": d.is_symlink()},
            )
        )
    return items
