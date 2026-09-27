import json
import shutil
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

    def runner(argv, timeout, cwd):
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
    # Plan-time "left in place" warnings travel on the plan itself, not on engine.lock_errors
    # (Task 16 fix round 1 controller ruling) — they must survive a cancel-then-retry, which
    # shared, unsynchronized engine state cannot guarantee.
    assert any("victim.txt" in msg for msg in plan.warnings)
    assert engine.lock_errors == []

    assert engine.apply(plan).ok
    assert victim.exists()
    assert not (env.home / ".claude" / "hooks" / "block-secrets-read" / "secrets.sh").exists()


def _cwd_recording_claude(env, log):
    script = env.bin / "claude"
    script.write_text(f'#!/bin/sh\necho "$(pwd) $@" >> "{log}"\n')
    script.chmod(0o755)


def test_project_scope_plugin_commands_run_in_the_project(engine, env, tmp_path, monkeypatch):
    from harnessctl.model import InstalledItem

    log = tmp_path / "claude-cwd.log"
    _cwd_recording_claude(env, log)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    item = _item(engine, "jira-context")
    assert engine.apply(engine.plan_install(item, "claude-code", Scope.PROJECT)).ok
    plugin = InstalledItem(
        "claude-code",
        Scope.PROJECT,
        Kind.PLUGIN,
        "jira-context",
        "claude-plugin:jira-context@acme-plugins",
        meta={"plugin_id": "jira-context@acme-plugins"},
    )
    assert engine.apply(engine.plan_toggle(plugin)).ok
    assert engine.apply(engine.plan_remove(plugin)).ok
    assert engine.apply(engine.plan_install(item, "claude-code", Scope.USER)).ok
    lines = log.read_text().splitlines()
    assert [line.split(" ", 1)[0] for line in lines] == [
        str(env.project),  # marketplace add
        str(env.project),  # install --scope project
        str(env.project),  # disable --scope project
        str(env.project),  # uninstall --scope project
        str(elsewhere),  # marketplace add (user scope runs wherever harnessctl runs)
        str(elsewhere),  # install --scope user
    ]
    assert "install jira-context@acme-plugins --scope project" in lines[1]


def test_malformed_lock_entries_are_skipped_and_reported(engine, env):
    engine.apply(engine.plan_install(_item(engine, "api-conventions"), "claude-code", Scope.USER))
    data = json.loads(env.paths.user_lock.read_text())
    data["entries"] += [7, {**data["entries"][0], "item_id": "ghost", "kind": "gadget"}]
    env.paths.user_lock.write_text(json.dumps(data))
    items = {i.name: i for i in engine.installed("claude-code")}
    assert items["api-conventions"].meta["lock"].item_id == "api-conventions"
    assert len(engine.lock_errors) == 2 and all("lock.json: entry" in e for e in engine.lock_errors)
    engine.catalog("claude-code")


def test_parked_catalog_hook_keeps_its_provenance_and_can_be_removed(engine, env):
    engine.apply(engine.plan_install(_item(engine, "block-secrets-read"), "claude-code", Scope.USER))
    hook = _installed(engine, "block-secrets-read")
    assert engine.apply(engine.plan_toggle(hook)).ok
    parked = _installed(engine, "block-secrets-read")
    assert parked.enabled is False and parked.provenance.origin == "corp"
    assert parked.location != hook.location and parked.origin_location == hook.location
    assert engine.apply(engine.plan_remove(parked)).ok
    assert not list((env.paths.parking / "claude-code").iterdir())
    assert json.loads(env.paths.user_lock.read_text())["entries"] == []


def test_plans_name_their_source_and_commit(engine, env):
    commit = engine.sources[0].commit
    item = _item(engine, "api-conventions")
    plan = engine.plan_install(item, "claude-code", Scope.USER)
    assert plan.origin == f"acme@{commit[:7]}"
    assert engine.apply(plan).ok
    inst = _installed(engine, "api-conventions")
    assert engine.plan_toggle(inst).origin == f"acme@{commit[:7]}"
    assert engine.plan_remove(inst).origin == f"acme@{commit[:7]}"
    skill(env.home / ".claude" / "skills" / "mine")
    assert engine.plan_toggle(_installed(engine, "mine")).origin == ""


