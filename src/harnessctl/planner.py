"""Plans: the exact steps a change makes, applied all-or-nothing."""

from __future__ import annotations

import copy
import difflib
import hashlib
import os
import shlex
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from harnessctl.jsonio import dumps, has_comments, loads_jsonc, sha256_file
from harnessctl.model import Scope


class PlanError(Exception):
    """A change that cannot be planned or a step that failed; the message says why."""


class PlanConflict(Exception):
    """A file the plan touches changed between planning and applying."""


@dataclass
class WriteFile:
    path: Path
    content: bytes
    executable: bool = False


@dataclass
class DeletePath:
    path: Path  # file, folder or symlink (a symlink is unlinked, never followed)


@dataclass
class EditJson:
    path: Path
    edit: Callable[[Any], Any]  # receives the parsed file (None if missing) and returns the new data
    description: str


@dataclass
class MovePath:
    src: Path
    dst: Path


@dataclass
class RunCommand:
    argv: list[str]
    timeout: int = 120
    cwd: Path | None = None  # e.g. the project, for `claude plugin ... --scope project`


Step = WriteFile | DeletePath | EditJson | MovePath | RunCommand

_SYMBOL = {WriteFile: "+", DeletePath: "−", EditJson: "~", MovePath: "→", RunCommand: "$"}


def step_symbol(step: Step) -> str:
    return _SYMBOL[type(step)]


def _show(path: Path, home: Path | None) -> str:
    if home is not None and path.is_relative_to(home):
        return "~/" + path.relative_to(home).as_posix()
    return str(path)


def step_label(step: Step, home: Path | None = None) -> str:
    match step:
        case WriteFile(path=p):
            return f"write  {_show(p, home)}"
        case DeletePath(path=p):
            return f"remove {_show(p, home)}"
        case EditJson(path=p, description=d):
            return f"merge  {_show(p, home)}  {d}"
        case MovePath(src=s, dst=d):
            return f"move   {_show(s, home)} → {_show(d, home)}"
        case RunCommand(argv=argv):
            return f"run    {shlex.join(argv)}"


def _resolved_target(path: Path) -> Path:
    """The file a WriteFile/EditJson step actually writes to: the resolved file if `path` is a
    symlink pointing at an existing file (so the link itself stays a link and its target gets the
    new content), else `path` unchanged (a dangling link, a link to a directory, or a plain path)."""
    if path.is_symlink():
        resolved = path.resolve()
        if resolved.is_file():
            return resolved
    return path


def _touched(step: Step) -> list[Path]:
    match step:
        case MovePath(src=s, dst=d):
            return [s, d]
        case RunCommand():
            return []
        case WriteFile(path=p) | EditJson(path=p):
            target = _resolved_target(p)
            return [p] if target == p else [p, target]
        case _:
            return [step.path]


def fingerprint(path: Path) -> str | None:
    """Content identity of a file, folder or symlink; None if nothing is there.

    A symlink's identity covers both where it points and that target's own content, so a plan
    notices when the file behind a dotfiles-style link changes underneath it — not just when the
    link itself is repointed."""
    if path.is_symlink():
        link_target = os.readlink(path)
        resolved = path.resolve()
        target_fp = fingerprint(resolved) if resolved.exists() else None
        return f"link:{link_target}:{target_fp}"
    if path.is_file():
        return sha256_file(path)
    if path.is_dir():
        h = hashlib.sha256()
        for p in sorted(path.rglob("*")):
            rel = p.relative_to(path).as_posix()
            if p.is_symlink():
                h.update(f"L{rel}->{os.readlink(p)}\n".encode())
            elif p.is_file():
                h.update(f"F{rel}:{sha256_file(p)}\n".encode())
        return "dir:" + h.hexdigest()
    return None


@dataclass
class Plan:
    title: str
    harness: str
    scope: Scope
    steps: list[Step]
    reload_hint: str = ""
    # Plan-time "left in place" warnings (e.g. a tampered lock entry pointing outside the scope
    # dir), discovered while building the plan. They travel on the Plan itself rather than on any
    # shared engine state, so they survive a cancel-then-retry and are immune to a concurrent
    # rescan thread resetting/reading that shared state.
    warnings: list[str] = field(default_factory=list)
    origin: str = ""  # "<source>@<commit7>" for catalog-backed plans (spec §8), else ""
    preimages: dict[Path, str | None] = field(default_factory=dict)
    # Step index -> the file a WriteFile/EditJson step resolved to at build time (itself, unless
    # its path was a symlink to a file). Lets apply() notice a repoint or a link-to-regular-file
    # swap right before that step runs, in addition to the up-front check over `preimages`.
    write_targets: dict[int, Path] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        title: str,
        harness: str,
        scope: Scope,
        steps: list[Step],
        reload_hint: str = "",
        warnings: list[str] | None = None,
        origin: str = "",
    ) -> Plan:
        plan = cls(title, harness, scope, list(steps), reload_hint, list(warnings or []), origin)
        plan.preimages = {p: fingerprint(p) for s in plan.steps for p in _touched(s)}
        plan.write_targets = {
            i: _resolved_target(s.path)
            for i, s in enumerate(plan.steps)
            if isinstance(s, WriteFile | EditJson)
        }
        return plan


@dataclass
class ApplyResult:
    ok: bool
    error: str | None = None
    failed_step: int | None = None  # index into plan.steps
    output: list[str] = field(default_factory=list)


Runner = Callable[[list[str], int, Path | None], str]


