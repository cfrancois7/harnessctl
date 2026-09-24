"""Lockfiles (what harnessctl installed) and provenance resolution (where an item came from)."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from harnessctl.jsonio import JsonFileError, read_json
from harnessctl.model import InstalledItem, Provenance, SourceSpec, Trust

LOCK_VERSION = 1


@dataclass
class LockEntry:
    item_id: str
    source: str
    harness: str
    kind: str
    version: str
    commit: str | None
    locations: list[str]  # InstalledItem.location values this install produced
    files: dict[str, str]  # absolute path → sha256 of what was written
    payload_hash: str = ""
    settings: dict = field(default_factory=dict)  # hook groups merged, placeholders expanded

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> LockEntry:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def read_lock(path: Path) -> list[LockEntry]:
    data = read_json(path, default={"version": LOCK_VERSION, "entries": []})
    if (
        not isinstance(data, dict)
        or data.get("version") != LOCK_VERSION
        or not isinstance(data.get("entries"), list)
    ):
        raise JsonFileError(path, f"not a harnessctl lockfile (version {LOCK_VERSION})")
    try:
        return [LockEntry.from_json(e) for e in data["entries"]]
    except TypeError as exc:
        raise JsonFileError(path, f"invalid lock entry: {exc}") from exc


def _same(raw: dict, entry: LockEntry) -> bool:
    return (raw.get("item_id"), raw.get("source"), raw.get("harness")) == (
        entry.item_id,
        entry.source,
        entry.harness,
    )


def add_entry_edit(entry: LockEntry) -> Callable[[dict | None], dict]:
    def edit(data: dict | None) -> dict:
        data = data if isinstance(data, dict) else {"version": LOCK_VERSION, "entries": []}
        data["entries"] = [e for e in data.get("entries", []) if not _same(e, entry)] + [entry.to_json()]
        return data

    return edit


def remove_entry_edit(entry: LockEntry) -> Callable[[dict | None], dict]:
    def edit(data: dict | None) -> dict:
        data = data if isinstance(data, dict) else {"version": LOCK_VERSION, "entries": []}
        data["entries"] = [e for e in data.get("entries", []) if not _same(e, entry)]
        return data

    return edit


_SCP_LIKE = re.compile(r"^[\w.-]+@([\w.-]+):(?!//)(.+)$")


def normalize_url(url: str) -> str:
    """'git@github.com:o/r.git', 'https://github.com/o/r', 'git+https://…/o/r.git' → 'github.com/o/r'."""
    u = url.strip()
    scp = _SCP_LIKE.match(u)
    if scp:
        u = f"{scp.group(1)}/{scp.group(2)}"
    else:
        u = re.sub(r"^[a-z][a-z0-9+.-]*://", "", u, flags=re.I)
        u = re.sub(r"^[^@/]+@", "", u)
    u = u.rstrip("/").removesuffix(".git").rstrip("/")
    host, _, path = u.partition("/")
    return f"{host.lower()}/{path}"


def _origin(spec: SourceSpec | None) -> str:
    if spec is None:
        return "unknown"
    return "corp" if spec.trust is Trust.CORPORATE else "public"


def resolve(
    item: InstalledItem, entries: list[LockEntry], sources: dict[str, SourceSpec]
) -> tuple[Provenance, LockEntry | None]:
    """Spec §6: lockfile first, then the item's repo URL, else unknown."""
    for entry in entries:
        if entry.harness == item.harness and item.location in entry.locations:
            return Provenance(
                _origin(sources.get(entry.source)), entry.source, entry.item_id, entry.commit
            ), entry
    repo = item.meta.get("repo_url")
    if repo:
        wanted = normalize_url(repo)
        for spec in sources.values():
            if normalize_url(spec.url) == wanted:
                return Provenance(_origin(spec), spec.name), None
        return Provenance("public", wanted), None
    return Provenance.unknown(), None
