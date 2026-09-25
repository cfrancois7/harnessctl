# harnessctl v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `harnessctl`, a Textual TUI that shows and manages the skills, hooks and plugins of Claude Code and opencode, with a corporate catalog, public sources and provenance badges.

**Architecture:** A headless core (`model`, `config`, `jsonio`, `sources/`, `provenance`, `planner`, `edits`, `parking`, `adapters/`, `engine`) that reads the harnesses' real config files and turns every change into a `Plan` of explicit steps applied all-or-nothing. A thin Textual layer (`tui/`) renders the engine's data in three tabs (Installed / Catalog / Sources) with a list + detail layout and a plan-confirmation modal. All git and CLI work runs in Textual thread workers.

**Tech Stack:** Python 3.14, Textual 8.2+, PyYAML, tomli-w, packaging; uv (one project venv), pytest, pytest-asyncio, pytest-textual-snapshot, ruff.

**Spec:** `docs/superpowers/specs/2026-09-24-harnessctl-design.md`

## Global Constraints

- `requires-python = ">=3.14"`; `.python-version` is `3.14`; one uv-managed `.venv` in the repo; run everything with `uv run`.
- Runtime deps: `textual>=8.2,<9`, `pyyaml>=6.0`, `tomli-w>=1.2`, `packaging>=24.0`. No others.
- Work happens on the `develop` branch; never commit to `main`.
- harnessctl **never writes** `~/.config/harnessctl/corporate.toml`.
- File locations are exactly those of spec §4 (`config.toml`, `lock.json`, `sources/`, `backups/`, `disabled/`, `harnessctl.log`), honouring `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, `XDG_STATE_HOME`. Project lock: `<project>/.harnessctl/lock.json`.
- Every change to the user's files goes through `planner.apply` (hash check, backup, rollback). Adapters never write.
- JSON is rewritten with 2-space indent, original key order, trailing newline. A file that cannot be parsed is never written. **A file containing comments (JSONC) is never rewritten**; the plan is refused with the manual edit to make.
- Catalog destinations must be relative, contain no `..`, and resolve inside the harness scope folder; `{scope_dir}` is the only placeholder; settings fragments may only contain `hooks`.
- Harness ids are exactly `claude-code` and `opencode`. Scopes are `user`, `project`, `local` (`local` is read-only).
- Provenance labels are exactly `corp`, `public`, `unknown`. Status marks: `↑` update, `±` modified, `✗` broken; nothing for ok.
- The UI thread never runs git or a subprocess. Git timeout 60 s, `claude plugin` timeout 120 s.
- TUI: list + detail at ≥100 columns; list only below 100 (Enter opens the detail full-screen, Esc returns); below 50×15 show `terminal too small — need 50×15`.
- Logs go to `~/.local/state/harnessctl/harnessctl.log`, never to the screen.

**Spec amendments made while planning** (found by inspecting the real machine; each is small and keeps the spec's intent):
1. opencode's config may be `opencode.jsonc` (the user's is). Both `opencode.json` and `opencode.jsonc` are read (comments stripped); a file with comments is never rewritten (constraint above).
2. A `claude-plugin` variant in `item.toml` also needs `marketplace_name` (the `plugin@marketplace` id cannot be derived from a URL).
3. Claude's `~/.claude/skills/synced/<bucket>/<skill>/` skills (synced from claude.ai) are listed read-only.
4. "Update available" is also shown when the item's version is unchanged but its payload hash differs from the one recorded at install (public skills repos rarely carry versions).
5. Parking (disabling) a hook moves its settings entry to the parking area; its script file stays in place, inert.

## Review Focus

1. **opencode config with comments** (`opencode.jsonc` containing `//`): any change touching it must be refused with the exact manual edit, and the file must stay byte-identical. — tested in Task 12.
2. **settings.json already holding the user's own hooks and keys**: installing merges without touching them; removing ours leaves theirs intact and drops only empty containers. — tested in Tasks 9 and 11.
3. **Symlinked skill folders** in `~/.claude/skills/`: removing or parking must act on the link, never delete the link's target. — tested in Tasks 8 and 11.
4. **The same repo written differently** (`git@github.com:o/r.git`, `https://github.com/o/r`, `git+https://…`, `known_marketplaces` `{"source":"github","repo":"o/r"}`): must resolve to the same source and trust. — tested in Tasks 7 and 10.
5. **The agent edits a file between plan and apply** (Claude writes `settings.json` while the modal is open): apply must refuse, change nothing, and say which file changed. — tested in Tasks 8 and 16.

---

## File map

```
pyproject.toml, .python-version, README.md
src/harnessctl/
  __init__.py            version
  cli.py                 argparse entry point: TUI (default) and `validate`
  model.py               enums and dataclasses shared by every layer
  config.py              Paths (XDG), source lists, project detection
  jsonio.py              JSON/JSONC read, JSON write, hashing
  validate.py            catalog item rules + validate_catalog()
  sources/__init__.py
  sources/formats.py     format detection, three parsers, payload_hash, frontmatter
  sources/cache.py       git clone/fetch → SourceState
  provenance.py          lockfile entries + edits, URL normalisation, resolve()
  planner.py             Step types, Plan, apply/rollback, diff
  edits.py               pure JSON edit functions (hooks, opencode plugin array), location keys
  parking.py             disable/enable by parking
  adapters/__init__.py
  adapters/base.py       Adapter protocol, Install, shared helpers (skills, payload files)
  adapters/claude_code.py
  adapters/opencode.py
  engine.py              the core the TUI drives
  tui/__init__.py
  tui/app.py             HarnessApp, header, layout, workers, apply flow
  tui/app.tcss
  tui/text.py            pure row/detail/summary formatters
  tui/views.py           ItemList, DetailPane, ListDetailView, Installed/Catalog/Sources views
  tui/modals.py          PlanModal, ScopePicker, AddSourceScreen, TextScreen, DetailScreen
examples/acme-catalog/   example corporate catalog (also the test fixture)
tests/                   conftest.py, helpers.py, one test module per core module, tui tests
```

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`, `.python-version`, `src/harnessctl/__init__.py`, `src/harnessctl/cli.py`
- Create: `tests/__init__.py`, `tests/helpers.py`, `tests/conftest.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `harnessctl.__version__ == "0.1.0"`; `harnessctl.cli.main(argv: list[str] | None = None) -> int`; `harnessctl.cli.run() -> None` (console script).
- Produces (tests): fixture `env` → `Env(home, project, bin, environ, paths)` with `Env.engine(**kw)` (used from Task 13); helpers `write`, `skill`, `make_repo`, `commit_all`, `stub_command`, `EXAMPLES`, `GIT_ENV`.

- [ ] **Step 1: Install Python 3.14 and write the project files**

Run: `uv python install 3.14 && echo "3.14" > .python-version`

`pyproject.toml`:

```toml
[project]
name = "harnessctl"
version = "0.1.0"
description = "Terminal UI to manage coding-agent harness config: skills, hooks and plugins for Claude Code and opencode"
readme = "README.md"
requires-python = ">=3.14"
dependencies = [
  "textual>=8.2,<9",
  "pyyaml>=6.0",
  "tomli-w>=1.2",
  "packaging>=24.0",
]

[project.scripts]
harnessctl = "harnessctl.cli:run"

[dependency-groups]
dev = [
  "pytest>=8.3",
  "pytest-asyncio>=1.0",
  "pytest-textual-snapshot>=1.1",
  "ruff>=0.12",
]

[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/harnessctl"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"

[tool.ruff]
line-length = 110
target-version = "py314"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]
```

`src/harnessctl/__init__.py`:

```python
"""harnessctl: manage coding-agent harness configuration from the terminal."""

__version__ = "0.1.0"
```

- [ ] **Step 2: Write the test helpers and fixture**

`tests/__init__.py`: empty file.

`tests/helpers.py`:

```python
"""Builders for fake homes, projects, skills and git repos used across the tests."""

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
    return write(folder / "SKILL.md", f"---\nname: {folder.name}\ndescription: {description}\n---\n\n{body}\n")


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


def stub_command(bin_dir: Path, name: str, log: Path, exit_code: int = 0) -> Path:
    """An executable `name` on PATH that appends its argv to `log`."""
    script = bin_dir / name
    script.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\nexit {exit_code}\n')
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script
```

`tests/conftest.py`:

```python
from dataclasses import dataclass
from pathlib import Path

import pytest

from harnessctl.config import Paths
from tests.helpers import GIT_ENV


@dataclass
class Env:
    home: Path
    project: Path
    bin: Path
    environ: dict[str, str]
    paths: Paths

    def engine(self, **kw):
        from harnessctl.engine import Engine

        return Engine(self.paths, self.project, env=self.environ, **kw)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    home = tmp_path / "home"
    project = home / "projects" / "api"
    (project / ".git").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    environ = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin"}
    for key in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME",
                "OPENCODE_DISABLE_CLAUDE_CODE", "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS", "VISUAL", "EDITOR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", environ["HOME"])
    monkeypatch.setenv("PATH", environ["PATH"])
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)
    return Env(home, project, bin_dir, environ, Paths.from_env(environ))
```

Note: `conftest.py` imports `harnessctl.config.Paths`, which Task 2 creates. In this task, create a minimal `src/harnessctl/config.py` holding only the `Paths` class from Task 2 Step 3 (copy that class and its imports verbatim); Task 2 adds the rest of the module.

- [ ] **Step 3: Write the failing CLI test**

`tests/test_cli.py`:

```python
import pytest

from harnessctl.cli import main


def test_version_flag_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "harnessctl 0.1.0"


def test_env_fixture_isolates_home(env):
    assert env.paths.home == env.home
    assert env.paths.config == env.home / ".config" / "harnessctl"
    assert (env.project / ".git").is_dir()
```

- [ ] **Step 4: Run it to see it fail**

Run: `uv sync && uv run pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harnessctl.cli'`.

- [ ] **Step 5: Write the CLI entry point**

`src/harnessctl/cli.py`:

```python
"""Command-line entry point. `harnessctl` opens the TUI (wired in Task 14)."""

import argparse
import sys
from pathlib import Path

from harnessctl import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harnessctl",
        description="Manage skills, hooks and plugins for Claude Code and opencode.",
    )
    parser.add_argument("--version", action="version", version=f"harnessctl {__version__}")
    parser.add_argument("--project", type=Path, help="project directory (default: nearest git root)")
    return parser


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    return 0


def run() -> None:
    sys.exit(main())
```

- [ ] **Step 6: Run the tests and lint**

Run: `uv run pytest tests/test_cli.py -v && uv run ruff check . && uv run ruff format --check .`
Expected: 2 passed; ruff reports no issues (run `uv run ruff format .` first if the format check fails).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock .python-version src tests
git commit -m "build: project scaffold with uv, Python 3.14 and test fixtures"
```

---

### Task 2: Domain model and configuration

**Files:**
- Create: `src/harnessctl/model.py`
- Modify: `src/harnessctl/config.py` (complete it)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces (`model`): `Trust`, `Kind`, `Scope`, `Status`, `SourceFormat` (StrEnums); `HARNESSES = ("claude-code", "opencode")`; dataclasses `SourceSpec(name, url, trust, ref=None, subdir="")`, `SkillVariant(path)`, `FilesVariant(files: list[tuple[Path, str]], settings: dict)`, `ClaudePluginVariant(marketplace_url, marketplace_name, plugin)` with `.plugin_id`, `NpmPluginVariant(package)`, `Variant` union, `CatalogItem(id, kind, version, description, source, variants, tags=[], readme="")`, `Provenance(origin, source=None, item_id=None, commit=None)` with `.unknown()` and `.label`, `InstalledItem(harness, scope, kind, name, location, enabled=True, parent=None, provenance, status=OK, detail="", error=None, readonly=None, also_in=[], meta={})`.
- Produces (`config`): `Paths` (`home, config, cache, state, xdg_config` + properties `corporate_toml, config_toml, user_lock, sources_cache, backups, parking, log_file`), `Paths.from_env(env)`, `project_lock(project) -> Path`, `find_project(start) -> Path | None`, `ConfigError`, `load_sources(paths) -> tuple[list[SourceSpec], list[str]]`, `add_public_source(paths, spec)`, `remove_public_source(paths, name)`, `default_source_name(url) -> str`, `NAME_RE`.

- [ ] **Step 1: Write the model**

`src/harnessctl/model.py`:

```python
"""Domain types shared by every layer of harnessctl."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class Trust(StrEnum):
    CORPORATE = "corporate"
    PUBLIC = "public"


class Kind(StrEnum):
    SKILL = "skill"
    HOOK = "hook"
    PLUGIN = "plugin"


class Scope(StrEnum):
    USER = "user"
    PROJECT = "project"
    LOCAL = "local"


class Status(StrEnum):
    OK = "ok"
    MODIFIED = "modified"
    UPDATE = "update"
    BROKEN = "broken"


class SourceFormat(StrEnum):
    CATALOG = "catalog"
    CLAUDE_MARKETPLACE = "claude-marketplace"
    SKILLS_REPO = "skills-repo"


HARNESSES = ("claude-code", "opencode")


@dataclass(frozen=True)
class SourceSpec:
    name: str
    url: str
    trust: Trust
    ref: str | None = None
    subdir: str = ""


@dataclass
class SkillVariant:
    path: Path  # folder containing SKILL.md


@dataclass
class FilesVariant:
    files: list[tuple[Path, str]]  # (absolute source file, destination relative to the scope folder)
    settings: dict = field(default_factory=dict)  # only "hooks"; "{scope_dir}" not yet expanded


@dataclass
class ClaudePluginVariant:
    marketplace_url: str
    marketplace_name: str
    plugin: str

    @property
    def plugin_id(self) -> str:
        return f"{self.plugin}@{self.marketplace_name}"


@dataclass
class NpmPluginVariant:
    package: str


Variant = SkillVariant | FilesVariant | ClaudePluginVariant | NpmPluginVariant


@dataclass
class CatalogItem:
    id: str
    kind: Kind
    version: str
    description: str
    source: str
    variants: dict[str, Variant]
    tags: list[str] = field(default_factory=list)
    readme: str = ""


@dataclass
class Provenance:
    origin: str  # "corp" | "public" | "unknown"
    source: str | None = None
    item_id: str | None = None
    commit: str | None = None

    @classmethod
    def unknown(cls) -> Provenance:
        return cls("unknown")

    @property
    def label(self) -> str:
        return self.origin


@dataclass
class InstalledItem:
    harness: str
    scope: Scope
    kind: Kind
    name: str
    location: str  # a path, or a config key such as "claude-plugin:<id>"
    enabled: bool = True
    parent: str | None = None  # plugin id this item ships with
    provenance: Provenance = field(default_factory=Provenance.unknown)
    status: Status = Status.OK
    detail: str = ""  # markdown for the detail pane
    error: str | None = None
    readonly: str | None = None  # why the item cannot be changed, if it cannot
    also_in: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
```

- [ ] **Step 2: Write the failing config tests**

`tests/test_config.py`:

```python
import pytest

from harnessctl.config import (
    ConfigError,
    Paths,
    add_public_source,
    default_source_name,
    find_project,
    load_sources,
    project_lock,
    remove_public_source,
)
from harnessctl.model import SourceSpec, Trust
from tests.helpers import write


def test_paths_honour_xdg(tmp_path):
    p = Paths.from_env({"HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path / "c"),
                        "XDG_CACHE_HOME": str(tmp_path / "k"), "XDG_STATE_HOME": str(tmp_path / "s")})
    assert p.corporate_toml == tmp_path / "c" / "harnessctl" / "corporate.toml"
    assert p.sources_cache == tmp_path / "k" / "harnessctl" / "sources"
    assert p.parking == tmp_path / "s" / "harnessctl" / "disabled"
    assert p.xdg_config == tmp_path / "c"


def test_paths_default_to_home(tmp_path):
    p = Paths.from_env({"HOME": str(tmp_path)})
    assert p.user_lock == tmp_path / ".config" / "harnessctl" / "lock.json"
    assert p.backups == tmp_path / ".local" / "state" / "harnessctl" / "backups"
    assert p.log_file == tmp_path / ".local" / "state" / "harnessctl" / "harnessctl.log"


def test_find_project_walks_up(tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    deep = tmp_path / "repo" / "a" / "b"
    deep.mkdir(parents=True)
    assert find_project(deep) == tmp_path / "repo"
    assert project_lock(tmp_path / "repo") == tmp_path / "repo" / ".harnessctl" / "lock.json"


def test_find_project_none_outside_git(tmp_path):
    assert find_project(tmp_path) is None


def test_load_sources_forces_trust_by_file(env):
    write(env.paths.corporate_toml, '[[source]]\nname = "acme"\nurl = "git@gitlab.acme.io:p/c.git"\nref = "main"\n')
    write(env.paths.config_toml, '[[source]]\nname = "superpowers"\nurl = "https://github.com/obra/superpowers"\n')
    specs, errors = load_sources(env.paths)
    assert errors == []
    assert specs == [
        SourceSpec("acme", "git@gitlab.acme.io:p/c.git", Trust.CORPORATE, "main", ""),
        SourceSpec("superpowers", "https://github.com/obra/superpowers", Trust.PUBLIC, None, ""),
    ]


def test_public_source_cannot_shadow_corporate(env):
    write(env.paths.corporate_toml, '[[source]]\nname = "acme"\nurl = "u1"\n')
    write(env.paths.config_toml, '[[source]]\nname = "acme"\nurl = "u2"\n')
    specs, errors = load_sources(env.paths)
    assert [s.url for s in specs] == ["u1"]
    assert "shadows a corporate source" in errors[0]


def test_invalid_entries_are_reported_not_fatal(env):
    write(env.paths.config_toml, '[[source]]\nname = "Bad Name"\nurl = "u"\n'
                                 '[[source]]\nname = "ok"\nurl = "u"\nsubdir = "../escape"\n'
                                 '[[source]]\nname = "good"\nurl = "u"\n')
    specs, errors = load_sources(env.paths)
    assert [s.name for s in specs] == ["good"]
    assert len(errors) == 2


def test_broken_toml_is_an_error_not_a_crash(env):
    write(env.paths.config_toml, "[[source]\n")
    specs, errors = load_sources(env.paths)
    assert specs == [] and "config.toml" in errors[0]


def test_add_and_remove_public_source(env):
    add_public_source(env.paths, SourceSpec("sp", "https://github.com/obra/superpowers", Trust.PUBLIC, ref="v6"))
    specs, _ = load_sources(env.paths)
    assert specs == [SourceSpec("sp", "https://github.com/obra/superpowers", Trust.PUBLIC, "v6", "")]
    with pytest.raises(ConfigError):
        add_public_source(env.paths, SourceSpec("sp", "other", Trust.PUBLIC))
    remove_public_source(env.paths, "sp")
    assert load_sources(env.paths)[0] == []
    with pytest.raises(ConfigError):
        remove_public_source(env.paths, "sp")


def test_add_source_never_touches_corporate_toml(env):
    corp = write(env.paths.corporate_toml, '[[source]]\nname = "acme"\nurl = "u"\n')
    before = corp.read_bytes()
    add_public_source(env.paths, SourceSpec("x", "u2", Trust.PUBLIC))
    assert corp.read_bytes() == before


@pytest.mark.parametrize(("url", "name"), [
    ("git@github.com:obra/superpowers.git", "superpowers"),
    ("https://github.com/gfargo/skills/", "skills"),
    ("https://example.com/My Repo.git", "my-repo"),
])
def test_default_source_name(url, name):
    assert default_source_name(url) == name
```

- [ ] **Step 3: Run to see it fail, then complete `config.py`**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'ConfigError'`.

`src/harnessctl/config.py`:

```python
"""Where harnessctl keeps its files, and the source lists it reads."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import tomli_w

from harnessctl.model import SourceSpec, Trust

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class ConfigError(Exception):
    """A configuration change that cannot be made; the message says why."""


@dataclass(frozen=True)
class Paths:
    home: Path
    config: Path  # ~/.config/harnessctl
    cache: Path  # ~/.cache/harnessctl
    state: Path  # ~/.local/state/harnessctl
    xdg_config: Path  # ~/.config (opencode lives under it)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Paths:
        env = dict(os.environ if env is None else env)
        home = Path(env.get("HOME") or Path.home())
        xdg_config = Path(env.get("XDG_CONFIG_HOME") or home / ".config")
        xdg_cache = Path(env.get("XDG_CACHE_HOME") or home / ".cache")
        xdg_state = Path(env.get("XDG_STATE_HOME") or home / ".local" / "state")
        return cls(home, xdg_config / "harnessctl", xdg_cache / "harnessctl", xdg_state / "harnessctl", xdg_config)

    @property
    def corporate_toml(self) -> Path:
        return self.config / "corporate.toml"

    @property
    def config_toml(self) -> Path:
        return self.config / "config.toml"

    @property
    def user_lock(self) -> Path:
        return self.config / "lock.json"

    @property
    def sources_cache(self) -> Path:
        return self.cache / "sources"

    @property
    def backups(self) -> Path:
        return self.state / "backups"

    @property
    def parking(self) -> Path:
        return self.state / "disabled"

    @property
    def log_file(self) -> Path:
        return self.state / "harnessctl.log"


def project_lock(project: Path) -> Path:
    return project / ".harnessctl" / "lock.json"


def find_project(start: Path) -> Path | None:
    """Nearest ancestor of `start` (inclusive) that contains `.git`."""
    for folder in [start, *start.parents]:
        if (folder / ".git").exists():
            return folder
    return None


def _valid_subdir(subdir: str) -> bool:
    p = PurePosixPath(subdir)
    return not p.is_absolute() and ".." not in p.parts


def _read_sources(path: Path, trust: Trust) -> tuple[list[SourceSpec], list[str]]:
    if not path.exists():
        return [], []
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        return [], [f"{path}: {exc}"]
    specs: list[SourceSpec] = []
    errors: list[str] = []
    for n, raw in enumerate(data.get("source", []), start=1):
        name, url, subdir = raw.get("name"), raw.get("url"), raw.get("subdir", "")
        if not (isinstance(name, str) and NAME_RE.match(name) and isinstance(url, str) and url):
            errors.append(f"{path}: source #{n} needs a lowercase name and a url")
            continue
        if not isinstance(subdir, str) or not _valid_subdir(subdir):
            errors.append(f"{path}: source '{name}' has an invalid subdir {subdir!r}")
            continue
        specs.append(SourceSpec(name, url, trust, raw.get("ref") or None, subdir))
    return specs, errors


def load_sources(paths: Paths) -> tuple[list[SourceSpec], list[str]]:
    """Corporate sources first, then public ones. Problems are returned, never raised."""
    corp, corp_errors = _read_sources(paths.corporate_toml, Trust.CORPORATE)
    public, public_errors = _read_sources(paths.config_toml, Trust.PUBLIC)
    errors = corp_errors + public_errors
    names = {s.name for s in corp}
    kept: list[SourceSpec] = []
    for spec in public:
        if spec.name in names:
            errors.append(f"{paths.config_toml}: source '{spec.name}' shadows a corporate source and is ignored")
            continue
        names.add(spec.name)
        kept.append(spec)
    return corp + kept, errors


def _read_config(paths: Paths) -> dict:
    if not paths.config_toml.exists():
        return {}
    try:
        return tomllib.loads(paths.config_toml.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{paths.config_toml}: {exc}") from exc


def _write_config(paths: Paths, data: dict) -> None:
    paths.config.mkdir(parents=True, exist_ok=True)
    paths.config_toml.write_text(tomli_w.dumps(data))


def add_public_source(paths: Paths, spec: SourceSpec) -> None:
    if not NAME_RE.match(spec.name):
        raise ConfigError(f"'{spec.name}' is not a valid source name (lowercase letters, digits, - and _)")
    if not _valid_subdir(spec.subdir):
        raise ConfigError(f"invalid subdir {spec.subdir!r}")
    existing, _ = load_sources(paths)
    if any(s.name == spec.name for s in existing):
        raise ConfigError(f"a source named '{spec.name}' already exists")
    data = _read_config(paths)
    entry = {"name": spec.name, "url": spec.url}
    if spec.ref:
        entry["ref"] = spec.ref
    if spec.subdir:
        entry["subdir"] = spec.subdir
    data.setdefault("source", []).append(entry)
    _write_config(paths, data)


def remove_public_source(paths: Paths, name: str) -> None:
    data = _read_config(paths)
    sources = data.get("source", [])
    kept = [s for s in sources if s.get("name") != name]
    if len(kept) == len(sources):
        raise ConfigError(f"no public source named '{name}'")
    data["source"] = kept
    _write_config(paths, data)


def default_source_name(url: str) -> str:
    """'git@github.com:obra/superpowers.git' → 'superpowers'."""
    tail = url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1].removesuffix(".git").lower()
    return re.sub(r"[^a-z0-9_-]+", "-", tail).strip("-") or "source"
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_config.py tests/test_cli.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/harnessctl/model.py src/harnessctl/config.py tests/test_config.py
git commit -m "feat: domain model, XDG paths and source configuration"
```

---

### Task 3: JSON and JSONC I/O

**Files:**
- Create: `src/harnessctl/jsonio.py`
- Test: `tests/test_jsonio.py`

**Interfaces:**
- Produces: `JsonFileError(path, message)` (attr `.path`), `strip_comments(text) -> tuple[str, bool]`, `has_comments(text) -> bool`, `loads_jsonc(text) -> Any`, `read_json(path, default=None) -> Any`, `dumps(data) -> str`, `sha256_bytes(data) -> str`, `sha256_file(path) -> str | None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_jsonio.py`:

```python
import pytest

from harnessctl.jsonio import JsonFileError, dumps, has_comments, loads_jsonc, read_json, sha256_file
from tests.helpers import write

JSONC = """{
  // line comment
  "$schema": "https://opencode.ai/config.json", /* block */
  "plugin": ["a", "b",],
}
"""


def test_loads_jsonc_strips_comments_and_trailing_commas():
    assert loads_jsonc(JSONC) == {"$schema": "https://opencode.ai/config.json", "plugin": ["a", "b"]}


def test_comment_markers_inside_strings_are_kept():
    assert loads_jsonc('{"u": "http://x/*y*/", "c": "a,]"}') == {"u": "http://x/*y*/", "c": "a,]"}
    assert has_comments('{"u": "http://x"}') is False


def test_has_comments():
    assert has_comments(JSONC) is True
    assert has_comments('{"a": 1}') is False


def test_read_json_missing_returns_default(tmp_path):
    assert read_json(tmp_path / "nope.json", default={"x": 1}) == {"x": 1}


def test_read_json_invalid_raises_with_path(tmp_path):
    bad = write(tmp_path / "settings.json", "{not json")
    with pytest.raises(JsonFileError) as exc:
        read_json(bad)
    assert exc.value.path == bad
    assert "settings.json" in str(exc.value)


def test_dumps_keeps_order_and_indent():
    assert dumps({"b": 1, "a": {"c": [1]}}) == '{\n  "b": 1,\n  "a": {\n    "c": [\n      1\n    ]\n  }\n}\n'


def test_sha256_file(tmp_path):
    f = write(tmp_path / "f", "x")
    assert sha256_file(f) == "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881"
    assert sha256_file(tmp_path / "missing") is None
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/test_jsonio.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harnessctl.jsonio'`.

- [ ] **Step 3: Implement**

`src/harnessctl/jsonio.py`:

