"""Claude Code: skills in .claude/skills, hooks in settings.json, plugins via the `claude plugin` CLI."""

from __future__ import annotations

import json
import shlex
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
from harnessctl.edits import expand_placeholders, hook_location, merge_hooks_edit, remove_hooks_edit
from harnessctl.jsonio import JsonFileError, read_json
from harnessctl.model import (
    CatalogItem,
    ClaudePluginVariant,
    FilesVariant,
    InstalledItem,
    Kind,
    Scope,
    SkillVariant,
    Status,
)
from harnessctl.parking import park_dir, park_steps, scan_parked, unpark_steps
from harnessctl.planner import DeletePath, EditJson, MovePath, PlanError, RunCommand, Step


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
        case "git" | "url" if isinstance(source.get("url"), str):
            return source["url"]
    return None


def _remove_this_hook(inst: InstalledItem) -> Callable[[object], dict]:
    m = inst.meta
    return remove_hooks_edit(m["event"], m.get("matcher"), m["command"], m.get("occurrence", 0))


def _neighbours(path: Path, m: dict, parking: Path) -> dict:
    """Where the hook sits, for a restore in any order: the other hooks of its group, before
    and after it (plus hooks parked earlier from that group, which recorded this one as their
    neighbour), and the other groups of its event, before and after its group."""
    try:
        groups = read_json(path, default={})["hooks"][m["event"]]
        n, gi = m["hook_index"], m["group_index"]
        hooks = groups[gi]["hooks"]
        before, after = list(hooks[:n]), list(hooks[n + 1 :])
        snapshot = [
            {"matcher": g.get("matcher"), "hooks": g.get("hooks", [])} for g in groups if isinstance(g, dict)
        ]
        own = sum(isinstance(g, dict) for g in groups[:gi])
    except JsonFileError, KeyError, IndexError, TypeError, AttributeError:
        return {"before": [], "after": [], "groups_before": [], "groups_after": []}
    for meta_file in sorted(parking.glob("*/meta.json")):
        try:
            other = json.loads(meta_file.read_text(encoding="utf-8"))["restore"]
        except OSError, ValueError, KeyError, TypeError:
            continue
        same = (other.get("type"), other.get("settings"), other.get("event")) == (
            "hook",
            str(path),
            m["event"],
        )
        if not same or (other.get("group") or {}).get("matcher") != m.get("matcher"):
            continue
        if m["hook"] in other.get("before", []):
            after.append(other["hook"])
        if m["hook"] in other.get("after", []):
            before.append(other["hook"])
    return {
        "before": before,
        "after": after,
        "groups_before": snapshot[:own],
        "groups_after": snapshot[own + 1 :],
    }


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
        seen: dict[tuple, int] = {}
        for event, groups in (hooks if isinstance(hooks, dict) else {}).items():
            for group_index, group in enumerate(groups if isinstance(groups, list) else []):
                if not isinstance(group, dict):
                    continue
                entries = group.get("hooks", [])
                for hook_index, hook in enumerate(entries if isinstance(entries, list) else []):
                    command = hook.get("command") if isinstance(hook, dict) else None
                    if not isinstance(command, str):
                        continue
                    matcher = group.get("matcher")
                    key = (event, str(matcher or ""), command)  # a matcher may be any JSON value
                    occurrence = seen.get(key, 0)
                    seen[key] = occurrence + 1
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
                            hook_location(path, event, matcher, command, occurrence),
                            parent=parent,
                            detail=detail,
                            readonly=readonly,
                            meta={
                                "event": event,
                                "matcher": matcher,
                                "command": command,
                                "occurrence": occurrence,
                                "group_index": group_index,
                                "hook_index": hook_index,
                                "group": {k: ([] if k == "hooks" else v) for k, v in group.items()},
                                "group_size": len(entries),
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
        installed_path = plugins_dir / "installed_plugins.json"
        try:
            data = read_json(installed_path, default={})
            markets = read_json(plugins_dir / "known_marketplaces.json", default={})
        except JsonFileError as exc:
            return [self._broken(scope, exc.path, Kind.PLUGIN, exc)]
        installed = data.get("plugins", {}) if isinstance(data, dict) else None
        if not isinstance(installed, dict):
            error = ValueError(f"{installed_path}: not a JSON object with a plugins object")
            return [self._broken(scope, installed_path, Kind.PLUGIN, error)]
        markets = markets if isinstance(markets, dict) else {}
        try:
            settings = read_json(self.settings_path(scope, project), default={})
        except JsonFileError:
            settings = {}  # the settings file itself is reported by _scan_hooks
        enabled = settings.get("enabledPlugins", {}) if isinstance(settings, dict) else {}
        enabled = enabled if isinstance(enabled, dict) else {}
        items: list[InstalledItem] = []
        for pid, records in sorted(installed.items()):
            for rec in records if isinstance(records, list) else []:
                if not isinstance(rec, dict) or rec.get("scope") != scope.value:
                    continue
                if scope is Scope.PROJECT and Path(str(rec.get("projectPath", ""))) != project:
                    continue
                items += self._plugin_items(pid, rec, scope, bool(enabled.get(pid, False)), markets)
        return items

    def _plugin_items(
        self, pid: str, rec: dict, scope: Scope, on: bool, markets: dict
    ) -> list[InstalledItem]:
        name, _, market = pid.partition("@")
        install_path = Path(str(rec.get("installPath", "")))
        meta = {"plugin_id": pid, "version": rec.get("version"), "install_path": str(install_path)}
        market_entry = markets.get(market)
        source = market_entry.get("source") if isinstance(market_entry, dict) else None
        repo = _market_url(source) if isinstance(source, dict) else None
        if repo:
            meta["repo_url"] = repo
        try:
            manifest = read_json(install_path / ".claude-plugin" / "plugin.json", default={})
        except JsonFileError:
            manifest = {}
        description = manifest.get("description", "") if isinstance(manifest, dict) else ""
        detail = f"{description}\n\n`{pid}` · version {rec.get('version', '?')}".strip()
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

    # --- changes -----------------------------------------------------------------------------

    @staticmethod
    def _cli_cwd(scope: Scope, project: Path | None) -> Path | None:
        """`claude plugin ... --scope project|local` acts on the project of its working directory."""
        if scope is Scope.USER:
            return None
        if project is None:
            raise PlanError("no project here: only user scope is available")
        return project

    def plan_install(
        self, item: CatalogItem, scope: Scope, project: Path | None, replace: bool = False
    ) -> Install:
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
                return self._install_plugin(variant, scope, project)
        raise PlanError(f"{type(variant).__name__} variants are not supported for Claude Code")

    def _install_files(
        self, variant: FilesVariant, scope: Scope, project: Path | None, replace: bool
    ) -> Install:
        scope_dir = self.scope_dir(scope, project)
        steps, hashes = write_payload_files(variant.files, scope_dir, replace, within=variant.root)
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
                    locations += [
                        hook_location(path, event, group.get("matcher"), h["command"])
                        for h in group.get("hooks", [])
                    ]
        return Install(steps, locations, hashes, settings)

    def _install_plugin(self, variant: ClaudePluginVariant, scope: Scope, project: Path | None) -> Install:
        if self._which("claude") is None:
            raise PlanError("the claude CLI is not on PATH, so plugins cannot be installed")
        try:
            markets = read_json(self.claude_dir / "plugins" / "known_marketplaces.json", default={})
        except JsonFileError:
            markets = {}
        cwd = self._cli_cwd(scope, project)
        steps: list[Step] = []
        if variant.marketplace_name not in markets:
            steps.append(
                RunCommand(["claude", "plugin", "marketplace", "add", variant.marketplace_url], cwd=cwd)
            )
        steps.append(
            RunCommand(["claude", "plugin", "install", variant.plugin_id, "--scope", scope.value], cwd=cwd)
        )
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
                return [
                    EditJson(
                        path,
                        _remove_this_hook(inst),
                        f"hooks −1 ({inst.meta['event']})",
                    )
                ]
            case Kind.PLUGIN:
                return [
                    RunCommand(
                        [
                            "claude",
                            "plugin",
                            "uninstall",
                            inst.meta["plugin_id"],
                            "--scope",
                            inst.scope.value,
                        ],
                        cwd=self._cli_cwd(inst.scope, project),
                    )
                ]

    def plan_toggle(self, inst: InstalledItem, project: Path | None) -> list[Step]:
        require_writable(inst)
        if inst.kind is Kind.PLUGIN:
            verb = "disable" if inst.enabled else "enable"
            return [
                RunCommand(
                    ["claude", "plugin", verb, inst.meta["plugin_id"], "--scope", inst.scope.value],
                    cwd=self._cli_cwd(inst.scope, project),
                )
            ]
        if not inst.enabled:
            return unpark_steps(inst)
        scope_dir = self.scope_dir(inst.scope, project)
        pdir = park_dir(self.parking, self.id, inst.location, inst.name)
        if inst.kind is Kind.SKILL:
            return park_steps(
                inst,
                pdir,
                scope_dir,
                {"type": "move", "to": inst.location},
                [MovePath(Path(inst.location), pdir / "payload")],
            )
        path = Path(inst.meta["settings"])
        ensure_json_writable(path)
        restore = {
            "type": "hook",
            "settings": str(path),
            "event": inst.meta["event"],
            "matcher": inst.meta.get("matcher"),
            "hook": inst.meta["hook"],
            "group": inst.meta["group"],
            "group_index": inst.meta["group_index"],
            "hook_index": inst.meta["hook_index"],
            **_neighbours(path, inst.meta, self.parking / self.id),
        }
        take_out = EditJson(
            path,
            _remove_this_hook(inst),
            f"hooks −1 ({inst.meta['event']}, parked)",
        )
        return park_steps(inst, pdir, scope_dir, restore, [take_out])
