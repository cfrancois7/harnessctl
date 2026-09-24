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
    except ValueError, IndexError:
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
        paths = [
            self.claude_dir / "settings.json",
            self.claude_dir / "skills",
            self.claude_dir / "plugins" / "installed_plugins.json",
            self.parking / self.id,
        ]
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
        return InstalledItem(
            self.id,
            scope,
            kind,
            path.name,
            str(path),
            status=Status.BROKEN,
            error=str(exc),
            readonly="the file cannot be parsed",
        )

    def _hooks_from(
        self, settings: dict, path: Path, scope: Scope, readonly: str | None, parent: str | None = None
    ) -> list[InstalledItem]:
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
                    detail = (
                        f"**{event}**"
                        + (f" · matcher `{matcher}`" if matcher else "")
                        + f"\n\n```\n{command}\n```"
                    )
                    items.append(
                        InstalledItem(
                            self.id,
                            scope,
                            Kind.HOOK,
                            f"{event}:{_command_name(command)}",
                            hook_location(path, event, command),
                            parent=parent,
                            detail=detail,
                            readonly=readonly,
                            meta={
                                "event": event,
                                "matcher": matcher,
                                "command": command,
                                "hook": hook,
                                "settings": str(path),
                            },
                        )
                    )
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
        except JsonFileError, AttributeError:
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

    def _plugin_items(
        self, pid: str, rec: dict, scope: Scope, on: bool, markets: dict
    ) -> list[InstalledItem]:
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
        plugin = InstalledItem(
            self.id, scope, Kind.PLUGIN, name, f"claude-plugin:{pid}", enabled=on, detail=detail, meta=meta
        )
        children = scan_skill_dirs(install_path / "skills", self.id, scope, readonly=f"part of plugin {name}")
        try:
            hooks = read_json(install_path / "hooks" / "hooks.json", default={})
        except JsonFileError:
            hooks = {}
        children += self._hooks_from(
            hooks, install_path / "hooks" / "hooks.json", scope, readonly=f"part of plugin {name}", parent=pid
        )
        for child in children:
            child.parent = pid
            child.enabled = on
        return [plugin, *children]
