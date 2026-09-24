"""Where harnessctl keeps its files, and the source lists it reads."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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
            home, xdg_config / "harnessctl", xdg_cache / "harnessctl", xdg_state / "harnessctl", xdg_config
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
