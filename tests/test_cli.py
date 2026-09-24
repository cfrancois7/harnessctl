import shutil

import pytest

from harnessctl.cli import main
from tests.helpers import EXAMPLES, write


def test_version_flag_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "harnessctl 0.1.0"


def test_env_fixture_isolates_home(env):
    assert env.paths.home == env.home
    assert env.paths.config == env.home / ".config" / "harnessctl"
    assert (env.project / ".git").is_dir()


def test_validate_ok(capsys):
    assert main(["validate", str(EXAMPLES)]) == 0
    assert capsys.readouterr().out.strip() == "catalog ok: 3 items"


def test_validate_reports_problems(tmp_path, capsys):
    root = tmp_path / "cat"
    shutil.copytree(EXAMPLES, root)
    write(root / "items" / "bad" / "item.toml", 'id = "bad"\nkind = "skill"\nversion = "1.0.0"\n')
    assert main(["validate", str(root)]) == 1
    captured = capsys.readouterr()
    assert "items/bad/item.toml: a skill item needs a [skill] table" in captured.err
    assert captured.out.strip() == "1 problem found"


def test_validate_unknown_layout(tmp_path, capsys):
    assert main(["validate", str(tmp_path)]) == 1
    assert "no catalog.toml" in capsys.readouterr().err