```python
"""JSON / JSONC reading, order-preserving JSON writing, and hashing."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

_STRING = r'"(?:\\.|[^"\\])*"'
_COMMENT = re.compile(rf"{_STRING}|//[^\n]*|/\*.*?\*/", re.S)
_TRAILING_COMMA = re.compile(rf"{_STRING}|,(?=\s*[}}\]])")


class JsonFileError(Exception):
    """A JSON file that exists but cannot be parsed."""

    def __init__(self, path: Path, message: str):
        super().__init__(f"{path}: {message}")
        self.path = path


def strip_comments(text: str) -> tuple[str, bool]:
    """Remove // and /* */ comments outside strings. Returns (text, whether any were found)."""
    found = False

    def replace(match: re.Match[str]) -> str:
        nonlocal found
        token = match.group(0)
        if token.startswith('"'):
            return token
        found = True
        return "" if token.startswith("//") else " "

    return _COMMENT.sub(replace, text), found


def has_comments(text: str) -> bool:
    return strip_comments(text)[1]


def loads_jsonc(text: str) -> Any:
    clean, _ = strip_comments(text)
    clean = _TRAILING_COMMA.sub(lambda m: m.group(0) if m.group(0).startswith('"') else "", clean)
    return json.loads(clean)


def read_json(path: Path, default: Any = None) -> Any:
    """Read JSON or JSONC. A missing file gives `default`; an invalid one raises JsonFileError."""
    if not path.exists():
        return default
    try:
        return loads_jsonc(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise JsonFileError(path, str(exc)) from exc


def dumps(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.is_file() else None
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_jsonio.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/harnessctl/jsonio.py tests/test_jsonio.py
git commit -m "feat: JSON and JSONC reading and writing"
```

---

### Task 4: Source formats, catalog rules and the example catalog

**Files:**
- Create: `src/harnessctl/validate.py`, `src/harnessctl/sources/__init__.py` (empty), `src/harnessctl/sources/formats.py`
- Create: `examples/acme-catalog/catalog.toml`, `examples/acme-catalog/README.md`, and the three items below
- Test: `tests/test_formats.py`

**Interfaces:**
- Consumes: `model` types (Task 2).
- Produces (`validate`): `ID_RE`, `check_item(item_dir: Path, data: dict) -> list[str]`, `validate_catalog(root: Path) -> list[str]`.
- Produces (`formats`): `detect_format(root) -> SourceFormat | None`, `read_frontmatter(skill_md) -> tuple[dict, str]`, `load_items(root, fmt, source, source_url="") -> tuple[list[CatalogItem], list[str]]`, `payload_hash(variant) -> str`.

- [ ] **Step 1: Create the example catalog**

`examples/acme-catalog/catalog.toml`:

```toml
name = "acme"
items = ["items/*"]
```

`examples/acme-catalog/items/api-conventions/item.toml`:

```toml
id = "api-conventions"
kind = "skill"
version = "1.4.0"
description = "REST API conventions for Acme services"
tags = ["api", "backend"]

[skill]
path = "skill"
harnesses = ["claude-code", "opencode"]
```

`examples/acme-catalog/items/api-conventions/skill/SKILL.md`:

```markdown
---
name: api-conventions
description: REST API conventions for Acme services. Use when designing or reviewing an HTTP endpoint.
---

# API conventions

## When to use
- Adding or changing a route
- Reviewing an OpenAPI diff

## Rules
- Plural nouns, kebab-case paths
- Errors follow RFC 9457 problem+json
- Never break a published field
```

`examples/acme-catalog/items/block-secrets-read/item.toml`:

```toml
id = "block-secrets-read"
kind = "hook"
version = "2.0.1"
description = "Blocks the agent from reading .env, *.pem and files under secrets/."
tags = ["security"]

[variants.claude-code]
type = "files"
files = { "claude/secrets.sh" = "hooks/block-secrets-read/secrets.sh" }

[variants.claude-code.settings]
hooks.PreToolUse = [{ matcher = "Read|Grep", hooks = [{ type = "command", command = "{scope_dir}/hooks/block-secrets-read/secrets.sh" }] }]

[variants.opencode]
type = "files"
files = { "opencode/block-secrets.ts" = "plugins/block-secrets-read.ts" }
```

`examples/acme-catalog/items/block-secrets-read/claude/secrets.sh` (make it executable: `chmod +x`):

```sh
#!/bin/sh
# Claude Code PreToolUse hook: exit 2 blocks the tool call.
input=$(cat)
case "$input" in
  *'.env"'*|*'.pem"'*|*'secrets/'*) echo "blocked: secrets are off limits" >&2; exit 2 ;;
esac
exit 0
```

`examples/acme-catalog/items/block-secrets-read/opencode/block-secrets.ts`:

```ts
export const BlockSecretsRead = async () => ({
  "tool.execute.before": async (input: { tool: string }, output: { args: { filePath?: string } }) => {
    const path = output.args.filePath ?? ""
    if (["read", "grep"].includes(input.tool) && /(\.env$|\.pem$|secrets\/)/.test(path)) {
      throw new Error("blocked: secrets are off limits")
    }
  },
})
```

`examples/acme-catalog/items/jira-context/item.toml`:

```toml
id = "jira-context"
kind = "plugin"
version = "1.2.0"
description = "Pulls the linked Jira ticket into the agent's context."

[variants.claude-code]
type = "claude-plugin"
marketplace = "https://github.com/acme/claude-plugins"
marketplace_name = "acme-plugins"
plugin = "jira-context"

[variants.opencode]
type = "npm-plugin"
package = "@acme/opencode-jira@1.2.0"
```

`examples/acme-catalog/README.md`:

````markdown
# Example corporate catalog

A harnessctl catalog is a git repo (or a subfolder of one) with a `catalog.toml`
listing item folders. Each item folder has an `item.toml` and its payload files.

- **skill**: one `SKILL.md` folder shared by every harness listed in `[skill].harnesses`.
- **hook** / **plugin**: one `[variants.<harness>]` table per supported harness
  (`claude-code`, `opencode`). Variant types:
  - `files`: copy files into the harness folder (`files = { "<source>" = "<destination>" }`);
    for Claude Code, `[variants.claude-code.settings]` holds `hooks` merged into `settings.json`.
    `{scope_dir}` expands to `~/.claude` / `<project>/.claude` (or the opencode folder).
  - `claude-plugin`: `marketplace` (git URL), `marketplace_name`, `plugin`.
  - `npm-plugin`: `package`, added to the `plugin` array of `opencode.json`.

Check a catalog with `harnessctl validate <path>`; run it in the catalog's CI.
````

- [ ] **Step 2: Write the failing tests**

`tests/test_formats.py`:

```python
import json
import shutil

from harnessctl.model import ClaudePluginVariant, FilesVariant, Kind, NpmPluginVariant, SkillVariant, SourceFormat
from harnessctl.sources.formats import detect_format, load_items, payload_hash, read_frontmatter
from harnessctl.validate import validate_catalog
from tests.helpers import EXAMPLES, skill, write


def test_detect_format(tmp_path):
    assert detect_format(EXAMPLES) is SourceFormat.CATALOG
    write(tmp_path / "m" / ".claude-plugin" / "marketplace.json", "{}")
    assert detect_format(tmp_path / "m") is SourceFormat.CLAUDE_MARKETPLACE
    skill(tmp_path / "s" / "skills" / "one")
    assert detect_format(tmp_path / "s") is SourceFormat.SKILLS_REPO
    assert detect_format(tmp_path) is None


def test_example_catalog_loads_cleanly():
    items, warnings = load_items(EXAMPLES, SourceFormat.CATALOG, "acme")
    assert warnings == []
    by_id = {i.id: i for i in items}
    assert set(by_id) == {"api-conventions", "block-secrets-read", "jira-context"}

    sk = by_id["api-conventions"]
    assert sk.kind is Kind.SKILL and sk.version == "1.4.0" and sk.source == "acme"
    assert set(sk.variants) == {"claude-code", "opencode"}
    assert isinstance(sk.variants["opencode"], SkillVariant)
    assert "# API conventions" in sk.readme

    hook = by_id["block-secrets-read"].variants["claude-code"]
    assert isinstance(hook, FilesVariant)
    assert hook.files[0][1] == "hooks/block-secrets-read/secrets.sh"
    assert hook.files[0][0].is_file()
    assert "{scope_dir}" in json.dumps(hook.settings)

    plug = by_id["jira-context"]
    assert plug.variants["claude-code"] == ClaudePluginVariant(
        "https://github.com/acme/claude-plugins", "acme-plugins", "jira-context")
    assert plug.variants["claude-code"].plugin_id == "jira-context@acme-plugins"
    assert plug.variants["opencode"] == NpmPluginVariant("@acme/opencode-jira@1.2.0")


def _catalog_with(tmp_path, item_toml: str, files: dict[str, str] | None = None):
    root = tmp_path / "cat"
    shutil.copytree(EXAMPLES, root)
    item = root / "items" / "bad"
    write(item / "item.toml", item_toml)
    for rel, text in (files or {}).items():
        write(item / rel, text)
    return root


def test_bad_items_are_skipped_with_warnings(tmp_path):
    root = _catalog_with(tmp_path, """
id = "Bad_Id"
kind = "hook"
version = "one"
[variants.claude-code]
type = "files"
files = { "missing.sh" = "../../etc/passwd" }
[variants.claude-code.settings]
permissions = {}
hooks.PreToolUse = [{ hooks = [{ type = "command", command = "{home}/x" }] }]
""")
    items, warnings = load_items(root, SourceFormat.CATALOG, "acme")
    assert {i.id for i in items} == {"api-conventions", "block-secrets-read", "jira-context"}
    text = "\n".join(warnings)
    for fragment in ["id must match", "semantic version", "not found in item folder",
                     "must be a relative path", "may only contain hooks", "unknown placeholder {home}"]:
        assert fragment in text
    assert all(w.startswith("items/bad/item.toml: ") for w in warnings)


def test_variant_type_harness_mismatch(tmp_path):
    root = _catalog_with(tmp_path, """
id = "x"
kind = "plugin"
version = "1.0.0"
[variants.opencode]
type = "claude-plugin"
marketplace = "u"
marketplace_name = "m"
plugin = "p"
""")
    _, warnings = load_items(root, SourceFormat.CATALOG, "acme")
    assert any("claude-plugin variants are only for claude-code" in w for w in warnings)


def test_duplicate_ids_are_rejected(tmp_path):
    root = _catalog_with(tmp_path, (EXAMPLES / "items/jira-context/item.toml").read_text())
    _, warnings = load_items(root, SourceFormat.CATALOG, "acme")
    assert any("duplicate id 'jira-context'" in w for w in warnings)


def test_validate_catalog_reports_everything(tmp_path):
    assert validate_catalog(EXAMPLES) == []
    assert "no catalog.toml" in validate_catalog(tmp_path)[0]


def test_marketplace_format(tmp_path):
    root = tmp_path / "m"
    write(root / ".claude-plugin" / "marketplace.json", json.dumps({
        "name": "gfargo-skills",
        "plugins": [{"name": "terminal", "version": "1.0.6", "description": "TUI tools"}, {"description": "no name"}],
    }))
    items, warnings = load_items(root, SourceFormat.CLAUDE_MARKETPLACE, "gfargo", "https://github.com/gfargo/skills")
    assert [i.id for i in items] == ["terminal"]
    assert items[0].kind is Kind.PLUGIN
    assert items[0].variants == {"claude-code": ClaudePluginVariant("https://github.com/gfargo/skills", "gfargo-skills", "terminal")}
    assert warnings == ["marketplace.json: a plugin has no name"]


def test_skills_repo_format(tmp_path):
    root = tmp_path / "s"
    skill(root / "skills" / "tdd", description="Red green refactor")
    write(root / "skills" / "raw" / "SKILL.md", "no frontmatter here")
    items, warnings = load_items(root, SourceFormat.SKILLS_REPO, "pub")
    assert warnings == []
    by_id = {i.id: i for i in items}
    assert by_id["tdd"].description == "Red green refactor"
    assert by_id["raw"].description == "" and by_id["raw"].version == "0.0.0"
    assert set(by_id["tdd"].variants) == {"claude-code", "opencode"}


def test_read_frontmatter_tolerates_bad_yaml(tmp_path):
    md = write(tmp_path / "SKILL.md", "---\nname: [unclosed\n---\nbody\n")
    assert read_frontmatter(md) == ({}, "---\nname: [unclosed\n---\nbody\n")


def test_payload_hash_tracks_content(tmp_path):
    folder = tmp_path / "sk"
    skill(folder, body="one")
    before = payload_hash(SkillVariant(folder))
    skill(folder, body="two")
    assert payload_hash(SkillVariant(folder)) != before
```

- [ ] **Step 3: Run to see it fail**

Run: `uv run pytest tests/test_formats.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harnessctl.sources'`.

- [ ] **Step 4: Implement the rules**

`src/harnessctl/validate.py`:

```python
"""Catalog linting, shared by `harnessctl validate` and source loading."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from packaging.version import InvalidVersion, Version

from harnessctl.model import HARNESSES

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_VARIANT_HARNESS = {"claude-plugin": "claude-code", "npm-plugin": "opencode"}


def _safe_destination(dest: object) -> bool:
    if not isinstance(dest, str) or not dest or "\\" in dest:
        return False
    p = PurePosixPath(dest)
    return not p.is_absolute() and ".." not in p.parts


def _placeholders(value: object) -> set[str]:
    match value:
        case str():
            return set(_PLACEHOLDER.findall(value))
        case dict():
            return set().union(*(_placeholders(v) for v in value.values())) if value else set()
        case list():
            return set().union(*(_placeholders(v) for v in value)) if value else set()
    return set()


def _check_skill(item_dir: Path, data: dict) -> list[str]:
    errors: list[str] = []
    if data.get("variants"):
        errors.append("a skill item uses [skill], not [variants.*]")
    table = data.get("skill")
    if not isinstance(table, dict):
        return [*errors, "a skill item needs a [skill] table"]
    rel = str(table.get("path", ""))
    if not _safe_destination(rel) or not (item_dir / rel / "SKILL.md").is_file():
        errors.append(f"[skill].path {rel!r} has no SKILL.md")
    unknown = [h for h in table.get("harnesses", list(HARNESSES)) if h not in HARNESSES]
    if unknown:
        errors.append(f"[skill].harnesses: unknown harness {', '.join(map(str, unknown))}")
    return errors


def _check_variant(item_dir: Path, harness: str, v: object) -> list[str]:
    where = f"[variants.{harness}]"
    if harness not in HARNESSES:
        return [f"{where}: unknown harness"]
    if not isinstance(v, dict):
        return [f"{where}: must be a table"]
    kind = v.get("type")
    if kind not in {"files", "claude-plugin", "npm-plugin"}:
        return [f"{where}: type must be files, claude-plugin or npm-plugin"]
    errors: list[str] = []
    if kind in _VARIANT_HARNESS and harness != _VARIANT_HARNESS[kind]:
        errors.append(f"{where}: {kind} variants are only for {_VARIANT_HARNESS[kind]}")
    if kind == "files":
        files = v.get("files")
        if not isinstance(files, dict) or not files:
            errors.append(f"{where}: files must list at least one file")
        else:
            for src, dest in files.items():
                if not (item_dir / src).is_file():
                    errors.append(f"{where}: file {src!r} not found in item folder")
                if not _safe_destination(dest):
                    errors.append(f"{where}: destination {dest!r} must be a relative path inside the harness folder")
        settings = v.get("settings", {})
        if not isinstance(settings, dict) or set(settings) - {"hooks"}:
            errors.append(f"{where}: settings may only contain hooks")
        if settings and harness != "claude-code":
            errors.append(f"{where}: settings are only supported for claude-code")
        for name in sorted(_placeholders(settings) - {"scope_dir"}):
            errors.append(f"{where}: unknown placeholder {{{name}}}")
    elif kind == "claude-plugin":
        for key in ("marketplace", "marketplace_name", "plugin"):
            if not isinstance(v.get(key), str) or not v.get(key):
                errors.append(f"{where}: {key} is required")
    elif not isinstance(v.get("package"), str) or not v.get("package"):
        errors.append(f"{where}: package is required")
    return errors


def check_item(item_dir: Path, data: dict) -> list[str]:
    """Every rule of spec §5 that `data` (a parsed item.toml in `item_dir`) breaks."""
    errors: list[str] = []
    if not isinstance(data.get("id"), str) or not ID_RE.match(data["id"]):
        errors.append("id must match [a-z0-9][a-z0-9-]*")
    kind = data.get("kind")
    if kind not in {"skill", "hook", "plugin"}:
        errors.append("kind must be skill, hook or plugin")
    try:
        Version(str(data.get("version", "")))
    except InvalidVersion:
        errors.append("version must be a semantic version")
    if kind == "skill":
        errors += _check_skill(item_dir, data)
    elif kind in {"hook", "plugin"}:
        variants = data.get("variants")
        if not isinstance(variants, dict) or not variants:
            errors.append("needs at least one [variants.<harness>] table")
        else:
            for harness, v in variants.items():
                errors += _check_variant(item_dir, harness, v)
    return errors


def validate_catalog(root: Path) -> list[str]:
    """Every problem in a source checkout, as 'path: message' lines. Empty means valid."""
    from harnessctl.sources.formats import detect_format, load_items

    fmt = detect_format(root)
    if fmt is None:
        return [f"{root}: no catalog.toml, .claude-plugin/marketplace.json or skills/*/SKILL.md found"]
    _, warnings = load_items(root, fmt, source="validate")
    return warnings
```

- [ ] **Step 5: Implement the parsers**

`src/harnessctl/sources/formats.py`:

```python
"""Turn a source checkout into catalog items, whatever its format."""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

import yaml

from harnessctl.jsonio import sha256_file
from harnessctl.model import (
    HARNESSES,
    CatalogItem,
    ClaudePluginVariant,
    FilesVariant,
    Kind,
    NpmPluginVariant,
    SkillVariant,
    SourceFormat,
    Variant,
)
from harnessctl.validate import ID_RE, check_item


def detect_format(root: Path) -> SourceFormat | None:
    if (root / "catalog.toml").is_file():
        return SourceFormat.CATALOG
    if (root / ".claude-plugin" / "marketplace.json").is_file():
        return SourceFormat.CLAUDE_MARKETPLACE
    if any((root / "skills").glob("*/SKILL.md")):
        return SourceFormat.SKILLS_REPO
    return None


def read_frontmatter(skill_md: Path) -> tuple[dict, str]:
    """(frontmatter, body). Missing or invalid frontmatter gives ({}, whole text)."""
    text = skill_md.read_text(errors="replace")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            try:
                data = yaml.safe_load(text[3:end]) or {}
            except yaml.YAMLError:
                data = None
            if isinstance(data, dict):
                return data, text[end + 4 :].lstrip("\n")
    return {}, text


def load_items(root: Path, fmt: SourceFormat, source: str, source_url: str = "") -> tuple[list[CatalogItem], list[str]]:
    match fmt:
        case SourceFormat.CATALOG:
            return _load_catalog(root, source)
        case SourceFormat.CLAUDE_MARKETPLACE:
            return _load_marketplace(root, source, source_url)
        case SourceFormat.SKILLS_REPO:
            return _load_skills_repo(root, source)


def _load_catalog(root: Path, source: str) -> tuple[list[CatalogItem], list[str]]:
    try:
        catalog = tomllib.loads((root / "catalog.toml").read_text())
    except tomllib.TOMLDecodeError as exc:
        return [], [f"catalog.toml: {exc}"]
    items: list[CatalogItem] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for pattern in catalog.get("items", ["items/*"]):
        for item_dir in sorted(root.glob(pattern)):
            toml_path = item_dir / "item.toml"
            if not toml_path.is_file():
                continue
            rel = toml_path.relative_to(root).as_posix()
            try:
                data = tomllib.loads(toml_path.read_text())
            except tomllib.TOMLDecodeError as exc:
                warnings.append(f"{rel}: {exc}")
                continue
            errors = check_item(item_dir, data)
            if not errors and data["id"] in seen:
                errors = [f"duplicate id {data['id']!r}"]
            if errors:
                warnings.extend(f"{rel}: {e}" for e in errors)
                continue
            seen.add(data["id"])
            items.append(_item_from_toml(item_dir, data, source))
    return items, warnings


def _item_from_toml(item_dir: Path, data: dict, source: str) -> CatalogItem:
    kind = Kind(data["kind"])
    variants: dict[str, Variant] = {}
    readme = ""
    if kind is Kind.SKILL:
        folder = item_dir / data["skill"]["path"]
        for harness in data["skill"].get("harnesses", list(HARNESSES)):
            variants[harness] = SkillVariant(folder)
        readme = read_frontmatter(folder / "SKILL.md")[1]
    else:
        for harness, v in data["variants"].items():
            match v["type"]:
                case "files":
                    files = [(item_dir / src, dest) for src, dest in v["files"].items()]
                    variants[harness] = FilesVariant(files, v.get("settings", {}))
                case "claude-plugin":
                    variants[harness] = ClaudePluginVariant(v["marketplace"], v["marketplace_name"], v["plugin"])
                case "npm-plugin":
                    variants[harness] = NpmPluginVariant(v["package"])
        if (item_dir / "README.md").is_file():
            readme = (item_dir / "README.md").read_text()
    return CatalogItem(
        id=data["id"], kind=kind, version=str(data["version"]), description=data.get("description", ""),
        source=source, variants=variants, tags=list(data.get("tags", [])), readme=readme,
    )


def _load_marketplace(root: Path, source: str, source_url: str) -> tuple[list[CatalogItem], list[str]]:
    try:
        data = json.loads((root / ".claude-plugin" / "marketplace.json").read_text())
    except json.JSONDecodeError as exc:
        return [], [f".claude-plugin/marketplace.json: {exc}"]
    market = data.get("name")
    if not isinstance(market, str) or not market:
        return [], ["marketplace.json: missing name"]
    items: list[CatalogItem] = []
    warnings: list[str] = []
    for plugin in data.get("plugins", []):
        name = plugin.get("name")
        if not isinstance(name, str) or not name:
            warnings.append("marketplace.json: a plugin has no name")
            continue
        items.append(CatalogItem(
            id=name, kind=Kind.PLUGIN, version=str(plugin.get("version", "0.0.0")),
            description=plugin.get("description", ""), source=source,
            variants={"claude-code": ClaudePluginVariant(source_url, market, name)},
        ))
    return items, warnings


def _load_skills_repo(root: Path, source: str) -> tuple[list[CatalogItem], list[str]]:
    items: list[CatalogItem] = []
    warnings: list[str] = []
    for md in sorted(root.glob("skills/*/SKILL.md")):
        sid = md.parent.name
        if not ID_RE.match(sid):
            warnings.append(f"skills/{sid}: folder name is not a valid id")
            continue
        front, body = read_frontmatter(md)
        items.append(CatalogItem(
            id=sid, kind=Kind.SKILL, version=str(front.get("version", "0.0.0")),
            description=str(front.get("description", "")), source=source,
            variants={h: SkillVariant(md.parent) for h in HARNESSES}, readme=body,
        ))
    return items, warnings


def payload_hash(variant: Variant) -> str:
    """A fingerprint of what installing `variant` would write; changes when the payload changes."""
    h = hashlib.sha256()
    match variant:
        case SkillVariant(path=folder):
            for f in sorted(p for p in folder.rglob("*") if p.is_file()):
                h.update(f"{f.relative_to(folder).as_posix()}:{sha256_file(f)}\n".encode())
        case FilesVariant(files=files, settings=settings):
            for src, dest in sorted(files, key=lambda pair: pair[1]):
                h.update(f"{dest}:{sha256_file(src)}\n".encode())
            h.update(json.dumps(settings, sort_keys=True).encode())
        case _:
            h.update(repr(variant).encode())
    return h.hexdigest()
```

- [ ] **Step 6: Run the tests**

Run: `chmod +x examples/acme-catalog/items/block-secrets-read/claude/secrets.sh && uv run pytest tests/test_formats.py -v`
Expected: 10 passed.

- [ ] **Step 7: Commit**

```bash
git add examples src/harnessctl/validate.py src/harnessctl/sources tests/test_formats.py
git commit -m "feat: source formats, catalog rules and example catalog"
```

---

### Task 5: `harnessctl validate`

**Files:**
- Modify: `src/harnessctl/cli.py`
- Test: `tests/test_cli.py` (append)

**Interfaces:**
- Consumes: `validate_catalog(root) -> list[str]` (Task 4).
- Produces: `harnessctl validate <path>` — prints each problem on stderr, a summary on stdout, exit 0 when clean and 1 otherwise. `main` returns the exit code.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_cli.py`)

```python
import shutil

from tests.helpers import EXAMPLES, write


def test_validate_ok(capsys):
    assert main(["validate", str(EXAMPLES)]) == 0
    assert capsys.readouterr().out.strip() == "catalog ok: 3 items"


def test_validate_reports_problems(tmp_path, capsys):
    root = tmp_path / "cat"
    shutil.copytree(EXAMPLES, root)
    write(root / "items" / "bad" / "item.toml", 'id = "bad"\nkind = "skill"\nversion = "1.0.0"\n')
    assert main(["validate", str(root)]) == 1
    captured = capsys.readouterr()
    assert "items/bad/item.toml: a skill item needs a [skill] table" in captured.err
    assert captured.out.strip() == "1 problem found"


def test_validate_unknown_layout(tmp_path, capsys):
    assert main(["validate", str(tmp_path)]) == 1
    assert "no catalog.toml" in capsys.readouterr().err
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: the three new tests FAIL (`unrecognized arguments: validate`).

- [ ] **Step 3: Implement** — replace `build_parser` and `main` in `src/harnessctl/cli.py`:

```python
from harnessctl.validate import validate_catalog


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harnessctl",
        description="Manage skills, hooks and plugins for Claude Code and opencode.",
    )
    parser.add_argument("--version", action="version", version=f"harnessctl {__version__}")
    parser.add_argument("--project", type=Path, help="project directory (default: nearest git root)")
    sub = parser.add_subparsers(dest="command")
    check = sub.add_parser("validate", help="check a catalog checkout (use it in the catalog's CI)")
    check.add_argument("path", type=Path)
    return parser


def _validate(path: Path) -> int:
    from harnessctl.sources.formats import detect_format, load_items

    problems = validate_catalog(path)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"{len(problems)} problem{'s' if len(problems) > 1 else ''} found")
        return 1
    fmt = detect_format(path)
    items, _ = load_items(path, fmt, source="validate")
    print(f"catalog ok: {len(items)} items")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate":
        return _validate(args.path)
    return 0
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_cli.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/harnessctl/cli.py tests/test_cli.py
git commit -m "feat: harnessctl validate command"
```

---

### Task 6: Source cache (git)

**Files:**
- Create: `src/harnessctl/sources/cache.py`
- Test: `tests/test_cache.py`

**Interfaces:**
- Consumes: `SourceSpec` (Task 2), `detect_format`, `load_items` (Task 4).
- Produces: `GitError`; `SourceState(spec, status, root=None, commit=None, last_sync=None, error=None, format=None, items=[], warnings=[])` where `status` is `"ok" | "stale" | "unavailable"`; `sync_source(spec: SourceSpec, cache_root: Path, fetch: bool = True, timeout: int = 60) -> SourceState`.

- [ ] **Step 1: Write the failing tests**

`tests/test_cache.py`:

