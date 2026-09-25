import contextlib
import json

from textual.widgets import Static

from harnessctl.config import project_lock
from harnessctl.tui.app import HarnessApp
from harnessctl.tui.modals import PlanModal, ScopePicker, TextScreen
from harnessctl.tui.views import InstalledView, ItemList
from tests.helpers import settle


def _items(app):
    return {i.name: i for i in app.query_one(InstalledView).query_one(ItemList).objects}


async def test_toggle_through_the_plan_modal(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("space")
        assert isinstance(app.screen, PlanModal)
        assert app.screen.plan.title == "Disable api-conventions (project)"
        await pilot.press("enter")
        await settle(pilot)
        assert _items(app)["api-conventions"].enabled is False
        assert not (tui.env.project / ".claude" / "skills" / "api-conventions").exists()


async def test_cancel_changes_nothing(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("space", "escape")
        await settle(pilot)
        assert not isinstance(app.screen, PlanModal)
        assert (tui.env.project / ".claude" / "skills" / "api-conventions" / "SKILL.md").is_file()


async def test_diff_view(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("d", "v")
        assert isinstance(app.screen, TextScreen)
        await pilot.press("escape")
        assert isinstance(app.screen, PlanModal)


async def test_install_from_catalog_with_scope_picker(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("2", "down", "i")
        assert isinstance(app.screen, ScopePicker)
        await pilot.press("enter")  # first choice: user
        assert isinstance(app.screen, PlanModal)
        assert app.screen.plan.title == "Install block-secrets-read → user"
        await pilot.press("enter")
        await settle(pilot)
        settings = json.loads((tui.env.home / ".claude" / "settings.json").read_text())
        assert "PreToolUse" in settings["hooks"]
        assert "block-secrets-read" in _items(app)


async def test_file_changed_while_modal_open_is_refused(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("space")
        (tui.env.project / ".claude" / "skills" / "api-conventions" / "SKILL.md").write_text(
            "edited by the agent"
        )
        await pilot.press("enter")
        await settle(pilot)
        assert "changed since the plan was made" in app.last_outcome
        assert (
            tui.env.project / ".claude" / "skills" / "api-conventions" / "SKILL.md"
        ).read_text() == "edited by the agent"


async def test_refused_action_explains_why(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("down", "u")
        assert not isinstance(app.screen, PlanModal)
        assert "not installed by harnessctl" in app.last_outcome


async def test_remove_warns_about_lock_entry_outside_scope_dir(tui):
    """A lock entry tampered with to list a file outside the scope dir must be reported
    inside the plan modal itself (Task 16 fix round 1 controller ruling: plan-time "left in
    place" warnings travel on the Plan and PlanModal renders `plan.warnings`), and must show
    up again on a cancel-then-retry — not depend on shared engine.lock_errors state that a
    cancelled modal (no rescan) would leave stale."""
    lock_path = project_lock(tui.env.project)
    lock = json.loads(lock_path.read_text())
    victim = tui.env.home / "victim.txt"
    victim.write_text("precious")
    lock["entries"][0]["files"][str(victim)] = "deadbeef"
    lock_path.write_text(json.dumps(lock))

    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("d")
        assert isinstance(app.screen, PlanModal)
        assert any("victim.txt" in w for w in app.screen.plan.warnings)
        warning_widget = app.screen.query_one("#plan-warnings", Static)
        assert "victim.txt" in str(warning_widget.render())
        assert victim.exists()  # left in place, not touched by the plan

        # cancel then retry the same action: the warning must be shown again, not swallowed
        # because it was already recorded once in shared engine state.
        await pilot.press("escape")
        assert not isinstance(app.screen, PlanModal)
        await pilot.press("d")
        assert isinstance(app.screen, PlanModal)
        assert any("victim.txt" in w for w in app.screen.plan.warnings)
        assert "victim.txt" in str(app.screen.query_one("#plan-warnings", Static).render())


async def test_open_in_editor(tui, monkeypatch):
    calls = []
    monkeypatch.setenv("EDITOR", "myeditor --wait")
    monkeypatch.setattr(HarnessApp, "suspend", lambda self: contextlib.nullcontext())
    monkeypatch.setattr("harnessctl.tui.app.run_editor", calls.append)
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("o")
        skill_md = tui.env.project / ".claude" / "skills" / "api-conventions" / "SKILL.md"
        assert calls == [["myeditor", "--wait", str(skill_md)]]
