import shutil

import pytest

from harnessctl.cli import main
from tests.helpers import EXAMPLES, write


def test_version_flag_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "harnessctl 0.2.0"


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


def test_default_command_launches_the_tui(env, monkeypatch):
    from harnessctl.tui.app import HarnessApp

    launched = []
    monkeypatch.setattr(HarnessApp, "run", lambda self: launched.append(self.engine.project))
    monkeypatch.chdir(env.project)
    assert main([]) == 0
    assert launched == [env.project]
    assert env.paths.state.is_dir()


@pytest.mark.parametrize(
    "content", ["[]", '{"name": "m", "plugins": ["x"]}', '{"name": "m", "plugins": [{"name": "--x"}]}']
)
def test_validate_malformed_marketplace_reports_instead_of_crashing(tmp_path, capsys, content):
    write(tmp_path / ".claude-plugin" / "marketplace.json", content)
    assert main(["validate", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "marketplace.json" in captured.err and "Traceback" not in captured.err


def test_validate_rejects_a_hooks_fragment_of_the_wrong_shape(tmp_path, capsys):
    root = tmp_path / "cat"
    shutil.copytree(EXAMPLES, root)
    write(root / "items" / "h" / "s.sh", "echo\n")
    write(
        root / "items" / "h" / "item.toml",
        'id = "h"\nkind = "hook"\nversion = "1.0.0"\n[variants.claude-code]\ntype = "files"\n'
        'files = { "s.sh" = "hooks/s.sh" }\n[variants.claude-code.settings]\nhooks.PreToolUse = "oops"\n',
    )
    assert main(["validate", str(root)]) == 1
    assert "hooks.PreToolUse must be a list of matcher groups" in capsys.readouterr().err
