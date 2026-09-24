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
        return cls(
            home,
            xdg_config / "harnessctl",
            xdg_cache / "harnessctl",
            xdg_state / "harnessctl",
            xdg_config,
        )

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
            msg = f"{paths.config_toml}: source '{spec.name}' shadows a corporate source and is ignored"
            errors.append(msg)
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
