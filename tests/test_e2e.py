"""Spec §10.4: a real git catalog as corporate source, a temp $HOME and project, a stub `claude` CLI."""

import json

from harnessctl.model import Scope, Status
from tests.helpers import EXAMPLES, commit_all, make_repo, stub_command, write


def test_full_lifecycle(env, tmp_path):
    repo = make_repo(EXAMPLES, tmp_path / "acme")
    write(env.paths.corporate_toml, f'[[source]]\nname = "acme"\nurl = "{repo.as_uri()}"\n')
    (env.home / ".claude").mkdir()
    calls = tmp_path / "claude-calls.log"
    stub_command(env.bin, "claude", calls)

    engine = env.engine()
    engine.load_sources(fetch=True)
    item = {i.item.id: i.item for i in engine.catalog("claude-code")}

    # install a skill (project), a hook (user) and a plugin (user)
    for item_id, scope in [
        ("api-conventions", Scope.PROJECT),
        ("block-secrets-read", Scope.USER),
        ("jira-context", Scope.USER),
    ]:
        result = engine.apply(engine.plan_install(item[item_id], "claude-code", scope))
        assert result.ok, (item_id, result.error)
    assert calls.read_text().splitlines() == [
        "plugin marketplace add https://github.com/acme/claude-plugins",
        "plugin install jira-context@acme-plugins --scope user",
    ]
    names = {i.name: i for i in engine.installed("claude-code")}
    assert names["api-conventions"].provenance.origin == "corp"
    assert names["block-secrets-read"].provenance.origin == "corp"

    # disable and re-enable the hook
    assert engine.apply(engine.plan_toggle(names["block-secrets-read"])).ok
    assert "hooks" not in json.loads((env.home / ".claude" / "settings.json").read_text())
    parked = {i.name: i for i in engine.installed("claude-code")}["block-secrets-read"]
    assert engine.apply(engine.plan_toggle(parked)).ok
    assert "PreToolUse" in json.loads((env.home / ".claude" / "settings.json").read_text())["hooks"]

    # publish a new version and update
    toml = repo / "items" / "block-secrets-read" / "item.toml"
    toml.write_text(toml.read_text().replace('version = "2.0.1"', 'version = "2.1.0"'))
    commit_all(repo, "2.1.0")
    engine.refresh_source("acme")
    hook = {i.name: i for i in engine.installed("claude-code")}["block-secrets-read"]
    assert hook.status is Status.UPDATE
    assert engine.apply(engine.plan_update(hook)).ok
    commands = json.loads((env.home / ".claude" / "settings.json").read_text())["hooks"]["PreToolUse"]
    assert len(commands) == 1  # updated in place, not duplicated

    # remove everything harnessctl installed
    for name in ("api-conventions", "block-secrets-read"):
        target = {i.name: i for i in engine.installed("claude-code")}[name]
        assert engine.apply(engine.plan_remove(target)).ok
    assert json.loads(env.paths.user_lock.read_text())["entries"][0]["item_id"] == "jira-context"
    assert json.loads((env.project / ".harnessctl" / "lock.json").read_text())["entries"] == []
    assert not (env.project / ".claude" / "skills" / "api-conventions").exists()
