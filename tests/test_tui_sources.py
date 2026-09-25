from textual.widgets import Input

from harnessctl.tui.modals import AddSourceScreen
from harnessctl.tui.views import CatalogView, DetailPane, ItemList, SourcesView
from tests.helpers import make_repo, settle, skill


def _sources(app):
    return [s.spec.name for s in app.query_one(SourcesView).query_one(ItemList).objects]


async def test_sources_tab_shows_corporate_source(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("3")
        assert _sources(app) == ["acme"]
        assert "corporate.toml" in app.query_one(SourcesView).query_one(DetailPane).markdown


async def test_add_and_remove_a_public_source(tui, tmp_path):
    public = tmp_path / "pub"
    skill(public / "skills" / "tdd")
    make_repo(None, public)
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("3", "a")
        assert isinstance(app.screen, AddSourceScreen)
        app.screen.query_one("#url", Input).value = public.as_uri()
        app.screen.query_one("#name", Input).value = "pub"
        await pilot.press("enter")
        await settle(pilot)
        assert _sources(app) == ["acme", "pub"]
        assert "tdd" in [e.item.id for e in app.query_one(CatalogView).query_one(ItemList).objects]
        await pilot.press("down", "d")
        await settle(pilot)
        assert _sources(app) == ["acme"]


async def test_corporate_source_cannot_be_removed(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("3", "d")
        await settle(pilot)
        assert "corporate sources are managed in corporate.toml" in app.last_outcome
        assert _sources(app) == ["acme"]


async def test_refresh_reports_status(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("3", "r")
        await settle(pilot)
        assert app.last_outcome == "acme: ok, 3 items"
