"""Pinned frames at the sizes the spec names (120×30 wide, 80×24 standard, 64×30 split)."""

from tests.helpers import settle


def test_installed_wide(snap_compare, tui):
    assert snap_compare(tui.app(), terminal_size=(120, 30), run_before=settle)


def test_installed_standard(snap_compare, tui):
    assert snap_compare(tui.app(), terminal_size=(80, 24), run_before=settle)


def test_catalog_split(snap_compare, tui):
    async def run_before(pilot):
        await settle(pilot)
        await pilot.press("2")
        await settle(pilot)

    assert snap_compare(tui.app(), terminal_size=(64, 30), run_before=run_before)


def test_plan_modal(snap_compare, tui):
    async def run_before(pilot):
        await settle(pilot)
        await pilot.press("space")
        await settle(pilot)

    assert snap_compare(tui.app(), terminal_size=(120, 30), run_before=run_before)
