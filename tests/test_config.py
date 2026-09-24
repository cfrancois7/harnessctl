import pytest

from harnessctl.config import (
    ConfigError,
    Paths,
    add_public_source,
    default_source_name,
    find_project,
    load_sources,
    project_lock,
    remove_public_source,
)
from harnessctl.model import SourceSpec, Trust
from tests.helpers import write


def test_paths_honour_xdg(tmp_path):
    p = Paths.from_env(
        {
            "HOME": str(tmp_path),
            "XDG_CONFIG_HOME": str(tmp_path / "c"),
            "XDG_CACHE_HOME": str(tmp_path / "k"),
            "XDG_STATE_HOME": str(tmp_path / "s"),
        }
    )
    assert p.corporate_toml == tmp_path / "c" / "harnessctl" / "corporate.toml"
    assert p.sources_cache == tmp_path / "k" / "harnessctl" / "sources"
    assert p.parking == tmp_path / "s" / "harnessctl" / "disabled"
    assert p.xdg_config == tmp_path / "c"


def test_paths_default_to_home(tmp_path):
    p = Paths.from_env({"HOME": str(tmp_path)})
    assert p.user_lock == tmp_path / ".config" / "harnessctl" / "lock.json"
    assert p.backups == tmp_path / ".local" / "state" / "harnessctl" / "backups"
    assert p.log_file == tmp_path / ".local" / "state" / "harnessctl" / "harnessctl.log"


def test_find_project_walks_up(tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    deep = tmp_path / "repo" / "a" / "b"
    deep.mkdir(parents=True)
    assert find_project(deep) == tmp_path / "repo"
    assert project_lock(tmp_path / "repo") == tmp_path / "repo" / ".harnessctl" / "lock.json"


def test_find_project_none_outside_git(tmp_path):
    assert find_project(tmp_path) is None


def test_load_sources_forces_trust_by_file(env):
    write(
        env.paths.corporate_toml,
        '[[source]]\nname = "acme"\nurl = "git@gitlab.acme.io:p/c.git"\nref = "main"\n',
    )
    write(
        env.paths.config_toml,
        '[[source]]\nname = "superpowers"\nurl = "https://github.com/obra/superpowers"\n',
    )
    specs, errors = load_sources(env.paths)
    assert errors == []
    assert specs == [
        SourceSpec("acme", "git@gitlab.acme.io:p/c.git", Trust.CORPORATE, "main", ""),
        SourceSpec("superpowers", "https://github.com/obra/superpowers", Trust.PUBLIC, None, ""),
    ]


def test_public_source_cannot_shadow_corporate(env):
    write(env.paths.corporate_toml, '[[source]]\nname = "acme"\nurl = "u1"\n')
    write(env.paths.config_toml, '[[source]]\nname = "acme"\nurl = "u2"\n')
    specs, errors = load_sources(env.paths)
    assert [s.url for s in specs] == ["u1"]
    assert "shadows a corporate source" in errors[0]


def test_invalid_entries_are_reported_not_fatal(env):
    write(
        env.paths.config_toml,
        '[[source]]\nname = "Bad Name"\nurl = "u"\n'
        '[[source]]\nname = "ok"\nurl = "u"\nsubdir = "../escape"\n'
        '[[source]]\nname = "good"\nurl = "u"\n',
    )
    specs, errors = load_sources(env.paths)
    assert [s.name for s in specs] == ["good"]
    assert len(errors) == 2


def test_broken_toml_is_an_error_not_a_crash(env):
    write(env.paths.config_toml, "[[source]\n")
    specs, errors = load_sources(env.paths)
    assert specs == [] and "config.toml" in errors[0]


def test_add_and_remove_public_source(env):
    add_public_source(
        env.paths, SourceSpec("sp", "https://github.com/obra/superpowers", Trust.PUBLIC, ref="v6")
    )
    specs, _ = load_sources(env.paths)
    assert specs == [SourceSpec("sp", "https://github.com/obra/superpowers", Trust.PUBLIC, "v6", "")]
    with pytest.raises(ConfigError):
        add_public_source(env.paths, SourceSpec("sp", "other", Trust.PUBLIC))
    remove_public_source(env.paths, "sp")
    assert load_sources(env.paths)[0] == []
    with pytest.raises(ConfigError):
        remove_public_source(env.paths, "sp")


def test_add_source_never_touches_corporate_toml(env):
    corp = write(env.paths.corporate_toml, '[[source]]\nname = "acme"\nurl = "u"\n')
    before = corp.read_bytes()
    add_public_source(env.paths, SourceSpec("x", "u2", Trust.PUBLIC))
    assert corp.read_bytes() == before


@pytest.mark.parametrize(
    ("url", "name"),
    [
        ("git@github.com:obra/superpowers.git", "superpowers"),
        ("https://github.com/gfargo/skills/", "skills"),
        ("https://example.com/My Repo.git", "my-repo"),
    ],
)
def test_default_source_name(url, name):
    assert default_source_name(url) == name
