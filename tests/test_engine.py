import json
from pathlib import Path

import pytest

from harnessctl.config import ConfigError
from harnessctl.model import Kind, Scope, Status
from harnessctl.planner import DeletePath, PlanError
from tests.helpers import EXAMPLES, commit_all, make_repo, skill, stub_command, write


@pytest.fixture
def acme(env, tmp_path):
    repo = make_repo(EXAMPLES, tmp_path / "acme-remote")
    write(env.paths.corporate_toml, f'[[source]]\nname = "acme"\nurl = "{repo.as_uri()}"\n')
    (env.home / ".claude").mkdir()
    return repo


@pytest.fixture
def engine(env, acme):
    e = env.engine()
    e.load_sources(fetch=True)
    return e


def _installed(engine, name, harness="claude-code"):
    return next(i for i in engine.installed(harness) if i.name == name)


def _item(engine, item_id):
    return engine.find_item("acme", item_id)


def test_catalog_lists_items_with_harness_support(engine):
    entries = {e.item.id: e for e in engine.catalog("claude-code")}
    assert set(entries) == {"api-conventions", "block-secrets-read", "jira-context"}
    assert entries["api-conventions"].trust == "corporate" and entries["api-conventions"].available
    assert entries["api-conventions"].installed == []


def test_install_records_lock_and_provenance(engine, env):
    result = engine.apply(engine.plan_install(_item(engine, "api-conventions"), "claude-code", Scope.PROJECT))
    assert result.ok, result.error
    lock = json.loads((env.project / ".harnessctl" / "lock.json").read_text())
    assert lock["entries"][0]["item_id"] == "api-conventions"
    inst = _installed(engine, "api-conventions")
    assert (inst.provenance.origin, inst.provenance.source, inst.status) == ("corp", "acme", Status.OK)
    assert inst.scope is Scope.PROJECT
    assert {e.item.id: e.installed for e in engine.catalog("claude-code")}["api-conventions"] == [
        Scope.PROJECT
    ]


def test_local_edit_shows_modified(engine, env):
    engine.apply(engine.plan_install(_item(engine, "api-conventions"), "claude-code", Scope.USER))
    (env.home / ".claude" / "skills" / "api-conventions" / "SKILL.md").write_text("edited")
    assert _installed(engine, "api-conventions").status is Status.MODIFIED


def test_new_version_shows_update_and_updates(engine, env, acme):
    engine.apply(engine.plan_install(_item(engine, "api-conventions"), "claude-code", Scope.USER))
    toml = acme / "items" / "api-conventions" / "item.toml"
    toml.write_text(toml.read_text().replace('version = "1.4.0"', 'version = "1.5.0"'))
    (acme / "items" / "api-conventions" / "skill" / "SKILL.md").write_text(
        "---\nname: api-conventions\n---\nv1.5\n"
    )
    commit_all(acme, "1.5.0")
    engine.refresh_source("acme")
    inst = _installed(engine, "api-conventions")
    assert inst.status is Status.UPDATE
    assert engine.apply(engine.plan_update(inst)).ok
    after = _installed(engine, "api-conventions")
    assert after.status is Status.OK and after.meta["lock"].version == "1.5.0"
    assert "v1.5" in (env.home / ".claude" / "skills" / "api-conventions" / "SKILL.md").read_text()


def test_remove_hook_deletes_script_and_lock_entry(engine, env):
    engine.apply(engine.plan_install(_item(engine, "block-secrets-read"), "claude-code", Scope.USER))
    inst = _installed(engine, "block-secrets-read")
    assert inst.kind is Kind.HOOK and inst.provenance.origin == "corp"
    assert engine.apply(engine.plan_remove(inst)).ok
    assert not (env.home / ".claude" / "hooks" / "block-secrets-read" / "secrets.sh").exists()
    assert json.loads(env.paths.user_lock.read_text())["entries"] == []
    assert "hooks" not in json.loads((env.home / ".claude" / "settings.json").read_text())


def test_toggle_keeps_provenance(engine):
    engine.apply(engine.plan_install(_item(engine, "api-conventions"), "claude-code", Scope.USER))
    assert engine.apply(engine.plan_toggle(_installed(engine, "api-conventions"))).ok
    parked = _installed(engine, "api-conventions")
    assert parked.enabled is False and parked.provenance.origin == "corp"
    assert engine.apply(engine.plan_toggle(parked)).ok
    assert _installed(engine, "api-conventions").enabled