```python
import shutil

from harnessctl.model import SourceFormat, SourceSpec, Trust
from harnessctl.sources.cache import sync_source
from tests.helpers import EXAMPLES, commit_all, make_repo, write


def _spec(url, **kw):
    return SourceSpec("acme", url, Trust.CORPORATE, **kw)


def test_first_sync_clones_and_loads(tmp_path):
    repo = make_repo(EXAMPLES, tmp_path / "remote")
    state = sync_source(_spec(repo.as_uri()), tmp_path / "cache")
    assert state.status == "ok" and state.error is None
    assert state.format is SourceFormat.CATALOG
    assert len(state.items) == 3 and len(state.commit) == 40
    assert state.last_sync is not None
    assert (tmp_path / "cache" / "acme" / "catalog.toml").is_file()


def test_resync_picks_up_new_commits(tmp_path):
    repo = make_repo(EXAMPLES, tmp_path / "remote")
    first = sync_source(_spec(repo.as_uri()), tmp_path / "cache")
    shutil.rmtree(repo / "items" / "jira-context")
    commit_all(repo, "drop jira")
    second = sync_source(_spec(repo.as_uri()), tmp_path / "cache")
    assert second.commit != first.commit
    assert {i.id for i in second.items} == {"api-conventions", "block-secrets-read"}


def test_unreachable_remote_with_cache_is_stale(tmp_path):
    repo = make_repo(EXAMPLES, tmp_path / "remote")
    sync_source(_spec(repo.as_uri()), tmp_path / "cache")
    shutil.rmtree(repo)
    state = sync_source(_spec(repo.as_uri()), tmp_path / "cache")
    assert state.status == "stale"
    assert state.error
    assert len(state.items) == 3


def test_unreachable_remote_without_cache_is_unavailable(tmp_path):
    state = sync_source(_spec((tmp_path / "nowhere").as_uri()), tmp_path / "cache")
    assert state.status == "unavailable" and state.items == []
    assert state.error


def test_no_fetch_uses_cache_only(tmp_path):
    state = sync_source(_spec("file:///never/used"), tmp_path / "cache", fetch=False)
    assert state.status == "unavailable" and state.error == "not synced yet"


def test_subdir_and_unknown_layout(tmp_path):
    mono = tmp_path / "mono"
    shutil.copytree(EXAMPLES, mono / "agents" / "catalog")
    write(mono / "README.md", "monorepo")
    make_repo(None, mono)
    ok = sync_source(_spec(mono.as_uri(), subdir="agents/catalog"), tmp_path / "c1")
    assert ok.status == "ok" and len(ok.items) == 3
    bad = sync_source(_spec(mono.as_uri()), tmp_path / "c2")
    assert bad.status == "unavailable" and "no recognised catalog format" in bad.error
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/test_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harnessctl.sources.cache'`.

- [ ] **Step 3: Implement**

`src/harnessctl/sources/cache.py`:

```python
"""Shallow git checkouts of sources under ~/.cache/harnessctl/sources/<name>/."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from harnessctl.model import CatalogItem, SourceFormat, SourceSpec
from harnessctl.sources.formats import detect_format, load_items

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
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}, stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {args[0]} timed out after {timeout}s") from exc
    if result.returncode:
        raise GitError(result.stderr.strip() or f"git {args[0]} failed")
    return result.stdout.strip()


def _fetch(spec: SourceSpec, checkout: Path, timeout: int) -> None:
    if (checkout / ".git").is_dir():
        _git(["fetch", "--depth", "1", "--quiet", "origin", spec.ref or "HEAD"], cwd=checkout, timeout=timeout)
        _git(["reset", "--hard", "--quiet", "FETCH_HEAD"], cwd=checkout, timeout=timeout)
    else:
        checkout.parent.mkdir(parents=True, exist_ok=True)
        tmp = checkout.with_name(checkout.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        branch = ["--branch", spec.ref] if spec.ref else []
        _git(["clone", "--depth", "1", "--quiet", *branch, spec.url, str(tmp)], timeout=timeout)
        shutil.rmtree(checkout, ignore_errors=True)
        tmp.rename(checkout)
    (checkout / ".git" / MARKER).touch()


def sync_source(spec: SourceSpec, cache_root: Path, fetch: bool = True, timeout: int = 60) -> SourceState:
    """Fetch (optionally) and load a source. Never raises for git or format problems."""
    checkout = cache_root / spec.name
    error: str | None = None
    if fetch:
        try:
            _fetch(spec, checkout, timeout)
        except (GitError, OSError) as exc:
            error = str(exc)
    if not (checkout / ".git").is_dir():
        return SourceState(spec, "unavailable", error=error or "not synced yet")

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
    state.items, state.warnings = load_items(root, state.format, spec.name, spec.url)
    return state
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_cache.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/harnessctl/sources/cache.py tests/test_cache.py
git commit -m "feat: git source cache with stale and unavailable states"
```

---

### Task 7: Lockfiles and provenance

**Files:**
- Create: `src/harnessctl/provenance.py`
- Test: `tests/test_provenance.py`

**Interfaces:**
- Consumes: `read_json`, `JsonFileError` (Task 3); `InstalledItem`, `Provenance`, `SourceSpec`, `Trust` (Task 2).
- Produces: `LOCK_VERSION = 1`; `LockEntry(item_id, source, harness, kind, version, commit, locations: list[str], files: dict[str, str], payload_hash="", settings={})` with `to_json()` / `from_json(d)`; `read_lock(path) -> list[LockEntry]` (raises `JsonFileError`); `add_entry_edit(entry) -> Callable`; `remove_entry_edit(entry) -> Callable`; `normalize_url(url) -> str`; `resolve(item, entries, sources: dict[str, SourceSpec]) -> tuple[Provenance, LockEntry | None]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_provenance.py`:

```python
import json

import pytest

from harnessctl.jsonio import JsonFileError
from harnessctl.model import InstalledItem, Kind, Scope, SourceSpec, Trust
from harnessctl.provenance import (
    LockEntry,
    add_entry_edit,
    normalize_url,
    read_lock,
    remove_entry_edit,
    resolve,
)
from tests.helpers import write


def _entry(**kw) -> LockEntry:
    base = dict(item_id="api-conventions", source="acme", harness="claude-code", kind="skill", version="1.4.0",
                commit="a" * 40, locations=["/h/.claude/skills/api-conventions"], files={})
    return LockEntry(**(base | kw))


def _item(location="/h/.claude/skills/api-conventions", **meta) -> InstalledItem:
    return InstalledItem("claude-code", Scope.USER, Kind.SKILL, "x", location, meta=meta)


SOURCES = {
    "acme": SourceSpec("acme", "git@gitlab.acme.io:platform/agent-catalog.git", Trust.CORPORATE),
    "sp": SourceSpec("sp", "https://github.com/obra/superpowers", Trust.PUBLIC),
}


def test_read_lock_missing_is_empty(tmp_path):
    assert read_lock(tmp_path / "lock.json") == []


def test_read_lock_rejects_foreign_files(tmp_path):
    with pytest.raises(JsonFileError):
        read_lock(write(tmp_path / "lock.json", '{"version": 7, "entries": []}'))
    with pytest.raises(JsonFileError):
        read_lock(write(tmp_path / "lock2.json", '{"version": 1, "entries": [{"item_id": "x"}]}'))


def test_edits_roundtrip(tmp_path):
    data = add_entry_edit(_entry())(None)
    data = add_entry_edit(_entry(version="1.5.0"))(data)
    assert [e["version"] for e in data["entries"]] == ["1.5.0"]
    lock = write(tmp_path / "lock.json", json.dumps(data))
    assert read_lock(lock) == [_entry(version="1.5.0")]
    assert remove_entry_edit(_entry())(data)["entries"] == []


@pytest.mark.parametrize("url", [
    "git@github.com:obra/superpowers.git",
    "https://github.com/obra/superpowers",
    "https://GitHub.com/obra/superpowers.git/",
    "git+https://github.com/obra/superpowers.git",
    "ssh://git@github.com/obra/superpowers",
])
def test_normalize_url_equivalences(url):
    assert normalize_url(url) == "github.com/obra/superpowers"


def test_resolve_by_lock_entry_uses_source_trust():
    prov, entry = resolve(_item(), [_entry()], SOURCES)
    assert (prov.origin, prov.source, prov.item_id, prov.commit) == ("corp", "acme", "api-conventions", "a" * 40)
    assert entry == _entry()
    prov, _ = resolve(_item(), [_entry(source="sp")], SOURCES)
    assert prov.origin == "public"


def test_resolve_lock_entry_of_removed_source_is_unknown_but_named():
    prov, entry = resolve(_item(), [_entry(source="gone")], SOURCES)
    assert (prov.origin, prov.source) == ("unknown", "gone") and entry is not None


def test_resolve_by_repo_url():
    corp = _item("claude-plugin:x@acme", repo_url="https://gitlab.acme.io/platform/agent-catalog")
    assert resolve(corp, [], SOURCES)[0].origin == "corp"
    other = _item("claude-plugin:y@z", repo_url="https://github.com/gfargo/skills")
    prov, _ = resolve(other, [], SOURCES)
    assert (prov.origin, prov.source) == ("public", "github.com/gfargo/skills")


def test_resolve_nothing_is_unknown():
    assert resolve(_item("/h/.claude/skills/mine"), [_entry()], SOURCES)[0].origin == "unknown"


def test_resolve_ignores_other_harness_entries():
    assert resolve(_item(), [_entry(harness="opencode")], SOURCES)[0].origin == "unknown"
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/test_provenance.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harnessctl.provenance'`.

- [ ] **Step 3: Implement**

`src/harnessctl/provenance.py`:

```python
"""Lockfiles (what harnessctl installed) and provenance resolution (where an item came from)."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from harnessctl.jsonio import JsonFileError, read_json
from harnessctl.model import InstalledItem, Provenance, SourceSpec, Trust

LOCK_VERSION = 1


@dataclass
class LockEntry:
    item_id: str
    source: str
    harness: str
    kind: str
    version: str
    commit: str | None
    locations: list[str]  # InstalledItem.location values this install produced
    files: dict[str, str]  # absolute path → sha256 of what was written
    payload_hash: str = ""
    settings: dict = field(default_factory=dict)  # hook groups merged, placeholders expanded

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> LockEntry:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def read_lock(path: Path) -> list[LockEntry]:
    data = read_json(path, default={"version": LOCK_VERSION, "entries": []})
    if not isinstance(data, dict) or data.get("version") != LOCK_VERSION or not isinstance(data.get("entries"), list):
        raise JsonFileError(path, f"not a harnessctl lockfile (version {LOCK_VERSION})")
    try:
        return [LockEntry.from_json(e) for e in data["entries"]]
    except TypeError as exc:
        raise JsonFileError(path, f"invalid lock entry: {exc}") from exc


def _same(raw: dict, entry: LockEntry) -> bool:
    return (raw.get("item_id"), raw.get("source"), raw.get("harness")) == (entry.item_id, entry.source, entry.harness)


def add_entry_edit(entry: LockEntry) -> Callable[[dict | None], dict]:
    def edit(data: dict | None) -> dict:
        data = data if isinstance(data, dict) else {"version": LOCK_VERSION, "entries": []}
        data["entries"] = [e for e in data.get("entries", []) if not _same(e, entry)] + [entry.to_json()]
        return data

    return edit


def remove_entry_edit(entry: LockEntry) -> Callable[[dict | None], dict]:
    def edit(data: dict | None) -> dict:
        data = data if isinstance(data, dict) else {"version": LOCK_VERSION, "entries": []}
        data["entries"] = [e for e in data.get("entries", []) if not _same(e, entry)]
        return data

    return edit


_SCP_LIKE = re.compile(r"^[\w.-]+@([\w.-]+):(?!//)(.+)$")


def normalize_url(url: str) -> str:
    """'git@github.com:o/r.git', 'https://github.com/o/r', 'git+https://…/o/r.git' → 'github.com/o/r'."""
    u = url.strip()
    scp = _SCP_LIKE.match(u)
    if scp:
        u = f"{scp.group(1)}/{scp.group(2)}"
    else:
        u = re.sub(r"^[a-z][a-z0-9+.-]*://", "", u, flags=re.I)
        u = re.sub(r"^[^@/]+@", "", u)
    u = u.rstrip("/").removesuffix(".git").rstrip("/")
    host, _, path = u.partition("/")
    return f"{host.lower()}/{path}"


def _origin(spec: SourceSpec | None) -> str:
    if spec is None:
        return "unknown"
    return "corp" if spec.trust is Trust.CORPORATE else "public"


def resolve(
    item: InstalledItem, entries: list[LockEntry], sources: dict[str, SourceSpec]
) -> tuple[Provenance, LockEntry | None]:
    """Spec §6: lockfile first, then the item's repo URL, else unknown."""
    for entry in entries:
        if entry.harness == item.harness and item.location in entry.locations:
            return Provenance(_origin(sources.get(entry.source)), entry.source, entry.item_id, entry.commit), entry
    repo = item.meta.get("repo_url")
    if repo:
        wanted = normalize_url(repo)
        for spec in sources.values():
            if normalize_url(spec.url) == wanted:
                return Provenance(_origin(spec), spec.name), None
        return Provenance("public", wanted), None
    return Provenance.unknown(), None
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_provenance.py -v`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add src/harnessctl/provenance.py tests/test_provenance.py
git commit -m "feat: lockfiles, URL normalisation and provenance resolution"
```

---
### Task 8: Planner — steps, plans, apply with backup and rollback

**Files:**
- Create: `src/harnessctl/planner.py`
- Test: `tests/test_planner.py`

**Interfaces:**
- Consumes: `jsonio` (Task 3), `Scope` (Task 2).
- Produces: `PlanError`, `PlanConflict`; step dataclasses `WriteFile(path, content: bytes, executable=False)`, `DeletePath(path)`, `EditJson(path, edit: Callable[[Any], Any], description)`, `MovePath(src, dst)`, `RunCommand(argv: list[str], timeout=120)`, `Step` union; `step_symbol(step) -> str`, `step_label(step, home: Path | None = None) -> str`; `fingerprint(path) -> str | None`; `Plan(title, harness, scope, steps, reload_hint="", preimages={})` with `Plan.build(title, harness, scope, steps, reload_hint="") -> Plan`; `ApplyResult(ok, error=None, failed_step=None, output=[])`; `run_command(argv, timeout) -> str`; `apply(plan, backup_root, runner=run_command, keep=20) -> ApplyResult` (raises `PlanConflict`); `plan_diff(plan) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/test_planner.py`:

```python
import json
import os

import pytest

from harnessctl.model import Scope
from harnessctl.planner import (
    DeletePath,
    EditJson,
    MovePath,
    Plan,
    PlanConflict,
    PlanError,
    RunCommand,
    WriteFile,
    apply,
    plan_diff,
    step_label,
)
from tests.helpers import write


def _plan(*steps):
    return Plan.build("t", "claude-code", Scope.USER, list(steps))


def _add_key(key, value):
    def edit(data):
        data = data or {}
        data[key] = value
        return data
    return edit


def _ok_runner(argv, timeout):
    return "ran " + " ".join(argv)


def test_apply_writes_and_merges(tmp_path):
    settings = write(tmp_path / "settings.json", '{"theme": "dark", "env": {"A": "1"}}\n')
    plan = _plan(WriteFile(tmp_path / "hooks" / "x.sh", b"#!/bin/sh\n", executable=True),
                 EditJson(settings, _add_key("hooks", {}), "hooks +1"))
    result = apply(plan, tmp_path / "backups", runner=_ok_runner)
    assert result.ok, result.error
    assert os.access(tmp_path / "hooks" / "x.sh", os.X_OK)
    assert json.loads(settings.read_text()) == {"theme": "dark", "env": {"A": "1"}, "hooks": {}}
    assert list(json.loads(settings.read_text())) == ["theme", "env", "hooks"]


def test_conflict_when_file_changed_after_planning(tmp_path):
    settings = write(tmp_path / "settings.json", "{}")
    plan = _plan(WriteFile(tmp_path / "new.txt", b"x"), EditJson(settings, _add_key("a", 1), "a"))
    settings.write_text('{"agent": "wrote this"}')
    with pytest.raises(PlanConflict) as exc:
        apply(plan, tmp_path / "backups")
    assert "settings.json changed since the plan was made" in str(exc.value)
    assert not (tmp_path / "new.txt").exists()
    assert settings.read_text() == '{"agent": "wrote this"}'


def test_failure_rolls_back_every_step(tmp_path):
    existing = write(tmp_path / "keep.txt", "original")

    def failing(argv, timeout):
        raise PlanError("claude: plugin not found")

    plan = _plan(WriteFile(existing, b"changed"), WriteFile(tmp_path / "new.txt", b"x"),
                 RunCommand(["claude", "plugin", "install", "p@m"]))
    result = apply(plan, tmp_path / "backups", runner=failing)
    assert not result.ok and result.failed_step == 2
    assert result.error == "claude: plugin not found"
    assert existing.read_text() == "original"
    assert not (tmp_path / "new.txt").exists()


def test_jsonc_with_comments_is_never_rewritten(tmp_path):
    cfg = write(tmp_path / "opencode.jsonc", '{\n  // mine\n  "plugin": []\n}\n')
    before = cfg.read_bytes()
    result = apply(_plan(EditJson(cfg, _add_key("x", 1), "x")), tmp_path / "backups")
    assert not result.ok and "contains comments" in result.error
    assert cfg.read_bytes() == before


def test_unparseable_json_is_never_rewritten(tmp_path):
    cfg = write(tmp_path / "settings.json", "{broken")
    result = apply(_plan(EditJson(cfg, _add_key("x", 1), "x")), tmp_path / "backups")
    assert not result.ok and cfg.read_text() == "{broken"


def test_delete_symlink_removes_link_not_target(tmp_path):
    target = tmp_path / "real-skill"
    write(target / "SKILL.md", "x")
    link = tmp_path / "skills" / "linked"
    link.parent.mkdir()
    link.symlink_to(target)
    assert apply(_plan(DeletePath(link)), tmp_path / "backups").ok
    assert not link.is_symlink() and (target / "SKILL.md").is_file()


def test_move_and_rollback_of_directories(tmp_path):
    src = tmp_path / "skills" / "a"
    write(src / "SKILL.md", "a")
    dst = tmp_path / "parking" / "a" / "payload"

    def failing(argv, timeout):
        raise PlanError("boom")

    result = apply(_plan(MovePath(src, dst), RunCommand(["x"])), tmp_path / "backups", runner=failing)
    assert not result.ok
    assert (src / "SKILL.md").read_text() == "a" and not dst.exists()
    assert apply(_plan(MovePath(src, dst)), tmp_path / "backups").ok
    assert (dst / "SKILL.md").is_file() and not src.exists()


def test_backups_are_pruned(tmp_path):
    f = write(tmp_path / "f", "0")
    for n in range(23):
        assert apply(_plan(WriteFile(f, str(n).encode())), tmp_path / "backups", keep=20).ok
    assert len(list((tmp_path / "backups").iterdir())) == 20


def test_plan_diff_and_labels(tmp_path):
    settings = write(tmp_path / "settings.json", '{"a": 1}\n')
    plan = _plan(EditJson(settings, _add_key("b", 2), "b"), WriteFile(tmp_path / "n.txt", b"hello\n"))
    diff = plan_diff(plan)
    assert '+  "b": 2' in diff and "+hello" in diff
    assert step_label(plan.steps[1], home=tmp_path) == "write  ~/n.txt"
    assert step_label(RunCommand(["claude", "plugin", "install", "a b"])) == "run    claude plugin install 'a b'"
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/test_planner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harnessctl.planner'`.

- [ ] **Step 3: Implement**

`src/harnessctl/planner.py`:

```python
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


def _touched(step: Step) -> list[Path]:
    match step:
        case MovePath(src=s, dst=d):
            return [s, d]
        case RunCommand():
            return []
        case _:
            return [step.path]


def fingerprint(path: Path) -> str | None:
    """Content identity of a file, folder or symlink; None if nothing is there."""
    if path.is_symlink():
        return "link:" + os.readlink(path)
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
    preimages: dict[Path, str | None] = field(default_factory=dict)

    @classmethod
    def build(cls, title: str, harness: str, scope: Scope, steps: list[Step], reload_hint: str = "") -> Plan:
        plan = cls(title, harness, scope, list(steps), reload_hint)
        plan.preimages = {p: fingerprint(p) for s in plan.steps for p in _touched(s)}
        return plan


@dataclass
class ApplyResult:
    ok: bool
    error: str | None = None
    failed_step: int | None = None  # index into plan.steps
    output: list[str] = field(default_factory=list)


def run_command(argv: list[str], timeout: int) -> str:
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise PlanError(f"{argv[0]}: command not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise PlanError(f"{shlex.join(argv)} timed out after {timeout}s") from exc
    if result.returncode:
        raise PlanError((result.stderr or result.stdout).strip() or f"{argv[0]} exited with {result.returncode}")
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
    text = step.path.read_text() if step.path.exists() else None
    if text is not None and has_comments(text):
        raise PlanError(f"{step.path} contains comments, which harnessctl will not rewrite")
    try:
        data = loads_jsonc(text) if text is not None and text.strip() else None
    except ValueError as exc:
        raise PlanError(f"{step.path} is not valid JSON: {exc}") from exc
    new = step.edit(copy.deepcopy(data))
    _write_atomic(step.path, dumps(new).encode(), like=step.path)


def _run(step: Step, runner: Callable[[list[str], int], str]) -> str:
    match step:
        case WriteFile(path=p, content=c, executable=x):
            _write_atomic(p, c, like=p)
            if x:
                p.chmod(p.stat().st_mode | 0o111)
        case DeletePath(path=p):
            _remove(p)
        case EditJson():
            _edit_json(step)
        case MovePath(src=s, dst=d):
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(s, d)
        case RunCommand(argv=argv, timeout=t):
            return runner(argv, t)
    return ""


def _prune(backup_root: Path, keep: int) -> None:
    runs = sorted(p for p in backup_root.iterdir() if p.is_dir())
    for old in runs[:-keep]:
        shutil.rmtree(old, ignore_errors=True)


def apply(plan: Plan, backup_root: Path, runner: Callable[[list[str], int], str] = run_command,
          keep: int = 20) -> ApplyResult:
    changed = [p for p, fp in plan.preimages.items() if fingerprint(p) != fp]
    if changed:
        raise PlanConflict(f"{changed[0].name} changed since the plan was made ({changed[0]}) — re-plan?")

    backup = backup_root / datetime.now().strftime("%Y%m%dT%H%M%S%f")
    backup.mkdir(parents=True, mode=0o700)
    saved: dict[Path, Path | None] = {}
    for n, path in enumerate(plan.preimages):
        if path.exists() or path.is_symlink():
            _copy(path, backup / str(n))
            saved[path] = backup / str(n)
        else:
            saved[path] = None

    output: list[str] = []
    for n, step in enumerate(plan.steps):
        try:
            out = _run(step, runner)
        except Exception as exc:  # noqa: BLE001 - any failure rolls the whole plan back
            for path, copy_ in saved.items():
                _remove(path)
                if copy_ is not None:
                    _copy(copy_, path)
            return ApplyResult(False, error=str(exc), failed_step=n, output=output)
        if out:
            output.append(out)
    _prune(backup_root, keep)
    return ApplyResult(True, output=output)


def plan_diff(plan: Plan) -> str:
    """Unified diff of every file the plan writes or edits, against what is on disk now."""
    chunks: list[str] = []
    for step in plan.steps:
        if isinstance(step, WriteFile):
            old = step.path.read_text(errors="replace") if step.path.is_file() else ""
            new = step.content.decode(errors="replace")
        elif isinstance(step, EditJson):
            old = step.path.read_text() if step.path.is_file() else ""
            try:
                new = dumps(step.edit(copy.deepcopy(loads_jsonc(old) if old.strip() else None)))
            except Exception as exc:  # noqa: BLE001 - a preview must never crash the UI
                new = f"<cannot preview: {exc}>\n"
        else:
            continue
        chunks.extend(difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True), f"a{step.path}", f"b{step.path}"))
    return "".join(chunks) or "(no file contents change)\n"
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_planner.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/harnessctl/planner.py tests/test_planner.py
git commit -m "feat: planner with hash check, backup and rollback"
```

---

### Task 9: JSON edits, parking and shared adapter helpers

**Files:**
- Create: `src/harnessctl/edits.py`, `src/harnessctl/parking.py`, `src/harnessctl/adapters/__init__.py` (empty), `src/harnessctl/adapters/base.py`
- Test: `tests/test_edits.py`, `tests/test_adapter_base.py`

**Interfaces:**
- Consumes: planner steps (Task 8), `read_frontmatter` (Task 4), `jsonio` (Task 3).
- Produces (`edits`): `hook_location(settings, event, command) -> str`, `plugin_location(config, spec) -> str`, `expand_placeholders(value, scope_dir) -> Any`, `merge_hooks_edit(hooks: dict)`, `remove_hooks_edit(event, command)`, `add_plugin_spec_edit(spec)`, `remove_plugin_spec_edit(spec)`, `plugin_spec_name(spec) -> str`.
- Produces (`parking`): `park_dir(parking, harness, location, name) -> Path`, `park_steps(inst, pdir, scope_dir, restore: dict, first: list[Step]) -> list[Step]`, `scan_parked(parking, harness, scope, scope_dir) -> list[InstalledItem]`, `unpark_steps(inst) -> list[Step]`.
- Produces (`adapters.base`): `Adapter` Protocol (spec §3, with `reload_hint`, `watched_paths(project)`, `plan_install(item, scope, project, replace=False) -> Install`, `plan_remove(inst, project) -> list[Step]`, `plan_toggle(inst, project) -> list[Step]`); `Install(steps, locations, files, settings={})`; `safe_join(root, rel) -> Path`; `ensure_json_writable(path, manual="")`; `install_skill(src, dest, replace=False) -> Install`; `write_payload_files(files, scope_dir, replace) -> tuple[list[Step], dict[str, str]]`; `scan_skill_dirs(folder, harness, scope, readonly=None) -> list[InstalledItem]`; `require_writable(inst)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_edits.py`:

```python
from pathlib import Path

from harnessctl.edits import (
    add_plugin_spec_edit,
    expand_placeholders,
    merge_hooks_edit,
    plugin_spec_name,
    remove_hooks_edit,
    remove_plugin_spec_edit,
)

THEIRS = {"theme": "dark", "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "mine.sh"}]}]}}
OURS = {"PreToolUse": [{"matcher": "Read", "hooks": [{"type": "command", "command": "/h/.claude/hooks/x.sh"}]}],
        "Stop": [{"hooks": [{"type": "command", "command": "/h/.claude/hooks/x.sh"}]}]}


def _copy(d):
    import copy
    return copy.deepcopy(d)


def test_merge_hooks_keeps_foreign_entries():
    data = merge_hooks_edit(OURS)(_copy(THEIRS))
    assert data["theme"] == "dark"
    assert [g["matcher"] for g in data["hooks"]["PreToolUse"]] == ["Bash", "Read"]
    assert data["hooks"]["Stop"] == OURS["Stop"]


def test_merge_into_missing_file():
    assert merge_hooks_edit(OURS)(None) == {"hooks": OURS}


def test_remove_hooks_only_removes_ours_and_prunes_empties():
    data = merge_hooks_edit(OURS)(_copy(THEIRS))
    data = remove_hooks_edit("PreToolUse", "/h/.claude/hooks/x.sh")(data)
    data = remove_hooks_edit("Stop", "/h/.claude/hooks/x.sh")(data)
    assert data == THEIRS
    data = remove_hooks_edit("PreToolUse", "mine.sh")(data)
    assert data == {"theme": "dark"}


def test_plugin_spec_edits():
    data = add_plugin_spec_edit("@acme/jira@1.2.0")(None)
    assert data == {"$schema": "https://opencode.ai/config.json", "plugin": ["@acme/jira@1.2.0"]}
    data = add_plugin_spec_edit("@acme/jira@1.2.0")(data)
    assert data["plugin"] == ["@acme/jira@1.2.0"]
    data["plugin"].append(["opencode-bar", {"k": "v"}])
    data = remove_plugin_spec_edit("opencode-bar")(data)
    assert data["plugin"] == ["@acme/jira@1.2.0"]


def test_plugin_spec_name():
    assert plugin_spec_name("superpowers@git+https://github.com/obra/superpowers.git") == "superpowers"
    assert plugin_spec_name("@acme/opencode-jira@1.2.0") == "@acme/opencode-jira"
    assert plugin_spec_name("opencode-foo") == "opencode-foo"


def test_expand_placeholders():
    value = {"a": ["{scope_dir}/x.sh", 3], "b": "{scope_dir}"}
    assert expand_placeholders(value, Path("/h/.claude")) == {"a": ["/h/.claude/x.sh", 3], "b": "/h/.claude"}
```

