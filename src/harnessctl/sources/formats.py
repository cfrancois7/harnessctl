"""Turn a source checkout into catalog items, whatever its format."""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

import yaml

from harnessctl.jsonio import sha256_file
from harnessctl.model import (
    HARNESSES,
    CatalogItem,
    ClaudePluginVariant,
    FilesVariant,
    Kind,
    NpmPluginVariant,
    SkillVariant,
    SourceFormat,
    Variant,
)
from harnessctl.validate import ID_RE, _safe_destination, check_item


def detect_format(root: Path) -> SourceFormat | None:
    if (root / "catalog.toml").is_file():
        return SourceFormat.CATALOG
    if (root / ".claude-plugin" / "marketplace.json").is_file():
        return SourceFormat.CLAUDE_MARKETPLACE
    if any((root / "skills").glob("*/SKILL.md")):
        return SourceFormat.SKILLS_REPO
    return None


def read_frontmatter(skill_md: Path) -> tuple[dict, str]:
    """(frontmatter, body). Missing or invalid frontmatter gives ({}, whole text)."""
    text = skill_md.read_text(errors="replace")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            try:
                data = yaml.safe_load(text[3:end]) or {}
            except yaml.YAMLError:
                data = None
            if isinstance(data, dict):
                return data, text[end + 4 :].lstrip("\n")
    return {}, text


def load_items(
    root: Path, fmt: SourceFormat, source: str, source_url: str = ""
) -> tuple[list[CatalogItem], list[str]]:
    match fmt:
        case SourceFormat.CATALOG:
            return _load_catalog(root, source)
        case SourceFormat.CLAUDE_MARKETPLACE:
            return _load_marketplace(root, source, source_url)
        case SourceFormat.SKILLS_REPO:
            return _load_skills_repo(root, source)


def _load_catalog(root: Path, source: str) -> tuple[list[CatalogItem], list[str]]:
    try:
        catalog = tomllib.loads((root / "catalog.toml").read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        return [], [f"catalog.toml: {exc}"]
    patterns = catalog.get("items", ["items/*"])
    if not isinstance(patterns, list) or not all(
        isinstance(p, str) and _safe_destination(p) for p in patterns
    ):
        return [], ["catalog.toml: items must be a list of relative glob patterns"]
    items: list[CatalogItem] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for item_dir in sorted(root.glob(pattern)):
            toml_path = item_dir / "item.toml"
            if not toml_path.is_file():
                continue
            rel = toml_path.relative_to(root).as_posix()
            try:
                data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
            except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
                warnings.append(f"{rel}: {exc}")
                continue
            errors = check_item(item_dir, data)
            if not errors and data["id"] in seen:
                errors = [f"duplicate id {data['id']!r}"]
            if errors:
                warnings.extend(f"{rel}: {e}" for e in errors)
                continue
            seen.add(data["id"])
            items.append(_item_from_toml(item_dir, data, source))
    return items, warnings


def _item_from_toml(item_dir: Path, data: dict, source: str) -> CatalogItem:
    kind = Kind(data["kind"])
    variants: dict[str, Variant] = {}
    readme = ""
    if kind is Kind.SKILL:
        folder = item_dir / data["skill"]["path"]
        for harness in data["skill"].get("harnesses", list(HARNESSES)):
            variants[harness] = SkillVariant(folder)
        readme = read_frontmatter(folder / "SKILL.md")[1]
    else:
        for harness, v in data["variants"].items():
            match v["type"]:
                case "files":
                    files = [(item_dir / src, dest) for src, dest in v["files"].items()]
                    variants[harness] = FilesVariant(files, v.get("settings", {}))
                case "claude-plugin":
                    variants[harness] = ClaudePluginVariant(
                        v["marketplace"], v["marketplace_name"], v["plugin"]
                    )
                case "npm-plugin":
                    variants[harness] = NpmPluginVariant(v["package"])
        if (item_dir / "README.md").is_file():
            readme = (item_dir / "README.md").read_text(errors="replace")
    return CatalogItem(
        id=data["id"],
        kind=kind,
        version=str(data["version"]),
        description=data.get("description", ""),
        source=source,
        variants=variants,
        tags=list(data.get("tags", [])),
        readme=readme,
    )


def _load_marketplace(root: Path, source: str, source_url: str) -> tuple[list[CatalogItem], list[str]]:
    try:
        data = json.loads((root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [], [f".claude-plugin/marketplace.json: {exc}"]
    if not isinstance(data, dict):
        return [], [".claude-plugin/marketplace.json: must be a JSON object"]
    market = data.get("name")
    if not isinstance(market, str) or not market:
        return [], ["marketplace.json: missing name"]
    plugins = data.get("plugins", [])
    if not isinstance(plugins, list):
        return [], ["marketplace.json: plugins must be a list"]
    items: list[CatalogItem] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for n, plugin in enumerate(plugins, start=1):
        if not isinstance(plugin, dict):
            warnings.append(f"marketplace.json: plugin {n} is not an object")
            continue
        name = plugin.get("name")
        if not isinstance(name, str) or not name:
            warnings.append("marketplace.json: a plugin has no name")
            continue
        # The name becomes an argument of `claude plugin install`: never let it look like an option.
        if not ID_RE.match(name):
            warnings.append(f"marketplace.json: plugin {name!r}: name must match [a-z0-9][a-z0-9-]*")
            continue
        if name in seen:
            warnings.append(f"marketplace.json: plugin {name!r}: duplicate name")
            continue
        seen.add(name)
        version = plugin.get("version")
        description = plugin.get("description")
        items.append(
            CatalogItem(
                id=name,
                kind=Kind.PLUGIN,
                version=str(version) if isinstance(version, (str, int, float)) else "0.0.0",
                description=description if isinstance(description, str) else "",
                source=source,
                variants={"claude-code": ClaudePluginVariant(source_url, market, name)},
            )
        )
    return items, warnings


def _load_skills_repo(root: Path, source: str) -> tuple[list[CatalogItem], list[str]]:
    items: list[CatalogItem] = []
    warnings: list[str] = []
    for md in sorted(root.glob("skills/*/SKILL.md")):
        sid = md.parent.name
        if not ID_RE.match(sid):
            warnings.append(f"skills/{sid}: folder name is not a valid id")
            continue
        front, body = read_frontmatter(md)
        items.append(
            CatalogItem(
                id=sid,
                kind=Kind.SKILL,
                version=str(front.get("version", "0.0.0")),
                description=str(front.get("description", "")),
                source=source,
                variants={h: SkillVariant(md.parent) for h in HARNESSES},
                readme=body,
            )
        )
    return items, warnings


def payload_hash(variant: Variant) -> str:
    """A fingerprint of what installing `variant` would write; changes when the payload changes."""
    h = hashlib.sha256()
    match variant:
        case SkillVariant(path=folder):
            for f in sorted(p for p in folder.rglob("*") if p.is_file()):
                h.update(f"{f.relative_to(folder).as_posix()}:{sha256_file(f)}\n".encode())
        case FilesVariant(files=files, settings=settings):
            for src, dest in sorted(files, key=lambda pair: pair[1]):
                h.update(f"{dest}:{sha256_file(src)}\n".encode())
            h.update(json.dumps(settings, sort_keys=True).encode())
        case _:
            h.update(repr(variant).encode())
    return h.hexdigest()
