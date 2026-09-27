"""The headless core the TUI drives: sources, adapters, lockfiles and plans."""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from packaging.version import InvalidVersion, Version

from harnessctl.adapters.base import Adapter, ensure_json_writable
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
from harnessctl.model import (
    CatalogItem,
    ClaudePluginVariant,
    InstalledItem,
    Kind,
    Scope,
    SourceSpec,
    Status,
    Trust,
)
from harnessctl.planner import (
    ApplyResult,
    DeletePath,
    EditJson,
    Plan,
    PlanError,
    Runner,
    apply,
    run_command,
)
from harnessctl.provenance import LockEntry, add_entry_edit, read_lock, remove_entry_edit, resolve
from harnessctl.sources.cache import SourceState, sync_source
from harnessctl.sources.formats import payload_hash

log = logging.getLogger(__name__)
KIND_ORDER = {Kind.SKILL: 0, Kind.HOOK: 1, Kind.PLUGIN: 2}


@dataclass
class CatalogEntry:
    item: CatalogItem
    trust: Trust
    available: bool  # the item can be installed for the harness being viewed
    installed: list[Scope]
    reason: str | None = None  # why it cannot be installed, when it cannot


def group_of(item: InstalledItem) -> Kind:
    """Plugin children are shown under Plugins, right after their plugin."""
    return Kind.PLUGIN if item.parent else item.kind


