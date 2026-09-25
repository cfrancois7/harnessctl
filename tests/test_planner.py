import json
import os

import pytest

from harnessctl import planner
from harnessctl.model import Scope
from harnessctl.planner import (
    DeletePath,
    EditJson,
    MovePath,
    Plan,
    PlanConflict,
    PlanError,
    RunCommand,
    WriteFile,
    apply,
    fingerprint,
    plan_diff,
    step_label,
)
from tests.helpers import write


def _plan(*steps):
    return Plan.build("t", "claude-code", Scope.USER, list(steps))


def _add_key(key, value):
    def edit(data):
        data = data or {}
        data[key] = value
        return data

    return edit


def _ok_runner(argv, timeout, cwd):
    return "ran " + " ".join(argv)


def test_apply_writes_and_merges(tmp_path):
    settings = write(tmp_path / "settings.json", '{"theme": "dark", "env": {"A": "1"}}\n')
    plan = _plan(
        WriteFile(tmp_path / "hooks" / "x.sh", b"#!/bin/sh\n", executable=True),
        EditJson(settings, _add_key("hooks", {}), "hooks +1"),
    )
    result = apply(plan, tmp_path / "backups", runner=_ok_runner)
    assert result.ok, result.error
    assert os.access(tmp_path / "hooks" / "x.sh", os.X_OK)
    assert json.loads(settings.read_text()) == {"theme": "dark", "env": {"A": "1"}, "hooks": {}}
    assert list(json.loads(settings.read_text())) == ["theme", "env", "hooks"]


def test_conflict_when_file_changed_after_planning(tmp_path):
    settings = write(tmp_path / "settings.json", "{}")
    plan = _plan(WriteFile(tmp_path / "new.txt", b"x"), EditJson(settings, _add_key("a", 1), "a"))
    settings.write_text('{"agent": "wrote this"}')
    with pytest.raises(PlanConflict) as exc:
        apply(plan, tmp_path / "backups")
    assert "settings.json changed since the plan was made" in str(exc.value)
    assert not (tmp_path / "new.txt").exists()
    assert settings.read_text() == '{"agent": "wrote this"}'


def test_failure_rolls_back_every_step(tmp_path):
    existing = write(tmp_path / "keep.txt", "original")

    def failing(argv, timeout, cwd):
        raise PlanError("claude: plugin not found")

    plan = _plan(
        WriteFile(existing, b"changed"),
        WriteFile(tmp_path / "new.txt", b"x"),
        RunCommand(["claude", "plugin", "install", "p@m"]),
    )
    result = apply(plan, tmp_path / "backups", runner=failing)
    assert not result.ok and result.failed_step == 2
    assert result.error == "claude: plugin not found"
    assert existing.read_text() == "original"
    assert not (tmp_path / "new.txt").exists()


def test_jsonc_with_comments_is_never_rewritten(tmp_path):
    cfg = write(tmp_path / "opencode.jsonc", '{\n  // mine\n  "plugin": []\n}\n')
    before = cfg.read_bytes()
    result = apply(_plan(EditJson(cfg, _add_key("x", 1), "x")), tmp_path / "backups")
    assert not result.ok and "contains comments" in result.error
    assert cfg.read_bytes() == before


def test_unparseable_json_is_never_rewritten(tmp_path):
    cfg = write(tmp_path / "settings.json", "{broken")
    result = apply(_plan(EditJson(cfg, _add_key("x", 1), "x")), tmp_path / "backups")
    assert not result.ok and cfg.read_text() == "{broken"


def test_delete_symlink_removes_link_not_target(tmp_path):
    target = tmp_path / "real-skill"
    write(target / "SKILL.md", "x")
    link = tmp_path / "skills" / "linked"
    link.parent.mkdir()
    link.symlink_to(target)
    assert apply(_plan(DeletePath(link)), tmp_path / "backups").ok
    assert not link.is_symlink() and (target / "SKILL.md").is_file()


def test_move_and_rollback_of_directories(tmp_path):
    src = tmp_path / "skills" / "a"
    write(src / "SKILL.md", "a")
    dst = tmp_path / "parking" / "a" / "payload"

    def failing(argv, timeout, cwd):
        raise PlanError("boom")

    result = apply(_plan(MovePath(src, dst), RunCommand(["x"])), tmp_path / "backups", runner=failing)
    assert not result.ok
    assert (src / "SKILL.md").read_text() == "a" and not dst.exists()
    assert apply(_plan(MovePath(src, dst)), tmp_path / "backups").ok
    assert (dst / "SKILL.md").is_file() and not src.exists()