`tests/test_adapter_base.py`:

```python
import pytest

from harnessctl.adapters.base import (
    ensure_json_writable,
    install_skill,
    safe_join,
    scan_skill_dirs,
    write_payload_files,
)
from harnessctl.model import InstalledItem, Kind, Scope
from harnessctl.parking import park_dir, park_steps, scan_parked, unpark_steps
from harnessctl.planner import MovePath, Plan, PlanError, WriteFile, apply
from tests.helpers import skill, write


def test_safe_join_rejects_escapes(tmp_path):
    assert safe_join(tmp_path, "hooks/x.sh") == tmp_path / "hooks" / "x.sh"
    for bad in ("../x", "/etc/passwd", "a/../../x"):
        with pytest.raises(PlanError):
            safe_join(tmp_path, bad)


def test_ensure_json_writable(tmp_path):
    ensure_json_writable(tmp_path / "missing.json")
    ensure_json_writable(write(tmp_path / "ok.json", '{"a": 1}'))
    with pytest.raises(PlanError) as exc:
        ensure_json_writable(write(tmp_path / "c.jsonc", '{// x\n}'), manual='add "p" to its plugin array')
    assert "contains comments" in str(exc.value) and 'add "p" to its plugin array' in str(exc.value)
    with pytest.raises(PlanError):
        ensure_json_writable(write(tmp_path / "bad.json", "{"))


def test_install_skill_writes_every_file(tmp_path):
    src = tmp_path / "src" / "tdd"
    skill(src)
    write(src / "refs" / "notes.md", "n")
    inst = install_skill(src, tmp_path / "skills" / "tdd")
    assert [type(s) for s in inst.steps] == [WriteFile, WriteFile]
    assert inst.locations == [str(tmp_path / "skills" / "tdd")]
    assert set(inst.files) == {str(tmp_path / "skills/tdd/SKILL.md"), str(tmp_path / "skills/tdd/refs/notes.md")}
    skill(tmp_path / "skills" / "tdd")
    with pytest.raises(PlanError):
        install_skill(src, tmp_path / "skills" / "tdd")
    assert install_skill(src, tmp_path / "skills" / "tdd", replace=True).steps


def test_write_payload_files_refuses_overwrite(tmp_path):
    src = write(tmp_path / "item" / "x.sh", "#!/bin/sh\n")
    steps, hashes = write_payload_files([(src, "hooks/x.sh")], tmp_path / "scope", replace=False)
    assert steps[0].path == tmp_path / "scope" / "hooks" / "x.sh" and len(hashes) == 1
    write(tmp_path / "scope" / "hooks" / "x.sh", "other")
    with pytest.raises(PlanError):
        write_payload_files([(src, "hooks/x.sh")], tmp_path / "scope", replace=False)


def test_scan_skill_dirs(tmp_path):
    skill(tmp_path / "skills" / "good", description="Does good things", body="# Good")
    write(tmp_path / "skills" / "plain" / "SKILL.md", "no frontmatter")
    (tmp_path / "skills" / "empty").mkdir()
    write(tmp_path / "skills" / "file.txt", "x")
    items = scan_skill_dirs(tmp_path / "skills", "claude-code", Scope.USER)
    assert [i.name for i in items] == ["good", "plain"]
    assert items[0].meta["description"] == "Does good things" and "# Good" in items[0].detail
    assert items[1].meta["description"] == "(no description)"
    assert scan_skill_dirs(tmp_path / "nope", "claude-code", Scope.USER) == []


def test_park_and_unpark_a_skill(tmp_path):
    scope_dir = tmp_path / ".claude"
    folder = scope_dir / "skills" / "tdd"
    skill(folder)
    inst = InstalledItem("claude-code", Scope.USER, Kind.SKILL, "tdd", str(folder), detail="d")
    parking = tmp_path / "disabled"
    pdir = park_dir(parking, "claude-code", inst.location, inst.name)
    steps = park_steps(inst, pdir, scope_dir, {"type": "move", "to": inst.location},
                       [MovePath(folder, pdir / "payload")])
    assert apply(Plan.build("park", "claude-code", Scope.USER, steps), tmp_path / "b").ok
    assert not folder.exists()

    parked = scan_parked(parking, "claude-code", Scope.USER, scope_dir)
    assert len(parked) == 1 and parked[0].enabled is False and parked[0].location == str(folder)
    assert scan_parked(parking, "claude-code", Scope.PROJECT, tmp_path / "other") == []

    assert apply(Plan.build("unpark", "claude-code", Scope.USER, unpark_steps(parked[0])), tmp_path / "b").ok
    assert (folder / "SKILL.md").is_file() and not pdir.exists()
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/test_edits.py tests/test_adapter_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harnessctl.edits'`.

- [ ] **Step 3: Implement `edits.py`**

`src/harnessctl/edits.py`:

```python
"""Pure edit functions for the JSON files harnessctl changes, and the location keys it uses."""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

OPENCODE_SCHEMA = "https://opencode.ai/config.json"


def hook_location(settings: Path, event: str, command: str) -> str:
    return f"{settings}::{event}::{command}"


def plugin_location(config: Path, spec: str) -> str:
    return f"{config}::plugin::{spec}"


def expand_placeholders(value: Any, scope_dir: Path) -> Any:
    match value:
        case str():
            return value.replace("{scope_dir}", str(scope_dir))
        case dict():
            return {k: expand_placeholders(v, scope_dir) for k, v in value.items()}
        case list():
            return [expand_placeholders(v, scope_dir) for v in value]
    return value


def merge_hooks_edit(hooks: dict) -> Callable[[Any], dict]:
    """Append our matcher groups to each event; never replace or reorder existing entries."""

    def edit(data: Any) -> dict:
        data = data if isinstance(data, dict) else {}
        target = data.setdefault("hooks", {})
        for event, groups in hooks.items():
            target.setdefault(event, []).extend(copy.deepcopy(groups))
        return data

    return edit


def remove_hooks_edit(event: str, command: str) -> Callable[[Any], dict]:
    """Drop hooks running `command` under `event`; drop groups, events and `hooks` left empty."""

    def edit(data: Any) -> dict:
        data = data if isinstance(data, dict) else {}
        hooks = data.get("hooks", {})
        groups = hooks.get(event, [])
        for group in groups:
            group["hooks"] = [h for h in group.get("hooks", []) if h.get("command") != command]
        groups[:] = [g for g in groups if g.get("hooks")]
        if not groups:
            hooks.pop(event, None)
        if not hooks:
            data.pop("hooks", None)
        return data

    return edit


def _spec_of(entry: Any) -> Any:
    return entry[0] if isinstance(entry, list) and entry else entry


def add_plugin_spec_edit(spec: str) -> Callable[[Any], dict]:
    def edit(data: Any) -> dict:
        data = data if isinstance(data, dict) else {"$schema": OPENCODE_SCHEMA}
        plugins = data.setdefault("plugin", [])
        if spec not in [_spec_of(p) for p in plugins]:
            plugins.append(spec)
        return data

    return edit


def remove_plugin_spec_edit(spec: str) -> Callable[[Any], dict]:
    def edit(data: Any) -> dict:
        data = data if isinstance(data, dict) else {}
        data["plugin"] = [p for p in data.get("plugin", []) if _spec_of(p) != spec]
        return data

    return edit


def plugin_spec_name(spec: str) -> str:
    """'@acme/jira@1.2.0' → '@acme/jira'; 'superpowers@git+https://…' → 'superpowers'."""
    if spec.startswith("@"):
        return "@" + spec[1:].split("@", 1)[0]
    return spec.split("@", 1)[0]
```

- [ ] **Step 4: Implement `adapters/base.py`**

`src/harnessctl/adapters/base.py`:

```python
"""The adapter contract and helpers shared by the Claude Code and opencode adapters."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from harnessctl.jsonio import JsonFileError, has_comments, read_json, sha256_bytes
from harnessctl.model import CatalogItem, InstalledItem, Kind, Scope
from harnessctl.planner import PlanError, Step, WriteFile
from harnessctl.sources.formats import read_frontmatter


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
    def plan_install(self, item: CatalogItem, scope: Scope, project: Path | None, replace: bool = False) -> Install: ...
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
    if has_comments(path.read_text()):
        raise PlanError(f"{path} contains comments, which harnessctl will not rewrite.{hint}")
    try:
        read_json(path)
    except JsonFileError as exc:
        raise PlanError(f"{exc}. Fix the file first.") from exc


def require_writable(inst: InstalledItem) -> None:
    if inst.readonly:
        raise PlanError(f"{inst.name}: {inst.readonly}")


def write_payload_files(files: list[tuple[Path, str]], scope_dir: Path, replace: bool) -> tuple[list[Step], dict[str, str]]:
    steps: list[Step] = []
    hashes: dict[str, str] = {}
    for src, dest in files:
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
    steps, hashes = write_payload_files(files, dest, replace=True)
    return Install(steps, [str(dest)], hashes)


def scan_skill_dirs(folder: Path, harness: str, scope: Scope, readonly: str | None = None) -> list[InstalledItem]:
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
        items.append(InstalledItem(
            harness=harness, scope=scope, kind=Kind.SKILL, name=d.name, location=str(d),
            detail=body, readonly=readonly,
            meta={"description": description, "symlink": d.is_symlink()},
        ))
    return items
```

- [ ] **Step 5: Implement `parking.py`**

`src/harnessctl/parking.py`:

```python
"""Disabling items that have no native off switch, by parking them under ~/.local/state/harnessctl/disabled/."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from harnessctl.edits import add_plugin_spec_edit, merge_hooks_edit
from harnessctl.jsonio import dumps
from harnessctl.model import InstalledItem, Kind, Scope
from harnessctl.planner import DeletePath, EditJson, MovePath, Step, WriteFile


def park_dir(parking: Path, harness: str, location: str, name: str) -> Path:
    digest = hashlib.sha1(location.encode()).hexdigest()[:10]
    safe = name.replace("/", "_").lstrip("@.")
    return parking / harness / f"{safe}-{digest}"


def park_steps(inst: InstalledItem, pdir: Path, scope_dir: Path, restore: dict, first: list[Step]) -> list[Step]:
    """`first` takes the item out of service; then its metadata is recorded in the parking folder."""
    meta = {
        "name": inst.name, "kind": inst.kind.value, "scope": inst.scope.value, "scope_dir": str(scope_dir),
        "location": inst.location, "detail": inst.detail, "restore": restore,
        "meta": {k: v for k, v in inst.meta.items() if isinstance(v, (str, int, float, bool, type(None)))},
    }
    return [*first, WriteFile(pdir / "meta.json", dumps(meta).encode())]


def scan_parked(parking: Path, harness: str, scope: Scope, scope_dir: Path) -> list[InstalledItem]:
    items: list[InstalledItem] = []
    for meta_file in sorted((parking / harness).glob("*/meta.json")):
        try:
            meta = json.loads(meta_file.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get("scope_dir") != str(scope_dir) or meta.get("scope") != scope.value:
            continue
        items.append(InstalledItem(
            harness=harness, scope=scope, kind=Kind(meta["kind"]), name=meta["name"], location=meta["location"],
            enabled=False, detail=meta.get("detail", ""),
            meta={**meta.get("meta", {}), "park_dir": str(meta_file.parent), "restore": meta["restore"]},
        ))
    return items


def unpark_steps(inst: InstalledItem) -> list[Step]:
    pdir = Path(inst.meta["park_dir"])
    restore = inst.meta["restore"]
    match restore["type"]:
        case "move":
            steps: list[Step] = [MovePath(pdir / "payload", Path(restore["to"]))]
        case "hook":
            group = {"hooks": [restore["hook"]]}
            if restore.get("matcher"):
                group = {"matcher": restore["matcher"], **group}
            steps = [EditJson(Path(restore["settings"]), merge_hooks_edit({restore["event"]: [group]}),
                              f"hooks +1 ({restore['event']}, restored)")]
        case "npm":
            steps = [EditJson(Path(restore["config"]), add_plugin_spec_edit(restore["spec"]),
                              f"plugin +{restore['spec']} (restored)")]
        case other:
            raise ValueError(f"unknown parking type {other!r}")
    return [*steps, DeletePath(pdir)]
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_edits.py tests/test_adapter_base.py -v`
Expected: 12 passed.

- [ ] **Step 7: Commit**

```bash
git add src/harnessctl/edits.py src/harnessctl/parking.py src/harnessctl/adapters tests/test_edits.py tests/test_adapter_base.py
git commit -m "feat: JSON edits, parking and shared adapter helpers"
```

---

### Task 10: Claude Code adapter — scanning

**Files:**
- Create: `src/harnessctl/adapters/claude_code.py`
- Test: `tests/test_claude_scan.py`

**Interfaces:**
- Consumes: `base` helpers, `parking.scan_parked`, `edits.hook_location` (Task 9), `read_json` (Task 3).
- Produces: `ClaudeCodeAdapter(home: Path, parking: Path, which=shutil.which)` with `id = "claude-code"`, `label = "Claude Code"`, `reload_hint`, `detect()`, `scope_dir(scope, project)`, `settings_path(scope, project)`, `scan(scope, project)`, `watched_paths(project)`. Items produced: skills (`location` = folder path), hooks (`location` = `hook_location(...)`, `meta` keys `event, matcher, command, hook, settings`), plugins (`location` = `"claude-plugin:<id>"`, `meta` keys `plugin_id, version, install_path, repo_url?`), plugin children (`parent` = plugin id, readonly), synced skills (readonly), parked items (disabled), broken files (`status=BROKEN`, readonly).

- [ ] **Step 1: Write the failing tests**

`tests/test_claude_scan.py`:

```python
import json

import pytest

from harnessctl.adapters.claude_code import ClaudeCodeAdapter
from harnessctl.model import Kind, Scope, Status
from tests.helpers import skill, write


@pytest.fixture
def claude(env):
    home = env.home
    skill(home / ".claude" / "skills" / "my-notes", description="Personal notes")
    skill(home / ".claude" / "skills" / "synced" / "bucket-1" / "pdf", description="PDF tools")
    write(home / ".claude" / "settings.json", json.dumps({
        "enabledPlugins": {"superpowers@claude-plugins-official": True},
        "hooks": {"PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "~/bin/fmt.sh --all", "timeout": 5}]}]},
    }))
    plugin_dir = home / ".claude" / "plugins" / "cache" / "official" / "superpowers" / "6.4.1"
    skill(plugin_dir / "skills" / "brainstorming")
    write(plugin_dir / ".claude-plugin" / "plugin.json", json.dumps({"description": "Core skills"}))
    write(plugin_dir / "hooks" / "hooks.json", json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "run-hook.cmd"}]}]}}))
    write(home / ".claude" / "plugins" / "installed_plugins.json", json.dumps({"version": 2, "plugins": {
        "superpowers@claude-plugins-official": [{"scope": "user", "installPath": str(plugin_dir), "version": "6.4.1"}],
        "terminal@gfargo-skills": [{"scope": "project", "projectPath": str(env.project), "installPath": str(home / "nope")}],
        "other@gfargo-skills": [{"scope": "project", "projectPath": "/somewhere/else", "installPath": "/x"}],
    }}))
    write(home / ".claude" / "plugins" / "known_marketplaces.json", json.dumps({
        "claude-plugins-official": {"source": {"source": "github", "repo": "anthropics/claude-plugins-official"}},
        "gfargo-skills": {"source": {"source": "git", "url": "https://github.com/gfargo/skills.git"}},
    }))
    skill(env.project / ".claude" / "skills" / "api-conventions")
    write(env.project / ".claude" / "settings.json", json.dumps({"enabledPlugins": {"terminal@gfargo-skills": True}}))
    write(env.project / ".claude" / "settings.local.json", json.dumps({
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "notify-send done"}]}]}}))
    return ClaudeCodeAdapter(env.home, env.paths.parking)


def _by_name(items):
    return {i.name: i for i in items}


def test_user_scope(claude, env):
    items = _by_name(claude.scan(Scope.USER, env.project))
    assert items["my-notes"].kind is Kind.SKILL and items["my-notes"].readonly is None
    assert items["pdf"].readonly == "synced by Claude from claude.ai"

    hook = items["PostToolUse:fmt.sh"]
    assert hook.kind is Kind.HOOK
    assert hook.location == f"{env.home}/.claude/settings.json::PostToolUse::~/bin/fmt.sh --all"
    assert hook.meta["matcher"] == "Edit" and hook.meta["hook"]["timeout"] == 5

    plugin = items["superpowers"]
    assert plugin.location == "claude-plugin:superpowers@claude-plugins-official"
    assert plugin.enabled is True
    assert plugin.meta["repo_url"] == "https://github.com/anthropics/claude-plugins-official"
    assert "Core skills" in plugin.detail

    child = items["brainstorming"]
    assert child.parent == "superpowers@claude-plugins-official" and child.readonly == "part of plugin superpowers"
    plugin_hook = items["SessionStart:run-hook.cmd"]
    assert plugin_hook.parent == "superpowers@claude-plugins-official"


def test_project_and_local_scopes(claude, env):
    project = _by_name(claude.scan(Scope.PROJECT, env.project))
    assert set(project) == {"api-conventions", "terminal"}
    assert project["terminal"].meta["repo_url"] == "https://github.com/gfargo/skills.git"
    local = claude.scan(Scope.LOCAL, env.project)
    assert [(i.name, i.readonly) for i in local] == [("Stop:notify-send", "local scope is read-only")]


def test_no_project_means_user_scope_only(claude):
    assert claude.scan(Scope.PROJECT, None) == []
    assert claude.scan(Scope.LOCAL, None) == []


def test_broken_settings_is_reported(claude, env):
    write(env.home / ".claude" / "settings.json", "{oops")
    items = claude.scan(Scope.USER, env.project)
    broken = [i for i in items if i.status is Status.BROKEN]
    assert broken and broken[0].readonly == "the file cannot be parsed"
    assert "settings.json" in broken[0].error
    assert "my-notes" in _by_name(items)  # the rest of the scan still works


def test_skill_with_bad_frontmatter_still_listed(claude, env):
    write(env.home / ".claude" / "skills" / "weird" / "SKILL.md", "---\n: : :\n---\n")
    weird = _by_name(claude.scan(Scope.USER, env.project))["weird"]
    assert weird.meta["description"] == "(no description)"


def test_detect_and_watched_paths(claude, env):
    assert claude.detect() is True
    paths = claude.watched_paths(env.project)
    assert env.home / ".claude" / "settings.json" in paths
    assert env.project / ".claude" / "settings.local.json" in paths
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/test_claude_scan.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harnessctl.adapters.claude_code'`.

- [ ] **Step 3: Implement scanning**

`src/harnessctl/adapters/claude_code.py`:

```python
"""Claude Code: skills in .claude/skills, hooks in settings.json, plugins via the `claude plugin` CLI."""

from __future__ import annotations

import shlex
import shutil
from collections.abc import Callable
from pathlib import Path

from harnessctl.adapters.base import scan_skill_dirs
from harnessctl.edits import hook_location
from harnessctl.jsonio import JsonFileError, read_json
from harnessctl.model import InstalledItem, Kind, Scope, Status
from harnessctl.parking import scan_parked
from harnessctl.planner import PlanError


def _command_name(command: str) -> str:
    try:
        first = shlex.split(command)[0]
    except (ValueError, IndexError):
        first = command
    return Path(first).name or command[:24]


def _market_url(source: dict) -> str | None:
    match source.get("source"):
        case "github" if source.get("repo"):
            return f"https://github.com/{source['repo']}"
        case "git" | "url":
            return source.get("url")
    return None


class ClaudeCodeAdapter:
    id = "claude-code"
    label = "Claude Code"
    reload_hint = "Restart Claude Code (or run /hooks or /plugin) to pick up the change."

    def __init__(self, home: Path, parking: Path, which: Callable[[str], str | None] = shutil.which):
        self.home = home
        self.claude_dir = home / ".claude"
        self.parking = parking
        self._which = which

    # --- locations ---------------------------------------------------------------------------

    def detect(self) -> bool:
        return self.claude_dir.is_dir() or self._which("claude") is not None

    def scope_dir(self, scope: Scope, project: Path | None) -> Path:
        if scope is Scope.USER:
            return self.claude_dir
        if project is None:
            raise PlanError("no project here: only user scope is available")
        return project / ".claude"

    def settings_path(self, scope: Scope, project: Path | None) -> Path:
        if scope is Scope.LOCAL:
            return self.scope_dir(Scope.PROJECT, project) / "settings.local.json"
        return self.scope_dir(scope, project) / "settings.json"

    def watched_paths(self, project: Path | None) -> list[Path]:
        paths = [self.claude_dir / "settings.json", self.claude_dir / "skills",
                 self.claude_dir / "plugins" / "installed_plugins.json", self.parking / self.id]
        if project is not None:
            pd = project / ".claude"
            paths += [pd / "settings.json", pd / "settings.local.json", pd / "skills"]
        return paths

    # --- scanning ----------------------------------------------------------------------------

    def scan(self, scope: Scope, project: Path | None) -> list[InstalledItem]:
        if scope is not Scope.USER and project is None:
            return []
        if scope is Scope.LOCAL:
            return self._scan_hooks(scope, project)
        scope_dir = self.scope_dir(scope, project)
        items = scan_skill_dirs(scope_dir / "skills", self.id, scope)
        if scope is Scope.USER:
            for bucket in sorted((scope_dir / "skills" / "synced").glob("*/")):
                items += scan_skill_dirs(bucket, self.id, scope, readonly="synced by Claude from claude.ai")
        items += self._scan_hooks(scope, project)
        items += self._scan_plugins(scope, project)
        items += scan_parked(self.parking, self.id, scope, scope_dir)
        return items

    def _broken(self, scope: Scope, path: Path, kind: Kind, exc: Exception) -> InstalledItem:
        return InstalledItem(self.id, scope, kind, path.name, str(path), status=Status.BROKEN,
                             error=str(exc), readonly="the file cannot be parsed")

    def _hooks_from(self, settings: dict, path: Path, scope: Scope, readonly: str | None,
                    parent: str | None = None) -> list[InstalledItem]:
        items: list[InstalledItem] = []
        hooks = settings.get("hooks") if isinstance(settings, dict) else None
        for event, groups in (hooks or {}).items():
            for group in groups if isinstance(groups, list) else []:
                if not isinstance(group, dict):
                    continue
                for hook in group.get("hooks", []):
                    command = hook.get("command") if isinstance(hook, dict) else None
                    if not isinstance(command, str):
                        continue
                    matcher = group.get("matcher")
                    detail = f"**{event}**" + (f" · matcher `{matcher}`" if matcher else "") + f"\n\n```\n{command}\n```"
                    items.append(InstalledItem(
                        self.id, scope, Kind.HOOK, f"{event}:{_command_name(command)}",
                        hook_location(path, event, command), parent=parent, detail=detail, readonly=readonly,
                        meta={"event": event, "matcher": matcher, "command": command, "hook": hook,
                              "settings": str(path)},
                    ))
        return items

    def _scan_hooks(self, scope: Scope, project: Path | None) -> list[InstalledItem]:
        path = self.settings_path(scope, project)
        try:
            settings = read_json(path, default={})
        except JsonFileError as exc:
            return [self._broken(scope, path, Kind.HOOK, exc)]
        if not isinstance(settings, dict):
            return [self._broken(scope, path, Kind.HOOK, ValueError(f"{path}: not a JSON object"))]
        readonly = "local scope is read-only" if scope is Scope.LOCAL else None
        return self._hooks_from(settings, path, scope, readonly)

    def _scan_plugins(self, scope: Scope, project: Path | None) -> list[InstalledItem]:
        plugins_dir = self.claude_dir / "plugins"
        try:
            installed = read_json(plugins_dir / "installed_plugins.json", default={}).get("plugins", {})
            markets = read_json(plugins_dir / "known_marketplaces.json", default={})
        except (JsonFileError, AttributeError) as exc:
            return [self._broken(scope, plugins_dir / "installed_plugins.json", Kind.PLUGIN, exc)]
        try:
            enabled = read_json(self.settings_path(scope, project), default={}).get("enabledPlugins", {})
        except (JsonFileError, AttributeError):
            enabled = {}  # the settings file itself is reported by _scan_hooks
        items: list[InstalledItem] = []
        for pid, records in sorted(installed.items()):
            for rec in records if isinstance(records, list) else []:
                if rec.get("scope") != scope.value:
                    continue
                if scope is Scope.PROJECT and Path(rec.get("projectPath", "")) != project:
                    continue
                items += self._plugin_items(pid, rec, scope, bool(enabled.get(pid, False)), markets)
        return items

    def _plugin_items(self, pid: str, rec: dict, scope: Scope, on: bool, markets: dict) -> list[InstalledItem]:
        name, _, market = pid.partition("@")
        install_path = Path(rec.get("installPath", ""))
        meta = {"plugin_id": pid, "version": rec.get("version"), "install_path": str(install_path)}
        repo = _market_url(markets.get(market, {}).get("source", {}))
        if repo:
            meta["repo_url"] = repo
        try:
            manifest = read_json(install_path / ".claude-plugin" / "plugin.json", default={})
        except JsonFileError:
            manifest = {}
        detail = f"{manifest.get('description', '')}\n\n`{pid}` · version {rec.get('version', '?')}".strip()
        plugin = InstalledItem(self.id, scope, Kind.PLUGIN, name, f"claude-plugin:{pid}", enabled=on,
                               detail=detail, meta=meta)
        children = scan_skill_dirs(install_path / "skills", self.id, scope, readonly=f"part of plugin {name}")
        try:
            hooks = read_json(install_path / "hooks" / "hooks.json", default={})
        except JsonFileError:
            hooks = {}
        children += self._hooks_from(hooks, install_path / "hooks" / "hooks.json", scope,
                                     readonly=f"part of plugin {name}", parent=pid)
        for child in children:
            child.parent = pid
            child.enabled = on
        return [plugin, *children]
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_claude_scan.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/harnessctl/adapters/claude_code.py tests/test_claude_scan.py
git commit -m "feat: Claude Code adapter scanning"
```

---

### Task 11: Claude Code adapter — install, remove, enable/disable

**Files:**
- Modify: `src/harnessctl/adapters/claude_code.py` (add methods)
- Test: `tests/test_claude_plans.py`

