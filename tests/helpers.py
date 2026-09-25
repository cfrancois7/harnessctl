"""Builders for fake homes, projects, skills and git repos used across the tests."""

import contextlib
import os
import shutil
import stat
import subprocess
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "acme-catalog"

# Deterministic commits: same content always gives the same sha.
GIT_ENV = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def skill(folder: Path, description: str = "A test skill", body: str = "Body text.") -> Path:
    """Create <folder>/SKILL.md with frontmatter."""
    return write(
        folder / "SKILL.md", f"---\nname: {folder.name}\ndescription: {description}\n---\n\n{body}\n"
    )


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env={**os.environ, **GIT_ENV})


def make_repo(src: Path | None, dest: Path) -> Path:
    """Copy `src` (if given) into `dest`, then `git init` and commit everything on `main`."""
    if src is not None:
        shutil.copytree(src, dest)
    dest.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", "-b", "main", cwd=dest)
    commit_all(dest, "initial")
    return dest


def commit_all(repo: Path, message: str) -> None:
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "--allow-empty", "-m", message, cwd=repo)


async def settle(pilot) -> None:
    """Let workers finish and the screen catch up (workers can start further workers).

    An exclusive worker (e.g. a newer `rescan()` superseding an older, still-in-flight one)
    is reported by Textual as `WorkerCancelled` once cancellation is delivered; that is normal
    supersession, not a test failure, so it is ignored here. A `WorkerFailed` (a worker that
    raised) is a real crash and propagates.
    """
    from textual.worker import WorkerCancelled

    for _ in range(4):
        with contextlib.suppress(WorkerCancelled):
            await pilot.app.workers.wait_for_complete()
        await pilot.pause()


def stub_command(bin_dir: Path, name: str, log: Path, exit_code: int = 0) -> Path:
    """An executable `name` on PATH that appends its argv to `log`."""
    script = bin_dir / name
    script.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\nexit {exit_code}\n')
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script