def test_backups_are_pruned(tmp_path):
    f = write(tmp_path / "f", "0")
    for n in range(23):
        assert apply(_plan(WriteFile(f, str(n).encode())), tmp_path / "backups", keep=20).ok
    assert len(list((tmp_path / "backups").iterdir())) == 20


def test_plan_diff_and_labels(tmp_path):
    settings = write(tmp_path / "settings.json", '{"a": 1}\n')
    plan = _plan(EditJson(settings, _add_key("b", 2), "b"), WriteFile(tmp_path / "n.txt", b"hello\n"))
    diff = plan_diff(plan)
    assert '+  "b": 2' in diff and "+hello" in diff
    assert step_label(plan.steps[1], home=tmp_path) == "write  ~/n.txt"
    label = step_label(RunCommand(["claude", "plugin", "install", "a b"]))
    assert label == "run    claude plugin install 'a b'"


# --- Review fix 1: symlinked config files ---------------------------------------------------


def test_symlink_fingerprint_changes_when_target_content_changes(tmp_path):
    target = write(tmp_path / "real.txt", "a")
    link = tmp_path / "linked.txt"
    link.symlink_to(target)
    before = fingerprint(link)
    target.write_text("b")
    after = fingerprint(link)
    assert before != after


def test_conflict_when_symlinked_json_target_changes(tmp_path):
    target = write(tmp_path / "real-settings.json", "{}")
    link = tmp_path / "settings.json"
    link.symlink_to(target)
    plan = _plan(EditJson(link, _add_key("a", 1), "a"))
    target.write_text('{"agent": "wrote this"}')
    with pytest.raises(PlanConflict) as exc:
        apply(plan, tmp_path / "backups")
    assert "settings.json changed since the plan was made" in str(exc.value)


def test_edit_json_through_symlink_updates_target_keeps_link(tmp_path):
    target = write(tmp_path / "real-settings.json", '{"a": 1}\n')
    link = tmp_path / "settings.json"
    link.symlink_to(target)
    result = apply(_plan(EditJson(link, _add_key("b", 2), "b")), tmp_path / "backups")
    assert result.ok, result.error
    assert link.is_symlink()
    assert os.readlink(link) == str(target)
    assert json.loads(target.read_text()) == {"a": 1, "b": 2}


def test_write_file_through_symlink_updates_target_keeps_link(tmp_path):
    target = write(tmp_path / "real.txt", "old")
    link = tmp_path / "linked.txt"
    link.symlink_to(target)
    result = apply(_plan(WriteFile(link, b"new")), tmp_path / "backups")
    assert result.ok, result.error
    assert link.is_symlink()
    assert os.readlink(link) == str(target)
    assert target.read_text() == "new"


def test_rollback_restores_symlink_target_and_link(tmp_path):
    target = write(tmp_path / "real-settings.json", '{"a": 1}\n')
    link = tmp_path / "settings.json"
    link.symlink_to(target)

    def failing(argv, timeout, cwd):
        raise PlanError("boom")

    plan = _plan(EditJson(link, _add_key("b", 2), "b"), RunCommand(["x"]))
    result = apply(plan, tmp_path / "backups", runner=failing)
    assert not result.ok
    assert link.is_symlink()
    assert os.readlink(link) == str(target)
    assert target.read_text() == '{"a": 1}\n'


# --- Review fix 2: guarded rollback -----------------------------------------------------------


def test_rollback_records_failed_restores_but_keeps_going(tmp_path, monkeypatch):
    a = write(tmp_path / "a.txt", "orig-a")
    b = write(tmp_path / "b.txt", "orig-b")

    def failing(argv, timeout, cwd):
        raise PlanError("boom")

    real_restore = planner._restore

    def broken_restore(path, snapshot):
        if path == a:
            raise OSError("disk full")
        real_restore(path, snapshot)

    monkeypatch.setattr(planner, "_restore", broken_restore)

    backup_root = tmp_path / "backups"
    plan = _plan(WriteFile(a, b"changed-a"), WriteFile(b, b"changed-b"), RunCommand(["x"]))
    result = apply(plan, backup_root, runner=failing)

    assert not result.ok
    assert result.error.startswith("boom")
    assert "rollback incomplete" in result.error
    assert str(a) in result.error
    assert "backup at" in result.error
    assert b.read_text() == "orig-b"