**Interfaces:**
- Consumes: `Install`, `install_skill`, `write_payload_files`, `ensure_json_writable`, `require_writable` (Task 9); `merge_hooks_edit`, `remove_hooks_edit`, `expand_placeholders`, `hook_location` (Task 9); `park_dir`, `park_steps`, `unpark_steps` (Task 9).
- Produces: `ClaudeCodeAdapter.plan_install(item, scope, project, replace=False) -> Install`, `.plan_remove(inst, project) -> list[Step]`, `.plan_toggle(inst, project) -> list[Step]`. Claude CLI argv exactly: `["claude", "plugin", "marketplace", "add", url]`, `["claude", "plugin", "install", id, "--scope", scope]`, `["claude", "plugin", "uninstall", id, "--scope", scope]`, `["claude", "plugin", "enable"|"disable", id, "--scope", scope]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_claude_plans.py`:

```python
import json

import pytest

from harnessctl.adapters.claude_code import ClaudeCodeAdapter
from harnessctl.model import InstalledItem, Kind, Scope, SourceFormat
from harnessctl.planner import DeletePath, Plan, PlanError, RunCommand, apply
from harnessctl.sources.formats import load_items
from tests.helpers import EXAMPLES, skill, write

ITEMS = {i.id: i for i in load_items(EXAMPLES, SourceFormat.CATALOG, "acme")[0]}


@pytest.fixture
def claude(env):
    (env.home / ".claude").mkdir()
    return ClaudeCodeAdapter(env.home, env.paths.parking, which=lambda name: f"/usr/bin/{name}")


def _apply(env, steps):
    result = apply(Plan.build("t", "claude-code", Scope.USER, steps), env.paths.backups,
                   runner=lambda argv, timeout: "")
    assert result.ok, result.error


def test_install_skill_user_scope(claude, env):
    inst = claude.plan_install(ITEMS["api-conventions"], Scope.USER, env.project)
    _apply(env, inst.steps)
    target = env.home / ".claude" / "skills" / "api-conventions"
    assert (target / "SKILL.md").is_file()
    assert inst.locations == [str(target)]


def test_install_hook_keeps_user_settings(claude, env):
    settings = write(env.project / ".claude" / "settings.json", json.dumps({
        "model": "opus", "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "mine.sh"}]}]}}))
    inst = claude.plan_install(ITEMS["block-secrets-read"], Scope.PROJECT, env.project)
    _apply(env, inst.steps)
    script = env.project / ".claude" / "hooks" / "block-secrets-read" / "secrets.sh"
    assert script.is_file() and script.stat().st_mode & 0o111
    data = json.loads(settings.read_text())
    assert data["model"] == "opus"
    commands = [h["command"] for g in data["hooks"]["PreToolUse"] for h in g["hooks"]]
    assert commands == ["mine.sh", str(script)]
    assert inst.locations == [f"{settings}::PreToolUse::{script}"]
    assert inst.settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == str(script)


def test_remove_hook_leaves_theirs(claude, env):
    settings = write(env.project / ".claude" / "settings.json", json.dumps({
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "mine.sh"}]}]}}))
    _apply(env, claude.plan_install(ITEMS["block-secrets-read"], Scope.PROJECT, env.project).steps)
    ours = [i for i in claude.scan(Scope.PROJECT, env.project) if i.meta.get("command", "").endswith("secrets.sh")][0]
    _apply(env, claude.plan_remove(ours, env.project))
    assert json.loads(settings.read_text()) == {
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "mine.sh"}]}]}}


def test_install_plugin_adds_marketplace_when_unknown(claude, env):
    steps = claude.plan_install(ITEMS["jira-context"], Scope.USER, env.project).steps
    assert [s.argv for s in steps] == [
        ["claude", "plugin", "marketplace", "add", "https://github.com/acme/claude-plugins"],
        ["claude", "plugin", "install", "jira-context@acme-plugins", "--scope", "user"],
    ]
    write(env.home / ".claude" / "plugins" / "known_marketplaces.json", json.dumps({"acme-plugins": {}}))
    steps = claude.plan_install(ITEMS["jira-context"], Scope.PROJECT, env.project).steps
    assert [s.argv for s in steps] == [["claude", "plugin", "install", "jira-context@acme-plugins", "--scope", "project"]]


def test_plugin_install_needs_the_cli(env):
    (env.home / ".claude").mkdir()
    adapter = ClaudeCodeAdapter(env.home, env.paths.parking, which=lambda name: None)
    with pytest.raises(PlanError, match="claude CLI is not on PATH"):
        adapter.plan_install(ITEMS["jira-context"], Scope.USER, env.project)


def test_install_refuses_existing_skill(claude, env):
    skill(env.home / ".claude" / "skills" / "api-conventions")
    with pytest.raises(PlanError, match="already exists"):
        claude.plan_install(ITEMS["api-conventions"], Scope.USER, env.project)


def test_park_and_restore_skill_and_hook(claude, env):
    skill(env.home / ".claude" / "skills" / "notes")
    write(env.home / ".claude" / "settings.json", json.dumps({
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "done.sh", "timeout": 3}]}]}}))
    items = {i.name: i for i in claude.scan(Scope.USER, None)}
    _apply(env, claude.plan_toggle(items["notes"], None))
    _apply(env, claude.plan_toggle(items["Stop:done.sh"], None))
    assert not (env.home / ".claude" / "skills" / "notes").exists()
    assert "hooks" not in json.loads((env.home / ".claude" / "settings.json").read_text())

    parked = {i.name: i for i in claude.scan(Scope.USER, None)}
    assert parked["notes"].enabled is False and parked["Stop:done.sh"].enabled is False
    _apply(env, claude.plan_toggle(parked["notes"], None))
    _apply(env, claude.plan_toggle(parked["Stop:done.sh"], None))
    assert (env.home / ".claude" / "skills" / "notes" / "SKILL.md").is_file()
    data = json.loads((env.home / ".claude" / "settings.json").read_text())
    assert data["hooks"]["Stop"][0]["hooks"][0] == {"type": "command", "command": "done.sh", "timeout": 3}
    assert not list((env.paths.parking / "claude-code").iterdir())


def test_toggle_plugin_uses_the_cli(claude, env):
    plugin = InstalledItem("claude-code", Scope.USER, Kind.PLUGIN, "sp", "claude-plugin:sp@m", enabled=True,
                           meta={"plugin_id": "sp@m"})
    assert claude.plan_toggle(plugin, None) == [RunCommand(["claude", "plugin", "disable", "sp@m", "--scope", "user"])]
    plugin.enabled = False
    assert claude.plan_toggle(plugin, None)[0].argv[2] == "enable"
    assert claude.plan_remove(plugin, None)[0].argv == ["claude", "plugin", "uninstall", "sp@m", "--scope", "user"]


def test_readonly_items_are_refused(claude, env):
    item = InstalledItem("claude-code", Scope.LOCAL, Kind.HOOK, "x", "loc", readonly="local scope is read-only")
    with pytest.raises(PlanError, match="local scope is read-only"):
        claude.plan_toggle(item, env.project)
    with pytest.raises(PlanError):
        claude.plan_remove(item, env.project)


def test_symlinked_skill_remove_and_park_act_on_the_link(claude, env, tmp_path):
    target = tmp_path / "shared-skills" / "linked"
    skill(target)
    link = env.home / ".claude" / "skills" / "linked"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    item = {i.name: i for i in claude.scan(Scope.USER, None)}["linked"]
    assert claude.plan_remove(item, None) == [DeletePath(link)]
    _apply(env, claude.plan_toggle(item, None))
    assert not link.is_symlink() and (target / "SKILL.md").is_file()


def test_edit_refused_on_broken_settings(claude, env):
    write(env.home / ".claude" / "settings.json", "{broken")
    with pytest.raises(PlanError, match="Fix the file first"):
        claude.plan_install(ITEMS["block-secrets-read"], Scope.USER, env.project)
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/test_claude_plans.py -v`
Expected: FAIL — `AttributeError: 'ClaudeCodeAdapter' object has no attribute 'plan_install'`.

- [ ] **Step 3: Implement** — add these imports to the top of `src/harnessctl/adapters/claude_code.py`:

```python
from harnessctl.adapters.base import (
    Install,
    ensure_json_writable,
    install_skill,
    require_writable,
    scan_skill_dirs,
    write_payload_files,
)
from harnessctl.edits import expand_placeholders, hook_location, merge_hooks_edit, remove_hooks_edit
from harnessctl.model import CatalogItem, ClaudePluginVariant, FilesVariant, SkillVariant
from harnessctl.parking import park_dir, park_steps, scan_parked, unpark_steps
from harnessctl.planner import DeletePath, EditJson, MovePath, PlanError, RunCommand, Step
```

(merge them with the existing import lines so each name is imported once), then add these methods to `ClaudeCodeAdapter`:

```python
    # --- changes -----------------------------------------------------------------------------

    def plan_install(self, item: CatalogItem, scope: Scope, project: Path | None, replace: bool = False) -> Install:
        variant = item.variants.get(self.id)
        if variant is None:
            raise PlanError(f"{item.id} has no Claude Code variant")
        scope_dir = self.scope_dir(scope, project)
        match variant:
            case SkillVariant(path=src):
                return install_skill(src, scope_dir / "skills" / item.id, replace)
            case FilesVariant():
                return self._install_files(variant, scope, project, replace)
            case ClaudePluginVariant():
                return self._install_plugin(variant, scope)
        raise PlanError(f"{type(variant).__name__} variants are not supported for Claude Code")

    def _install_files(self, variant: FilesVariant, scope: Scope, project: Path | None, replace: bool) -> Install:
        scope_dir = self.scope_dir(scope, project)
        steps, hashes = write_payload_files(variant.files, scope_dir, replace)
        settings = expand_placeholders(variant.settings, scope_dir)
        locations: list[str] = []
        hooks = settings.get("hooks", {})
        if hooks:
            path = self.settings_path(scope, project)
            ensure_json_writable(path)
            count = sum(len(g.get("hooks", [])) for groups in hooks.values() for g in groups)
            steps.append(EditJson(path, merge_hooks_edit(hooks), f"hooks +{count}"))
            for event, groups in hooks.items():
                for group in groups:
                    locations += [hook_location(path, event, h["command"]) for h in group.get("hooks", [])]
        return Install(steps, locations, hashes, settings)

    def _install_plugin(self, variant: ClaudePluginVariant, scope: Scope) -> Install:
        if self._which("claude") is None:
            raise PlanError("the claude CLI is not on PATH, so plugins cannot be installed")
        try:
            markets = read_json(self.claude_dir / "plugins" / "known_marketplaces.json", default={})
        except JsonFileError:
            markets = {}
        steps: list[Step] = []
        if variant.marketplace_name not in markets:
            steps.append(RunCommand(["claude", "plugin", "marketplace", "add", variant.marketplace_url]))
        steps.append(RunCommand(["claude", "plugin", "install", variant.plugin_id, "--scope", scope.value]))
        return Install(steps, [f"claude-plugin:{variant.plugin_id}"], {})

    def plan_remove(self, inst: InstalledItem, project: Path | None) -> list[Step]:
        require_writable(inst)
        if inst.meta.get("park_dir"):
            return [DeletePath(Path(inst.meta["park_dir"]))]
        match inst.kind:
            case Kind.SKILL:
                return [DeletePath(Path(inst.location))]
            case Kind.HOOK:
                path = Path(inst.meta["settings"])
                ensure_json_writable(path)
                return [EditJson(path, remove_hooks_edit(inst.meta["event"], inst.meta["command"]),
                                 f"hooks −1 ({inst.meta['event']})")]
            case Kind.PLUGIN:
                return [RunCommand(["claude", "plugin", "uninstall", inst.meta["plugin_id"], "--scope", inst.scope.value])]

    def plan_toggle(self, inst: InstalledItem, project: Path | None) -> list[Step]:
        require_writable(inst)
        if inst.kind is Kind.PLUGIN:
            verb = "disable" if inst.enabled else "enable"
            return [RunCommand(["claude", "plugin", verb, inst.meta["plugin_id"], "--scope", inst.scope.value])]
        if not inst.enabled:
            return unpark_steps(inst)
        scope_dir = self.scope_dir(inst.scope, project)
        pdir = park_dir(self.parking, self.id, inst.location, inst.name)
        if inst.kind is Kind.SKILL:
            return park_steps(inst, pdir, scope_dir, {"type": "move", "to": inst.location},
                              [MovePath(Path(inst.location), pdir / "payload")])
        path = Path(inst.meta["settings"])
        ensure_json_writable(path)
        restore = {"type": "hook", "settings": str(path), "event": inst.meta["event"],
                   "matcher": inst.meta.get("matcher"), "hook": inst.meta["hook"]}
        take_out = EditJson(path, remove_hooks_edit(inst.meta["event"], inst.meta["command"]),
                            f"hooks −1 ({inst.meta['event']}, parked)")
        return park_steps(inst, pdir, scope_dir, restore, [take_out])
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_claude_plans.py tests/test_claude_scan.py -v`
Expected: all pass (17).

- [ ] **Step 5: Commit**

```bash
git add src/harnessctl/adapters/claude_code.py tests/test_claude_plans.py
git commit -m "feat: Claude Code adapter install, remove and enable/disable"
```

---

### Task 12: opencode adapter

**Files:**
- Create: `src/harnessctl/adapters/opencode.py`
- Test: `tests/test_opencode.py`

**Interfaces:**
- Consumes: everything `ClaudeCodeAdapter` consumes, plus `add_plugin_spec_edit`, `remove_plugin_spec_edit`, `plugin_location`, `plugin_spec_name` (Task 9).
- Produces: `OpencodeAdapter(home: Path, xdg_config: Path, parking: Path, env: dict | None = None, which=shutil.which)` implementing `Adapter` (`id = "opencode"`, `label = "opencode"`), plus `config_path(scope, project) -> Path` and `claude_skills_dir(scope, project) -> Path`. npm plugin items have `location = plugin_location(config, spec)` and `meta` keys `spec, config, repo_url?`; skills visible through `.claude/skills` have `meta["via"] = "claude"` and are readonly.

- [ ] **Step 1: Write the failing tests**

`tests/test_opencode.py`:

```python
import json

import pytest

from harnessctl.adapters.opencode import OpencodeAdapter
from harnessctl.model import Kind, Scope, SourceFormat, Status
from harnessctl.planner import Plan, PlanError, apply
from harnessctl.sources.formats import load_items
from tests.helpers import EXAMPLES, skill, write

ITEMS = {i.id: i for i in load_items(EXAMPLES, SourceFormat.CATALOG, "acme")[0]}


@pytest.fixture
def oc(env):
    (env.home / ".config" / "opencode").mkdir(parents=True)
    return OpencodeAdapter(env.home, env.paths.xdg_config, env.paths.parking, env={}, which=lambda n: None)


def _apply(env, steps):
    result = apply(Plan.build("t", "opencode", Scope.USER, steps), env.paths.backups, runner=lambda a, t: "")
    assert result.ok, result.error


def test_scan_skills_plugins_and_claude_shared(oc, env):
    cfg = env.home / ".config" / "opencode"
    skill(cfg / "skills" / "own")
    skill(env.home / ".claude" / "skills" / "shared")
    skill(env.home / ".claude" / "skills" / "own")  # same name as an opencode skill: not listed twice
    write(cfg / "plugins" / "guard.ts", "export const Guard = async () => ({})\n")
    write(cfg / "opencode.jsonc", '{\n  // mine\n  "plugin": ["superpowers@git+https://github.com/obra/superpowers.git", ["opencode-bar", {"k": 1}]]\n}\n')
    items = {i.name: i for i in oc.scan(Scope.USER, env.project)}
    assert set(items) == {"own", "shared", "guard", "superpowers", "opencode-bar"}
    assert items["shared"].meta["via"] == "claude" and items["shared"].readonly
    assert items["guard"].kind is Kind.PLUGIN and items["guard"].location == str(cfg / "plugins" / "guard.ts")
    sp = items["superpowers"]
    assert sp.meta["repo_url"] == "https://github.com/obra/superpowers.git"
    assert sp.location == f"{cfg / 'opencode.jsonc'}::plugin::superpowers@git+https://github.com/obra/superpowers.git"


def test_env_switch_hides_claude_skills(env):
    (env.home / ".config" / "opencode").mkdir(parents=True)
    skill(env.home / ".claude" / "skills" / "shared")
    oc = OpencodeAdapter(env.home, env.paths.xdg_config, env.paths.parking, env={"OPENCODE_DISABLE_CLAUDE_CODE_SKILLS": "1"})
    assert oc.scan(Scope.USER, None) == []


def test_project_scope_paths(oc, env):
    skill(env.project / ".opencode" / "skills" / "p")
    write(env.project / "opencode.json", json.dumps({"plugin": ["opencode-foo"]}))
    items = {i.name for i in oc.scan(Scope.PROJECT, env.project)}
    assert items == {"p", "opencode-foo"}
    assert oc.scan(Scope.PROJECT, None) == [] and oc.scan(Scope.LOCAL, env.project) == []


def test_broken_config_is_reported(oc, env):
    write(env.home / ".config" / "opencode" / "opencode.json", "{nope")
    [broken] = oc.scan(Scope.USER, None)
    assert broken.status is Status.BROKEN and broken.readonly


def test_install_npm_plugin_creates_config(oc, env):
    inst = oc.plan_install(ITEMS["jira-context"], Scope.PROJECT, env.project)
    _apply(env, inst.steps)
    data = json.loads((env.project / "opencode.json").read_text())
    assert data == {"$schema": "https://opencode.ai/config.json", "plugin": ["@acme/opencode-jira@1.2.0"]}
    assert inst.locations == [f"{env.project / 'opencode.json'}::plugin::@acme/opencode-jira@1.2.0"]


def test_jsonc_with_comments_is_refused_with_manual_edit(oc, env):
    cfg = write(env.home / ".config" / "opencode" / "opencode.jsonc", '{\n  // keep me\n  "plugin": []\n}\n')
    before = cfg.read_bytes()
    with pytest.raises(PlanError) as exc:
        oc.plan_install(ITEMS["jira-context"], Scope.USER, None)
    assert "contains comments" in str(exc.value)
    assert '"@acme/opencode-jira@1.2.0"' in str(exc.value)
    assert cfg.read_bytes() == before


def test_install_files_variant_and_skill(oc, env):
    hook = oc.plan_install(ITEMS["block-secrets-read"], Scope.USER, None)
    _apply(env, hook.steps)
    target = env.home / ".config" / "opencode" / "plugins" / "block-secrets-read.ts"
    assert target.is_file() and hook.locations == [str(target)]
    sk = oc.plan_install(ITEMS["api-conventions"], Scope.USER, None)
    _apply(env, sk.steps)
    assert (env.home / ".config" / "opencode" / "skills" / "api-conventions" / "SKILL.md").is_file()


def test_skill_already_shared_through_claude_is_refused(oc, env):
    skill(env.home / ".claude" / "skills" / "api-conventions")
    with pytest.raises(PlanError, match="already active in opencode"):
        oc.plan_install(ITEMS["api-conventions"], Scope.USER, None)


def test_park_and_restore_npm_plugin_and_file(oc, env):
    cfg = write(env.home / ".config" / "opencode" / "opencode.json", json.dumps({"plugin": ["opencode-foo"]}))
    write(env.home / ".config" / "opencode" / "plugins" / "guard.ts", "x")
    items = {i.name: i for i in oc.scan(Scope.USER, None)}
    _apply(env, oc.plan_toggle(items["opencode-foo"], None))
    _apply(env, oc.plan_toggle(items["guard"], None))
    assert json.loads(cfg.read_text())["plugin"] == []
    parked = {i.name: i for i in oc.scan(Scope.USER, None)}
    assert not parked["guard"].enabled and not parked["opencode-foo"].enabled
    _apply(env, oc.plan_toggle(parked["opencode-foo"], None))
    _apply(env, oc.plan_toggle(parked["guard"], None))
    assert json.loads(cfg.read_text())["plugin"] == ["opencode-foo"]
    assert (env.home / ".config" / "opencode" / "plugins" / "guard.ts").read_text() == "x"


def test_remove(oc, env):
    cfg = write(env.home / ".config" / "opencode" / "opencode.json", json.dumps({"plugin": ["a", "b"]}))
    items = {i.name: i for i in oc.scan(Scope.USER, None)}
    _apply(env, oc.plan_remove(items["a"], None))
    assert json.loads(cfg.read_text())["plugin"] == ["b"]
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/test_opencode.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harnessctl.adapters.opencode'`.

- [ ] **Step 3: Implement**

`src/harnessctl/adapters/opencode.py`:

```python
"""opencode: skills in skills/, plugins as files in plugins/ or npm specs in opencode.json(c)."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path

from harnessctl.adapters.base import (
    Install,
    ensure_json_writable,
    install_skill,
    require_writable,
    scan_skill_dirs,
    write_payload_files,
)
from harnessctl.edits import add_plugin_spec_edit, plugin_location, plugin_spec_name, remove_plugin_spec_edit
from harnessctl.jsonio import JsonFileError, read_json
from harnessctl.model import CatalogItem, FilesVariant, InstalledItem, Kind, NpmPluginVariant, Scope, SkillVariant, Status
from harnessctl.parking import park_dir, park_steps, scan_parked, unpark_steps
from harnessctl.planner import DeletePath, EditJson, MovePath, PlanError, Step

PLUGIN_SUFFIXES = {".js", ".mjs", ".ts"}


class OpencodeAdapter:
    id = "opencode"
    label = "opencode"
    reload_hint = "Restart opencode to pick up the change."

    def __init__(self, home: Path, xdg_config: Path, parking: Path, env: dict[str, str] | None = None,
                 which: Callable[[str], str | None] = shutil.which):
        self.home = home
        self.global_dir = xdg_config / "opencode"
        self.parking = parking
        self.env = dict(os.environ if env is None else env)
        self._which = which

    # --- locations ---------------------------------------------------------------------------

    def detect(self) -> bool:
        return self.global_dir.is_dir() or self._which("opencode") is not None

    def scope_dir(self, scope: Scope, project: Path | None) -> Path:
        if scope is Scope.USER:
            return self.global_dir
        if scope is Scope.PROJECT and project is not None:
            return project / ".opencode"
        raise PlanError("opencode has user and project scopes only" if project else "no project here")

    def config_path(self, scope: Scope, project: Path | None) -> Path:
        base = self.global_dir if scope is Scope.USER else project
        for name in ("opencode.json", "opencode.jsonc"):
            if (base / name).exists():
                return base / name
        return base / "opencode.json"

    def claude_skills_dir(self, scope: Scope, project: Path | None) -> Path:
        return (self.home if scope is Scope.USER else project) / ".claude" / "skills"

    def _reads_claude_skills(self) -> bool:
        return not (self.env.get("OPENCODE_DISABLE_CLAUDE_CODE") or self.env.get("OPENCODE_DISABLE_CLAUDE_CODE_SKILLS"))

    def watched_paths(self, project: Path | None) -> list[Path]:
        paths = [self.global_dir / n for n in ("opencode.json", "opencode.jsonc", "skills", "plugins")]
        paths.append(self.parking / self.id)
        if project is not None:
            paths += [project / "opencode.json", project / "opencode.jsonc",
                      project / ".opencode" / "skills", project / ".opencode" / "plugins"]
        return paths

    # --- scanning ----------------------------------------------------------------------------

    def scan(self, scope: Scope, project: Path | None) -> list[InstalledItem]:
        if scope is Scope.LOCAL or (scope is Scope.PROJECT and project is None):
            return []
        scope_dir = self.scope_dir(scope, project)
        items = scan_skill_dirs(scope_dir / "skills", self.id, scope)
        if self._reads_claude_skills():
            own = {i.name for i in items}
            for shared in scan_skill_dirs(self.claude_skills_dir(scope, project), self.id, scope,
                                          readonly="shared with Claude Code; manage it from the Claude Code view"):
                if shared.name not in own:
                    shared.meta["via"] = "claude"
                    items.append(shared)
        for folder in ("plugins", "plugin"):
            directory = scope_dir / folder
            if directory.is_dir():
                for f in sorted(directory.iterdir()):
                    if f.is_file() and f.suffix in PLUGIN_SUFFIXES:
                        preview = "\n".join(f.read_text(errors="replace").splitlines()[:30])
                        items.append(InstalledItem(self.id, scope, Kind.PLUGIN, f.stem, str(f),
                                                   detail=f"```ts\n{preview}\n```"))
        items += self._scan_config(scope, project)
        items += scan_parked(self.parking, self.id, scope, scope_dir)
        return items

    def _scan_config(self, scope: Scope, project: Path | None) -> list[InstalledItem]:
        path = self.config_path(scope, project)
        try:
            config = read_json(path, default={})
        except JsonFileError as exc:
            return [InstalledItem(self.id, scope, Kind.PLUGIN, path.name, str(path), status=Status.BROKEN,
                                  error=str(exc), readonly="the file cannot be parsed")]
        items: list[InstalledItem] = []
        for entry in config.get("plugin", []) if isinstance(config, dict) else []:
            spec = entry[0] if isinstance(entry, list) and entry else entry
            if not isinstance(spec, str):
                continue
            meta = {"spec": spec, "config": str(path)}
            if "git+" in spec:
                meta["repo_url"] = spec.split("git+", 1)[1]
            items.append(InstalledItem(self.id, scope, Kind.PLUGIN, plugin_spec_name(spec), plugin_location(path, spec),
                                       detail=f"npm plugin `{spec}`\n\nlisted in `{path}`", meta=meta))
        return items

    # --- changes -----------------------------------------------------------------------------

    def plan_install(self, item: CatalogItem, scope: Scope, project: Path | None, replace: bool = False) -> Install:
        variant = item.variants.get(self.id)
        if variant is None:
            raise PlanError(f"{item.id} has no opencode variant")
        scope_dir = self.scope_dir(scope, project)
        match variant:
            case SkillVariant(path=src):
                shared = self.claude_skills_dir(scope, project) / item.id
                if not replace and self._reads_claude_skills() and shared.exists():
                    raise PlanError(f"{item.id} is already active in opencode through {shared}")
                return install_skill(src, scope_dir / "skills" / item.id, replace)
            case FilesVariant(files=files):
                steps, hashes = write_payload_files(files, scope_dir, replace)
                return Install(steps, [str(s.path) for s in steps], hashes)
            case NpmPluginVariant(package=spec):
                path = self.config_path(scope, project)
                ensure_json_writable(path, manual=f'add "{spec}" to its plugin array')
                return Install([EditJson(path, add_plugin_spec_edit(spec), f"plugin +{spec}")],
                               [plugin_location(path, spec)], {})
        raise PlanError(f"{type(variant).__name__} variants are not supported for opencode")

    def plan_remove(self, inst: InstalledItem, project: Path | None) -> list[Step]:
        require_writable(inst)
        if inst.meta.get("park_dir"):
            return [DeletePath(Path(inst.meta["park_dir"]))]
        if "spec" in inst.meta:
            path, spec = Path(inst.meta["config"]), inst.meta["spec"]
            ensure_json_writable(path, manual=f'remove "{spec}" from its plugin array')
            return [EditJson(path, remove_plugin_spec_edit(spec), f"plugin −{spec}")]
        return [DeletePath(Path(inst.location))]

    def plan_toggle(self, inst: InstalledItem, project: Path | None) -> list[Step]:
        require_writable(inst)
        if not inst.enabled:
            return unpark_steps(inst)
        scope_dir = self.scope_dir(inst.scope, project)
        pdir = park_dir(self.parking, self.id, inst.location, inst.name)
        if "spec" in inst.meta:
            path, spec = Path(inst.meta["config"]), inst.meta["spec"]
            ensure_json_writable(path, manual=f'remove "{spec}" from its plugin array')
            take_out = EditJson(path, remove_plugin_spec_edit(spec), f"plugin −{spec} (parked)")
            return park_steps(inst, pdir, scope_dir, {"type": "npm", "config": str(path), "spec": spec}, [take_out])
        return park_steps(inst, pdir, scope_dir, {"type": "move", "to": inst.location},
                          [MovePath(Path(inst.location), pdir / "payload")])
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_opencode.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add src/harnessctl/adapters/opencode.py tests/test_opencode.py
git commit -m "feat: opencode adapter"
```

