import json

import pytest

from harnessctl.adapters.claude_code import ClaudeCodeAdapter
from harnessctl.model import Kind, Scope, Status
from harnessctl.planner import PlanError
from tests.helpers import skill, write


@pytest.fixture
def claude(env):
    home = env.home
    skill(home / ".claude" / "skills" / "my-notes", description="Personal notes")
    skill(home / ".claude" / "skills" / "synced" / "bucket-1" / "pdf", description="PDF tools")
    write(
        home / ".claude" / "settings.json",
        json.dumps(
            {
                "enabledPlugins": {"superpowers@claude-plugins-official": True},
                "hooks": {
                    "PostToolUse": [
                        {
                            "matcher": "Edit",
                            "hooks": [{"type": "command", "command": "~/bin/fmt.sh --all", "timeout": 5}],
                        }
                    ]
                },
            }
        ),
    )
    plugin_dir = home / ".claude" / "plugins" / "cache" / "official" / "superpowers" / "6.4.1"
    skill(plugin_dir / "skills" / "brainstorming")
    write(plugin_dir / ".claude-plugin" / "plugin.json", json.dumps({"description": "Core skills"}))
    write(
        plugin_dir / "hooks" / "hooks.json",
        json.dumps(
            {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "run-hook.cmd"}]}]}}
        ),
    )
    write(
        home / ".claude" / "plugins" / "installed_plugins.json",
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "superpowers@claude-plugins-official": [
                        {"scope": "user", "installPath": str(plugin_dir), "version": "6.4.1"}
                    ],
                    "terminal@gfargo-skills": [
                        {
                            "scope": "project",
                            "projectPath": str(env.project),
                            "installPath": str(home / "nope"),
                        }
                    ],
                    "other@gfargo-skills": [
                        {"scope": "project", "projectPath": "/somewhere/else", "installPath": "/x"}
                    ],
                },
            }
        ),
    )
    write(
        home / ".claude" / "plugins" / "known_marketplaces.json",
        json.dumps(
            {
                "claude-plugins-official": {
                    "source": {"source": "github", "repo": "anthropics/claude-plugins-official"}
                },
                "gfargo-skills": {"source": {"source": "git", "url": "https://github.com/gfargo/skills.git"}},
            }
        ),
    )
    skill(env.project / ".claude" / "skills" / "api-conventions")
    write(
        env.project / ".claude" / "settings.json",
        json.dumps({"enabledPlugins": {"terminal@gfargo-skills": True}}),
    )
    write(
        env.project / ".claude" / "settings.local.json",
        json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "notify-send done"}]}]}}),
    )
    return ClaudeCodeAdapter(env.home, env.paths.parking)


def _by_name(items):
    return {i.name: i for i in items}


def test_user_scope(claude, env):
    items = _by_name(claude.scan(Scope.USER, env.project))
    assert items["my-notes"].kind is Kind.SKILL and items["my-notes"].readonly is None
    assert items["pdf"].readonly == "synced by Claude from claude.ai"

    hook = items["PostToolUse:fmt.sh"]
    assert hook.kind is Kind.HOOK
    assert hook.location == f"{env.home}/.claude/settings.json::PostToolUse::Edit::~/bin/fmt.sh --all"
    assert hook.meta["matcher"] == "Edit" and hook.meta["hook"]["timeout"] == 5

    plugin = items["superpowers"]
    assert plugin.location == "claude-plugin:superpowers@claude-plugins-official"
    assert plugin.enabled is True
    assert plugin.meta["repo_url"] == "https://github.com/anthropics/claude-plugins-official"
    assert "Core skills" in plugin.detail

    child = items["brainstorming"]
    assert (
        child.parent == "superpowers@claude-plugins-official"
        and child.readonly == "part of plugin superpowers"
    )
    plugin_hook = items["SessionStart:run-hook.cmd"]
    assert plugin_hook.parent == "superpowers@claude-plugins-official"


def test_project_and_local_scopes(claude, env):
    project = _by_name(claude.scan(Scope.PROJECT, env.project))
    assert set(project) == {"api-conventions", "terminal"}
    assert project["terminal"].meta["repo_url"] == "https://github.com/gfargo/skills.git"
    local = claude.scan(Scope.LOCAL, env.project)
    assert [(i.name, i.readonly) for i in local] == [("Stop:notify-send", "local scope is read-only")]


def test_no_project_means_user_scope_only(claude):
    assert claude.scan(Scope.PROJECT, None) == []
    assert claude.scan(Scope.LOCAL, None) == []


