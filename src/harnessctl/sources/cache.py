"""Shallow git checkouts of sources under ~/.cache/harnessctl/sources/<name>/."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from harnessctl.model import CatalogItem, SourceFormat, SourceSpec
from harnessctl.provenance import normalize_url
from harnessctl.sources.formats import detect_format, load_items

log = logging.getLogger(__name__)
MARKER = "harnessctl-synced"  # touched inside .git after every successful fetch


class GitError(Exception):
    """A git command failed; the message is git's own error text."""


@dataclass
class SourceState:
    spec: SourceSpec
    status: str  # "ok" | "stale" | "unavailable"
    root: Path | None = None
    commit: str | None = None
    last_sync: datetime | None = None
    error: str | None = None
    format: SourceFormat | None = None
    items: list[CatalogItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _git(args: list[str], cwd: Path | None = None, timeout: int = 60) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {args[0]} timed out after {timeout}s") from exc
    if result.returncode:
        raise GitError(result.stderr.strip() or f"git {args[0]} failed")
    return result.stdout.strip()


def _clone(spec: SourceSpec, checkout: Path, timeout: int) -> None:
    """Clone into a sibling tmp dir, then swap it in: a failed clone leaves any existing
    checkout untouched."""
    checkout.parent.mkdir(parents=True, exist_ok=True)
    tmp = checkout.with_name(checkout.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    branch = ["--branch", spec.ref] if spec.ref else []
    _git(["clone", "--depth", "1", "--quiet", *branch, spec.url, str(tmp)], timeout=timeout)
    shutil.rmtree(checkout, ignore_errors=True)
    tmp.rename(checkout)


def _remote_url(checkout: Path, timeout: int) -> str | None:
    """The origin remote's url exactly as configured at clone time. Deliberately `git config
    --get` rather than `git remote get-url`: the latter applies `url.<base>.insteadOf`
    rewriting, so with a corporate mirror configured that way it would never equal `spec.url`
    even though nothing changed."""
    try:
        return _git(["config", "--get", "remote.origin.url"], cwd=checkout, timeout=timeout)
    except GitError:
        return None


def _fetch(spec: SourceSpec, checkout: Path, timeout: int) -> None:
    if (checkout / ".git").is_dir():
        current = _remote_url(checkout, timeout)
        if current is None or normalize_url(current) != normalize_url(spec.url):
            # The source's url changed since the last sync: `origin` still points at the old
            # repo, so fetching it would silently keep serving stale content. Re-clone instead.
            _clone(spec, checkout, timeout)
        else:
            _git(
                ["fetch", "--depth", "1", "--quiet", "origin", spec.ref or "HEAD"],
                cwd=checkout,
                timeout=timeout,
            )
            _git(
                ["reset", "--hard", "--quiet", "FETCH_HEAD"],
                cwd=checkout,
                timeout=timeout,
            )
    else:
        _clone(spec, checkout, timeout)
    (checkout / ".git" / MARKER).touch()


def sync_source(spec: SourceSpec, cache_root: Path, fetch: bool = True, timeout: int = 60) -> SourceState:
    """Fetch (optionally) and load a source. Never raises for git, format or content problems."""
    checkout = cache_root / spec.name
    error: str | None = None
    if fetch:
        try:
            _fetch(spec, checkout, timeout)
        except (GitError, OSError) as exc:
            error = str(exc)
    if not (checkout / ".git").is_dir():
        return SourceState(spec, "unavailable", error=error or "not synced yet")

    origin = _remote_url(checkout, timeout)
    if origin is None:
        # The checkout's origin could not be read at all (a broken checkout, not necessarily a
        # url change). Don't guess which; just say so and leave the checkout untouched.
        error = error or "cannot read the checkout's origin; refresh to re-clone"
        return SourceState(spec, "unavailable", error=error)
    if normalize_url(origin) != normalize_url(spec.url):
        # The checkout on disk belongs to a different repo than the spec now points at (a
        # re-clone just failed, or the url changed and we haven't fetched since). Serving its
        # items under the new spec would be silently wrong, so report unavailable and leave the
        # old checkout untouched rather than loading anything from it.
        error = error or f"source url changed; not yet fetched from {spec.url}"
        return SourceState(spec, "unavailable", error=error)

    root = checkout / spec.subdir if spec.subdir else checkout
    state = SourceState(spec, "stale" if error else "ok", root=root, error=error)
    marker = checkout / ".git" / MARKER
    if marker.exists():
        state.last_sync = datetime.fromtimestamp(marker.stat().st_mtime, UTC)
    try:
        state.commit = _git(["rev-parse", "HEAD"], cwd=checkout)
    except GitError:
        state.commit = None
    state.format = detect_format(root) if root.is_dir() else None
    if state.format is None:
        state.status = "unavailable"
        state.error = f"{error}; no recognised catalog format" if error else "no recognised catalog format"
        return state
    try:
        state.items, state.warnings = load_items(root, state.format, spec.name, spec.url)
    except Exception as exc:  # noqa: BLE001 - a malformed source must never take the app down
        log.exception("loading items of source %s", spec.name)
        state.status = "unavailable"
        state.error = f"cannot load items: {type(exc).__name__}: {exc}"
    return state
