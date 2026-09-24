import json

import pytest

from harnessctl.adapters.opencode import OpencodeAdapter
from harnessctl.model import Kind, Scope, SourceFormat, Status
from harnessctl.planner import Plan, PlanError, apply
from harnessctl.sources.formats import load_items
from tests.helpers import EXAMPLES, skill, write

ITEMS = {i.id: i for i in load_items(EXAMPLES, SourceFormat.CATALOG, "acme")[0]}


@pytest.fixture
def oc(env):
    (env.home / ".config" / "opencode").mkdir(parents=True)
    return OpencodeAdapter(env.home, env.paths.xdg_config, env.paths.parking, env={}, which=lambda n: None)


def _apply(env, steps):
    result = apply(Plan.build("t", "opencode", Scope.USER, steps), env.paths.backups, runner=lambda a, t: "")
    assert result.ok, result.error


def test_scan_skills_plugins_and_claude_shared(oc, env):
    cfg = env.home / ".config" / "opencode"
    skill(cfg / "skills" / "own")
    skill(env.home / ".claude" / "skills" / "shared")
    skill(env.home / ".claude" / "skills" / "own")  # same name as an opencode skill: not listed twice
    write(cfg / "plugins" / "guard.ts", "export const Guard = async () => ({})\n")
    write(
        cfg / "opencode.jsonc",
        '{\n  // mine\n  "plugin": ["superpowers@git+https://github.com/obra/superpowers.git", '
        '["opencode-bar", {"k": 1}]]\n}\n',
    )
    items = {i.name: i for i in oc.scan(Scope.USER, env.project)}
    assert set(items) == {"own", "shared", "guard", "superpowers", "opencode-bar"}
    assert items["shared"].meta["via"] == "claude" and items["shared"].readonly
    assert items["guard"].kind is Kind.PLUGIN and items["guard"].location == str(cfg / "plugins" / "guard.ts")
    sp = items["superpowers"]
    assert sp.meta["repo_url"] == "https://github.com/obra/superpowers.git"
    assert (
        sp.location
        == f"{cfg / 'opencode.jsonc'}::plugin::superpowers@git+https://github.com/obra/superpowers.git"
    )


def test_env_switch_hides_claude_skills(env):
    (env.home / ".config" / "opencode").mkdir(parents=True)
    skill(env.home / ".claude" / "skills" / "shared")
    oc = OpencodeAdapter(
        env.home, env.paths.xdg_config, env.paths.parking, env={"OPENCODE_DISABLE_CLAUDE_CODE_SKILLS": "1"}
    )
    assert oc.scan(Scope.USER, None) == []


def test_project_scope_paths(oc, env):
    skill(env.project / ".opencode" / "skills" / "p")
    write(env.project / "opencode.json", json.dumps({"plugin": ["opencode-foo"]}))
    items = {i.name for i in oc.scan(Scope.PROJECT, env.project)}
    assert items == {"p", "opencode-foo"}
    assert oc.scan(Scope.PROJECT, None) == [] and oc.scan(Scope.LOCAL, env.project) == []


def test_broken_config_is_reported(oc, env):
    write(env.home / ".config" / "opencode" / "opencode.json", "{nope")
    [broken] = oc.scan(Scope.USER, None)
    assert broken.status is Status.BROKEN and broken.readonly


def test_install_npm_plugin_creates_config(oc, env):
    inst = oc.plan_install(ITEMS["jira-context"], Scope.PROJECT, env.project)
    _apply(env, inst.steps)
    data = json.loads((env.project / "opencode.json").read_text())
    assert data == {"$schema": "https://opencode.ai/config.json", "plugin": ["@acme/opencode-jira@1.2.0"]}
    assert inst.locations == [f"{env.project / 'opencode.json'}::plugin::@acme/opencode-jira@1.2.0"]


def test_jsonc_with_comments_is_refused_with_manual_edit(oc, env):
    cfg = write(env.home / ".config" / "opencode" / "opencode.jsonc", '{\n  // keep me\n  "plugin": []\n}\n')
    before = cfg.read_bytes()
    with pytest.raises(PlanError) as exc:
        oc.plan_install(ITEMS["jira-context"], Scope.USER, None)
    assert "contains comments" in str(exc.value)
    assert '"@acme/opencode-jira@1.2.0"' in str(exc.value)
    assert cfg.read_bytes() == before


def test_install_files_variant_and_skill(oc, env):
    hook = oc.plan_install(ITEMS["block-secrets-read"], Scope.USER, None)
    _apply(env, hook.steps)
    target = env.home / ".config" / "opencode" / "plugins" / "block-secrets-read.ts"
    assert target.is_file() and hook.locations == [str(target)]
    sk = oc.plan_install(ITEMS["api-conventions"], Scope.USER, None)
    _apply(env, sk.steps)
    assert (env.home / ".config" / "opencode" / "skills" / "api-conventions" / "SKILL.md").is_file()


def test_skill_already_shared_through_claude_is_refused(oc, env):
    skill(env.home / ".claude" / "skills" / "api-conventions")
    with pytest.raises(PlanError, match="already active in opencode"):
        oc.plan_install(ITEMS["api-conventions"], Scope.USER, None)


def test_park_and_restore_npm_plugin_and_file(oc, env):
    cfg = write(env.home / ".config" / "opencode" / "opencode.json", json.dumps({"plugin": ["opencode-foo"]}))
    write(env.home / ".config" / "opencode" / "plugins" / "guard.ts", "x")
    items = {i.name: i for i in oc.scan(Scope.USER, None)}
    _apply(env, oc.plan_toggle(items["opencode-foo"], None))
    _apply(env, oc.plan_toggle(items["guard"], None))
    assert json.loads(cfg.read_text())["plugin"] == []
    parked = {i.name: i for i in oc.scan(Scope.USER, None)}
    assert not parked["guard"].enabled and not parked["opencode-foo"].enabled
    _apply(env, oc.plan_toggle(parked["opencode-foo"], None))
    _apply(env, oc.plan_toggle(parked["guard"], None))
    assert json.loads(cfg.read_text())["plugin"] == ["opencode-foo"]
    assert (env.home / ".config" / "opencode" / "plugins" / "guard.ts").read_text() == "x"


def test_remove(oc, env):
    cfg = write(env.home / ".config" / "opencode" / "opencode.json", json.dumps({"plugin": ["a", "b"]}))
    items = {i.name: i for i in oc.scan(Scope.USER, None)}
    _apply(env, oc.plan_remove(items["a"], None))
    assert json.loads(cfg.read_text())["plugin"] == ["b"]