def test_broken_settings_is_reported(claude, env):
    write(env.home / ".claude" / "settings.json", "{oops")
    items = claude.scan(Scope.USER, env.project)
    broken = [i for i in items if i.status is Status.BROKEN]
    assert broken and broken[0].readonly == "the file cannot be parsed"
    assert "settings.json" in broken[0].error
    assert "my-notes" in _by_name(items)  # the rest of the scan still works


def test_skill_with_bad_frontmatter_still_listed(claude, env):
    write(env.home / ".claude" / "skills" / "weird" / "SKILL.md", "---\n: : :\n---\n")
    weird = _by_name(claude.scan(Scope.USER, env.project))["weird"]
    assert weird.meta["description"] == "(no description)"


def test_broken_known_marketplaces_reported_correctly(claude, env):
    # When known_marketplaces.json is corrupt, the BROKEN item should refer to it, not installed_plugins.json
    write(env.home / ".claude" / "plugins" / "known_marketplaces.json", "{bad")
    items = claude.scan(Scope.USER, env.project)
    broken = [i for i in items if i.status is Status.BROKEN]
    assert broken and "known_marketplaces.json" in broken[0].error
    assert "known_marketplaces.json" in broken[0].location
    # Verify installed_plugins.json is still valid and not reported as broken
    assert "installed_plugins.json" not in broken[0].location


def test_detect_and_watched_paths(claude, env):
    assert claude.detect() is True
    paths = claude.watched_paths(env.project)
    assert env.home / ".claude" / "settings.json" in paths
    assert env.project / ".claude" / "settings.local.json" in paths


@pytest.mark.parametrize(
    "installed, settings, markets",
    [
        ("[]", "{}", "{}"),
        ('{"plugins": []}', "{}", "{}"),
        ('{"plugins": {"a@m": ["x", {"scope": "user", "installPath": 3}]}}', "{}", "{}"),
        ('{"plugins": {"a@m": [{"scope": "user", "installPath": "/nope"}]}}', '{"enabledPlugins": []}', "[]"),
        ('{"plugins": {"a@m": [{"scope": "user", "installPath": "/nope"}]}}', "{}", '{"m": {"source": "x"}}'),
    ],
)
def test_plugin_files_of_the_wrong_shape_do_not_crash_the_scan(env, installed, settings, markets):
    home = env.home
    write(home / ".claude" / "plugins" / "installed_plugins.json", installed)
    write(home / ".claude" / "plugins" / "known_marketplaces.json", markets)
    write(home / ".claude" / "settings.json", settings)
    items = ClaudeCodeAdapter(home, env.paths.parking, which=lambda n: None).scan(Scope.USER, None)
    plugins = [i for i in items if i.kind is Kind.PLUGIN]
    assert all(p.status is Status.BROKEN or p.name == "a" for p in plugins)


def test_local_scope_plugins_are_listed_read_only(claude, env):
    path = env.home / ".claude" / "plugins" / "installed_plugins.json"
    data = json.loads(path.read_text())
    data["plugins"]["scratch@gfargo-skills"] = [
        {"scope": "local", "projectPath": str(env.project), "installPath": str(env.home / "nope")},
        {"scope": "local", "projectPath": "/somewhere/else", "installPath": "/x"},
    ]
    path.write_text(json.dumps(data))
    write(
        env.project / ".claude" / "settings.local.json",
        json.dumps({"enabledPlugins": {"scratch@gfargo-skills": True}}),
    )
    local = _by_name(claude.scan(Scope.LOCAL, env.project))
    assert set(local) == {"scratch"}
    scratch = local["scratch"]
    assert scratch.location == "claude-plugin:scratch@gfargo-skills"
    assert scratch.enabled is True and scratch.scope is Scope.LOCAL
    assert scratch.readonly == "local scope is read-only"
    with pytest.raises(PlanError, match="local scope is read-only"):
        claude.plan_toggle(scratch, env.project)


def test_broken_plugin_files_are_not_reported_a_third_time_for_local_scope(env):
    write(env.home / ".claude" / "plugins" / "installed_plugins.json", "[]")
    adapter = ClaudeCodeAdapter(env.home, env.paths.parking)
    assert [i for i in adapter.scan(Scope.LOCAL, env.project) if i.status is Status.BROKEN] == []


def test_installed_plugins_that_is_not_an_object_is_a_broken_item(env):
    write(env.home / ".claude" / "plugins" / "installed_plugins.json", "[]")
    items = ClaudeCodeAdapter(env.home, env.paths.parking, which=lambda n: None).scan(Scope.USER, None)
    broken = [i for i in items if i.status is Status.BROKEN]
    assert [b.name for b in broken] == ["installed_plugins.json"]
    assert "not a JSON object" in broken[0].error
