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