---

### Task 13: Engine and end-to-end smoke test

**Files:**
- Create: `src/harnessctl/engine.py`
- Test: `tests/test_engine.py`, `tests/test_e2e.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `CatalogEntry(item, trust, available: bool, installed: list[Scope])`; `Engine(paths, project, adapters=None, runner=run_command, env=None)` with attributes `paths, project, adapters, sources: list[SourceState], config_errors: list[str], lock_errors: list[str]` and methods `adapter(harness)`, `detected() -> list[Adapter]`, `scopes() -> list[Scope]`, `specs() -> dict[str, SourceSpec]`, `load_sources(fetch: bool) -> None`, `refresh_source(name) -> SourceState`, `add_source(url, name=None, ref=None, subdir="") -> SourceState`, `remove_source(name) -> None`, `lock_path(scope) -> Path`, `installed(harness) -> list[InstalledItem]`, `catalog(harness) -> list[CatalogEntry]`, `find_item(source, item_id) -> CatalogItem | None`, `plan_install(item, harness, scope, replace=False) -> Plan`, `plan_remove(inst) -> Plan`, `plan_toggle(inst) -> Plan`, `plan_update(inst) -> Plan`, `apply(plan) -> ApplyResult`, `watched_paths() -> list[Path]`. Lock entries are attached to installed items as `inst.meta["lock"]` (a `LockEntry`).

- [ ] **Step 1: Write the failing engine tests**

`tests/test_engine.py`:

```python
import json

import pytest

from harnessctl.config import ConfigError
from harnessctl.model import Kind, Scope, Status
from harnessctl.planner import PlanError
from tests.helpers import EXAMPLES, commit_all, make_repo, skill, write


@pytest.fixture
def acme(env, tmp_path):
    repo = make_repo(EXAMPLES, tmp_path / "acme-remote")
    write(env.paths.corporate_toml, f'[[source]]\nname = "acme"\nurl = "{repo.as_uri()}"\n')
    (env.home / ".claude").mkdir()
    return repo


@pytest.fixture
def engine(env, acme):
    e = env.engine()
    e.load_sources(fetch=True)
    return e


def _installed(engine, name, harness="claude-code"):
    return next(i for i in engine.installed(harness) if i.name == name)


def _item(engine, item_id):
    return engine.find_item("acme", item_id)


def test_catalog_lists_items_with_harness_support(engine):
    entries = {e.item.id: e for e in engine.catalog("claude-code")}
    assert set(entries) == {"api-conventions", "block-secrets-read", "jira-context"}
    assert entries["api-conventions"].trust == "corporate" and entries["api-conventions"].available
    assert entries["api-conventions"].installed == []


def test_install_records_lock_and_provenance(engine, env):
    result = engine.apply(engine.plan_install(_item(engine, "api-conventions"), "claude-code", Scope.PROJECT))
    assert result.ok, result.error
    lock = json.loads((env.project / ".harnessctl" / "lock.json").read_text())
    assert lock["entries"][0]["item_id"] == "api-conventions"
    inst = _installed(engine, "api-conventions")
    assert (inst.provenance.origin, inst.provenance.source, inst.status) == ("corp", "acme", Status.OK)
    assert inst.scope is Scope.PROJECT
    assert {e.item.id: e.installed for e in engine.catalog("claude-code")}["api-conventions"] == [Scope.PROJECT]


def test_local_edit_shows_modified(engine, env):
    engine.apply(engine.plan_install(_item(engine, "api-conventions"), "claude-code", Scope.USER))
    (env.home / ".claude" / "skills" / "api-conventions" / "SKILL.md").write_text("edited")
    assert _installed(engine, "api-conventions").status is Status.MODIFIED


def test_new_version_shows_update_and_updates(engine, env, acme):
    engine.apply(engine.plan_install(_item(engine, "api-conventions"), "claude-code", Scope.USER))
    toml = acme / "items" / "api-conventions" / "item.toml"
    toml.write_text(toml.read_text().replace('version = "1.4.0"', 'version = "1.5.0"'))
    (acme / "items" / "api-conventions" / "skill" / "SKILL.md").write_text("---\nname: api-conventions\n---\nv1.5\n")
    commit_all(acme, "1.5.0")
    engine.refresh_source("acme")
    inst = _installed(engine, "api-conventions")
    assert inst.status is Status.UPDATE
    assert engine.apply(engine.plan_update(inst)).ok
    after = _installed(engine, "api-conventions")
    assert after.status is Status.OK and after.meta["lock"].version == "1.5.0"
    assert "v1.5" in (env.home / ".claude" / "skills" / "api-conventions" / "SKILL.md").read_text()


def test_remove_hook_deletes_script_and_lock_entry(engine, env):
    engine.apply(engine.plan_install(_item(engine, "block-secrets-read"), "claude-code", Scope.USER))
    inst = _installed(engine, "block-secrets-read")
    assert inst.kind is Kind.HOOK and inst.provenance.origin == "corp"
    assert engine.apply(engine.plan_remove(inst)).ok
    assert not (env.home / ".claude" / "hooks" / "block-secrets-read" / "secrets.sh").exists()
    assert json.loads(env.paths.user_lock.read_text())["entries"] == []
    assert "hooks" not in json.loads((env.home / ".claude" / "settings.json").read_text())


def test_toggle_keeps_provenance(engine):
    engine.apply(engine.plan_install(_item(engine, "api-conventions"), "claude-code", Scope.USER))
    assert engine.apply(engine.plan_toggle(_installed(engine, "api-conventions"))).ok
    parked = _installed(engine, "api-conventions")
    assert parked.enabled is False and parked.provenance.origin == "corp"
    assert engine.apply(engine.plan_toggle(parked)).ok
    assert _installed(engine, "api-conventions").enabled


def test_unknown_items_and_also_in(engine, env):
    skill(env.home / ".claude" / "skills" / "mine")
    (env.home / ".config" / "opencode").mkdir(parents=True)
    inst = _installed(engine, "mine")
    assert inst.provenance.origin == "unknown" and inst.also_in == ["opencode"]
    with pytest.raises(PlanError, match="not installed by harnessctl"):
        engine.plan_update(inst)


def test_plugin_children_inherit_provenance(engine, env):
    plugin_dir = env.home / "pl"
    skill(plugin_dir / "skills" / "child")
    write(env.home / ".claude" / "plugins" / "installed_plugins.json", json.dumps({"plugins": {
        "sp@official": [{"scope": "user", "installPath": str(plugin_dir)}]}}))
    write(env.home / ".claude" / "plugins" / "known_marketplaces.json", json.dumps({
        "official": {"source": {"source": "github", "repo": "anthropics/claude-plugins-official"}}}))
    child = _installed(engine, "child")
    assert child.provenance.origin == "public"
    names = [i.name for i in engine.installed("claude-code")]
    assert names.index("child") == names.index("sp") + 1


def test_add_and_remove_public_source(engine, tmp_path):
    other = tmp_path / "pub"
    skill(other / "skills" / "tdd")
    make_repo(None, other)
    state = engine.add_source(other.as_uri(), name="pub")
    assert state.status == "ok" and [i.id for i in state.items] == ["tdd"]
    with pytest.raises(ConfigError):
        engine.remove_source("acme")
    engine.remove_source("pub")
    assert [s.spec.name for s in engine.sources] == ["acme"]


def test_broken_lockfile_is_reported_not_fatal(engine, env):
    write(env.paths.user_lock, "[1, 2]")
    assert engine.installed("claude-code") is not None
    assert engine.lock_errors and "lock.json" in engine.lock_errors[0]


def test_no_project_offers_user_scope_only(env, acme):
    engine = env.engine()
    engine.project = None
    assert engine.scopes() == [Scope.USER]


def test_unavailable_source_is_kept(env, tmp_path):
    write(env.paths.config_toml, f'[[source]]\nname = "gone"\nurl = "{(tmp_path / "nothing").as_uri()}"\n')
    engine = env.engine()
    engine.load_sources(fetch=True)
    assert [s.status for s in engine.sources] == ["unavailable"]
    assert engine.catalog("claude-code") == []
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/test_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harnessctl.engine'`.

- [ ] **Step 3: Implement**

`src/harnessctl/engine.py`:

```python
"""The headless core the TUI drives: sources, adapters, lockfiles and plans."""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from packaging.version import InvalidVersion, Version

from harnessctl.adapters.base import Adapter
from harnessctl.adapters.claude_code import ClaudeCodeAdapter
from harnessctl.adapters.opencode import OpencodeAdapter
from harnessctl.config import (
    ConfigError,
    Paths,
    add_public_source,
    default_source_name,
    load_sources,
    project_lock,
    remove_public_source,
)
from harnessctl.jsonio import JsonFileError, sha256_file
from harnessctl.model import CatalogItem, ClaudePluginVariant, InstalledItem, Kind, Scope, SourceSpec, Status, Trust
from harnessctl.planner import ApplyResult, DeletePath, EditJson, Plan, PlanError, apply, run_command
from harnessctl.provenance import LockEntry, add_entry_edit, read_lock, remove_entry_edit, resolve
from harnessctl.sources.cache import SourceState, sync_source
from harnessctl.sources.formats import payload_hash

log = logging.getLogger(__name__)
KIND_ORDER = {Kind.SKILL: 0, Kind.HOOK: 1, Kind.PLUGIN: 2}


@dataclass
class CatalogEntry:
    item: CatalogItem
    trust: Trust
    available: bool  # the item has a variant for the harness being viewed
    installed: list[Scope]


def group_of(item: InstalledItem) -> Kind:
    """Plugin children are shown under Plugins, right after their plugin."""
    return Kind.PLUGIN if item.parent else item.kind


class Engine:
    def __init__(self, paths: Paths, project: Path | None, adapters: list[Adapter] | None = None,
                 runner: Callable[[list[str], int], str] = run_command, env: dict[str, str] | None = None):
        self.paths = paths
        self.project = project
        self.runner = runner
        self.env = dict(os.environ if env is None else env)
        self.adapters: list[Adapter] = adapters or [
            ClaudeCodeAdapter(paths.home, paths.parking),
            OpencodeAdapter(paths.home, paths.xdg_config, paths.parking, self.env),
        ]
        self.sources: list[SourceState] = []
        self.config_errors: list[str] = []
        self.lock_errors: list[str] = []

    # --- harnesses and scopes ----------------------------------------------------------------

    def adapter(self, harness: str) -> Adapter:
        return next(a for a in self.adapters if a.id == harness)

    def detected(self) -> list[Adapter]:
        return [a for a in self.adapters if a.detect()] or self.adapters[:1]

    def scopes(self) -> list[Scope]:
        return [Scope.USER, Scope.PROJECT] if self.project else [Scope.USER]

    def lock_path(self, scope: Scope) -> Path:
        if scope is Scope.USER:
            return self.paths.user_lock
        if self.project is None:
            raise PlanError("no project here: only user scope is available")
        return project_lock(self.project)

    # --- sources -----------------------------------------------------------------------------

    def specs(self) -> dict[str, SourceSpec]:
        if self.sources:
            return {s.spec.name: s.spec for s in self.sources}
        return {s.name: s for s in load_sources(self.paths)[0]}

    def load_sources(self, fetch: bool) -> None:
        specs, self.config_errors = load_sources(self.paths)
        self.sources = [sync_source(s, self.paths.sources_cache, fetch=fetch) for s in specs]

    def refresh_source(self, name: str) -> SourceState:
        index = next(n for n, s in enumerate(self.sources) if s.spec.name == name)
        self.sources[index] = sync_source(self.sources[index].spec, self.paths.sources_cache, fetch=True)
        return self.sources[index]

    def add_source(self, url: str, name: str | None = None, ref: str | None = None, subdir: str = "") -> SourceState:
        spec = SourceSpec(name or default_source_name(url), url, Trust.PUBLIC, ref or None, subdir)
        add_public_source(self.paths, spec)
        state = sync_source(spec, self.paths.sources_cache, fetch=True)
        self.sources.append(state)
        return state

    def remove_source(self, name: str) -> None:
        spec = self.specs().get(name)
        if spec is not None and spec.trust is Trust.CORPORATE:
            raise ConfigError("corporate sources are managed in corporate.toml")
        remove_public_source(self.paths, name)
        self.sources = [s for s in self.sources if s.spec.name != name]
        shutil.rmtree(self.paths.sources_cache / name, ignore_errors=True)

    def find_item(self, source: str, item_id: str) -> CatalogItem | None:
        for state in self.sources:
            if state.spec.name == source:
                return next((i for i in state.items if i.id == item_id), None)
        return None

    # --- reading -----------------------------------------------------------------------------

    def _locks(self) -> dict[Scope, list[LockEntry]]:
        self.lock_errors = []
        locks: dict[Scope, list[LockEntry]] = {}
        for scope in self.scopes():
            try:
                locks[scope] = read_lock(self.lock_path(scope))
            except JsonFileError as exc:
                locks[scope] = []
                self.lock_errors.append(str(exc))
        return locks

    def _has_update(self, entry: LockEntry) -> bool:
        item = self.find_item(entry.source, entry.item_id)
        if item is None or entry.harness not in item.variants:
            return False
        try:
            if Version(item.version) != Version(entry.version):
                return Version(item.version) > Version(entry.version)
        except InvalidVersion:
            return False
        return bool(entry.payload_hash) and payload_hash(item.variants[entry.harness]) != entry.payload_hash

    def installed(self, harness: str) -> list[InstalledItem]:
        adapter = self.adapter(harness)
        specs = self.specs()
        entries = [e for es in self._locks().values() for e in es]
        items: list[InstalledItem] = []
        for scope in [*self.scopes(), *([Scope.LOCAL] if self.project else [])]:
            items += adapter.scan(scope, self.project)
        plugins: dict[str, InstalledItem] = {}
        for item in items:
            item.provenance, entry = resolve(item, entries, specs)
            if entry is not None:
                item.name, item.kind = entry.item_id, Kind(entry.kind)
                item.meta["lock"] = entry
                if item.enabled and item.status is Status.OK:
                    if any(sha256_file(Path(p)) != h for p, h in entry.files.items()):
                        item.status = Status.MODIFIED
                    elif self._has_update(entry):
                        item.status = Status.UPDATE
            if item.kind is Kind.PLUGIN and "plugin_id" in item.meta:
                plugins[item.meta["plugin_id"]] = item
        opencode_sees_claude = harness == "claude-code" and any(
            a.id == "opencode" and a.detect() for a in self.adapters
        ) and not (self.env.get("OPENCODE_DISABLE_CLAUDE_CODE") or self.env.get("OPENCODE_DISABLE_CLAUDE_CODE_SKILLS"))
        for item in items:
            if item.parent in plugins:
                item.provenance = plugins[item.parent].provenance
            if opencode_sees_claude and item.kind is Kind.SKILL and not item.parent and item.readonly is None \
                    and item.enabled and item.scope in (Scope.USER, Scope.PROJECT):
                item.also_in = ["opencode"]
        return sorted(items, key=lambda i: (KIND_ORDER[group_of(i)], i.parent or i.meta.get("plugin_id") or i.name,
                                            i.parent is not None, i.name))

    def catalog(self, harness: str) -> list[CatalogEntry]:
        locks = self._locks()
        native = {i.location: i.scope for i in self.installed(harness) if i.location.startswith("claude-plugin:")}
        entries: list[CatalogEntry] = []
        for state in self.sources:
            for item in state.items:
                scopes = [scope for scope, es in locks.items()
                          if any((e.item_id, e.source, e.harness) == (item.id, item.source, harness) for e in es)]
                variant = item.variants.get(harness)
                if isinstance(variant, ClaudePluginVariant) and not scopes:
                    found = native.get(f"claude-plugin:{variant.plugin_id}")
                    scopes = [found] if found else []
                entries.append(CatalogEntry(item, state.spec.trust, variant is not None, scopes))
        return entries

    # --- planning ----------------------------------------------------------------------------

    def _commit_of(self, source: str) -> str | None:
        return next((s.commit for s in self.sources if s.spec.name == source), None)

    def plan_install(self, item: CatalogItem, harness: str, scope: Scope, replace: bool = False) -> Plan:
        adapter = self.adapter(harness)
        if item.variants.get(harness) is None:
            raise PlanError(f"{item.id} has no {adapter.label} variant")
        inst = adapter.plan_install(item, scope, self.project, replace=replace)
        entry = LockEntry(
            item_id=item.id, source=item.source, harness=harness, kind=item.kind.value, version=item.version,
            commit=self._commit_of(item.source), locations=inst.locations, files=inst.files,
            payload_hash=payload_hash(item.variants[harness]), settings=inst.settings,
        )
        steps = [*inst.steps, EditJson(self.lock_path(scope), add_entry_edit(entry), f"record {item.id}")]
        return Plan.build(f"Install {item.id} → {scope}", harness, scope, steps, adapter.reload_hint)

    def plan_remove(self, inst: InstalledItem) -> Plan:
        adapter = self.adapter(inst.harness)
        entry: LockEntry | None = inst.meta.get("lock")
        targets = [inst]
        if entry is not None:
            targets = [i for i in self.installed(inst.harness)
                       if i.location in entry.locations and i.scope is inst.scope] or [inst]
        steps = [s for t in targets for s in adapter.plan_remove(t, self.project)]
        if entry is not None:
            covered = [s.path for s in steps if isinstance(s, DeletePath)]
            for f in entry.files:
                path = Path(f)
                if (path.exists() or path.is_symlink()) and not any(path.is_relative_to(c) for c in covered):
                    steps.append(DeletePath(path))
            steps.append(EditJson(self.lock_path(inst.scope), remove_entry_edit(entry), f"forget {entry.item_id}"))
        return Plan.build(f"Remove {inst.name} ({inst.scope})", inst.harness, inst.scope, steps, adapter.reload_hint)

    def plan_toggle(self, inst: InstalledItem) -> Plan:
        adapter = self.adapter(inst.harness)
        steps = adapter.plan_toggle(inst, self.project)
        verb = "Disable" if inst.enabled else "Enable"
        return Plan.build(f"{verb} {inst.name} ({inst.scope})", inst.harness, inst.scope, steps, adapter.reload_hint)

    def plan_update(self, inst: InstalledItem) -> Plan:
        entry: LockEntry | None = inst.meta.get("lock")
        if entry is None:
            raise PlanError(f"{inst.name} was not installed by harnessctl; update it with the harness's own tools")
        item = self.find_item(entry.source, entry.item_id)
        if item is None:
            raise PlanError(f"{entry.item_id} is no longer in source {entry.source}")
        remove = self.plan_remove(inst)
        install = self.plan_install(item, inst.harness, inst.scope, replace=True)
        return Plan.build(f"Update {inst.name} {entry.version} → {item.version}", inst.harness, inst.scope,
                          [*remove.steps, *install.steps], install.reload_hint)

    def apply(self, plan: Plan) -> ApplyResult:
        result = apply(plan, self.paths.backups, runner=self.runner)
        log.info("%s: %s", plan.title, "ok" if result.ok else f"failed at step {result.failed_step}: {result.error}")
        return result

    def watched_paths(self) -> list[Path]:
        paths = [self.paths.corporate_toml, self.paths.config_toml, self.paths.user_lock]
        if self.project is not None:
            paths.append(project_lock(self.project))
        for adapter in self.detected():
            paths += adapter.watched_paths(self.project)
        return paths
```

- [ ] **Step 4: Run the engine tests**

Run: `uv run pytest tests/test_engine.py -v`
Expected: 12 passed.

- [ ] **Step 5: Write the end-to-end smoke test**

`tests/test_e2e.py`:

```python
"""Spec §10.4: a real git catalog as corporate source, a temp $HOME and project, a stub `claude` CLI."""

import json

from harnessctl.model import Scope, Status
from tests.helpers import EXAMPLES, commit_all, make_repo, stub_command, write


def test_full_lifecycle(env, tmp_path):
    repo = make_repo(EXAMPLES, tmp_path / "acme")
    write(env.paths.corporate_toml, f'[[source]]\nname = "acme"\nurl = "{repo.as_uri()}"\n')
    (env.home / ".claude").mkdir()
    calls = tmp_path / "claude-calls.log"
    stub_command(env.bin, "claude", calls)

    engine = env.engine()
    engine.load_sources(fetch=True)
    item = {i.item.id: i.item for i in engine.catalog("claude-code")}

    # install a skill (project), a hook (user) and a plugin (user)
    for item_id, scope in [("api-conventions", Scope.PROJECT), ("block-secrets-read", Scope.USER),
                           ("jira-context", Scope.USER)]:
        result = engine.apply(engine.plan_install(item[item_id], "claude-code", scope))
        assert result.ok, (item_id, result.error)
    assert calls.read_text().splitlines() == [
        "plugin marketplace add https://github.com/acme/claude-plugins",
        "plugin install jira-context@acme-plugins --scope user",
    ]
    names = {i.name: i for i in engine.installed("claude-code")}
    assert names["api-conventions"].provenance.origin == "corp"
    assert names["block-secrets-read"].provenance.origin == "corp"

    # disable and re-enable the hook
    assert engine.apply(engine.plan_toggle(names["block-secrets-read"])).ok
    assert "hooks" not in json.loads((env.home / ".claude" / "settings.json").read_text())
    parked = {i.name: i for i in engine.installed("claude-code")}["block-secrets-read"]
    assert engine.apply(engine.plan_toggle(parked)).ok
    assert "PreToolUse" in json.loads((env.home / ".claude" / "settings.json").read_text())["hooks"]

    # publish a new version and update
    toml = repo / "items" / "block-secrets-read" / "item.toml"
    toml.write_text(toml.read_text().replace('version = "2.0.1"', 'version = "2.1.0"'))
    commit_all(repo, "2.1.0")
    engine.refresh_source("acme")
    hook = {i.name: i for i in engine.installed("claude-code")}["block-secrets-read"]
    assert hook.status is Status.UPDATE
    assert engine.apply(engine.plan_update(hook)).ok
    commands = json.loads((env.home / ".claude" / "settings.json").read_text())["hooks"]["PreToolUse"]
    assert len(commands) == 1  # updated in place, not duplicated

    # remove everything harnessctl installed
    for name in ("api-conventions", "block-secrets-read"):
        target = {i.name: i for i in engine.installed("claude-code")}[name]
        assert engine.apply(engine.plan_remove(target)).ok
    assert json.loads(env.paths.user_lock.read_text())["entries"][0]["item_id"] == "jira-context"
    assert json.loads((env.project / ".harnessctl" / "lock.json").read_text())["entries"] == []
    assert not (env.project / ".claude" / "skills" / "api-conventions").exists()
```

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -v && uv run ruff check .`
Expected: all tests pass; no lint errors.

- [ ] **Step 7: Commit**

```bash
git add src/harnessctl/engine.py tests/test_engine.py tests/test_e2e.py
git commit -m "feat: engine tying sources, adapters, lockfiles and plans together"
```

---
### Task 14: TUI text formatters

**Files:**
- Create: `src/harnessctl/tui/__init__.py` (empty), `src/harnessctl/tui/text.py`
- Test: `tests/test_tui_text.py`

**Interfaces:**
- Consumes: model types, `CatalogEntry` (Task 13), `SourceState` (Task 6), `Plan`, `step_symbol`, `step_label` (Task 8).
- Produces: `short_path(path, home) -> str`, `installed_row(item) -> Text`, `catalog_row(entry) -> Text`, `source_row(state) -> Text`, `installed_detail(item, home) -> str`, `catalog_detail(entry) -> str`, `source_detail(state, now) -> str`, `age(when, now) -> str`, `sync_summary(states, now, syncing) -> str`, `plan_text(plan, home) -> Text`, `HARNESS_LABEL`.

- [ ] **Step 1: Write the failing tests**

`tests/test_tui_text.py`:

```python
from datetime import UTC, datetime, timedelta
from pathlib import Path

from harnessctl.engine import CatalogEntry
from harnessctl.model import (
    CatalogItem,
    ClaudePluginVariant,
    InstalledItem,
    Kind,
    Provenance,
    Scope,
    SourceSpec,
    Status,
    Trust,
)
from harnessctl.planner import Plan, RunCommand, WriteFile
from harnessctl.sources.cache import SourceState
from harnessctl.tui.text import (
    age,
    catalog_detail,
    catalog_row,
    installed_detail,
    installed_row,
    plan_text,
    short_path,
    source_detail,
    sync_summary,
)

HOME = Path("/home/u")
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def _item(**kw):
    base = dict(harness="claude-code", scope=Scope.PROJECT, kind=Kind.SKILL, name="api-conventions",
                location="/home/u/p/.claude/skills/api-conventions",
                provenance=Provenance("corp", "acme", "api-conventions", "abcdef1234"), status=Status.UPDATE)
    return InstalledItem(**(base | kw))


def _entry(installed=()):
    item = CatalogItem("jira-context", Kind.PLUGIN, "1.2.0", "Jira context", "acme",
                       {"claude-code": ClaudePluginVariant("u", "m", "jira-context")})
    return CatalogEntry(item, Trust.CORPORATE, True, list(installed))


def test_short_path():
    assert short_path(HOME / "x", HOME) == "~/x"
    assert short_path(HOME, HOME) == "~"
    assert short_path("/etc/x", HOME) == "/etc/x"
    assert short_path("/home/user2/x", HOME) == "/home/user2/x"


def test_installed_row_encodes_state_as_text():
    row = installed_row(_item()).plain
    assert row.startswith(" ● api-conventions")
    assert " P  corp    ↑ acme" in row


def test_ok_status_has_no_mark_and_disabled_uses_hollow_dot():
    row = installed_row(_item(status=Status.OK, enabled=False)).plain
    assert row.startswith(" ○ ") and "↑" not in row and "±" not in row


def test_children_are_indented_and_long_names_truncated():
    row = installed_row(_item(parent="sp@m", name="x" * 40)).plain
    assert row.startswith(" ●   xxx") and "…" in row


def test_catalog_row():
    assert catalog_row(_entry()).plain.startswith("   jira-context")
    assert "plugin  CC –" in catalog_row(_entry()).plain
    assert catalog_row(_entry([Scope.USER])).plain.startswith(" ✓ jira-context")


def test_installed_detail():
    md = installed_detail(_item(), HOME)
    assert "## api-conventions" in md
    assert "**origin** corp · acme @ `abcdef1`" in md
    assert "`~/p/.claude/skills/api-conventions`" in md
    assert "update available" in md


def test_catalog_detail():
    md = catalog_detail(_entry())
    assert "**Claude Code**: Claude plugin `jira-context@m`" in md
    assert "**opencode**: not available" in md
    assert "**Installed** not installed" in md


def test_age():
    assert age(NOW - timedelta(seconds=30), NOW) == "just now"
    assert age(NOW - timedelta(minutes=5), NOW) == "5m ago"
    assert age(NOW - timedelta(hours=3), NOW) == "3h ago"
    assert age(NOW - timedelta(days=2), NOW) == "2d ago"