class Engine:
    def __init__(
        self,
        paths: Paths,
        project: Path | None,
        adapters: list[Adapter] | None = None,
        runner: Runner = run_command,
        env: dict[str, str] | None = None,
    ):
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

    def add_source(
        self, url: str, name: str | None = None, ref: str | None = None, subdir: str = ""
    ) -> SourceState:
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
                locks[scope] = read_lock(self.lock_path(scope), self.lock_errors)
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
        opencode_sees_claude = (
            harness == "claude-code"
            and any(a.id == "opencode" and a.detect() for a in self.adapters)
            and not (
                self.env.get("OPENCODE_DISABLE_CLAUDE_CODE")
                or self.env.get("OPENCODE_DISABLE_CLAUDE_CODE_SKILLS")
            )
        )
        for item in items:
            if item.parent in plugins:
                item.provenance = plugins[item.parent].provenance
            if (
                opencode_sees_claude
                and item.kind is Kind.SKILL
                and not item.parent
                and item.readonly is None
                and item.enabled
                and item.scope in (Scope.USER, Scope.PROJECT)
            ):
                item.also_in = ["opencode"]
        return sorted(
            items,
            key=lambda i: (
                KIND_ORDER[group_of(i)],
                i.parent or i.meta.get("plugin_id") or i.name,
                i.parent is not None,
                i.name,
            ),
        )

    def find_installed(self, item: InstalledItem) -> InstalledItem | None:
        """The same item in a fresh scan, matched on scope, kind and location. `location` (not
        `origin_location`) is used because several parked copies of one skill can share an
        origin location (park_dir suffixes `-2`, `-3`, ...); `location` includes the park folder
        for a parked item (`<original>::parked::<folder>`) and equals `origin_location` for an
        enabled one, so it identifies one exact copy."""
        key = (item.scope, item.kind, item.location)
        return next(
            (i for i in self.installed(item.harness) if (i.scope, i.kind, i.location) == key),
            None,
        )

    def catalog(self, harness: str) -> list[CatalogEntry]:
        adapter = self.adapter(harness)
        locks = self._locks()
        native = {
            i.location: i.scope for i in self.installed(harness) if i.location.startswith("claude-plugin:")
        }
        entries: list[CatalogEntry] = []
        for state in self.sources:
            for item in state.items:
                scopes = [
                    scope
                    for scope, es in locks.items()
                    if any((e.item_id, e.source, e.harness) == (item.id, item.source, harness) for e in es)
                ]
                variant = item.variants.get(harness)
                if isinstance(variant, ClaudePluginVariant) and not scopes:
                    found = native.get(f"claude-plugin:{variant.plugin_id}")
                    scopes = [found] if found else []
                reason = (
                    f"no {adapter.label} variant" if variant is None else adapter.unavailable_reason(variant)
                )
                entries.append(CatalogEntry(item, state.spec.trust, reason is None, scopes, reason))
        return entries

    # --- planning ----------------------------------------------------------------------------

    def _commit_of(self, source: str) -> str | None:
        return next((s.commit for s in self.sources if s.spec.name == source), None)

    @staticmethod
    def _origin(source: str, commit: str | None) -> str:
        return f"{source}@{commit[:7]}" if commit else source

    def _origin_of(self, inst: InstalledItem) -> str:
        entry: LockEntry | None = inst.meta.get("lock")
        return self._origin(entry.source, entry.commit) if entry is not None else ""

    def _check_lock_writable(self, path: Path) -> None:
        """A lock harnessctl cannot safely read back and rewrite must block planning, not
        just fail partway through apply (after side effects such as `claude plugin ...` ran)."""
        try:
            read_lock(path)
        except JsonFileError as exc:
            raise PlanError(str(exc)) from exc
        ensure_json_writable(path)

    def plan_install(self, item: CatalogItem, harness: str, scope: Scope, replace: bool = False) -> Plan:
        adapter = self.adapter(harness)
        if item.variants.get(harness) is None:
            raise PlanError(f"{item.id} has no {adapter.label} variant")
        self._check_lock_writable(self.lock_path(scope))
        inst = adapter.plan_install(item, scope, self.project, replace=replace)
        entry = LockEntry(
            item_id=item.id,
            source=item.source,
            harness=harness,
            kind=item.kind.value,
            version=item.version,
            commit=self._commit_of(item.source),
            locations=inst.locations,
            files=inst.files,
            payload_hash=payload_hash(item.variants[harness]),
            settings=inst.settings,
        )
        steps = [*inst.steps, EditJson(self.lock_path(scope), add_entry_edit(entry), f"record {item.id}")]
        return Plan.build(
            f"Install {item.id} → {scope}",
            harness,
            scope,
            steps,
            adapter.reload_hint,
            origin=self._origin(item.source, self._commit_of(item.source)),
        )

    def _scope_dir_for(self, harness: str, scope: Scope) -> Path | None:
        """The folder a lock entry's files must live under to be safe to delete. None if the
        adapter cannot resolve a scope dir here (e.g. no project) — nothing outside is then safe."""
        try:
            return self.adapter(harness).scope_dir(scope, self.project).resolve()
        except PlanError:
            return None

    def plan_remove(self, inst: InstalledItem) -> Plan:
        adapter = self.adapter(inst.harness)
        entry: LockEntry | None = inst.meta.get("lock")
        if entry is not None:
            self._check_lock_writable(self.lock_path(inst.scope))
        targets = [inst]
        if entry is not None:
            targets = [
                i
                for i in self.installed(inst.harness)
                if i.origin_location in entry.locations and i.scope is inst.scope
            ] or [inst]
        steps = [s for t in targets for s in adapter.plan_remove(t, self.project)]
        warnings: list[str] = []
        if entry is not None:
            covered = [s.path for s in steps if isinstance(s, DeletePath)]
            scope_dir = self._scope_dir_for(inst.harness, inst.scope)
            for f in entry.files:
                path = Path(f)
                if not (path.exists() or path.is_symlink()) or any(path.is_relative_to(c) for c in covered):
                    continue
                if scope_dir is not None and path.resolve().is_relative_to(scope_dir):
                    steps.append(DeletePath(path))
                else:
                    warnings.append(
                        f"{entry.item_id}: {path} is outside the {inst.scope} scope and was left in place "
                        "(the lock entry may have been tampered with)"
                    )
            steps.append(
                EditJson(self.lock_path(inst.scope), remove_entry_edit(entry), f"forget {entry.item_id}")
            )
        return Plan.build(
            f"Remove {inst.name} ({inst.scope})",
            inst.harness,
            inst.scope,
            steps,
            adapter.reload_hint,
            warnings=warnings,
            origin=self._origin_of(inst),
        )

    def plan_toggle(self, inst: InstalledItem) -> Plan:
        adapter = self.adapter(inst.harness)
        steps = adapter.plan_toggle(inst, self.project)
        verb = "Disable" if inst.enabled else "Enable"
        return Plan.build(
            f"{verb} {inst.name} ({inst.scope})",
            inst.harness,
            inst.scope,
            steps,
            adapter.reload_hint,
            origin=self._origin_of(inst),
        )

    def plan_update(self, inst: InstalledItem) -> Plan:
        entry: LockEntry | None = inst.meta.get("lock")
        if entry is None:
            raise PlanError(
                f"{inst.name} was not installed by harnessctl; update it with the harness's own tools"
            )
        item = self.find_item(entry.source, entry.item_id)
        if item is None:
            raise PlanError(f"{entry.item_id} is no longer in source {entry.source}")
        remove = self.plan_remove(inst)
        install = self.plan_install(item, inst.harness, inst.scope, replace=True)
        return Plan.build(
            f"Update {inst.name} {entry.version} → {item.version}",
            inst.harness,
            inst.scope,
            [*remove.steps, *install.steps],
            install.reload_hint,
            warnings=[*remove.warnings, *install.warnings],
            origin=install.origin,
        )

    def apply(self, plan: Plan) -> ApplyResult:
        result = apply(plan, self.paths.backups, runner=self.runner)
        log.info(
            "%s: %s",
            plan.title,
            "ok" if result.ok else f"failed at step {result.failed_step}: {result.error}",
        )
        return result

    def watched_paths(self) -> list[Path]:
        paths = [self.paths.corporate_toml, self.paths.config_toml, self.paths.user_lock]
        if self.project is not None:
            paths.append(project_lock(self.project))
        for adapter in self.detected():
            paths += adapter.watched_paths(self.project)
        return paths
