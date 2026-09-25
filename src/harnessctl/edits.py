"""Pure edit functions for the JSON files harnessctl changes, and the location keys it uses."""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

OPENCODE_SCHEMA = "https://opencode.ai/config.json"


def hook_location(settings: Path, event: str, matcher: str | None, command: str, occurrence: int = 0) -> str:
    """Identity of one hook entry: event, matcher and command, plus `#n` for the n-th repeat
    (0-based) of that same triple within the file."""
    base = f"{settings}::{event}::{matcher or ''}::{command}"
    return f"{base}#{occurrence}" if occurrence else base


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


def _matcher(group: dict) -> str:
    return group.get("matcher") or ""


def _prune_hooks(data: dict, event: str) -> None:
    hooks = data.get("hooks", {})
    groups = hooks.get(event, [])
    groups[:] = [g for g in groups if not isinstance(g, dict) or g.get("hooks")]
    if not groups:
        hooks.pop(event, None)
    if not hooks:
        data.pop("hooks", None)


def remove_hooks_edit(
    event: str, matcher: str | None, command: str, occurrence: int = 0
) -> Callable[[Any], dict]:
    """Drop exactly one hook: the `occurrence`-th hook running `command` in a group of `event`
    with this `matcher`. Drop the group, event and `hooks` if that leaves them empty."""

    def edit(data: Any) -> dict:
        data = data if isinstance(data, dict) else {}
        seen = 0
        for group in data.get("hooks", {}).get(event, []):
            if not isinstance(group, dict) or _matcher(group) != (matcher or ""):
                continue
            for n, hook in enumerate(group.get("hooks", [])):
                if isinstance(hook, dict) and hook.get("command") == command:
                    if seen == occurrence:
                        del group["hooks"][n]
                        _prune_hooks(data, event)
                        return data
                    seen += 1
        return data

    return edit


def _same_group(group: Any, snapshot: dict) -> bool:
    """`group` in the file is the group `snapshot` recorded: same matcher, a hook in common."""
    return (
        isinstance(group, dict)
        and _matcher(group) == _matcher(snapshot)
        and any(h in snapshot.get("hooks", []) for h in group.get("hooks", []))
    )


def restore_hook_edit(event: str, hook: dict, where: dict) -> Callable[[Any], dict]:
    """Put a parked hook back where it was taken from, whatever order hooks are restored in.

    `where` (recorded at park time) holds `group` (its matcher group without other hooks; key
    order kept), `group_index`, `before`/`after` (the group's other hooks, including ones parked
    from it), and `groups_before`/`groups_after` (the event's other groups). The hook rejoins
    the group holding one of its neighbours, between them; else its group is recreated after
    its preceding groups / ahead of its following ones."""
    before, after = where.get("before", []), where.get("after", [])

    def edit(data: Any) -> dict:
        data = data if isinstance(data, dict) else {}
        groups = data.setdefault("hooks", {}).setdefault(event, [])
        for group in groups:
            if not isinstance(group, dict) or _matcher(group) != _matcher(where["group"]):
                continue
            hooks = group.get("hooks", [])
            if any(h in before or h in after for h in hooks):
                spot = next((n for n, h in enumerate(hooks) if h in after), None)
                if spot is None:
                    spot = max(n + 1 for n, h in enumerate(hooks) if h in before)
                hooks.insert(spot, copy.deepcopy(hook))
                return data
        spot = next(
            (
                n
                for n, g in enumerate(groups)
                if any(_same_group(g, s) for s in where.get("groups_after", []))
            ),
            None,
        )
        if spot is None:
            spot = max(
                (
                    n + 1
                    for n, g in enumerate(groups)
                    if any(_same_group(g, s) for s in where.get("groups_before", []))
                ),
                default=min(where.get("group_index", len(groups)), len(groups)),
            )
        rebuilt = {k: copy.deepcopy(v) for k, v in where["group"].items()}
        rebuilt["hooks"] = [copy.deepcopy(hook)]
        groups.insert(spot, rebuilt)
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
        if "plugin" in data:
            data["plugin"] = [p for p in data["plugin"] if _spec_of(p) != spec]
        return data

    return edit


def plugin_spec_name(spec: str) -> str:
    """'@acme/jira@1.2.0' → '@acme/jira'; 'superpowers@git+https://…' → 'superpowers'."""
    if spec.startswith("@"):
        return "@" + spec[1:].split("@", 1)[0]
    return spec.split("@", 1)[0]
