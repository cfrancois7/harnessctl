import json
import os

import pytest

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


def _ok_runner(argv, timeout):
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

    def failing(argv, timeout):
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

    def failing(argv, timeout):
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
