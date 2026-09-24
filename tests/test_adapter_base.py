import pytest

from harnessctl.adapters.base import (
    ensure_json_writable,
    install_skill,
    safe_join,
    scan_skill_dirs,
    write_payload_files,
)
from harnessctl.model import InstalledItem, Kind, Scope
from harnessctl.parking import park_dir, park_steps, scan_parked, unpark_steps
from harnessctl.planner import MovePath, Plan, PlanError, WriteFile, apply
from tests.helpers import skill, write


def test_safe_join_rejects_escapes(tmp_path):
    assert safe_join(tmp_path, "hooks/x.sh") == tmp_path / "hooks" / "x.sh"
    for bad in ("../x", "/etc/passwd", "a/../../x"):
        with pytest.raises(PlanError):
            safe_join(tmp_path, bad)


def test_ensure_json_writable(tmp_path):
    ensure_json_writable(tmp_path / "missing.json")
    ensure_json_writable(write(tmp_path / "ok.json", '{"a": 1}'))
    with pytest.raises(PlanError) as exc:
        ensure_json_writable(write(tmp_path / "c.jsonc", "{// x\n}"), manual='add "p" to its plugin array')
    assert "contains comments" in str(exc.value) and 'add "p" to its plugin array' in str(exc.value)
    with pytest.raises(PlanError):
        ensure_json_writable(write(tmp_path / "bad.json", "{"))


def test_install_skill_writes_every_file(tmp_path):
    src = tmp_path / "src" / "tdd"
    skill(src)
    write(src / "refs" / "notes.md", "n")
    inst = install_skill(src, tmp_path / "skills" / "tdd")
    assert [type(s) for s in inst.steps] == [WriteFile, WriteFile]
    assert inst.locations == [str(tmp_path / "skills" / "tdd")]
    assert set(inst.files) == {
        str(tmp_path / "skills/tdd/SKILL.md"),
        str(tmp_path / "skills/tdd/refs/notes.md"),
    }
    skill(tmp_path / "skills" / "tdd")
    with pytest.raises(PlanError):
        install_skill(src, tmp_path / "skills" / "tdd")
    assert install_skill(src, tmp_path / "skills" / "tdd", replace=True).steps


def test_write_payload_files_refuses_overwrite(tmp_path):
    src = write(tmp_path / "item" / "x.sh", "#!/bin/sh\n")
    steps, hashes = write_payload_files([(src, "hooks/x.sh")], tmp_path / "scope", replace=False)
    assert steps[0].path == tmp_path / "scope" / "hooks" / "x.sh" and len(hashes) == 1
    write(tmp_path / "scope" / "hooks" / "x.sh", "other")
    with pytest.raises(PlanError):
        write_payload_files([(src, "hooks/x.sh")], tmp_path / "scope", replace=False)


def test_scan_skill_dirs(tmp_path):
    skill(tmp_path / "skills" / "good", description="Does good things", body="# Good")
    write(tmp_path / "skills" / "plain" / "SKILL.md", "no frontmatter")
    (tmp_path / "skills" / "empty").mkdir()
    write(tmp_path / "skills" / "file.txt", "x")
    items = scan_skill_dirs(tmp_path / "skills", "claude-code", Scope.USER)
    assert [i.name for i in items] == ["good", "plain"]
    assert items[0].meta["description"] == "Does good things" and "# Good" in items[0].detail
    assert items[1].meta["description"] == "(no description)"
    assert scan_skill_dirs(tmp_path / "nope", "claude-code", Scope.USER) == []


def test_park_and_unpark_a_skill(tmp_path):
    scope_dir = tmp_path / ".claude"
    folder = scope_dir / "skills" / "tdd"
    skill(folder)
    inst = InstalledItem("claude-code", Scope.USER, Kind.SKILL, "tdd", str(folder), detail="d")
    parking = tmp_path / "disabled"
    pdir = park_dir(parking, "claude-code", inst.location, inst.name)
    steps = park_steps(
        inst, pdir, scope_dir, {"type": "move", "to": inst.location}, [MovePath(folder, pdir / "payload")]
    )
    assert apply(Plan.build("park", "claude-code", Scope.USER, steps), tmp_path / "b").ok
    assert not folder.exists()

    parked = scan_parked(parking, "claude-code", Scope.USER, scope_dir)
    assert len(parked) == 1 and parked[0].enabled is False and parked[0].location == str(folder)
    assert scan_parked(parking, "claude-code", Scope.PROJECT, tmp_path / "other") == []

    assert apply(Plan.build("unpark", "claude-code", Scope.USER, unpark_steps(parked[0])), tmp_path / "b").ok
    assert (folder / "SKILL.md").is_file() and not pdir.exists()
