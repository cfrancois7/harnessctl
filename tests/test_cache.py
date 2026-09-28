import shutil

from harnessctl.model import SourceFormat, SourceSpec, Trust
from harnessctl.sources.cache import sync_source
from tests.helpers import EXAMPLES, commit_all, make_repo, write


def _spec(url, **kw):
    return SourceSpec("acme", url, Trust.CORPORATE, **kw)


def test_first_sync_clones_and_loads(tmp_path):
    repo = make_repo(EXAMPLES, tmp_path / "remote")
    state = sync_source(_spec(repo.as_uri()), tmp_path / "cache")
    assert state.status == "ok" and state.error is None
    assert state.format is SourceFormat.CATALOG
    assert len(state.items) == 3 and len(state.commit) == 40
    assert state.last_sync is not None
    assert (tmp_path / "cache" / "acme" / "catalog.toml").is_file()


def test_resync_picks_up_new_commits(tmp_path):
    repo = make_repo(EXAMPLES, tmp_path / "remote")
    first = sync_source(_spec(repo.as_uri()), tmp_path / "cache")
    shutil.rmtree(repo / "items" / "jira-context")
    commit_all(repo, "drop jira")
    second = sync_source(_spec(repo.as_uri()), tmp_path / "cache")
    assert second.commit != first.commit
    assert {i.id for i in second.items} == {"api-conventions", "block-secrets-read"}


def test_unreachable_remote_with_cache_is_stale(tmp_path):
    repo = make_repo(EXAMPLES, tmp_path / "remote")
    sync_source(_spec(repo.as_uri()), tmp_path / "cache")
    shutil.rmtree(repo)
    state = sync_source(_spec(repo.as_uri()), tmp_path / "cache")
    assert state.status == "stale"
    assert state.error
    assert len(state.items) == 3


def test_unreachable_remote_without_cache_is_unavailable(tmp_path):
    state = sync_source(_spec((tmp_path / "nowhere").as_uri()), tmp_path / "cache")
    assert state.status == "unavailable" and state.items == []
    assert state.error


def test_no_fetch_uses_cache_only(tmp_path):
    state = sync_source(_spec("file:///never/used"), tmp_path / "cache", fetch=False)
    assert state.status == "unavailable" and state.error == "not synced yet"


def test_subdir_and_unknown_layout(tmp_path):
    mono = tmp_path / "mono"
    shutil.copytree(EXAMPLES, mono / "agents" / "catalog")
    write(mono / "README.md", "monorepo")
    make_repo(None, mono)
    ok = sync_source(_spec(mono.as_uri(), subdir="agents/catalog"), tmp_path / "c1")
    assert ok.status == "ok" and len(ok.items) == 3
    bad = sync_source(_spec(mono.as_uri()), tmp_path / "c2")
    assert bad.status == "unavailable" and "no recognised catalog format" in bad.error


def test_a_source_whose_items_cannot_load_is_unavailable_not_a_crash(tmp_path, monkeypatch):
    from harnessctl.sources import cache

    repo = make_repo(EXAMPLES, tmp_path / "remote")

    def boom(*args, **kwargs):
        raise AttributeError("'list' object has no attribute 'get'")

    monkeypatch.setattr(cache, "load_items", boom)
    state = sync_source(_spec(repo.as_uri()), tmp_path / "cache")
    assert state.status == "unavailable" and state.items == []
    assert "cannot load items" in state.error and "has no attribute" in state.error


def test_a_changed_url_reclones_from_the_new_repo_instead_of_fetching_the_old_one(tmp_path):
    repo_a = make_repo(EXAMPLES, tmp_path / "remote-a")
    cache_root = tmp_path / "cache"
    first = sync_source(_spec(repo_a.as_uri()), cache_root)
    assert {i.id for i in first.items} == {"api-conventions", "block-secrets-read", "jira-context"}

    other = tmp_path / "remote-b-src"
    shutil.copytree(EXAMPLES, other)
    shutil.rmtree(other / "items" / "jira-context")
    repo_b = make_repo(None, other)

    second = sync_source(_spec(repo_b.as_uri()), cache_root)
    assert second.status == "ok" and second.error is None
    assert {i.id for i in second.items} == {"api-conventions", "block-secrets-read"}


def test_a_url_changed_to_unreachable_leaves_the_source_unavailable_not_the_old_repo(tmp_path):
    repo_a = make_repo(EXAMPLES, tmp_path / "remote-a")
    cache_root = tmp_path / "cache"
    first = sync_source(_spec(repo_a.as_uri()), cache_root)
    assert first.status == "ok" and len(first.items) == 3
    checkout = cache_root / "acme"
    assert (checkout / ".git").is_dir()

    bad_spec = _spec((tmp_path / "nowhere").as_uri())

    changed = sync_source(bad_spec, cache_root)
    assert changed.status == "unavailable"
    assert changed.items == []
    assert changed.error
    # the old checkout is kept on disk, untouched, not deleted:
    assert (checkout / ".git").is_dir()
    assert (checkout / "catalog.toml").is_file()

    stale_no_fetch = sync_source(bad_spec, cache_root, fetch=False)
    assert stale_no_fetch.status == "unavailable"
    assert stale_no_fetch.items == []
    assert stale_no_fetch.error

    reverted = sync_source(_spec(repo_a.as_uri()), cache_root, fetch=False)
    assert reverted.status == "ok" and reverted.error is None
    assert {i.id for i in reverted.items} == {"api-conventions", "block-secrets-read", "jira-context"}


def test_marketplace_that_is_a_list_leaves_the_source_unavailable_with_a_warning(tmp_path):
    remote = tmp_path / "remote"
    write(remote / ".claude-plugin" / "marketplace.json", "[]")
    make_repo(None, remote)
    state = sync_source(_spec(remote.as_uri()), tmp_path / "cache")
    assert state.items == [] and state.warnings
