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


def _check_hooks(hooks: object) -> list[str]:
    """`hooks` must be {event: [{matcher?: str, hooks: [{type?: str, command: str, ...}]}]}."""
    if not isinstance(hooks, dict):
        return ["hooks must be a table of events"]
    errors: list[str] = []
    for event, groups in hooks.items():
        where = f"hooks.{event}"
        if not isinstance(groups, list) or not groups:
            errors.append(f"{where} must be a list of matcher groups")
            continue
        for g, group in enumerate(groups):
            at = f"{where}[{g}]"
            if not isinstance(group, dict):
                errors.append(f"{at} must be a table")
                continue
            if "matcher" in group and not isinstance(group["matcher"], str):
                errors.append(f"{at}.matcher must be a string")
            entries = group.get("hooks")
            if not isinstance(entries, list) or not entries:
                errors.append(f"{at}.hooks must be a non-empty list")
                continue
            for h, hook in enumerate(entries):
                if not isinstance(hook, dict):
                    errors.append(f"{at}.hooks[{h}] must be a table")
                    continue
                if not isinstance(hook.get("command"), str) or not hook["command"]:
                    errors.append(f"{at}.hooks[{h}].command must be a non-empty string")
                if "type" in hook and not isinstance(hook["type"], str):
                    errors.append(f"{at}.hooks[{h}].type must be a string")
    return errors


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
                if not _safe_destination(src):
                    errors.append(f"{where}: source {src!r} must be a relative path inside the item folder")
                elif not (item_dir / src).is_file():
                    errors.append(f"{where}: file {src!r} not found in item folder")
                if not _safe_destination(dest):
                    errors.append(
                        f"{where}: destination {dest!r} must be a relative path inside the harness folder"
                    )
        settings = v.get("settings", {})
        if not isinstance(settings, dict) or set(settings) - {"hooks"}:
            errors.append(f"{where}: settings may only contain hooks")
        elif "hooks" in settings:
            errors += [f"{where}: settings.{e}" for e in _check_hooks(settings["hooks"])]
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
    if not isinstance(data.get("description", ""), str):
        errors.append("description must be a string")
    tags = data.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        errors.append("tags must be a list of strings")
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
