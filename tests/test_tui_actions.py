import contextlib
import json
import shutil

from textual.widgets import Static

from harnessctl.config import project_lock
from harnessctl.tui.app import HarnessApp
from harnessctl.tui.modals import ConfirmScreen, PlanModal, ScopePicker, TextScreen
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


async def test_apply_that_raises_is_reported_and_the_app_survives(tui, monkeypatch):
    app = tui.app()

    def broken_apply(plan):
        raise PermissionError(13, "Permission denied", str(tui.env.paths.backups))

    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        monkeypatch.setattr(app.engine, "apply", broken_apply)
        await pilot.press("space", "enter")
        await settle(pilot)
        assert app.is_running
        assert "Permission denied" in app.last_outcome
        assert "api-conventions" in _items(app)


async def test_plan_build_that_raises_unexpectedly_is_reported(tui, monkeypatch):
    app = tui.app()

    def broken_toggle(inst):
        raise AttributeError("'str' object has no attribute 'get'")

    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        monkeypatch.setattr(app.engine, "plan_toggle", broken_toggle)
        await pilot.press("space")
        await settle(pilot)
        assert app.is_running and not isinstance(app.screen, PlanModal)
        assert "has no attribute" in app.last_outcome


async def test_rescan_that_raises_is_reported_and_the_app_survives(tui, monkeypatch):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)

        def broken_installed(harness):
            raise KeyError("boom")

        monkeypatch.setattr(app.engine, "installed", broken_installed)
        await pilot.press("r")
        await settle(pilot)
        assert app.is_running
        assert "boom" in app.last_outcome
        assert "api-conventions" in _items(app)  # the last good scan stays on screen


async def test_malformed_marketplace_source_does_not_crash_startup(tui, tmp_path):
    from tests.helpers import make_repo, write

    remote = tmp_path / "market"
    write(remote / ".claude-plugin" / "marketplace.json", '{"name": "m", "plugins": ["x"]}')
    make_repo(None, remote)
    write(tui.env.paths.config_toml, f'[[source]]\nname = "market"\nurl = "{remote.as_uri()}"\n')
    engine = tui.env.engine()
    engine.load_sources(fetch=True)
    app = HarnessApp(engine, fetch=False, poll_interval=3600)
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        assert app.is_running
        assert "api-conventions" in _items(app)


async def test_plan_modal_names_source_and_commit(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("space")
        assert isinstance(app.screen, PlanModal)
        where = str(app.screen.query_one("#plan-where", Static).render())
        assert where.startswith("Claude Code · project scope · acme@")


async def test_install_of_an_unavailable_plugin_says_why(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("2", "down", "down", "i")
        assert not isinstance(app.screen, ScopePicker)
        assert app.last_outcome == (
            "jira-context: the claude CLI is not on PATH, so plugins cannot be installed."
        )


async def test_failure_before_any_step_is_reported_as_is(tui, monkeypatch):
    from harnessctl.planner import ApplyResult

    message = "cannot back up before applying: disk full; nothing was changed"
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        monkeypatch.setattr(app.engine, "apply", lambda plan: ApplyResult(False, error=message))
        await pilot.press("space", "enter")
        await settle(pilot)
        assert app.is_running
        assert app.last_outcome == message


def _skill_md(tui):
    return tui.env.project / ".claude" / "skills" / "api-conventions" / "SKILL.md"


async def test_confirm_with_y_is_never_confirmed_by_enter(tui):
    app = tui.app()
    answers: list[bool | None] = []
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        app.push_screen(ConfirmScreen("Remove?", "gone", "remove", yes_key="y"), answers.append)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        app.push_screen(ConfirmScreen("Remove?", "gone", "remove", yes_key="y"), answers.append)
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
    assert answers == [False, True]


async def test_conflict_offers_to_re_plan(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("space")
        _skill_md(tui).write_text("edited by the agent")
        await pilot.press("enter")
        await settle(pilot)
        assert isinstance(app.screen, ConfirmScreen)
        assert "changed since the plan was made" in str(
            app.screen.query_one("#confirm-message", Static).render()
        )
        await pilot.press("enter")
        await settle(pilot)
        assert isinstance(app.screen, PlanModal)
        assert app.screen.plan.title == "Disable api-conventions (project)"
        await pilot.press("enter")
        await settle(pilot)
        assert not _skill_md(tui).exists()
        payload = next((tui.env.paths.parking / "claude-code").glob("*/payload/SKILL.md"))
        assert payload.read_text() == "edited by the agent"


async def test_declining_to_re_plan_changes_nothing(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("space")
        _skill_md(tui).write_text("edited by the agent")
        await pilot.press("enter")
        await settle(pilot)
        await pilot.press("escape")
        await settle(pilot)
        assert not isinstance(app.screen, ConfirmScreen | PlanModal)
        assert _skill_md(tui).read_text() == "edited by the agent"


async def test_re_plan_when_the_item_is_gone_says_so(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("space")
        shutil.rmtree(_skill_md(tui).parent)  # the agent deleted it
        await pilot.press("enter")
        await settle(pilot)
        await pilot.press("enter")  # re-plan
        await settle(pilot)
        assert not isinstance(app.screen, PlanModal)
        assert app.last_outcome == "api-conventions is no longer there; nothing to re-plan"
        assert not (tui.env.paths.parking / "claude-code").exists()
