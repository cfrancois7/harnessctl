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
        Plan.build("t", "claude-code", Scope.USER, steps),
        env.paths.backups,
        runner=lambda argv, timeout, cwd: "",
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
    assert inst.locations == [f"{settings}::PreToolUse::Read|Grep::{script}"]
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


SHARED_COMMAND = {
    "model": "opus",
    "hooks": {
        "PreToolUse": [
            {"matcher": "Edit", "hooks": [{"type": "command", "command": "fmt.sh"}]},
            {"matcher": "Write", "hooks": [{"type": "command", "command": "fmt.sh"}, {"command": "lint.sh"}]},
            {"matcher": "Edit", "hooks": [{"type": "command", "command": "fmt.sh", "timeout": 9}]},
        ],
        "Stop": [{"hooks": [{"type": "command", "command": "fmt.sh"}]}],
    },
}


def _shared_hooks(claude, env):
    settings = write(env.home / ".claude" / "settings.json", json.dumps(SHARED_COMMAND))
    hooks = [i for i in claude.scan(Scope.USER, None) if i.kind is Kind.HOOK and i.enabled]
    return settings, hooks


def test_hooks_sharing_a_command_have_distinct_locations(claude, env):
    _, hooks = _shared_hooks(claude, env)
    assert len(hooks) == 5
    assert len({h.location for h in hooks}) == 5


@pytest.mark.parametrize("index", range(5))
def test_disable_enable_one_of_several_hooks_sharing_a_command_round_trips(claude, env, index):
    settings, hooks = _shared_hooks(claude, env)
    target = hooks[index]
    _apply(env, claude.plan_toggle(target, None))
    remaining = [
        (h["command"], h.get("timeout"))
        for gs in json.loads(settings.read_text())["hooks"].values()
        for g in gs
        for h in g["hooks"]
    ]
    assert len(remaining) == 4
    parked = [i for i in claude.scan(Scope.USER, None) if i.kind is Kind.HOOK and not i.enabled]
    assert len(parked) == 1
    _apply(env, claude.plan_toggle(parked[0], None))
    assert json.loads(settings.read_text()) == SHARED_COMMAND
    assert not list((env.paths.parking / "claude-code").iterdir())


def test_disabling_two_hooks_sharing_a_command_parks_them_separately(claude, env):
    settings, hooks = _shared_hooks(claude, env)
    edit, write_ = hooks[0], hooks[1]
    _apply(env, claude.plan_toggle(edit, None))
    write_ = next(
        i
        for i in claude.scan(Scope.USER, None)
        if i.enabled and i.meta.get("matcher") == "Write" and i.meta.get("command") == "fmt.sh"
    )
    _apply(env, claude.plan_toggle(write_, None))
    assert len(list((env.paths.parking / "claude-code").iterdir())) == 2
    for parked in [i for i in claude.scan(Scope.USER, None) if not i.enabled]:
        _apply(env, claude.plan_toggle(parked, None))
    data = json.loads(settings.read_text())
    commands = sorted(
        (g.get("matcher"), h["command"]) for g in data["hooks"]["PreToolUse"] for h in g["hooks"]
    )
    assert commands == sorted(
        (g.get("matcher"), h["command"]) for g in SHARED_COMMAND["hooks"]["PreToolUse"] for h in g["hooks"]
    )


@pytest.mark.parametrize("index", range(5))
def test_remove_one_of_several_hooks_sharing_a_command_removes_exactly_one(claude, env, index):
    settings, hooks = _shared_hooks(claude, env)
    steps = claude.plan_remove(hooks[index], None)
    assert steps[0].description.startswith("hooks −1")
    _apply(env, steps)
    after = [i for i in claude.scan(Scope.USER, None) if i.kind is Kind.HOOK]
    assert len(after) == 4
    kept = [(i.meta["event"], i.meta["matcher"], i.meta["hook"]) for i in after]
    gone = (hooks[index].meta["event"], hooks[index].meta["matcher"], hooks[index].meta["hook"])
    expected = [(h.meta["event"], h.meta["matcher"], h.meta["hook"]) for h in hooks]
    expected.remove(gone)
    assert kept == expected
    assert json.loads(settings.read_text())["model"] == "opus"


def _hooks(claude, enabled=True):
    return [i for i in claude.scan(Scope.USER, None) if i.kind is Kind.HOOK and i.enabled is enabled]


def _edit_fmt(claude):
    return [
        i for i in _hooks(claude) if i.meta.get("matcher") == "Edit" and i.meta.get("command") == "fmt.sh"
    ]


@pytest.mark.parametrize("restore_order", [[0, 1], [1, 0]])
def test_parking_two_hooks_with_the_same_event_matcher_and_command_keeps_both(claude, env, restore_order):
    settings, _ = _shared_hooks(claude, env)
    _apply(env, claude.plan_toggle(_edit_fmt(claude)[0], None))
    remaining = _edit_fmt(claude)
    assert len(remaining) == 1
    parked = _hooks(claude, enabled=False)
    assert remaining[0].location not in {p.location for p in parked}
    _apply(env, claude.plan_toggle(remaining[0], None))
    parked = _hooks(claude, enabled=False)
    assert len(parked) == 2 and len({p.location for p in parked}) == 2
    assert len(list((env.paths.parking / "claude-code").iterdir())) == 2
    assert sorted(p.meta["restore"]["hook"].get("timeout", 0) for p in parked) == [0, 9]
    for n in restore_order:
        _apply(env, claude.plan_toggle(parked[n], None))
    assert json.loads(settings.read_text()) == SHARED_COMMAND
    assert not list((env.paths.parking / "claude-code").iterdir())


def test_a_non_string_matcher_does_not_hide_the_other_hooks(claude, env):
    write(
        env.home / ".claude" / "settings.json",
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {"matcher": ["Edit"], "hooks": [{"command": "a.sh"}]},
                        {"matcher": "Write", "hooks": [{"command": "b.sh"}]},
                    ]
                }
            }
        ),
    )
    names = sorted(i.name for i in claude.scan(Scope.USER, None) if i.kind is Kind.HOOK)
    assert "PreToolUse:b.sh" in names


@pytest.mark.parametrize("enable_order", [["a.sh", "b.sh"], ["b.sh", "a.sh"]])
@pytest.mark.parametrize("disable_order", [["a.sh", "b.sh"], ["b.sh", "a.sh"]])
def test_disabling_every_hook_of_a_group_restores_one_group(claude, env, disable_order, enable_order):
    original = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"command": "x.sh"}]},
                {"matcher": "Edit", "hooks": [{"command": "a.sh"}, {"command": "b.sh", "timeout": 2}]},
            ]
        }
    }
    settings = write(env.home / ".claude" / "settings.json", json.dumps(original))
    for command in disable_order:
        _apply(env, claude.plan_toggle(next(i for i in _hooks(claude) if i.meta["command"] == command), None))
    for command in enable_order:
        parked = next(i for i in _hooks(claude, enabled=False) if i.meta["command"] == command)
        _apply(env, claude.plan_toggle(parked, None))
    assert json.loads(settings.read_text()) == original