def run_command(argv: list[str], timeout: int, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, cwd=cwd
        )
    except FileNotFoundError as exc:
        raise PlanError(f"{argv[0]}: command not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise PlanError(f"{shlex.join(argv)} timed out after {timeout}s") from exc
    if result.returncode:
        msg = (result.stderr or result.stdout).strip() or f"{argv[0]} exited with {result.returncode}"
        raise PlanError(msg)
    return result.stdout.strip()


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_symlink():
        os.symlink(os.readlink(src), dst)
    elif src.is_dir():
        shutil.copytree(src, dst, symlinks=True)
    else:
        shutil.copy2(src, dst)


def _write_atomic(path: Path, data: bytes, like: Path | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.harnessctl-tmp")
    tmp.write_bytes(data)
    if like is not None and like.exists():
        shutil.copymode(like, tmp)
    os.replace(tmp, path)


def _edit_json(step: EditJson) -> None:
    target = _resolved_target(step.path)
    text = target.read_text(encoding="utf-8") if target.exists() else None
    if text is not None and has_comments(text):
        raise PlanError(f"{target} contains comments, which harnessctl will not rewrite")
    try:
        data = loads_jsonc(text) if text is not None and text.strip() else None
    except ValueError as exc:
        raise PlanError(f"{target} is not valid JSON: {exc}") from exc
    new = step.edit(copy.deepcopy(data))
    _write_atomic(target, dumps(new).encode(), like=target)


def _run(step: Step, runner: Runner) -> str:
    match step:
        case WriteFile(path=p, content=c, executable=x):
            target = _resolved_target(p)
            _write_atomic(target, c, like=target)
            if x:
                target.chmod(target.stat().st_mode | 0o111)
        case DeletePath(path=p):
            _remove(p)
        case EditJson():
            _edit_json(step)
        case MovePath(src=s, dst=d):
            if d.exists() or d.is_symlink():
                raise PlanError(f"{d} already exists")
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(s, d)
        case RunCommand(argv=argv, timeout=t, cwd=cwd):
            return runner(argv, t, cwd)
    return ""


def _restore(path: Path, snapshot: Path | None) -> None:
    """Put `path` back to what `snapshot` holds, or to absence if `snapshot` is None."""
    _remove(path)
    if snapshot is not None:
        _copy(snapshot, path)


def _prune(backup_root: Path, keep: int) -> None:
    runs = sorted(p for p in backup_root.iterdir() if p.is_dir())
    for old in runs[:-keep]:
        shutil.rmtree(old, ignore_errors=True)


def apply(plan: Plan, backup_root: Path, runner: Runner = run_command, keep: int = 20) -> ApplyResult:
    changed = [p for p, fp in plan.preimages.items() if fingerprint(p) != fp]
    if changed:
        raise PlanConflict(f"{changed[0].name} changed since the plan was made ({changed[0]}) — re-plan?")

    backup = backup_root / datetime.now().strftime("%Y%m%dT%H%M%S%f")
    saved: dict[Path, Path | None] = {}
    try:
        backup.mkdir(parents=True, mode=0o700)
        for n, path in enumerate(plan.preimages):
            if path.exists() or path.is_symlink():
                _copy(path, backup / str(n))
                saved[path] = backup / str(n)
            else:
                saved[path] = None
    except OSError as exc:
        shutil.rmtree(backup, ignore_errors=True)
        return ApplyResult(False, error=f"cannot back up before applying: {exc}; nothing was changed")

    output: list[str] = []
    for n, step in enumerate(plan.steps):
        try:
            if n in plan.write_targets and _resolved_target(step.path) != plan.write_targets[n]:
                raise PlanConflict(
                    f"{step.path.name} changed since the plan was made ({step.path}) — re-plan?"
                )
            out = _run(step, runner)
        except Exception as exc:  # noqa: BLE001 - any failure rolls the whole plan back
            failed_restores: list[Path] = []
            for path, snapshot in saved.items():
                try:
                    _restore(path, snapshot)
                except Exception:  # noqa: BLE001 - a broken restore must not hide the real error
                    failed_restores.append(path)
            error = str(exc)
            if failed_restores:
                names = ", ".join(str(p) for p in failed_restores)
                error += f"; rollback incomplete: {names}; backup at {backup}"
            return ApplyResult(False, error=error, failed_step=n, output=output)
        if out:
            output.append(out)
    _prune(backup_root, keep)
    return ApplyResult(True, output=output)


def plan_diff(plan: Plan) -> str:
    """Unified diff per file, from what is on disk now to what the whole plan leaves there.
    Steps touching the same file (an update's remove, then its install) are applied in order."""
    before: dict[Path, str] = {}
    after: dict[Path, str] = {}

    def current(path: Path) -> str:
        if path not in after:
            before[path] = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
            after[path] = before[path]
        return after[path]

    for step in plan.steps:
        match step:
            case WriteFile(path=p, content=c):
                current(p)
                after[p] = c.decode(errors="replace")
            case EditJson(path=p, edit=edit):
                old = current(p)
                try:
                    after[p] = dumps(edit(copy.deepcopy(loads_jsonc(old) if old.strip() else None)))
                except Exception as exc:  # noqa: BLE001 - a preview must never crash the UI
                    after[p] = f"<cannot preview: {exc}>\n"
            case DeletePath(path=p) if p in after:
                after[p] = ""
    chunks: list[str] = []
    for path, new in after.items():
        chunks.extend(
            difflib.unified_diff(
                before[path].splitlines(keepends=True), new.splitlines(keepends=True), f"a{path}", f"b{path}"
            )
        )
    return "".join(chunks) or "(no file contents change)\n"
