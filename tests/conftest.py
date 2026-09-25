from dataclasses import dataclass
from pathlib import Path

import pytest

from harnessctl.config import Paths
from tests.helpers import GIT_ENV


@dataclass
class Env:
    home: Path
    project: Path
    bin: Path
    environ: dict[str, str]
    paths: Paths

    def engine(self, **kw):
        from harnessctl.engine import Engine

        return Engine(self.paths, self.project, env=self.environ, **kw)


@dataclass
class TuiEnv:
    env: Env
    repo: Path

    def app(self, **kw):
        from harnessctl.tui.app import HarnessApp

        return HarnessApp(self.env.engine(), fetch=False, poll_interval=3600, **kw)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    home = tmp_path / "home"
    project = home / "projects" / "api"
    (project / ".git").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    environ = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin"}
    for key in (
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_STATE_HOME",
        "OPENCODE_DISABLE_CLAUDE_CODE",
        "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS",
        "VISUAL",
        "EDITOR",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", environ["HOME"])
    monkeypatch.setenv("PATH", environ["PATH"])
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)
    return Env(home, project, bin_dir, environ, Paths.from_env(environ))


@pytest.fixture
def tui(env: Env, tmp_path: Path) -> TuiEnv:
    """acme as corporate source, api-conventions installed at project scope, my-notes at user scope."""
    from harnessctl.model import Scope
    from tests.helpers import EXAMPLES, make_repo, skill, write

    repo = make_repo(EXAMPLES, tmp_path / "acme")
    write(env.paths.corporate_toml, f'[[source]]\nname = "acme"\nurl = "{repo.as_uri()}"\n')
    skill(env.home / ".claude" / "skills" / "my-notes", description="Personal notes")
    engine = env.engine()
    engine.load_sources(fetch=True)
    item = engine.find_item("acme", "api-conventions")
    assert engine.apply(engine.plan_install(item, "claude-code", Scope.PROJECT)).ok
    return TuiEnv(env, repo)
