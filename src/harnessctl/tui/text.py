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
STATUS_MARK = {
    Status.UPDATE: ("↑", "bold #5fd4c0"),
    Status.MODIFIED: ("±", "bold #ff8a65"),
    Status.BROKEN: ("✗", "bold red"),
}
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
    return "~" + s[len(h) :] if s.startswith(h + "/") else s


def _origin_of(trust: Trust) -> str:
    return "corp" if trust is Trust.CORPORATE else "public"


def installed_row(item: InstalledItem) -> Text:
    dim = "" if item.enabled else "dim"
    mark, mark_style = STATUS_MARK.get(item.status, ("", ""))
    name = ("  " if item.parent else "") + item.name
    note = item.provenance.source or item.meta.get("event") or ""
    return Text.assemble(
        " ",
        ("●" if item.enabled else "○", dim),
        " ",
        (_cell(name, 24), dim),
        " ",
        (SCOPE_LETTER[item.scope], "dim"),
        "  ",
        (_cell(item.provenance.label, 8), ORIGIN_STYLE[item.provenance.origin]),
        (_cell(mark, 2), mark_style),
        (note, "dim"),
    )


def catalog_row(entry: CatalogEntry) -> Text:
    dim = "" if entry.available else "dim"
    support = " ".join(HARNESS_SHORT[h] if h in entry.item.variants else "–" for h in HARNESSES)
    return Text.assemble(
        " ",
        ("✓" if entry.installed else " ", "green"),
        " ",
        (_cell(entry.item.id, 24), dim),
        " ",
        (_cell(entry.item.kind.value, 8), "dim"),
        (support, "dim"),
    )


def source_row(state: SourceState) -> Text:
    origin = _origin_of(state.spec.trust)
    return Text.assemble(
        " ",
        _cell(state.spec.name, 20),
        " ",
        (_cell(origin, 8), ORIGIN_STYLE[origin]),
        (_cell(state.status, 12), STATE_STYLE[state.status]),
        (f"{len(state.items)} items", "dim"),
    )


def installed_detail(item: InstalledItem, home: Path) -> str:
    p = item.provenance
    origin = p.label + (f" · {p.source}" if p.source else "") + (f" @ `{p.commit[:7]}`" if p.commit else "")
    where = item.meta.get("settings") or item.meta.get("config") or item.origin_location
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
        f"- **{HARNESS_LABEL[h]}**: "
        f"{_variant_summary(item.variants[h]) if h in item.variants else 'not available'}"
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
    fmt = state.format or "unknown format"
    parts = [f"## {spec.name}", f"{trust} source · {fmt}", f"**url** `{spec.url}`"]
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