# --- Review fix 3: MovePath onto an existing destination -------------------------------------


def test_move_onto_existing_destination_conflicts(tmp_path):
    src = tmp_path / "skills" / "a"
    write(src / "SKILL.md", "a")
    dst = tmp_path / "skills" / "b"
    write(dst / "SKILL.md", "existing-b")

    result = apply(_plan(MovePath(src, dst)), tmp_path / "backups")
    assert not result.ok
    assert "already exists" in result.error
    assert (src / "SKILL.md").read_text() == "a"
    assert (dst / "SKILL.md").read_text() == "existing-b"


# --- Review re-fix: repointed/replaced symlink between Plan.build and apply -------------------


def test_conflict_when_symlink_is_repointed_before_apply(tmp_path):
    a = write(tmp_path / "a.json", '{"a": 1}\n')
    b = write(tmp_path / "b.json", '{"b": 1}\n')
    link = tmp_path / "settings.json"
    link.symlink_to(a)
    plan = _plan(EditJson(link, _add_key("x", 1), "x"))

    link.unlink()
    link.symlink_to(b)

    with pytest.raises(PlanConflict):
        apply(plan, tmp_path / "backups")
    assert json.loads(a.read_text()) == {"a": 1}
    assert json.loads(b.read_text()) == {"b": 1}


def test_conflict_when_symlink_replaced_by_regular_file_before_apply(tmp_path):
    target = write(tmp_path / "real-settings.json", '{"a": 1}\n')
    link = tmp_path / "settings.json"
    link.symlink_to(target)
    plan = _plan(EditJson(link, _add_key("x", 1), "x"))

    link.unlink()
    write(link, '{"agent": "wrote this"}')

    with pytest.raises(PlanConflict):
        apply(plan, tmp_path / "backups")
    assert link.read_text() == '{"agent": "wrote this"}'
    assert target.read_text() == '{"a": 1}\n'


def test_conflict_when_symlink_is_repointed_during_apply(tmp_path):
    """Defence in depth: a repoint that happens *during* apply (e.g. an earlier step's side
    effect, or a race that lands after the up-front conflict check but before this step runs)
    is still caught, right before the step that would otherwise write through the stale link."""
    a = write(tmp_path / "a.json", '{"a": 1}\n')
    b = write(tmp_path / "b.json", '{"b": 1}\n')
    link = tmp_path / "settings.json"
    link.symlink_to(a)

    def repoint_then_ok(argv, timeout, cwd):
        link.unlink()
        link.symlink_to(b)
        return "ran"

    plan = _plan(RunCommand(["noop"]), EditJson(link, _add_key("x", 1), "x"))
    result = apply(plan, tmp_path / "backups", runner=repoint_then_ok)

    assert not result.ok
    assert "changed since the plan was made" in result.error
    assert link.is_symlink() and os.readlink(link) == str(a)
    assert json.loads(a.read_text()) == {"a": 1}
    assert json.loads(b.read_text()) == {"b": 1}


def test_edit_json_reads_utf8_whatever_the_locale(tmp_path):
    import subprocess
    import sys

    target = tmp_path / "settings.json"
    target.write_text('{"name": "café"}\n', encoding="utf-8")
    script = (
        "import sys; from pathlib import Path\n"
        "from harnessctl.model import Scope\n"
        "from harnessctl.planner import EditJson, Plan, apply\n"
        "p = Path(sys.argv[1])\n"
        "def edit(d):\n    d['k'] = 1\n    return d\n"
        "plan = Plan.build('t', 'claude-code', Scope.USER, [EditJson(p, edit, 'k')])\n"
        "r = apply(plan, p.parent / 'backups')\n"
        "print(r.ok, r.error)\n"
    )
    env = {**os.environ, "PYTHONUTF8": "0", "LC_ALL": "POSIX", "LANG": "", "PYTHONCOERCECLOCALE": "0"}
    out = subprocess.run(
        [sys.executable, "-c", script, str(target)], capture_output=True, text=True, env=env, check=True
    ).stdout
    assert out.strip() == "True None"
    assert json.loads(target.read_text(encoding="utf-8")) == {"name": "café", "k": 1}
