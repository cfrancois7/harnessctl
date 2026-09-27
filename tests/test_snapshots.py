"""Pinned frames at the sizes the spec names (120×30 wide, 80×24 standard, 64×30 split, and just
under the 50×15 floor)."""

import hashlib
import os
from pathlib import Path

from harnessctl import parking
from harnessctl.adapters import claude_code, opencode
from tests.helpers import settle


def _stable_park_dir(home: Path):
    """A `park_dir` that hashes the location *relative to `home`* instead of its absolute path.

    Production's `park_dir` (harnessctl.parking.park_dir) hashes the item's absolute filesystem
    location, which is correct behaviour there. In this test's fixtures that absolute path is
    rooted under pytest's `tmp_path`, which is unique to each test *process* — so the digest (and
    the plan text that shows it) would otherwise differ on every independent pytest invocation.
    Hashing the path relative to the fixture's `home` keeps the digest stable across invocations
    without changing what production hashes.
    """

    def park_dir(parking_dir: Path, harness: str, location: str, name: str) -> Path:
        rel = os.path.relpath(location, home)
        digest = hashlib.sha1(rel.encode()).hexdigest()[:10]
        safe = name.replace("/", "_").lstrip("@.")
        return parking_dir / harness / f"{safe}-{digest}"

    return park_dir


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


def test_plan_modal(snap_compare, tui, monkeypatch):
    # `park_dir` is imported by name into each adapter module (`from harnessctl.parking import
    # park_dir`), so each rebinds its own module-level reference; patching harnessctl.parking
    # alone would leave the adapters using the original. Patch every site that holds a reference.
    stable = _stable_park_dir(tui.env.home)
    monkeypatch.setattr(parking, "park_dir", stable)
    monkeypatch.setattr(claude_code, "park_dir", stable)
    monkeypatch.setattr(opencode, "park_dir", stable)

    async def run_before(pilot):
        await settle(pilot)
        await pilot.press("space")
        await settle(pilot)

    assert snap_compare(tui.app(), terminal_size=(120, 30), run_before=run_before)


def test_sources_split(snap_compare, tui):
    # 64 columns: list only. The detail pane would show the source's file:// URL, which contains
    # pytest's temporary path and would differ on every run.
    async def run_before(pilot):
        await settle(pilot)
        await pilot.press("3")
        await settle(pilot)

    assert snap_compare(tui.app(), terminal_size=(64, 30), run_before=run_before)


def test_too_small(snap_compare, tui):
    # One cell under the 50×15 floor: the only thing on screen is the message naming it.
    assert snap_compare(tui.app(), terminal_size=(49, 14), run_before=settle)