def _state(status="ok", error=None, minutes=5):
    spec = SourceSpec("acme", "git@x:a/b.git", Trust.CORPORATE)
    return SourceState(spec, status, last_sync=NOW - timedelta(minutes=minutes), error=error)


def test_sync_summary():
    assert sync_summary([], NOW, syncing=False) == "no sources"
    assert sync_summary([_state()], NOW, syncing=True) == "syncing…"
    assert sync_summary([_state()], NOW, syncing=False) == "1 source · synced 5m ago"
    assert sync_summary([_state(), _state("stale", "offline")], NOW, syncing=False) == "2 sources · 1 with problems"


def test_source_detail():
    md = source_detail(_state("stale", "fatal: could not read from remote"), NOW)
    assert "**status** stale · fatal: could not read from remote" in md
    assert "corporate.toml" in md


def test_plan_text():
    plan = Plan.build("Install x", "claude-code", Scope.USER, [WriteFile(HOME / "a", b""), RunCommand(["claude", "x"])])
    lines = plan_text(plan, HOME).plain.splitlines()
    assert lines == [" + write  ~/a", " $ run    claude x"]
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/test_tui_text.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harnessctl.tui'`.

- [ ] **Step 3: Implement**

`src/harnessctl/tui/text.py`:

```python
"""Pure text builders for the TUI: list rows, detail markdown, header summaries, plan steps."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.cells import cell_len, set_cell_size
from rich.text import Text

from harnessctl.engine import CatalogEntry
from harnessctl.model import (
    HARNESSES,
    ClaudePluginVariant,
    FilesVariant,
    InstalledItem,
    NpmPluginVariant,
    Scope,
    SkillVariant,
    Status,
    Trust,
    Variant,
)
from harnessctl.planner import Plan, step_label, step_symbol
from harnessctl.sources.cache import SourceState

HARNESS_LABEL = {"claude-code": "Claude Code", "opencode": "opencode"}
HARNESS_SHORT = {"claude-code": "CC", "opencode": "OC"}
ORIGIN_STYLE = {"corp": "bold #7fb2ff", "public": "#e8b460", "unknown": "italic #9c9990"}
STATUS_MARK = {Status.UPDATE: ("↑", "bold #5fd4c0"), Status.MODIFIED: ("±", "bold #ff8a65"),
               Status.BROKEN: ("✗", "bold red")}
STATE_STYLE = {"ok": "green", "stale": "yellow", "unavailable": "red"}
SCOPE_LETTER = {Scope.USER: "U", Scope.PROJECT: "P", Scope.LOCAL: "L"}
STEP_STYLE = {"+": "green", "~": "yellow", "−": "red", "→": "cyan", "$": "magenta"}


def _cell(text: str, width: int) -> str:
    """Pad or crop to exactly `width` terminal cells, marking a crop with an ellipsis."""
    if cell_len(text) > width:
        return set_cell_size(text, width - 1) + "…"
    return set_cell_size(text, width)


def short_path(path: str | Path, home: Path) -> str:
    s, h = str(path), str(home)
    if s == h:
        return "~"
    return "~" + s[len(h):] if s.startswith(h + "/") else s


def _origin_of(trust: Trust) -> str:
    return "corp" if trust is Trust.CORPORATE else "public"


def installed_row(item: InstalledItem) -> Text:
    dim = "" if item.enabled else "dim"
    mark, mark_style = STATUS_MARK.get(item.status, ("", ""))
    name = ("  " if item.parent else "") + item.name
    note = item.provenance.source or item.meta.get("event") or ""
    return Text.assemble(
        " ", ("●" if item.enabled else "○", dim), " ", (_cell(name, 24), dim), " ",
        (SCOPE_LETTER[item.scope], "dim"), "  ",
        (_cell(item.provenance.label, 8), ORIGIN_STYLE[item.provenance.origin]),
        (_cell(mark, 2), mark_style), (note, "dim"),
    )


def catalog_row(entry: CatalogEntry) -> Text:
    dim = "" if entry.available else "dim"
    support = " ".join(HARNESS_SHORT[h] if h in entry.item.variants else "–" for h in HARNESSES)
    return Text.assemble(
        " ", ("✓" if entry.installed else " ", "green"), " ", (_cell(entry.item.id, 24), dim), " ",
        (_cell(entry.item.kind.value, 8), "dim"), (support, "dim"),
    )


def source_row(state: SourceState) -> Text:
    origin = _origin_of(state.spec.trust)
    return Text.assemble(
        " ", _cell(state.spec.name, 20), " ", (_cell(origin, 8), ORIGIN_STYLE[origin]),
        (_cell(state.status, 12), STATE_STYLE[state.status]), (f"{len(state.items)} items", "dim"),
    )


def installed_detail(item: InstalledItem, home: Path) -> str:
    p = item.provenance
    origin = p.label + (f" · {p.source}" if p.source else "") + (f" @ `{p.commit[:7]}`" if p.commit else "")
    where = item.meta.get("settings") or item.meta.get("config") or item.location
    facts = [
        f"## {item.name}",
        f"{item.kind} · {item.scope} scope · {'enabled' if item.enabled else 'disabled'}",
        f"**origin** {origin}",
        f"**location** `{short_path(where, home)}`",
    ]
    lock = item.meta.get("lock")
    if lock is not None:
        facts.append(f"**version** {lock.version}")
    if item.status is Status.UPDATE:
        facts.append("**update available**: press `u`")
    if item.status is Status.MODIFIED:
        facts.append("**modified locally** since harnessctl installed it")
    if item.error:
        facts.append(f"**error** {item.error}")
    if item.readonly:
        facts.append(f"*{item.readonly}*")
    if item.also_in:
        facts.append("**also active in** " + ", ".join(item.also_in))
    description = item.meta.get("description")
    body = [description] if description and description != "(no description)" else []
    return "\n\n".join([*facts, "---", *body, item.detail]).strip()


def _variant_summary(variant: Variant) -> str:
    match variant:
        case SkillVariant():
            return "skill folder (SKILL.md)"
        case FilesVariant(files=files, settings=settings):
            text = "files " + ", ".join(f"`{dest}`" for _, dest in files)
            return text + (" + settings.json hooks" if settings else "")
        case ClaudePluginVariant():
            return f"Claude plugin `{variant.plugin_id}`"
        case NpmPluginVariant(package=package):
            return f"npm plugin `{package}`"
    return type(variant).__name__


def catalog_detail(entry: CatalogEntry) -> str:
    item = entry.item
    variants = "\n".join(
        f"- **{HARNESS_LABEL[h]}**: {_variant_summary(item.variants[h]) if h in item.variants else 'not available'}"
        for h in HARNESSES
    )
    installed = ", ".join(s.value for s in entry.installed) or "not installed"
    parts = [
        f"## {item.id}",
        f"{item.kind} · {_origin_of(entry.trust)} · {item.source} · v{item.version}",
        item.description,
        "**Harness variants**\n\n" + variants,
        f"**Installed** {installed}",
    ]
    if not entry.available:
        parts.append("*No variant for this harness.*")
    if item.readme:
        parts += ["---", item.readme]
    return "\n\n".join(p for p in parts if p)


def age(when: datetime, now: datetime) -> str:
    seconds = int((now - when).total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def source_detail(state: SourceState, now: datetime) -> str:
    spec = state.spec
    trust = "corporate" if spec.trust is Trust.CORPORATE else "public"
    parts = [f"## {spec.name}", f"{trust} source · {state.format or 'unknown format'}", f"**url** `{spec.url}`"]
    if spec.ref:
        parts.append(f"**ref** `{spec.ref}`")
    if spec.subdir:
        parts.append(f"**subdir** `{spec.subdir}`")
    parts.append(f"**status** {state.status}" + (f" · {state.error}" if state.error else ""))
    if state.commit:
        parts.append(f"**commit** `{state.commit[:7]}`")
    if state.last_sync:
        parts.append(f"**last synced** {age(state.last_sync, now)}")
    parts.append(f"**items** {len(state.items)}")
    if state.warnings:
        parts.append("**warnings**\n\n" + "\n".join(f"- {w}" for w in state.warnings))
    if spec.trust is Trust.CORPORATE:
        parts.append("*Corporate sources are managed in `~/.config/harnessctl/corporate.toml`.*")
    return "\n\n".join(parts)


def sync_summary(states: list[SourceState], now: datetime, syncing: bool) -> str:
    if syncing:
        return "syncing…"
    if not states:
        return "no sources"
    text = f"{len(states)} source{'s' if len(states) != 1 else ''}"
    problems = [s for s in states if s.status != "ok"]
    if problems:
        return f"{text} · {len(problems)} with problems"
    synced = [s.last_sync for s in states if s.last_sync]
    return f"{text} · synced {age(min(synced), now)}" if synced else text


def plan_text(plan: Plan, home: Path) -> Text:
    text = Text()
    for n, step in enumerate(plan.steps):
        symbol = step_symbol(step)
        if n:
            text.append("\n")
        text.append(f" {symbol} ", style=STEP_STYLE[symbol])
        text.append(step_label(step, home))
    return text
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_tui_text.py -v`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add src/harnessctl/tui tests/test_tui_text.py
git commit -m "feat: TUI row, detail and summary formatters"
```

---

### Task 15: TUI shell — tabs, list/detail views, responsive layout, rescan

**Files:**
- Create: `src/harnessctl/tui/views.py`, `src/harnessctl/tui/modals.py`, `src/harnessctl/tui/app.py`, `src/harnessctl/tui/app.tcss`
- Modify: `src/harnessctl/cli.py` (launch the TUI), `tests/conftest.py` (add `tui` fixture), `tests/helpers.py` (add `settle`)
- Test: `tests/test_tui.py`, `tests/test_cli.py` (append)

**Interfaces:**
- Consumes: `Engine`, `CatalogEntry`, `group_of` (Task 13); formatters (Task 14).
- Produces (`views`): `ItemList(OptionList)` with `.objects`, `.selected`, `.set_rows(groups, key)`; `DetailPane` with `.markdown` and `.show(md)`; `ListDetailView` with `.show(data)`, `.selected`, `.set_narrow(bool)`, subclass hooks `groups(data, text)`, `key(obj)`, `detail(obj)`, `empty_text`; `InstalledView`, `CatalogView`, `SourcesView`.
- Produces (`modals`): `DetailScreen(markdown)`, `TextScreen(title, text)`.
- Produces (`app`): `HarnessApp(engine, fetch=True, poll_interval=2.0)` with attributes `engine, harness, snapshot, syncing, narrow, last_outcome` and methods `rescan()`, `sync_sources()`, `poll_changes()`, actions `show_tab`, `rescan`, `switch_harness`; `Snapshot(installed, catalog, sources)`; `HeaderBar`; constants `MIN_WIDTH = 50`, `MIN_HEIGHT = 15`, `NARROW_BELOW = 100`.
- Produces (tests): fixture `tui` → `TuiEnv(env, repo)` with `.app()`; `settle(pilot)` in `tests/helpers.py`.

- [ ] **Step 1: Add the TUI fixture and helper**

Append to `tests/helpers.py`:

```python
async def settle(pilot) -> None:
    """Let workers finish and the screen catch up (workers can start further workers)."""
    for _ in range(4):
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
```

Append to `tests/conftest.py`:

```python
@dataclass
class TuiEnv:
    env: Env
    repo: Path

    def app(self, **kw):
        from harnessctl.tui.app import HarnessApp

        return HarnessApp(self.env.engine(), fetch=False, poll_interval=3600, **kw)


@pytest.fixture
def tui(env: Env, tmp_path: Path) -> TuiEnv:
    """acme as corporate source, api-conventions installed at project scope, my-notes at user scope."""
    from harnessctl.model import Scope
    from tests.helpers import EXAMPLES, make_repo, skill, write

    repo = make_repo(EXAMPLES, tmp_path / "acme")
    write(env.paths.corporate_toml, f'[[source]]\nname = "acme"\nurl = "{repo.as_uri()}"\n')
    skill(env.home / ".claude" / "skills" / "my-notes", description="Personal notes")
    engine = env.engine()
    engine.load_sources(fetch=True)
    item = engine.find_item("acme", "api-conventions")
    assert engine.apply(engine.plan_install(item, "claude-code", Scope.PROJECT)).ok
    return TuiEnv(env, repo)
```

- [ ] **Step 2: Write the failing TUI tests**

`tests/test_tui.py`:

```python
from textual.widgets import Static, TabbedContent

from harnessctl.tui.modals import DetailScreen
from harnessctl.tui.views import CatalogView, DetailPane, InstalledView, ItemList
from tests.helpers import settle, skill


def _names(app, view=InstalledView):
    return [getattr(o, "name", None) or o.item.id for o in app.query_one(view).query_one(ItemList).objects]


