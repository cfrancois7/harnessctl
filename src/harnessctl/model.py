"""Domain types shared by every layer of harnessctl."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class Trust(StrEnum):
    CORPORATE = "corporate"
    PUBLIC = "public"


class Kind(StrEnum):
    SKILL = "skill"
    HOOK = "hook"
    PLUGIN = "plugin"


class Scope(StrEnum):
    USER = "user"
    PROJECT = "project"
    LOCAL = "local"


class Status(StrEnum):
    OK = "ok"
    MODIFIED = "modified"
    UPDATE = "update"
    BROKEN = "broken"


class SourceFormat(StrEnum):
    CATALOG = "catalog"
    CLAUDE_MARKETPLACE = "claude-marketplace"
    SKILLS_REPO = "skills-repo"


HARNESSES = ("claude-code", "opencode")


@dataclass(frozen=True)
class SourceSpec:
    name: str
    url: str
    trust: Trust
    ref: str | None = None
    subdir: str = ""


@dataclass
class SkillVariant:
    path: Path  # folder containing SKILL.md


@dataclass
class FilesVariant:
    files: list[tuple[Path, str]]  # (absolute source file, destination relative to the scope folder)
    settings: dict = field(default_factory=dict)  # only "hooks"; "{scope_dir}" not yet expanded
    root: Path | None = None  # the item folder; no source file may resolve outside it


@dataclass
class ClaudePluginVariant:
    marketplace_url: str
    marketplace_name: str
    plugin: str

    @property
    def plugin_id(self) -> str:
        return f"{self.plugin}@{self.marketplace_name}"


@dataclass
class NpmPluginVariant:
    package: str


Variant = SkillVariant | FilesVariant | ClaudePluginVariant | NpmPluginVariant


@dataclass
class CatalogItem:
    id: str
    kind: Kind
    version: str
    description: str
    source: str
    variants: dict[str, Variant]
    tags: list[str] = field(default_factory=list)
    readme: str = ""


@dataclass
class Provenance:
    origin: str  # "corp" | "public" | "unknown"
    source: str | None = None
    item_id: str | None = None
    commit: str | None = None

    @classmethod
    def unknown(cls) -> Provenance:
        return cls("unknown")

    @property
    def label(self) -> str:
        return self.origin


@dataclass
class InstalledItem:
    harness: str
    scope: Scope
    kind: Kind
    name: str
    location: str  # a path, or a config key such as "claude-plugin:<id>"
    enabled: bool = True
    parent: str | None = None  # plugin id this item ships with
    provenance: Provenance = field(default_factory=Provenance.unknown)
    status: Status = Status.OK
    detail: str = ""  # markdown for the detail pane
    error: str | None = None
    readonly: str | None = None  # why the item cannot be changed, if it cannot
    also_in: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
