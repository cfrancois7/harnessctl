from textual.widgets import Static, TabbedContent

from harnessctl.tui.modals import DetailScreen
from harnessctl.tui.views import CatalogView, DetailPane, InstalledView, ItemList
from tests.helpers import settle, skill


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