def test_unknown_items_and_also_in(engine, env):
    skill(env.home / ".claude" / "skills" / "mine")
    (env.home / ".config" / "opencode").mkdir(parents=True)
    inst = _installed(engine, "mine")
    assert inst.provenance.origin == "unknown" and inst.also_in == ["opencode"]
    with pytest.raises(PlanError, match="not installed by harnessctl"):
        engine.plan_update(inst)


def test_plugin_children_inherit_provenance(engine, env):
    plugin_dir = env.home / "pl"
    skill(plugin_dir / "skills" / "child")
    write(
        env.home / ".claude" / "plugins" / "installed_plugins.json",
        json.dumps({"plugins": {"sp@official": [{"scope": "user", "installPath": str(plugin_dir)}]}}),
    )
    write(
        env.home / ".claude" / "plugins" / "known_marketplaces.json",
        json.dumps(
            {"official": {"source": {"source": "github", "repo": "anthropics/claude-plugins-official"}}}
        ),
    )
    child = _installed(engine, "child")
    assert child.provenance.origin == "public"
    names = [i.name for i in engine.installed("claude-code")]
    assert names.index("child") == names.index("sp") + 1


def test_add_and_remove_public_source(engine, tmp_path):
    other = tmp_path / "pub"
    skill(other / "skills" / "tdd")
    make_repo(None, other)
    state = engine.add_source(other.as_uri(), name="pub")
    assert state.status == "ok" and [i.id for i in state.items] == ["tdd"]
    with pytest.raises(ConfigError):
        engine.remove_source("acme")
    engine.remove_source("pub")
    assert [s.spec.name for s in engine.sources] == ["acme"]


def test_broken_lockfile_is_reported_not_fatal(engine, env):
    write(env.paths.user_lock, "[1, 2]")
    assert engine.installed("claude-code") is not None
    assert engine.lock_errors and "lock.json" in engine.lock_errors[0]


def test_no_project_offers_user_scope_only(env, acme):
    engine = env.engine()
    engine.project = None
    assert engine.scopes() == [Scope.USER]


def test_unavailable_source_is_kept(env, tmp_path):
    write(env.paths.config_toml, f'[[source]]\nname = "gone"\nurl = "{(tmp_path / "nothing").as_uri()}"\n')
    engine = env.engine()
    engine.load_sources(fetch=True)
    assert [s.status for s in engine.sources] == ["unavailable"]
    assert engine.catalog("claude-code") == []


def test_install_refuses_truncated_lock_before_running_anything(env, acme, tmp_path):
    calls: list[list[str]] = []

    def runner(argv, timeout):
        calls.append(argv)
        return ""

    stub_command(env.bin, "claude", tmp_path / "claude-calls.log")
    e = env.engine(runner=runner)
    e.load_sources(fetch=True)
    write(env.paths.user_lock, '{"version": 1, "entries": [')  # truncated JSON
    item = e.find_item("acme", "jira-context")
    with pytest.raises(PlanError, match="lock.json"):
        e.plan_install(item, "claude-code", Scope.USER)
    assert calls == []


def test_install_refuses_non_dict_lock_without_touching_it(engine, env):
    write(env.paths.user_lock, "[1, 2]")
    before = env.paths.user_lock.read_text()
    with pytest.raises(PlanError, match="lock.json"):
        engine.plan_install(_item(engine, "api-conventions"), "claude-code", Scope.USER)
    assert env.paths.user_lock.read_text() == before


def test_remove_only_deletes_files_inside_the_scope_dir(engine, env):
    engine.apply(engine.plan_install(_item(engine, "block-secrets-read"), "claude-code", Scope.USER))
    victim = env.home / "victim.txt"
    victim.write_text("precious")
    lock_path = env.paths.user_lock
    lock = json.loads(lock_path.read_text())
    lock["entries"][0]["files"][str(victim)] = "deadbeef"
    lock_path.write_text(json.dumps(lock))

    inst = _installed(engine, "block-secrets-read")
    plan = engine.plan_remove(inst)
    assert not any(isinstance(s, DeletePath) and Path(s.path) == victim for s in plan.steps)
    assert any("victim.txt" in msg for msg in engine.lock_errors)

    assert engine.apply(plan).ok
    assert victim.exists()
    assert not (env.home / ".claude" / "hooks" / "block-secrets-read" / "secrets.sh").exists()
