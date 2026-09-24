import pytest

from harnessctl.cli import main


def test_version_flag_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "harnessctl 0.1.0"


def test_env_fixture_isolates_home(env):
    assert env.paths.home == env.home
    assert env.paths.config == env.home / ".config" / "harnessctl"
    assert (env.project / ".git").is_dir()
