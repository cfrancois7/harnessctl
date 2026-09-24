import json

import pytest

from harnessctl.jsonio import JsonFileError
from harnessctl.model import InstalledItem, Kind, Scope, SourceSpec, Trust
from harnessctl.provenance import (
    LockEntry,
    add_entry_edit,
    normalize_url,
    read_lock,
    remove_entry_edit,
    resolve,
)
from tests.helpers import write


def _entry(**kw) -> LockEntry:
    base = dict(
        item_id="api-conventions",
        source="acme",
        harness="claude-code",
        kind="skill",
        version="1.4.0",
        commit="a" * 40,
        locations=["/h/.claude/skills/api-conventions"],
        files={},
    )
    return LockEntry(**(base | kw))


def _item(location="/h/.claude/skills/api-conventions", **meta) -> InstalledItem:
    return InstalledItem("claude-code", Scope.USER, Kind.SKILL, "x", location, meta=meta)


SOURCES = {
    "acme": SourceSpec("acme", "git@gitlab.acme.io:platform/agent-catalog.git", Trust.CORPORATE),
    "sp": SourceSpec("sp", "https://github.com/obra/superpowers", Trust.PUBLIC),
}


def test_read_lock_missing_is_empty(tmp_path):
    assert read_lock(tmp_path / "lock.json") == []


def test_read_lock_rejects_foreign_files(tmp_path):
    with pytest.raises(JsonFileError):
        read_lock(write(tmp_path / "lock.json", '{"version": 7, "entries": []}'))
    with pytest.raises(JsonFileError):
        read_lock(write(tmp_path / "lock2.json", '{"version": 1, "entries": [{"item_id": "x"}]}'))


def test_edits_roundtrip(tmp_path):
    data = add_entry_edit(_entry())(None)
    data = add_entry_edit(_entry(version="1.5.0"))(data)
    assert [e["version"] for e in data["entries"]] == ["1.5.0"]
    lock = write(tmp_path / "lock.json", json.dumps(data))
    assert read_lock(lock) == [_entry(version="1.5.0")]
    assert remove_entry_edit(_entry())(data)["entries"] == []


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:obra/superpowers.git",
        "https://github.com/obra/superpowers",
        "https://GitHub.com/obra/superpowers.git/",
        "git+https://github.com/obra/superpowers.git",
        "ssh://git@github.com/obra/superpowers",
    ],
)
def test_normalize_url_equivalences(url):
    assert normalize_url(url) == "github.com/obra/superpowers"


def test_resolve_by_lock_entry_uses_source_trust():
    prov, entry = resolve(_item(), [_entry()], SOURCES)
    assert (prov.origin, prov.source, prov.item_id, prov.commit) == (
        "corp",
        "acme",
        "api-conventions",
        "a" * 40,
    )
    assert entry == _entry()
    prov, _ = resolve(_item(), [_entry(source="sp")], SOURCES)
    assert prov.origin == "public"


def test_resolve_lock_entry_of_removed_source_is_unknown_but_named():
    prov, entry = resolve(_item(), [_entry(source="gone")], SOURCES)
    assert (prov.origin, prov.source) == ("unknown", "gone") and entry is not None


def test_resolve_by_repo_url():
    corp = _item("claude-plugin:x@acme", repo_url="https://gitlab.acme.io/platform/agent-catalog")
    assert resolve(corp, [], SOURCES)[0].origin == "corp"
    other = _item("claude-plugin:y@z", repo_url="https://github.com/gfargo/skills")
    prov, _ = resolve(other, [], SOURCES)
    assert (prov.origin, prov.source) == ("public", "github.com/gfargo/skills")


def test_resolve_nothing_is_unknown():
    assert resolve(_item("/h/.claude/skills/mine"), [_entry()], SOURCES)[0].origin == "unknown"


def test_resolve_ignores_other_harness_entries():
    assert resolve(_item(), [_entry(harness="opencode")], SOURCES)[0].origin == "unknown"