async def test_installed_tab_lists_items_and_header(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        assert _names(app) == ["api-conventions", "my-notes"]
        assert "Claude Code" in str(app.query_one("#harness", Static).render())
        assert "~/projects/api" in str(app.query_one("#where", Static).render())


async def test_detail_follows_the_highlight(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        pane = app.query_one(InstalledView).query_one(DetailPane)
        assert "## api-conventions" in pane.markdown and "corp · acme" in pane.markdown
        await pilot.press("down")
        assert "## my-notes" in pane.markdown and "unknown" in pane.markdown


async def test_narrow_terminal_uses_drill_in(tui):
    app = tui.app()
    async with app.run_test(size=(64, 30)) as pilot:
        await settle(pilot)
        assert app.query_one(InstalledView).query_one(DetailPane).display is False
        await pilot.press("enter")
        assert isinstance(app.screen, DetailScreen) and "## api-conventions" in app.screen.markdown
        await pilot.press("escape")
        assert not isinstance(app.screen, DetailScreen)


async def test_too_small_terminal_says_so(tui):
    app = tui.app()
    async with app.run_test(size=(40, 10)) as pilot:
        await settle(pilot)
        assert app.query_one("#too-small").display is True
        assert app.query_one("#main").display is False
        assert "need 50×15" in str(app.query_one("#too-small", Static).render())


async def test_filter_narrows_the_list(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("slash", *"notes")
        assert _names(app) == ["my-notes"]
        await pilot.press("escape")
        assert _names(app) == ["api-conventions", "my-notes"]


async def test_number_keys_switch_tabs(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("2")
        assert app.query_one(TabbedContent).active == "catalog"
        assert _names(app, CatalogView) == ["api-conventions", "block-secrets-read", "jira-context"]
        await pilot.press("3")
        assert app.query_one(TabbedContent).active == "sources"


async def test_harness_switch(tui):
    (tui.env.home / ".config" / "opencode").mkdir(parents=True)
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("h")
        await settle(pilot)
        assert app.harness == "opencode"
        assert "opencode" in str(app.query_one("#harness", Static).render())
        assert "api-conventions" in _names(app)  # seen through .claude/skills


async def test_file_changes_trigger_a_rescan(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        skill(tui.env.home / ".claude" / "skills" / "fresh")
        app.poll_changes()
        await settle(pilot)
        assert "fresh" in _names(app)
```

Append to `tests/test_cli.py`:

```python
def test_default_command_launches_the_tui(env, monkeypatch):
    from harnessctl.tui.app import HarnessApp

    launched = []
    monkeypatch.setattr(HarnessApp, "run", lambda self: launched.append(self.engine.project))
    monkeypatch.chdir(env.project)
    assert main([]) == 0
    assert launched == [env.project]
    assert env.paths.state.is_dir()
```

- [ ] **Step 3: Run to see them fail**

Run: `uv run pytest tests/test_tui.py tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harnessctl.tui.modals'`.

- [ ] **Step 4: Implement the screens**

`src/harnessctl/tui/modals.py`:

```python
"""Screens pushed over the main view."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer, Markdown, Static


class DetailScreen(Screen[None]):
    """Full-screen detail used when the terminal is too narrow for the side pane."""

    BINDINGS = [Binding("escape", "back", "back")]

    def __init__(self, markdown: str):
        super().__init__()
        self.markdown = markdown

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Markdown(self.markdown)
        yield Footer()

    def action_back(self) -> None:
        self.app.pop_screen()


class TextScreen(ModalScreen[None]):
    """Scrollable plain text (diffs)."""

    BINDINGS = [Binding("escape", "close", "close")]
    DEFAULT_CSS = """
    TextScreen { align: center middle; }
    TextScreen > VerticalScroll { width: 90%; height: 80%; border: round $accent; background: $surface; padding: 0 1; }
    """

    def __init__(self, title: str, text: str):
        super().__init__()
        self.title_text = title
        self.body = text

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(Text(self.title_text, style="bold"))
            yield Static(Text(self.body))

    def action_close(self) -> None:
        self.dismiss(None)
```

- [ ] **Step 5: Implement the views**

`src/harnessctl/tui/views.py`:

```python
"""The three tabs: a grouped list on the left, a markdown detail pane on the right."""

from __future__ import annotations

from collections.abc import Callable, Hashable
from datetime import UTC, datetime
from typing import Any

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Markdown, OptionList
from textual.widgets.option_list import Option

from harnessctl.engine import CatalogEntry, group_of
from harnessctl.model import InstalledItem, Kind, Trust
from harnessctl.sources.cache import SourceState
from harnessctl.tui.modals import DetailScreen
from harnessctl.tui.text import (
    catalog_detail,
    catalog_row,
    installed_detail,
    installed_row,
    source_detail,
    source_row,
)

Groups = list[tuple[str, list[tuple[Text, Any]]]]


class ItemList(OptionList):
    """Grouped rows with disabled group headers; every other row maps to an object."""

    DEFAULT_CSS = "ItemList { border: none; height: 1fr; width: 1fr; min-width: 40; padding: 0; }"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.objects: list[Any] = []

    @property
    def selected(self) -> Any | None:
        if self.highlighted is None or not self.objects:
            return None
        option = self.get_option_at_index(self.highlighted)
        return self.objects[int(option.id)] if option.id is not None else None

    def set_rows(self, groups: Groups, key: Callable[[Any], Hashable]) -> None:
        current = self.selected
        wanted = key(current) if current is not None else None
        options: list[Option | None] = []
        self.objects = []
        keep_id: str | None = None
        for title, rows in groups:
            if not rows:
                continue
            if options:
                options.append(None)
            options.append(Option(Text(f" {title} {len(rows)}", style="bold"), disabled=True))
            for text, obj in rows:
                option_id = str(len(self.objects))
                if wanted is not None and key(obj) == wanted:
                    keep_id = option_id
                options.append(Option(text, id=option_id))
                self.objects.append(obj)
        self.clear_options()
        self.add_options(options)
        if self.objects:
            self.highlighted = self.get_option_index(keep_id or "0")


class DetailPane(VerticalScroll):
    DEFAULT_CSS = "DetailPane { width: 1fr; border-left: solid $panel-lighten-2; padding: 0 1; }"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.markdown = ""

    def compose(self) -> ComposeResult:
        yield Markdown()

    def show(self, markdown: str) -> None:
        self.markdown = markdown
        self.query_one(Markdown).update(markdown)
        self.scroll_home(animate=False)


class ListDetailView(Vertical):
    BINDINGS = [Binding("slash", "filter", "filter"), Binding("escape", "clear_filter", "clear filter", show=False)]
    DEFAULT_CSS = """
    ListDetailView { height: 1fr; }
    ListDetailView > Input { display: none; margin: 0 1; }
    ListDetailView > Input.-shown { display: block; }
    ListDetailView > Horizontal { height: 1fr; }
    """
    empty_text = "Nothing here yet."

    def __init__(self, **kw):
        super().__init__(**kw)
        self.data: list[Any] = []

    def compose(self) -> ComposeResult:
        yield Input(placeholder="filter…")
        with Horizontal():
            yield ItemList()
            yield DetailPane()

    # --- hooks for subclasses ----------------------------------------------------------------

    def groups(self, data: list[Any], text: str) -> Groups:
        raise NotImplementedError

    def key(self, obj: Any) -> Hashable:
        return id(obj)

    def detail(self, obj: Any) -> str:
        raise NotImplementedError

    # --- behaviour ---------------------------------------------------------------------------

    @property
    def selected(self) -> Any | None:
        return self.query_one(ItemList).selected

    def show(self, data: list[Any]) -> None:
        self.data = data
        self._render()

    def set_narrow(self, narrow: bool) -> None:
        self.query_one(DetailPane).display = not narrow

    def _render(self) -> None:
        text = self.query_one(Input).value.strip().lower()
        self.query_one(ItemList).set_rows(self.groups(self.data, text), self.key)
        self._update_detail()

    def _update_detail(self) -> None:
        obj = self.selected
        self.query_one(DetailPane).show(self.detail(obj) if obj is not None else self.empty_text)

    def action_filter(self) -> None:
        box = self.query_one(Input)
        box.add_class("-shown")
        box.focus()

    def action_clear_filter(self) -> None:
        box = self.query_one(Input)
        box.value = ""
        box.remove_class("-shown")
        self.query_one(ItemList).focus()

    @on(Input.Changed)
    def _filter_changed(self) -> None:
        self._render()

    @on(Input.Submitted)
    def _filter_done(self) -> None:
        self.query_one(ItemList).focus()

    @on(OptionList.OptionHighlighted)
    def _highlighted(self) -> None:
        self._update_detail()

    @on(OptionList.OptionSelected)
    def _selected(self) -> None:
        obj = self.selected
        if obj is not None and not self.query_one(DetailPane).display:
            self.app.push_screen(DetailScreen(self.detail(obj)))


GROUPS = [("Skills", Kind.SKILL), ("Hooks", Kind.HOOK), ("Plugins", Kind.PLUGIN)]


class InstalledView(ListDetailView):
    empty_text = "Nothing installed yet. Open the **Catalog** tab (press `2`) to install something."

    def groups(self, items: list[InstalledItem], text: str) -> Groups:
        def keep(i: InstalledItem) -> bool:
            haystack = f"{i.name} {i.provenance.label} {i.provenance.source or ''}".lower()
            return not text or text in haystack

        return [(title, [(installed_row(i), i) for i in items if group_of(i) is kind and keep(i)])
                for title, kind in GROUPS]

    def key(self, item: InstalledItem) -> Hashable:
        return (item.harness, item.scope, item.location)

    def detail(self, item: InstalledItem) -> str:
        return installed_detail(item, self.app.engine.paths.home)


class CatalogView(ListDetailView):
    empty_text = "No catalog items. Add a source in the **Sources** tab (press `3`)."

    def groups(self, entries: list[CatalogEntry], text: str) -> Groups:
        by_source: dict[str, list[CatalogEntry]] = {}
        for entry in entries:
            by_source.setdefault(entry.item.source, []).append(entry)
        groups: Groups = []
        for source, group in by_source.items():
            trust = "corp" if group[0].trust is Trust.CORPORATE else "public"
            rows = [(catalog_row(e), e) for e in group
                    if not text or text in f"{e.item.id} {e.item.kind} {e.item.source} {e.item.description}".lower()]
            groups.append((f"{source} · {trust}", rows))
        return groups

    def key(self, entry: CatalogEntry) -> Hashable:
        return (entry.item.source, entry.item.id)

    def detail(self, entry: CatalogEntry) -> str:
        return catalog_detail(entry)


class SourcesView(ListDetailView):
    empty_text = ("No sources. Press `a` to add a public git repo, "
                  "or ask IT for `~/.config/harnessctl/corporate.toml`.")

    def groups(self, states: list[SourceState], text: str) -> Groups:
        def rows(trust: Trust) -> list[tuple[Text, SourceState]]:
            return [(source_row(s), s) for s in states
                    if s.spec.trust is trust and (not text or text in s.spec.name)]

        return [("Corporate", rows(Trust.CORPORATE)), ("Public", rows(Trust.PUBLIC))]

    def key(self, state: SourceState) -> Hashable:
        return state.spec.name

    def detail(self, state: SourceState) -> str:
        return source_detail(state, datetime.now(UTC))
```

- [ ] **Step 6: Implement the app**

`src/harnessctl/tui/app.tcss`:

```css
#main { height: 1fr; }
#too-small { display: none; width: 1fr; height: 1fr; content-align: center middle; text-style: bold; }
TabbedContent { height: 1fr; }
TabPane { padding: 0; }
```

`src/harnessctl/tui/app.py`:

```python
"""The harnessctl Textual application: header, three tabs, footer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.widgets import Footer, Static, TabbedContent, TabPane

from harnessctl.engine import CatalogEntry, Engine
from harnessctl.model import InstalledItem
from harnessctl.sources.cache import SourceState
from harnessctl.tui.text import short_path, sync_summary
from harnessctl.tui.views import CatalogView, InstalledView, ItemList, ListDetailView, SourcesView

MIN_WIDTH, MIN_HEIGHT, NARROW_BELOW = 50, 15, 100


@dataclass
class Snapshot:
    installed: list[InstalledItem] = field(default_factory=list)
    catalog: list[CatalogEntry] = field(default_factory=list)
    sources: list[SourceState] = field(default_factory=list)


class HeaderBar(Horizontal):
    DEFAULT_CSS = """
    HeaderBar { height: 1; background: $panel; }
    HeaderBar > Static { width: auto; padding: 0 1; }
    HeaderBar > #brand { text-style: bold; }
    HeaderBar > #harness { background: $boost; }
    HeaderBar > #where { width: 1fr; color: $text-muted; }
    HeaderBar > #sync { color: $text-muted; }
    """

    def compose(self) -> ComposeResult:
        yield Static("harnessctl", id="brand")
        yield Static(id="harness")
        yield Static(id="where")
        yield Static(id="sync")

    def update_from(self, harness: str, where: str, sync: str) -> None:
        self.query_one("#harness", Static).update(f"{harness} ▾")
        self.query_one("#where", Static).update(where)
        self.query_one("#sync", Static).update(sync)


class HarnessApp(App[None]):
    CSS_PATH = "app.tcss"
    TITLE = "harnessctl"
    BINDINGS = [
        Binding("q", "quit", "quit"),
        Binding("h", "switch_harness", "harness"),
        Binding("r", "rescan", "rescan"),
        Binding("1", "show_tab('installed')", "installed", show=False),
        Binding("2", "show_tab('catalog')", "catalog", show=False),
        Binding("3", "show_tab('sources')", "sources", show=False),
        Binding("question_mark", "show_help_panel", "help"),
    ]

    def __init__(self, engine: Engine, fetch: bool = True, poll_interval: float = 2.0):
        super().__init__()
        self.engine = engine
        self.fetch = fetch
        self.poll_interval = poll_interval
        self.harness = engine.detected()[0].id
        self.snapshot = Snapshot()
        self.syncing = True
        self.narrow = False
        self.last_outcome = ""
        self._signature: tuple | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="main"):
            yield HeaderBar()
            with TabbedContent(initial="installed", id="tabs"):
                with TabPane("Installed", id="installed"):
                    yield InstalledView()
                with TabPane("Catalog", id="catalog"):
                    yield CatalogView()
                with TabPane("Sources", id="sources"):
                    yield SourcesView()
            yield Footer()
        yield Static(f"terminal too small — need {MIN_WIDTH}×{MIN_HEIGHT}", id="too-small")

    def on_mount(self) -> None:
        self._layout(self.size.width, self.size.height)
        self._update_header()
        self.query_one(InstalledView).query_one(ItemList).focus()
        self.rescan()
        self.sync_sources()
        self.set_interval(self.poll_interval, self.poll_changes)

    # --- layout ------------------------------------------------------------------------------

    def on_resize(self, event: Resize) -> None:
        self._layout(event.size.width, event.size.height)

    def _layout(self, width: int, height: int) -> None:
        small = width < MIN_WIDTH or height < MIN_HEIGHT
        self.query_one("#main").display = not small
        self.query_one("#too-small").display = small
        self.narrow = width < NARROW_BELOW
        for view in self.query(ListDetailView):
            view.set_narrow(self.narrow)

    @on(TabbedContent.TabActivated)
    def _tab_changed(self, event: TabbedContent.TabActivated) -> None:
        event.pane.query_one(ItemList).focus()

    # --- data --------------------------------------------------------------------------------

    @work(thread=True, exclusive=True, group="sources")
    def sync_sources(self) -> None:
        self.engine.load_sources(fetch=False)
        self.call_from_thread(self.rescan)
        if self.fetch:
            self.engine.load_sources(fetch=True)
        self.syncing = False
        self.call_from_thread(self._after_sync)

    def _after_sync(self) -> None:
        for problem in self.engine.config_errors:
            self.notify(problem, title="Configuration", severity="warning", timeout=10)
        self.rescan()

    @work(thread=True, exclusive=True, group="scan")
    def rescan(self) -> None:
        signature = self._current_signature()
        snap = Snapshot(self.engine.installed(self.harness), self.engine.catalog(self.harness),
                        list(self.engine.sources))
        self._signature = signature
        self.call_from_thread(self._show, snap)

    def _show(self, snap: Snapshot) -> None:
        self.snapshot = snap
        self._update_header()
        self.query_one(InstalledView).show(snap.installed)
        self.query_one(CatalogView).show(snap.catalog)
        self.query_one(SourcesView).show(snap.sources)

    def _update_header(self) -> None:
        home = self.engine.paths.home
        project = self.engine.project
        where = short_path(project, home) if project else "no project · user scope only"
        sync = sync_summary(self.engine.sources, datetime.now(UTC), self.syncing)
        self.query_one(HeaderBar).update_from(self.engine.adapter(self.harness).label, where, sync)

    def _current_signature(self) -> tuple:
        signature = []
        for path in self.engine.watched_paths():
            try:
                signature.append((str(path), path.stat().st_mtime_ns))
            except OSError:
                signature.append((str(path), None))
        return tuple(signature)

    def poll_changes(self) -> None:
        if self._signature is not None and self._current_signature() != self._signature:
            self.rescan()

    # --- actions -----------------------------------------------------------------------------

    def action_show_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab

    def action_rescan(self) -> None:
        self.rescan()

    def action_switch_harness(self) -> None:
        ids = [a.id for a in self.engine.detected()]
        if len(ids) < 2:
            self.notify("Only one harness is set up on this machine.", timeout=3)
            return
        self.harness = ids[(ids.index(self.harness) + 1) % len(ids)] if self.harness in ids else ids[0]
        self._update_header()
        self.rescan()
```

- [ ] **Step 7: Launch the TUI from the CLI** — in `src/harnessctl/cli.py`, add `import logging` at the top and replace `main`:

```python
def _setup_logging(paths) -> None:
    paths.state.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=paths.log_file, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate":
        return _validate(args.path)

    from harnessctl.config import Paths, find_project
    from harnessctl.engine import Engine
    from harnessctl.tui.app import HarnessApp

    paths = Paths.from_env()
    _setup_logging(paths)
    project = args.project.resolve() if args.project else find_project(Path.cwd())
    HarnessApp(Engine(paths, project)).run()
    return 0
```

- [ ] **Step 8: Run the tests**

Run: `uv run pytest tests/test_tui.py tests/test_cli.py -v`
Expected: all pass (8 TUI, 6 CLI). If `test_harness_switch` fails because `api-conventions` is missing, check that the opencode adapter lists project `.claude/skills` (Task 12) — it should.

- [ ] **Step 9: Try it by hand**

Run: `uv run harnessctl` in a real terminal from this repo. Expected: the header shows `Claude Code ▾` and `~/projects/…`; your real `~/.claude` skills and plugins are listed with `unknown` or `public` badges; `2` and `3` switch tabs; `q` quits and the terminal is restored. Shrink the window below 100 columns: the detail pane disappears and Enter opens it full-screen.

- [ ] **Step 10: Commit**

```bash
git add src/harnessctl/tui src/harnessctl/cli.py tests/conftest.py tests/helpers.py tests/test_tui.py tests/test_cli.py
git commit -m "feat: TUI shell with tabs, list/detail views and responsive layout"
```

---

### Task 16: Changes from the TUI — plan modal, scope picker, apply, editor

**Files:**
- Modify: `src/harnessctl/tui/modals.py` (add `PlanModal`, `ScopePicker`), `src/harnessctl/tui/views.py` (bindings on `InstalledView`, `CatalogView`), `src/harnessctl/tui/app.py` (add `propose`, `apply_plan`, `install`, `edit_item`, `_report`)
- Test: `tests/test_tui_actions.py`

**Interfaces:**
- Consumes: `Engine.plan_*`, `Engine.apply`, `Engine.scopes` (Task 13); `plan_text` (Task 14); `plan_diff`, `PlanConflict`, `PlanError` (Task 8); `ConfigError` (Task 2).
- Produces: `PlanModal(plan, home, harness_label)` dismissing with the `Plan` (apply) or `None`; `ScopePicker(item_id, choices: list[tuple[Scope, str]])` dismissing with a `Scope` or `None`; `HarnessApp.propose(build: Callable[[], Plan])`, `.apply_plan(plan)` (thread worker), `.install(entry: CatalogEntry)`, `.edit_item(item)`, `._report(message, title, error=False)` which also sets `last_outcome`. Keys: Installed `space` toggle, `u` update, `d` remove, `o` open in `$EDITOR`; Catalog `i` install; modal `enter` apply, `v` diff, `esc` cancel.

- [ ] **Step 1: Write the failing tests**

`tests/test_tui_actions.py`:

```python
import contextlib
import json

from harnessctl.tui.app import HarnessApp
from harnessctl.tui.modals import PlanModal, ScopePicker, TextScreen
from harnessctl.tui.views import InstalledView, ItemList
from tests.helpers import settle


def _items(app):
    return {i.name: i for i in app.query_one(InstalledView).query_one(ItemList).objects}


async def test_toggle_through_the_plan_modal(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("space")
        assert isinstance(app.screen, PlanModal)
        assert app.screen.plan.title == "Disable api-conventions (project)"
        await pilot.press("enter")
        await settle(pilot)
        assert _items(app)["api-conventions"].enabled is False
        assert not (tui.env.project / ".claude" / "skills" / "api-conventions").exists()


async def test_cancel_changes_nothing(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("space", "escape")
        await settle(pilot)
        assert not isinstance(app.screen, PlanModal)
        assert (tui.env.project / ".claude" / "skills" / "api-conventions" / "SKILL.md").is_file()


async def test_diff_view(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("d", "v")
        assert isinstance(app.screen, TextScreen)
        await pilot.press("escape")
        assert isinstance(app.screen, PlanModal)


async def test_install_from_catalog_with_scope_picker(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("2", "down", "i")
        assert isinstance(app.screen, ScopePicker)
        await pilot.press("enter")  # first choice: user
        assert isinstance(app.screen, PlanModal)
        assert app.screen.plan.title == "Install block-secrets-read → user"
        await pilot.press("enter")
        await settle(pilot)
        settings = json.loads((tui.env.home / ".claude" / "settings.json").read_text())
        assert "PreToolUse" in settings["hooks"]
        assert "block-secrets-read" in _items(app)


async def test_file_changed_while_modal_open_is_refused(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("space")
        (tui.env.project / ".claude" / "skills" / "api-conventions" / "SKILL.md").write_text("edited by the agent")
        await pilot.press("enter")
        await settle(pilot)
        assert "changed since the plan was made" in app.last_outcome
        assert (tui.env.project / ".claude" / "skills" / "api-conventions" / "SKILL.md").read_text() == "edited by the agent"


async def test_refused_action_explains_why(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("down", "u")
        assert not isinstance(app.screen, PlanModal)
        assert "not installed by harnessctl" in app.last_outcome


async def test_open_in_editor(tui, monkeypatch):
    calls = []
    monkeypatch.setenv("EDITOR", "myeditor --wait")
    monkeypatch.setattr(HarnessApp, "suspend", lambda self: contextlib.nullcontext())
    monkeypatch.setattr("harnessctl.tui.app.run_editor", calls.append)
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("o")
        skill_md = tui.env.project / ".claude" / "skills" / "api-conventions" / "SKILL.md"
        assert calls == [["myeditor", "--wait", str(skill_md)]]
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/test_tui_actions.py -v`
Expected: FAIL — `ImportError: cannot import name 'PlanModal'`.

- [ ] **Step 3: Add the modals** — append to `src/harnessctl/tui/modals.py` (and extend its imports: `from pathlib import Path`, `from textual import on`, `from textual.containers import Vertical`, `from textual.widgets import OptionList`, `from textual.widgets.option_list import Option`, `from harnessctl.model import Scope`, `from harnessctl.planner import Plan, plan_diff`, `from harnessctl.tui.text import plan_text`):

```python
class PlanModal(ModalScreen[Plan | None]):
    """Shows every step of a plan; Enter applies it, Esc cancels."""

    BINDINGS = [Binding("enter", "apply", "apply"), Binding("v", "diff", "view diff"),
                Binding("escape", "cancel", "cancel")]
    DEFAULT_CSS = """
    PlanModal { align: center middle; }
    PlanModal > Vertical { width: 96; max-width: 100%; height: auto; max-height: 90%;
                           border: round $accent; background: $surface; padding: 1 2; }
    PlanModal .dim { color: $text-muted; }
    PlanModal #plan-steps { margin: 1 0; }
    """

    def __init__(self, plan: Plan, home: Path, harness_label: str):
        super().__init__()
        self.plan = plan
        self.home = home
        self.harness_label = harness_label

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(Text(self.plan.title, style="bold"))
            yield Static(f"{self.harness_label} · {self.plan.scope} scope", classes="dim")
            yield Static(plan_text(self.plan, self.home) if self.plan.steps else "Nothing to do.", id="plan-steps")
            if self.plan.reload_hint:
                yield Static(self.plan.reload_hint, classes="dim")
            yield Static(Text.assemble(("enter", "bold"), " apply   ", ("v", "bold"), " view diff   ",
                                       ("esc", "bold"), " cancel"))

    def action_apply(self) -> None:
        self.dismiss(self.plan)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_diff(self) -> None:
        self.app.push_screen(TextScreen("Diff", plan_diff(self.plan)))


class ScopePicker(ModalScreen[Scope | None]):
    BINDINGS = [Binding("escape", "cancel", "cancel")]
    DEFAULT_CSS = """
    ScopePicker { align: center middle; }
    ScopePicker > Vertical { width: 70; max-width: 100%; height: auto; border: round $accent;
                             background: $surface; padding: 1 2; }
    ScopePicker OptionList { height: auto; border: none; margin-top: 1; }
    """

    def __init__(self, item_id: str, choices: list[tuple[Scope, str]]):
        super().__init__()
        self.item_id = item_id
        self.choices = choices

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(Text(f"Install {self.item_id} where?", style="bold"))
            yield OptionList(*[Option(f"{scope.value:<8} {where}", id=scope.value) for scope, where in self.choices])

    def on_mount(self) -> None:
        self.query_one(OptionList).highlighted = 0

    @on(OptionList.OptionSelected)
    def _chosen(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(Scope(event.option.id))

    def action_cancel(self) -> None:
        self.dismiss(None)
```

- [ ] **Step 4: Add the view bindings** — in `src/harnessctl/tui/views.py`, give `InstalledView` and `CatalogView` these members:

```python
class InstalledView(ListDetailView):
    BINDINGS = [Binding("space", "toggle", "enable/disable"), Binding("u", "update", "update"),
                Binding("d", "remove", "remove"), Binding("o", "edit", "open in $EDITOR")]
    # … existing empty_text, groups, key, detail …

    def _propose(self, method: str) -> None:
        item = self.selected
        if item is not None:
            engine = self.app.engine
            self.app.propose(lambda: getattr(engine, method)(item))

    def action_toggle(self) -> None:
        self._propose("plan_toggle")

    def action_update(self) -> None:
        self._propose("plan_update")

    def action_remove(self) -> None:
        self._propose("plan_remove")

    def action_edit(self) -> None:
        if self.selected is not None:
            self.app.edit_item(self.selected)


class CatalogView(ListDetailView):
    BINDINGS = [Binding("i", "install", "install")]
    # … existing empty_text, groups, key, detail …

    def action_install(self) -> None:
        if self.selected is not None:
            self.app.install(self.selected)
```

- [ ] **Step 5: Add the app methods** — in `src/harnessctl/tui/app.py` add this module-level function (tests replace it, so it must stay a module global looked up at call time):

```python
def run_editor(argv: list[str]) -> None:
    subprocess.run(argv, check=False)
```

Then add imports `import os`, `import shlex`, `import subprocess`, `from collections.abc import Callable`, `from pathlib import Path`, `from textual.app import SuspendNotSupported`, `from harnessctl.config import ConfigError`, `from harnessctl.model import Scope`, `from harnessctl.planner import Plan, PlanConflict, PlanError`, `from harnessctl.tui.modals import PlanModal, ScopePicker`, then add to `HarnessApp`:

```python
    # --- changes -----------------------------------------------------------------------------

    def _report(self, message: str, title: str, error: bool = False) -> None:
        self.last_outcome = message
        self.notify(message, title=title, severity="error" if error else "information", timeout=12 if error else 6)

    def propose(self, build: Callable[[], Plan]) -> None:
        try:
            plan = build()
        except (PlanError, ConfigError) as exc:
            self._report(str(exc), "Cannot do that", error=True)
            return
        label = self.engine.adapter(plan.harness).label
        self.push_screen(PlanModal(plan, self.engine.paths.home, label), self._confirmed)

    def _confirmed(self, plan: Plan | None) -> None:
        if plan is not None:
            self.apply_plan(plan)

    @work(thread=True, group="apply")
    def apply_plan(self, plan: Plan) -> None:
        try:
            result = self.engine.apply(plan)
        except PlanConflict as exc:
            self.call_from_thread(self._report, f"{exc}\nNothing was changed.", plan.title, True)
        else:
            if result.ok:
                self.call_from_thread(self._report, plan.reload_hint or "Done.", plan.title)
            else:
                message = f"Step {result.failed_step + 1} failed: {result.error}\nEvery change was rolled back."
                self.call_from_thread(self._report, message, plan.title, True)
        self.call_from_thread(self.rescan)

    def install(self, entry: CatalogEntry) -> None:
        adapter = self.engine.adapter(self.harness)
        if not entry.available:
            self._report(f"{entry.item.id} has no {adapter.label} variant.", "Cannot do that", error=True)
            return
        scopes = self.engine.scopes()
        if len(scopes) == 1:
            self.propose(lambda: self.engine.plan_install(entry.item, self.harness, Scope.USER))
            return
        home = self.engine.paths.home
        choices = [(s, short_path(adapter.scope_dir(s, self.engine.project), home)) for s in scopes]

        def chosen(scope: Scope | None) -> None:
            if scope is not None:
                self.propose(lambda: self.engine.plan_install(entry.item, self.harness, scope))

        self.push_screen(ScopePicker(entry.item.id, choices), chosen)

    def edit_item(self, item: InstalledItem) -> None:
        target = Path(item.meta.get("settings") or item.meta.get("config") or item.meta.get("install_path")
                      or item.location)
        if target.is_dir() and (target / "SKILL.md").is_file():
            target = target / "SKILL.md"
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
        try:
            with self.suspend():
                run_editor([*shlex.split(editor), str(target)])
        except SuspendNotSupported:
            self._report("Opening an editor is not supported in this terminal.", "Cannot do that", error=True)
            return
        self.rescan()
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_tui_actions.py tests/test_tui.py -v`
Expected: all pass (7 + 8).

- [ ] **Step 7: Commit**

```bash
git add src/harnessctl/tui tests/test_tui_actions.py
git commit -m "feat: plan modal, scope picker, apply and editor from the TUI"
```

---

### Task 17: Sources tab actions

**Files:**
- Modify: `src/harnessctl/tui/modals.py` (add `AddSourceScreen`), `src/harnessctl/tui/views.py` (bindings on `SourcesView`), `src/harnessctl/tui/app.py` (add `add_source`, `refresh_source`, `remove_source`)
- Test: `tests/test_tui_sources.py`

**Interfaces:**
- Consumes: `Engine.add_source`, `.refresh_source`, `.remove_source` (Task 13); `_report`, `rescan` (Tasks 15–16).
- Produces: `AddSourceScreen()` dismissing with `{"url": str, "name": str | None, "ref": str | None}` or `None`; `HarnessApp.add_source(answer)`, `.refresh_source(name)` (thread worker), `.remove_source(name)`. Sources keys: `a` add, `r` refresh, `d` remove.

- [ ] **Step 1: Write the failing tests**

`tests/test_tui_sources.py`:

```python
from textual.widgets import Input

from harnessctl.tui.modals import AddSourceScreen
from harnessctl.tui.views import CatalogView, DetailPane, ItemList, SourcesView
from tests.helpers import make_repo, settle, skill


def _sources(app):
    return [s.spec.name for s in app.query_one(SourcesView).query_one(ItemList).objects]


async def test_sources_tab_shows_corporate_source(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("3")
        assert _sources(app) == ["acme"]
        assert "corporate.toml" in app.query_one(SourcesView).query_one(DetailPane).markdown


async def test_add_and_remove_a_public_source(tui, tmp_path):
    public = tmp_path / "pub"
    skill(public / "skills" / "tdd")
    make_repo(None, public)
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("3", "a")
        assert isinstance(app.screen, AddSourceScreen)
        app.screen.query_one("#url", Input).value = public.as_uri()
        app.screen.query_one("#name", Input).value = "pub"
        await pilot.press("enter")
        await settle(pilot)
        assert _sources(app) == ["acme", "pub"]
        assert "tdd" in [e.item.id for e in app.query_one(CatalogView).query_one(ItemList).objects]
        await pilot.press("down", "d")
        await settle(pilot)
        assert _sources(app) == ["acme"]


async def test_corporate_source_cannot_be_removed(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("3", "d")
        await settle(pilot)
        assert "corporate sources are managed in corporate.toml" in app.last_outcome
        assert _sources(app) == ["acme"]


async def test_refresh_reports_status(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("3", "r")
        await settle(pilot)
        assert app.last_outcome == "acme: ok, 3 items"
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/test_tui_sources.py -v`
Expected: FAIL — `ImportError: cannot import name 'AddSourceScreen'`.

- [ ] **Step 3: Add the screen** — append to `src/harnessctl/tui/modals.py` (add `from textual.widgets import Input` to its imports):

```python
class AddSourceScreen(ModalScreen[dict | None]):
    BINDINGS = [Binding("escape", "cancel", "cancel")]
    DEFAULT_CSS = """
    AddSourceScreen { align: center middle; }
    AddSourceScreen > Vertical { width: 80; max-width: 100%; height: auto; border: round $accent;
                                 background: $surface; padding: 1 2; }
    AddSourceScreen .dim { color: $text-muted; }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(Text("Add a public source", style="bold"))
            yield Static("A git URL: a harnessctl catalog, a Claude plugin marketplace or a skills repo.",
                         classes="dim")
            yield Input(placeholder="https://github.com/owner/repo", id="url")
            yield Input(placeholder="name (optional)", id="name")
            yield Input(placeholder="branch or tag (optional)", id="ref")
            yield Static(Text.assemble(("enter", "bold"), " add   ", ("esc", "bold"), " cancel"), classes="dim")

    @on(Input.Submitted)
    def _submit(self) -> None:
        url = self.query_one("#url", Input).value.strip()
        if not url:
            self.query_one("#url", Input).focus()
            return
        self.dismiss({"url": url, "name": self.query_one("#name", Input).value.strip() or None,
                      "ref": self.query_one("#ref", Input).value.strip() or None})

    def action_cancel(self) -> None:
        self.dismiss(None)
```

- [ ] **Step 4: Add the bindings** — give `SourcesView` in `src/harnessctl/tui/views.py`:

```python
class SourcesView(ListDetailView):
    BINDINGS = [Binding("a", "add", "add source"), Binding("r", "refresh", "refresh"),
                Binding("d", "remove", "remove")]
    # … existing empty_text, groups, key, detail …

    def action_add(self) -> None:
        from harnessctl.tui.modals import AddSourceScreen

        self.app.push_screen(AddSourceScreen(), self.app.add_source)

    def action_refresh(self) -> None:
        if self.selected is not None:
            self.app.refresh_source(self.selected.spec.name)

    def action_remove(self) -> None:
        if self.selected is not None:
            self.app.remove_source(self.selected.spec.name)
```

- [ ] **Step 5: Add the app methods** — add to `HarnessApp` in `src/harnessctl/tui/app.py`:

```python
    # --- sources -----------------------------------------------------------------------------

    @staticmethod
    def _source_outcome(state: SourceState) -> str:
        if state.error:
            return f"{state.spec.name}: {state.status} — {state.error}"
        return f"{state.spec.name}: {state.status}, {len(state.items)} items"

    def add_source(self, answer: dict | None) -> None:
        if answer:
            self._add_source(answer)

    @work(thread=True, group="sources")
    def _add_source(self, answer: dict) -> None:
        try:
            state = self.engine.add_source(answer["url"], name=answer["name"], ref=answer["ref"])
        except ConfigError as exc:
            self.call_from_thread(self._report, str(exc), "Cannot add source", True)
            return
        self.call_from_thread(self._report, self._source_outcome(state), "Source added", state.status != "ok")
        self.call_from_thread(self.rescan)

    @work(thread=True, group="sources")
    def refresh_source(self, name: str) -> None:
        state = self.engine.refresh_source(name)
        self.call_from_thread(self._report, self._source_outcome(state), "Source refreshed", state.status != "ok")
        self.call_from_thread(self.rescan)

    def remove_source(self, name: str) -> None:
        try:
            self.engine.remove_source(name)
        except ConfigError as exc:
            self._report(str(exc), "Cannot remove source", error=True)
            return
        self._report(f"{name} removed.", "Source removed")
        self.rescan()
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_tui_sources.py -v`
Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add src/harnessctl/tui tests/test_tui_sources.py
git commit -m "feat: add, refresh and remove sources from the TUI"
```

---

### Task 18: Snapshots, README and final verification

**Files:**
- Create: `tests/test_snapshots.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: the `tui` fixture and `settle` (Task 15).
- Produces: SVG snapshots under `tests/__snapshots__/`; user documentation.

- [ ] **Step 1: Write the snapshot tests**

`tests/test_snapshots.py`:

```python
"""Pinned frames at the sizes the spec names (120×30 wide, 80×24 standard, 64×30 split)."""

from tests.helpers import settle


def test_installed_wide(snap_compare, tui):
    assert snap_compare(tui.app(), terminal_size=(120, 30), run_before=settle)


def test_installed_standard(snap_compare, tui):
    assert snap_compare(tui.app(), terminal_size=(80, 24), run_before=settle)


def test_catalog_split(snap_compare, tui):
    async def run_before(pilot):
        await settle(pilot)
        await pilot.press("2")
        await settle(pilot)

    assert snap_compare(tui.app(), terminal_size=(64, 30), run_before=run_before)


def test_plan_modal(snap_compare, tui):
    async def run_before(pilot):
        await settle(pilot)
        await pilot.press("space")
        await settle(pilot)

    assert snap_compare(tui.app(), terminal_size=(120, 30), run_before=run_before)
```

- [ ] **Step 2: Generate and review the snapshots**

Run: `uv run pytest tests/test_snapshots.py --snapshot-update && uv run pytest tests/test_snapshots.py -v`
Expected: first command writes 4 SVGs; second passes. Open `snapshot_report.html` (or the SVGs in `tests/__snapshots__/`) and check by eye: header on one line, no border inside another border, `corp`/`unknown` words beside each row, a status mark only on items that need attention, the 64-column frame showing the list only.

- [ ] **Step 3: Write the README**

`README.md`:

````markdown
# harnessctl

A terminal UI to see and manage what your coding agent is configured with: **skills, hooks
and plugins** for **Claude Code** and **opencode**. Run it in a pane next to your agent.

- **Installed**: everything active for this machine (user scope) and this repo (project scope),
  each item labelled `corp` (from your company's catalog), `public` (from a public repo) or
  `unknown`, with `↑` when an update is available and `±` when you edited it locally.
- **Catalog**: browse the corporate catalog and the public sources you added; install with `i`.
- **Sources**: add public git repos (harnessctl catalogs, Claude plugin marketplaces, skills repos).

Every change is shown as a plan first (files written, settings keys merged, commands run) and
applied all-or-nothing, with a backup under `~/.local/state/harnessctl/backups/`.

## Install

```bash
uv tool install git+https://github.com/cfrancois7/harnessctl@main
harnessctl                # opens the TUI for the current repo
harnessctl --project DIR  # or for another one
```

## Keys

| Where | Keys |
|---|---|
| everywhere | `1` `2` `3` tabs · `h` switch harness · `r` rescan · `/` filter · `?` help · `q` quit |
| Installed | `space` enable/disable · `u` update · `d` remove · `o` open in `$EDITOR` |
| Catalog | `i` install (then pick user or project scope) |
| Sources | `a` add · `r` refresh · `d` remove |
| plan | `enter` apply · `v` view diff · `esc` cancel |

Below 100 columns the detail pane is hidden: `enter` opens it full-screen, `esc` goes back.

## Configuration

`~/.config/harnessctl/corporate.toml` lists the corporate sources. harnessctl never writes this
file; your company distributes it:

```toml
[[source]]
name = "acme"
url  = "git@gitlab.acme.io:platform/agent-catalog.git"
ref  = "main"
```

Public sources you add from the TUI go to `~/.config/harnessctl/config.toml`. Git uses your own
credentials (SSH agent or credential helper).

What harnessctl installed is recorded in `~/.config/harnessctl/lock.json` (user scope) and
`<repo>/.harnessctl/lock.json` (project scope, commit it so your team sees the same provenance).

## Writing a catalog

See [`examples/acme-catalog/`](examples/acme-catalog/README.md). Check a catalog with:

```bash
harnessctl validate path/to/catalog   # exit 1 and one line per problem; use it in the catalog's CI
```

## Limits

- harnessctl never rewrites a JSON file that contains comments (such as a commented
  `opencode.jsonc`); it tells you the edit to make instead.
- Claude Code's `settings.local.json` is shown but never changed.
- Hooks are never translated between harnesses: a catalog item ships one variant per harness.

## Development

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run harnessctl
```
````

- [ ] **Step 4: Full verification**

Run each and check the output:
- `uv run pytest -q` → all tests pass, 0 failures.
- `uv run ruff check . && uv run ruff format --check .` → no issues.
- `uv run harnessctl validate examples/acme-catalog` → `catalog ok: 3 items`, exit 0.
- `uv tool install --editable . --force && harnessctl --version` → `harnessctl 0.1.0`.
- `uv run harnessctl` in a real terminal, next to a Claude Code session: switch tabs, filter, open a detail at a narrow width, press `space` on an item and cancel with `esc`, quit with `q`; the shell prompt comes back clean.

- [ ] **Step 5: Commit and push**

```bash
git add README.md tests/test_snapshots.py tests/__snapshots__
git commit -m "docs: README; test: pinned TUI snapshots"
git push origin develop
```
