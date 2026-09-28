from datetime import UTC, datetime, timedelta
from pathlib import Path

from harnessctl.engine import CatalogEntry
from harnessctl.model import (
    CatalogItem,
    ClaudePluginVariant,
    InstalledItem,
    Kind,
    Provenance,
    Scope,
    SourceSpec,
    Status,
    Trust,
)
from harnessctl.planner import Plan, RunCommand, WriteFile
from harnessctl.sources.cache import SourceState
from harnessctl.tui.text import (
    age,
    catalog_detail,
    catalog_row,
    installed_detail,
    installed_row,
    plan_text,
    short_path,
    source_detail,
    sync_summary,
)

HOME = Path("/home/u")
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def _item(**kw):
    base = dict(
        harness="claude-code",
        scope=Scope.PROJECT,
        kind=Kind.SKILL,
        name="api-conventions",
        location="/home/u/p/.claude/skills/api-conventions",
        provenance=Provenance("corp", "acme", "api-conventions", "abcdef1234"),
        status=Status.UPDATE,
    )
    return InstalledItem(**(base | kw))


def _entry(installed=()):
    item = CatalogItem(
        "jira-context",
        Kind.PLUGIN,
        "1.2.0",
        "Jira context",
        "acme",
        {"claude-code": ClaudePluginVariant("u", "m", "jira-context")},
    )
    return CatalogEntry(item, Trust.CORPORATE, True, list(installed))


def test_short_path():
    assert short_path(HOME / "x", HOME) == "~/x"
    assert short_path(HOME, HOME) == "~"
    assert short_path("/etc/x", HOME) == "/etc/x"
    assert short_path("/home/user2/x", HOME) == "/home/user2/x"


def test_installed_row_encodes_state_as_text():
    row = installed_row(_item()).plain
    assert row.startswith(" ● api-conventions")
    assert " P  corp    ↑ acme" in row


def test_ok_status_has_no_mark_and_disabled_uses_hollow_dot():
    row = installed_row(_item(status=Status.OK, enabled=False)).plain
    assert row.startswith(" ○ ") and "↑" not in row and "±" not in row


def test_children_are_indented_and_long_names_truncated():
    row = installed_row(_item(parent="sp@m", name="x" * 40)).plain
    assert row.startswith(" ●   xxx") and "…" in row


def test_catalog_row():
    assert catalog_row(_entry()).plain.startswith("   jira-context")
    assert "plugin  CC –" in catalog_row(_entry()).plain
    assert catalog_row(_entry([Scope.USER])).plain.startswith(" ✓ jira-context")


def test_installed_detail():
    md = installed_detail(_item(), HOME)
    assert "## api-conventions" in md
    assert "**origin** corp · acme @ `abcdef1`" in md
    assert "`~/p/.claude/skills/api-conventions`" in md
    assert "update available" in md


def test_catalog_detail():
    md = catalog_detail(_entry())
    assert "**Claude Code**: Claude plugin `jira-context@m`" in md
    assert "**opencode**: not available" in md
    assert "**Installed** not installed" in md


def test_age():
    assert age(NOW - timedelta(seconds=30), NOW) == "just now"
    assert age(NOW - timedelta(minutes=5), NOW) == "5m ago"
    assert age(NOW - timedelta(hours=3), NOW) == "3h ago"
    assert age(NOW - timedelta(days=2), NOW) == "2d ago"


def _state(status="ok", error=None, minutes=5):
    spec = SourceSpec("acme", "git@x:a/b.git", Trust.CORPORATE)
    return SourceState(spec, status, last_sync=NOW - timedelta(minutes=minutes), error=error)


def test_sync_summary():
    assert sync_summary([], NOW, syncing=False) == "no sources"
    assert sync_summary([_state()], NOW, syncing=True) == "syncing…"
    assert sync_summary([_state()], NOW, syncing=False) == "1 source · synced 5m ago"
    expected = "2 sources · 1 with problems"
    assert sync_summary([_state(), _state("stale", "offline")], NOW, syncing=False) == expected


def test_source_detail():
    md = source_detail(_state("stale", "fatal: could not read from remote"), NOW)
    assert "**status** stale · fatal: could not read from remote" in md
    assert "corporate.toml" in md


def test_plan_text():
    steps = [WriteFile(HOME / "a", b""), RunCommand(["claude", "x"])]
    plan = Plan.build("Install x", "claude-code", Scope.USER, steps)
    lines = plan_text(plan, HOME).plain.splitlines()
    assert lines == [" + write  ~/a", " $ run    claude x"]


def test_catalog_detail_says_why_an_item_is_unavailable():
    entry = _entry()
    entry.available = False
    entry.reason = "the claude CLI is not on PATH, so plugins cannot be installed"
    md = catalog_detail(entry)
    assert "*Not available: the claude CLI is not on PATH, so plugins cannot be installed.*" in md


def test_catalog_row_marks_an_unavailable_item_with_a_symbol_not_only_dimming():
    # Colour (dim) is never the only signal, and below 100 columns the detail pane is hidden.
    entry = _entry()
    entry.available = False
    entry.reason = "the claude CLI is not on PATH, so plugins cannot be installed"
    assert catalog_row(entry).plain.startswith(" ✗ jira-context")
    installed = _entry([Scope.USER])
    installed.available = False
    installed.reason = entry.reason
    assert catalog_row(installed).plain.startswith(" ✓ jira-context")  # installed wins
