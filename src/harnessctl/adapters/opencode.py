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
from harnessctl.model import (
    CatalogItem,
    FilesVariant,
    InstalledItem,
    Kind,
    NpmPluginVariant,
    Scope,
    SkillVariant,
    Status,
)
from harnessctl.parking import park_dir, park_steps, scan_parked, unpark_steps
from harnessctl.planner import DeletePath, EditJson, MovePath, PlanError, Step

PLUGIN_SUFFIXES = {".js", ".mjs", ".ts"}


class OpencodeAdapter:
    id = "opencode"
    label = "opencode"
    reload_hint = "Restart opencode to pick up the change."

    def __init__(
        self,
        home: Path,
        xdg_config: Path,
        parking: Path,
        env: dict[str, str] | None = None,
        which: Callable[[str], str | None] = shutil.which,
    ):
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
        self.scope_dir(scope, project)
        base = self.global_dir if scope is Scope.USER else project
        for name in ("opencode.json", "opencode.jsonc"):
            if (base / name).exists():
                return base / name
        return base / "opencode.json"

    def claude_skills_dir(self, scope: Scope, project: Path | None) -> Path:
        self.scope_dir(scope, project)
        return (self.home if scope is Scope.USER else project) / ".claude" / "skills"

    def _reads_claude_skills(self) -> bool:
        return not (
            self.env.get("OPENCODE_DISABLE_CLAUDE_CODE")
            or self.env.get("OPENCODE_DISABLE_CLAUDE_CODE_SKILLS")
        )

    def watched_paths(self, project: Path | None) -> list[Path]:
        paths = [self.global_dir / n for n in ("opencode.json", "opencode.jsonc", "skills", "plugins")]
        paths.append(self.parking / self.id)
        if project is not None:
            paths += [
                project / "opencode.json",
                project / "opencode.jsonc",
                project / ".opencode" / "skills",
                project / ".opencode" / "plugins",
            ]
        return paths

    # --- scanning ----------------------------------------------------------------------------

    def scan(self, scope: Scope, project: Path | None) -> list[InstalledItem]:
        if scope is Scope.LOCAL or (scope is Scope.PROJECT and project is None):
            return []
        scope_dir = self.scope_dir(scope, project)
        items = scan_skill_dirs(scope_dir / "skills", self.id, scope)
        if self._reads_claude_skills():
            own = {i.name for i in items}
            for shared in scan_skill_dirs(
                self.claude_skills_dir(scope, project),
                self.id,
                scope,
                readonly="shared with Claude Code; manage it from the Claude Code view",
            ):
                if shared.name not in own:
                    shared.meta["via"] = "claude"
                    items.append(shared)
        for folder in ("plugins", "plugin"):
            directory = scope_dir / folder
            if directory.is_dir():
                for f in sorted(directory.iterdir()):
                    if f.is_file() and f.suffix in PLUGIN_SUFFIXES:
                        preview = "\n".join(f.read_text(errors="replace").splitlines()[:30])
                        items.append(
                            InstalledItem(
                                self.id, scope, Kind.PLUGIN, f.stem, str(f), detail=f"```ts\n{preview}\n```"
                            )
                        )
        items += self._scan_config(scope, project)
        items += scan_parked(self.parking, self.id, scope, scope_dir)
        return items

    def _scan_config(self, scope: Scope, project: Path | None) -> list[InstalledItem]:
        path = self.config_path(scope, project)
        try:
            config = read_json(path, default={})
        except JsonFileError as exc:
            return [
                InstalledItem(
                    self.id,
                    scope,
                    Kind.PLUGIN,
                    path.name,
                    str(path),
                    status=Status.BROKEN,
                    error=str(exc),
                    readonly="the file cannot be parsed",
                )
            ]
        items: list[InstalledItem] = []
        for entry in config.get("plugin", []) if isinstance(config, dict) else []:
            spec = entry[0] if isinstance(entry, list) and entry else entry
            if not isinstance(spec, str):
                continue
            meta = {"spec": spec, "config": str(path)}
            if "git+" in spec:
                meta["repo_url"] = spec.split("git+", 1)[1]
            items.append(
                InstalledItem(
                    self.id,
                    scope,
                    Kind.PLUGIN,
                    plugin_spec_name(spec),
                    plugin_location(path, spec),
                    detail=f"npm plugin `{spec}`\n\nlisted in `{path}`",
                    meta=meta,
                )
            )
        return items

    # --- changes -----------------------------------------------------------------------------

    def plan_install(
        self, item: CatalogItem, scope: Scope, project: Path | None, replace: bool = False
    ) -> Install:
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
                return Install(
                    [EditJson(path, add_plugin_spec_edit(spec), f"plugin +{spec}")],
                    [plugin_location(path, spec)],
                    {},
                )
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
            return park_steps(
                inst, pdir, scope_dir, {"type": "npm", "config": str(path), "spec": spec}, [take_out]
            )
        return park_steps(
            inst,
            pdir,
            scope_dir,
            {"type": "move", "to": inst.location},
            [MovePath(Path(inst.location), pdir / "payload")],
        )
