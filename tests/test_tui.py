import asyncio
import copy
import threading

import pytest
from textual.widgets import Static, TabbedContent

from harnessctl.tui.modals import DetailScreen
from harnessctl.tui.views import CatalogView, DetailPane, InstalledView, ItemList
from tests.helpers import make_repo, settle, skill, write


def _names(app, view=InstalledView):
    return [getattr(o, "name", None) or o.item.id for o in app.query_one(view).query_one(ItemList).objects]


async def test_installed_tab_lists_items_and_header(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        assert _names(app) == ["api-conventions", "my-notes"]
        assert "Claude Code" in str(app.query_one("#harness", Static).render())
        assert "~/projects/api" in str(app.query_one("#where", Static).render())


async def test_detail_follows_the_highlight(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        pane = app.query_one(InstalledView).query_one(DetailPane)
        assert "## api-conventions" in pane.markdown and "corp · acme" in pane.markdown
        await pilot.press("down")
        assert "## my-notes" in pane.markdown and "unknown" in pane.markdown


async def test_narrow_terminal_uses_drill_in(tui):
    app = tui.app()
    async with app.run_test(size=(64, 30)) as pilot:
        await settle(pilot)
        assert app.query_one(InstalledView).query_one(DetailPane).display is False
        await pilot.press("enter")
        assert isinstance(app.screen, DetailScreen) and "## api-conventions" in app.screen.markdown
        await pilot.press("escape")
        assert not isinstance(app.screen, DetailScreen)


async def test_too_small_terminal_says_so(tui):
    app = tui.app()
    async with app.run_test(size=(40, 10)) as pilot:
        await settle(pilot)
        assert app.query_one("#too-small").display is True
        assert app.query_one("#main").display is False
        assert "need 50×15" in str(app.query_one("#too-small", Static).render())


async def test_filter_narrows_the_list(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("slash", *"notes")
        assert _names(app) == ["my-notes"]
        await pilot.press("escape")
        assert _names(app) == ["api-conventions", "my-notes"]


async def test_number_keys_switch_tabs(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("2")
        assert app.query_one(TabbedContent).active == "catalog"
        assert _names(app, CatalogView) == ["api-conventions", "block-secrets-read", "jira-context"]
        await pilot.press("3")
        assert app.query_one(TabbedContent).active == "sources"


async def test_harness_switch(tui):
    (tui.env.home / ".config" / "opencode").mkdir(parents=True)
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("h")
        await settle(pilot)
        assert app.harness == "opencode"
        assert "opencode" in str(app.query_one("#harness", Static).render())
        assert "api-conventions" in _names(app)  # seen through .claude/skills


async def test_file_changes_trigger_a_rescan(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        skill(tui.env.home / ".claude" / "skills" / "fresh")
        app.poll_changes()
        await settle(pilot)
        assert "fresh" in _names(app)


async def test_superseded_rescan_does_not_paint(tui):
    """A scan started before a newer one must not overwrite the newer scan's result, even if
    the older scan's engine calls happen to finish later (the thread keeps running after its
    worker is marked cancelled)."""
    app = tui.app()
    release = threading.Event()
    calls: list[str] = []
    real_installed = app.engine.installed
    stale_items = copy.deepcopy(real_installed("claude-code"))
    for item in stale_items:
        item.name = f"stale-{item.name}"

    def fake_installed(harness: str):
        idx = len(calls)
        calls.append(harness)
        if idx == 0:
            release.wait(5)  # block the first (soon-to-be-superseded) scan in flight
            return stale_items
        return real_installed(harness)

    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        app.engine.installed = fake_installed

        app.rescan()  # scan #1: will block inside installed()
        await asyncio.sleep(0.1)  # let its thread actually start and hit the block
        app.rescan()  # scan #2: exclusive, supersedes #1 in the "scan" group

        for _ in range(50):
            await pilot.pause()
            if app.snapshot.installed and app.snapshot.installed != stale_items:
                break
        else:
            pytest.fail("the newer scan never landed")

        release.set()  # let the stale scan's thread body finish running
        await settle(pilot)
        # the stale scan must not have painted over the newer, correct result
        assert _names(app) == ["api-conventions", "my-notes"]
        assert app.snapshot.installed != stale_items


async def test_broken_lock_file_toasts_once(tui):
    write(tui.env.paths.user_lock, "[1, 2]")
    app = tui.app()
    notifications: list[tuple[str, str]] = []
    app.notify = lambda message, **kw: notifications.append((message, kw.get("severity")))

    def warnings():
        return [m for m, severity in notifications if severity == "warning" and "lock.json" in m]

    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        assert len(warnings()) == 1

        app.rescan()
        await settle(pilot)
        assert len(warnings()) == 1  # not re-toasted on a second scan of the same broken file


def _public_source(tui, tmp_path):
    public = tmp_path / "pub"
    skill(public / "skills" / "tdd")
    make_repo(None, public)
    write(tui.env.paths.config_toml, f'[[source]]\nname = "pub"\nurl = "{public.as_uri()}"\n')
    tui.env.engine().load_sources(fetch=True)  # clone it into the shared cache
    return public


async def test_catalog_filters_by_source_and_type(tui, tmp_path):
    _public_source(tui, tmp_path)
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("2")
        view = app.query_one(CatalogView)
        everything = ["api-conventions", "block-secrets-read", "jira-context", "tdd"]
        assert _names(app, CatalogView) == everything
        await pilot.press("s")
        assert _names(app, CatalogView) == ["api-conventions", "block-secrets-read", "jira-context"]
        status = str(view.query_one("#filters", Static).render())
        assert "source: acme" in status and "3/4" in status
        await pilot.press("s")
        assert _names(app, CatalogView) == ["tdd"]
        await pilot.press("s")
        assert _names(app, CatalogView) == everything
        assert view.query_one("#filters").display is False
        await pilot.press("t")
        assert _names(app, CatalogView) == ["api-conventions", "tdd"]
        assert "type: skill" in str(view.query_one("#filters", Static).render())
        await pilot.press("t")
        assert _names(app, CatalogView) == ["block-secrets-read"]
        await pilot.press("t", "t")
        assert _names(app, CatalogView) == everything


async def test_escape_clears_the_source_and_type_filters(tui, tmp_path):
    _public_source(tui, tmp_path)
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("2", "s", "t")
        assert _names(app, CatalogView) == ["api-conventions"]
        await pilot.press("escape")
        view = app.query_one(CatalogView)
        assert view.source_filter is None and view.kind_filter is None
        assert _names(app, CatalogView) == ["api-conventions", "block-secrets-read", "jira-context", "tdd"]
        assert view.query_one("#filters").display is False


async def test_filters_that_match_nothing_say_how_to_change_them(tui, tmp_path):
    _public_source(tui, tmp_path)
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("2", "s", "s", "t", "t")  # source pub, type hook: nothing
        assert _names(app, CatalogView) == []
        detail = app.query_one(CatalogView).query_one(DetailPane).markdown
        assert "No item matches these filters" in detail and "`s`" in detail and "`esc`" in detail


async def test_editing_config_toml_reloads_sources(tui, tmp_path):
    public = tmp_path / "pub"
    skill(public / "skills" / "tdd")
    make_repo(None, public)
    app = tui.app()
    notifications: list[str] = []
    app.notify = lambda message, **kw: notifications.append(message)
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        write(tui.env.paths.config_toml, f'[[source]]\nname = "pub"\nurl = "{public.as_uri()}"\n')
        app.poll_changes()
        await settle(pilot)
        assert "Fetching source pub…" in notifications  # a fetch may take long: say so first
        await pilot.press("2")
        assert "tdd" in _names(app, CatalogView)


async def test_a_broken_config_toml_is_reported_and_the_app_keeps_going(tui):
    app = tui.app()
    notifications: list[str] = []
    app.notify = lambda message, **kw: notifications.append(message)
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        write(tui.env.paths.config_toml, "[[source]\n")
        app.poll_changes()
        await settle(pilot)
        assert app.is_running
        assert any("config.toml" in m for m in notifications)
        await pilot.press("2")
        assert "api-conventions" in _names(app, CatalogView)  # corporate sources still there


async def test_cursor_stays_on_the_item_after_disabling_it(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("down")
        assert app.query_one(InstalledView).selected.name == "my-notes"
        await pilot.press("space", "enter")
        await settle(pilot)
        selected = app.query_one(InstalledView).selected
        assert selected.name == "my-notes" and selected.enabled is False
