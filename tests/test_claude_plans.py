import json

import pytest

from harnessctl.adapters.claude_code import ClaudeCodeAdapter
from harnessctl.model import InstalledItem, Kind, Scope, SourceFormat
from harnessctl.planner import DeletePath, Plan, PlanError, RunCommand, apply
from harnessctl.sources.formats import load_items
from tests.helpers import EXAMPLES, skill, write

ITEMS = {i.id: i for i in load_items(EXAMPLES, SourceFormat.CATALOG, "acme")[0]}


@pytest.fixture
def claude(env):
    (env.home / ".claude").mkdir()
    return ClaudeCodeAdapter(env.home, env.paths.parking, which=lambda name: f"/usr/bin/{name}")


def _apply(env, steps):
    result = apply(
        Plan.build("t", "claude-code", Scope.USER, steps), env.paths.backups, runner=lambda argv, timeout: ""
    )
    assert result.ok, result.error


def test_install_skill_user_scope(claude, env):
    inst = claude.plan_install(ITEMS["api-conventions"], Scope.USER, env.project)
    _apply(env, inst.steps)
    target = env.home / ".claude" / "skills" / "api-conventions"
    assert (target / "SKILL.md").is_file()
    assert inst.locations == [str(target)]


def test_install_hook_keeps_user_settings(claude, env):
    settings = write(
        env.project / ".claude" / "settings.json",
        json.dumps(
            {
                "model": "opus",
                "hooks": {
                    "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "mine.sh"}]}]
                },
            }
        ),
    )
    inst = claude.plan_install(ITEMS["block-secrets-read"], Scope.PROJECT, env.project)
    _apply(env, inst.steps)
    script = env.project / ".claude" / "hooks" / "block-secrets-read" / "secrets.sh"
    assert script.is_file() and script.stat().st_mode & 0o111
    data = json.loads(settings.read_text())
    assert data["model"] == "opus"
    commands = [h["command"] for g in data["hooks"]["PreToolUse"] for h in g["hooks"]]
    assert commands == ["mine.sh", str(script)]
    assert inst.locations == [f"{settings}::PreToolUse::{script}"]
    assert inst.settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == str(script)


def test_remove_hook_leaves_theirs(claude, env):
    settings = write(
        env.project / ".claude" / "settings.json",
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "mine.sh"}]}]
                }
            }
        ),
    )
    _apply(env, claude.plan_install(ITEMS["block-secrets-read"], Scope.PROJECT, env.project).steps)
    ours = [
        i for i in claude.scan(Scope.PROJECT, env.project) if i.meta.get("command", "").endswith("secrets.sh")
    ][0]
    _apply(env, claude.plan_remove(ours, env.project))
    assert json.loads(settings.read_text()) == {
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "mine.sh"}]}]}
    }


def test_install_plugin_adds_marketplace_when_unknown(claude, env):
    steps = claude.plan_install(ITEMS["jira-context"], Scope.USER, env.project).steps
    assert [s.argv for s in steps] == [
        ["claude", "plugin", "marketplace", "add", "https://github.com/acme/claude-plugins"],
        ["claude", "plugin", "install", "jira-context@acme-plugins", "--scope", "user"],
    ]
    write(env.home / ".claude" / "plugins" / "known_marketplaces.json", json.dumps({"acme-plugins": {}}))
    steps = claude.plan_install(ITEMS["jira-context"], Scope.PROJECT, env.project).steps
    assert [s.argv for s in steps] == [
        ["claude", "plugin", "install", "jira-context@acme-plugins", "--scope", "project"]
    ]


def test_plugin_install_needs_the_cli(env):
    (env.home / ".claude").mkdir()
    adapter = ClaudeCodeAdapter(env.home, env.paths.parking, which=lambda name: None)
    with pytest.raises(PlanError, match="claude CLI is not on PATH"):
        adapter.plan_install(ITEMS["jira-context"], Scope.USER, env.project)


def test_install_refuses_existing_skill(claude, env):
    skill(env.home / ".claude" / "skills" / "api-conventions")
    with pytest.raises(PlanError, match="already exists"):
        claude.plan_install(ITEMS["api-conventions"], Scope.USER, env.project)


def test_park_and_restore_skill_and_hook(claude, env):
    skill(env.home / ".claude" / "skills" / "notes")
    write(
        env.home / ".claude" / "settings.json",
        json.dumps(
            {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "done.sh", "timeout": 3}]}]}}
        ),
    )
    items = {i.name: i for i in claude.scan(Scope.USER, None)}
    _apply(env, claude.plan_toggle(items["notes"], None))
    _apply(env, claude.plan_toggle(items["Stop:done.sh"], None))
    assert not (env.home / ".claude" / "skills" / "notes").exists()
    assert "hooks" not in json.loads((env.home / ".claude" / "settings.json").read_text())

    parked = {i.name: i for i in claude.scan(Scope.USER, None)}
    assert parked["notes"].enabled is False and parked["Stop:done.sh"].enabled is False
    _apply(env, claude.plan_toggle(parked["notes"], None))
    _apply(env, claude.plan_toggle(parked["Stop:done.sh"], None))
    assert (env.home / ".claude" / "skills" / "notes" / "SKILL.md").is_file()
    data = json.loads((env.home / ".claude" / "settings.json").read_text())
    assert data["hooks"]["Stop"][0]["hooks"][0] == {"type": "command", "command": "done.sh", "timeout": 3}
    assert not list((env.paths.parking / "claude-code").iterdir())


def test_toggle_plugin_uses_the_cli(claude, env):
    plugin = InstalledItem(
        "claude-code",
        Scope.USER,
        Kind.PLUGIN,
        "sp",
        "claude-plugin:sp@m",
        enabled=True,
        meta={"plugin_id": "sp@m"},
    )
    assert claude.plan_toggle(plugin, None) == [
        RunCommand(["claude", "plugin", "disable", "sp@m", "--scope", "user"])
    ]
    plugin.enabled = False
    assert claude.plan_toggle(plugin, None)[0].argv[2] == "enable"
    assert claude.plan_remove(plugin, None)[0].argv == [
        "claude",
        "plugin",
        "uninstall",
        "sp@m",
        "--scope",
        "user",
    ]


def test_readonly_items_are_refused(claude, env):
    item = InstalledItem(
        "claude-code", Scope.LOCAL, Kind.HOOK, "x", "loc", readonly="local scope is read-only"
    )
    with pytest.raises(PlanError, match="local scope is read-only"):
        claude.plan_toggle(item, env.project)
    with pytest.raises(PlanError):
        claude.plan_remove(item, env.project)


def test_symlinked_skill_remove_and_park_act_on_the_link(claude, env, tmp_path):
    target = tmp_path / "shared-skills" / "linked"
    skill(target)
    link = env.home / ".claude" / "skills" / "linked"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    item = {i.name: i for i in claude.scan(Scope.USER, None)}["linked"]
    assert claude.plan_remove(item, None) == [DeletePath(link)]
    _apply(env, claude.plan_toggle(item, None))
    assert not link.is_symlink() and (target / "SKILL.md").is_file()


def test_edit_refused_on_broken_settings(claude, env):
    write(env.home / ".claude" / "settings.json", "{broken")
    with pytest.raises(PlanError, match="Fix the file first"):
        claude.plan_install(ITEMS["block-secrets-read"], Scope.USER, env.project)