def test_plugin_unavailable_without_the_claude_cli_until_it_appears(engine, env):
    entries = {e.item.id: e for e in engine.catalog("claude-code")}
    assert entries["jira-context"].available is False
    assert entries["jira-context"].reason == "the claude CLI is not on PATH, so plugins cannot be installed"
    assert entries["api-conventions"].available and entries["api-conventions"].reason is None

    stub_command(env.bin, "claude", env.home / "claude-calls.log")  # installed while running
    entries = {e.item.id: e for e in engine.catalog("claude-code")}
    assert entries["jira-context"].available is True and entries["jira-context"].reason is None


def test_find_installed_returns_the_item_from_a_fresh_scan(engine, env):
    engine.apply(engine.plan_install(_item(engine, "api-conventions"), "claude-code", Scope.USER))
    old = _installed(engine, "api-conventions")
    (env.home / ".claude" / "skills" / "api-conventions" / "SKILL.md").write_text("edited")
    fresh = engine.find_installed(old)
    assert fresh is not old and fresh.status is Status.MODIFIED
    assert engine.apply(engine.plan_toggle(fresh)).ok
    assert engine.find_installed(old) is None  # disabled now: a different item


def test_find_installed_picks_the_exact_parked_copy_among_several(engine, env):
    """Two parked copies of the same skill share an origin_location (park_dir suffixes -2, -3,
    ... when a location is parked more than once); find_installed must not confuse them."""
    item = _item(engine, "api-conventions")
    engine.apply(engine.plan_install(item, "claude-code", Scope.USER))
    assert engine.apply(engine.plan_toggle(_installed(engine, "api-conventions"))).ok
    old1 = _installed(engine, "api-conventions")
    assert old1.enabled is False

    engine.apply(engine.plan_install(item, "claude-code", Scope.USER))  # reinstall over the free spot
    assert engine.apply(engine.plan_toggle(_installed(engine, "api-conventions"))).ok
    parked = [i for i in engine.installed("claude-code") if i.name == "api-conventions" and not i.enabled]
    assert len(parked) == 2
    old2 = next(i for i in parked if i.location != old1.location)

    assert old1.origin_location == old2.origin_location  # same origin: this is the ambiguity
    assert old1.location != old2.location  # but distinct parking folders

    fresh1 = engine.find_installed(old1)
    fresh2 = engine.find_installed(old2)
    assert fresh1 is not None and fresh1.location == old1.location
    assert fresh2 is not None and fresh2.location == old2.location

    shutil.rmtree(Path(old1.meta["park_dir"]))  # only old1's copy vanishes
    assert engine.find_installed(old1) is None
    assert engine.find_installed(old2) is not None and engine.find_installed(old2).location == old2.location


def test_the_same_repo_under_another_url_form_is_refused(engine, env):
    write(env.paths.config_toml, '[[source]]\nname = "tools"\nurl = "git@github.com:acme/tools.git"\n')
    engine.load_sources(fetch=False)
    with pytest.raises(ConfigError, match="already configured as source 'tools'"):
        engine.add_source("https://github.com/acme/tools", name="tools2")
    assert "tools2" not in env.paths.config_toml.read_text()


def test_removing_a_source_keeps_its_installed_items_as_unknown(engine, env, tmp_path):
    other = tmp_path / "pub"
    skill(other / "skills" / "tdd")
    make_repo(None, other)
    engine.add_source(other.as_uri(), name="pub")
    assert engine.apply(engine.plan_install(engine.find_item("pub", "tdd"), "claude-code", Scope.USER)).ok
    engine.remove_source("pub")
    tdd = _installed(engine, "tdd")
    assert tdd.provenance.origin == "unknown"
    assert (env.home / ".claude" / "skills" / "tdd" / "SKILL.md").is_file()


def test_reload_sources_keeps_unchanged_states_and_fetches_new_ones(engine, env, tmp_path):
    acme_state = engine.sources[0]
    other = tmp_path / "pub"
    skill(other / "skills" / "tdd")
    make_repo(None, other)
    write(env.paths.config_toml, f'[[source]]\nname = "pub"\nurl = "{other.as_uri()}"\n')
    fetched: list[str] = []
    assert engine.reload_sources(on_fetch=fetched.append) == []
    assert fetched == ["pub"]
    assert engine.sources[0] is acme_state  # not fetched again
    assert [i.id for i in engine.sources[1].items] == ["tdd"]
    env.paths.config_toml.write_text("")
    engine.reload_sources()
    assert [s.spec.name for s in engine.sources] == ["acme"]
