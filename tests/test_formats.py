import json
import shutil

import pytest

from harnessctl.model import (
    ClaudePluginVariant,
    FilesVariant,
    Kind,
    NpmPluginVariant,
    SkillVariant,
    SourceFormat,
)
from harnessctl.sources.formats import detect_format, load_items, payload_hash, read_frontmatter
from harnessctl.validate import validate_catalog
from tests.helpers import EXAMPLES, skill, write


def test_detect_format(tmp_path):
    assert detect_format(EXAMPLES) is SourceFormat.CATALOG
    write(tmp_path / "m" / ".claude-plugin" / "marketplace.json", "{}")
    assert detect_format(tmp_path / "m") is SourceFormat.CLAUDE_MARKETPLACE
    skill(tmp_path / "s" / "skills" / "one")
    assert detect_format(tmp_path / "s") is SourceFormat.SKILLS_REPO
    assert detect_format(tmp_path) is None


def test_example_catalog_loads_cleanly():
    items, warnings = load_items(EXAMPLES, SourceFormat.CATALOG, "acme")
    assert warnings == []
    by_id = {i.id: i for i in items}
    assert set(by_id) == {"api-conventions", "block-secrets-read", "jira-context"}

    sk = by_id["api-conventions"]
    assert sk.kind is Kind.SKILL and sk.version == "1.4.0" and sk.source == "acme"
    assert set(sk.variants) == {"claude-code", "opencode"}
    assert isinstance(sk.variants["opencode"], SkillVariant)
    assert "# API conventions" in sk.readme

    hook = by_id["block-secrets-read"].variants["claude-code"]
    assert isinstance(hook, FilesVariant)
    assert hook.files[0][1] == "hooks/block-secrets-read/secrets.sh"
    assert hook.files[0][0].is_file()
    assert "{scope_dir}" in json.dumps(hook.settings)

    plug = by_id["jira-context"]
    assert plug.variants["claude-code"] == ClaudePluginVariant(
        "https://github.com/acme/claude-plugins", "acme-plugins", "jira-context"
    )
    assert plug.variants["claude-code"].plugin_id == "jira-context@acme-plugins"
    assert plug.variants["opencode"] == NpmPluginVariant("@acme/opencode-jira@1.2.0")


def _catalog_with(tmp_path, item_toml: str, files: dict[str, str] | None = None):
    root = tmp_path / "cat"
    shutil.copytree(EXAMPLES, root)
    item = root / "items" / "bad"
    write(item / "item.toml", item_toml)
    for rel, text in (files or {}).items():
        write(item / rel, text)
    return root


def test_bad_items_are_skipped_with_warnings(tmp_path):
    root = _catalog_with(
        tmp_path,
        """
id = "Bad_Id"
kind = "hook"
version = "one"
[variants.claude-code]
type = "files"
files = { "missing.sh" = "../../etc/passwd" }
[variants.claude-code.settings]
permissions = {}
hooks.PreToolUse = [{ hooks = [{ type = "command", command = "{home}/x" }] }]
""",
    )
    items, warnings = load_items(root, SourceFormat.CATALOG, "acme")
    assert {i.id for i in items} == {"api-conventions", "block-secrets-read", "jira-context"}
    text = "\n".join(warnings)
    for fragment in [
        "id must match",
        "semantic version",
        "not found in item folder",
        "must be a relative path",
        "may only contain hooks",
        "unknown placeholder {home}",
    ]:
        assert fragment in text
    assert all(w.startswith("items/bad/item.toml: ") for w in warnings)


def test_file_source_escaping_item_folder_is_rejected(tmp_path):
    root = _catalog_with(
        tmp_path,
        """
id = "y"
kind = "hook"
version = "1.0.0"
[variants.claude-code]
type = "files"
files = { "/etc/passwd" = "hooks/y/leak.txt", "../outside.sh" = "hooks/y/leak2.txt" }
""",
    )
    _, warnings = load_items(root, SourceFormat.CATALOG, "acme")
    text = "\n".join(warnings)
    assert "'/etc/passwd'" in text
    assert "'../outside.sh'" in text
    assert text.count("must be a relative path inside the item folder") == 2
    assert "not found in item folder" not in text


def test_variant_type_harness_mismatch(tmp_path):
    root = _catalog_with(
        tmp_path,
        """
id = "x"
kind = "plugin"
version = "1.0.0"
[variants.opencode]
type = "claude-plugin"
marketplace = "u"
marketplace_name = "m"
plugin = "p"
""",
    )
    _, warnings = load_items(root, SourceFormat.CATALOG, "acme")
    assert any("claude-plugin variants are only for claude-code" in w for w in warnings)


def test_duplicate_ids_are_rejected(tmp_path):
    root = _catalog_with(tmp_path, (EXAMPLES / "items/jira-context/item.toml").read_text())
    _, warnings = load_items(root, SourceFormat.CATALOG, "acme")
    assert any("duplicate id 'jira-context'" in w for w in warnings)


def test_validate_catalog_reports_everything(tmp_path):
    assert validate_catalog(EXAMPLES) == []
    assert "no catalog.toml" in validate_catalog(tmp_path)[0]


def test_marketplace_format(tmp_path):
    root = tmp_path / "m"
    write(
        root / ".claude-plugin" / "marketplace.json",
        json.dumps(
            {
                "name": "gfargo-skills",
                "plugins": [
                    {"name": "terminal", "version": "1.0.6", "description": "TUI tools"},
                    {"description": "no name"},
                ],
            }
        ),
    )
    items, warnings = load_items(
        root, SourceFormat.CLAUDE_MARKETPLACE, "gfargo", "https://github.com/gfargo/skills"
    )
    assert [i.id for i in items] == ["terminal"]
    assert items[0].kind is Kind.PLUGIN
    assert items[0].variants == {
        "claude-code": ClaudePluginVariant("https://github.com/gfargo/skills", "gfargo-skills", "terminal")
    }
    assert warnings == ["marketplace.json: a plugin has no name"]


def test_skills_repo_format(tmp_path):
    root = tmp_path / "s"
    skill(root / "skills" / "tdd", description="Red green refactor")
    write(root / "skills" / "raw" / "SKILL.md", "no frontmatter here")
    items, warnings = load_items(root, SourceFormat.SKILLS_REPO, "pub")
    assert warnings == []
    by_id = {i.id: i for i in items}
    assert by_id["tdd"].description == "Red green refactor"
    assert by_id["raw"].description == "" and by_id["raw"].version == "0.0.0"
    assert set(by_id["tdd"].variants) == {"claude-code", "opencode"}


def test_read_frontmatter_tolerates_bad_yaml(tmp_path):
    md = write(tmp_path / "SKILL.md", "---\nname: [unclosed\n---\nbody\n")
    assert read_frontmatter(md) == ({}, "---\nname: [unclosed\n---\nbody\n")


def test_payload_hash_tracks_content(tmp_path):
    folder = tmp_path / "sk"
    skill(folder, body="one")
    before = payload_hash(SkillVariant(folder))
    skill(folder, body="two")
    assert payload_hash(SkillVariant(folder)) != before


def _marketplace(tmp_path, content):
    root = tmp_path / "m"
    path = root / ".claude-plugin" / "marketplace.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode())
    return root


@pytest.mark.parametrize(
    "content",
    [
        "[]",
        '"x"',
        json.dumps({"name": ["m"]}),
        json.dumps({"name": "m", "plugins": "x"}),
        json.dumps({"name": "m", "plugins": {"a": 1}}),
        b'{"name": "m\xff"}',
    ],
)
def test_marketplace_of_the_wrong_shape_is_a_warning(tmp_path, content):
    root = _marketplace(tmp_path, content)
    items, warnings = load_items(root, SourceFormat.CLAUDE_MARKETPLACE, "m", "u")
    assert items == [] and len(warnings) == 1
    assert "marketplace.json: " in warnings[0]
    assert validate_catalog(root) == warnings


def test_marketplace_plugin_entries_are_checked(tmp_path):
    plugins = [
        "x",
        {"name": "--help"},
        {"name": "Bad Name"},
        {"name": "ok", "version": "1.0.0", "description": ["not", "a", "string"]},
        {"name": "ok"},
        {"name": "fine", "version": {"no": 1}},
    ]
    root = _marketplace(tmp_path, json.dumps({"name": "m", "plugins": plugins}))
    items, warnings = load_items(root, SourceFormat.CLAUDE_MARKETPLACE, "m", "u")
    assert [i.id for i in items] == ["ok", "fine"]
    assert items[0].description == "" and items[1].version == "0.0.0"
    assert warnings == [
        "marketplace.json: plugin 1 is not an object",
        "marketplace.json: plugin '--help': name must match [a-z0-9][a-z0-9-]*",
        "marketplace.json: plugin 'Bad Name': name must match [a-z0-9][a-z0-9-]*",
        "marketplace.json: plugin 'ok': duplicate name",
    ]


def test_non_utf8_catalog_files_are_warnings(tmp_path):
    root = tmp_path / "c"
    shutil.copytree(EXAMPLES, root)
    (root / "items" / "api-conventions" / "item.toml").write_bytes(b'id = "caf\xe9"\n')
    items, warnings = load_items(root, SourceFormat.CATALOG, "acme")
    assert {i.id for i in items} == {"block-secrets-read", "jira-context"}
    assert len(warnings) == 1 and warnings[0].startswith("items/api-conventions/item.toml: ")
    (root / "catalog.toml").write_bytes(b'name = "caf\xe9"\n')
    items, warnings = load_items(root, SourceFormat.CATALOG, "acme")
    assert items == [] and len(warnings) == 1 and warnings[0].startswith("catalog.toml: ")


@pytest.mark.parametrize(
    "hooks, message",
    [
        ('hooks = "oops"', "hooks must be a table of events"),
        ('hooks.PreToolUse = "oops"', "hooks.PreToolUse must be a list of matcher groups"),
        ('hooks.PreToolUse = ["oops"]', "hooks.PreToolUse[0] must be a table"),
        ("hooks.PreToolUse = [{ matcher = 3, hooks = [] }]", "hooks.PreToolUse[0].matcher must be a string"),
        ('hooks.PreToolUse = [{ matcher = "Read" }]', "hooks.PreToolUse[0].hooks must be a non-empty list"),
        ('hooks.PreToolUse = [{ hooks = ["x"] }]', "hooks.PreToolUse[0].hooks[0] must be a table"),
        ('hooks.PreToolUse = [{ hooks = [{ type = "command" }] }]', "hooks.PreToolUse[0].hooks[0].command"),
        (
            'hooks.PreToolUse = [{ hooks = [{ type = 1, command = "x" }] }]',
            "hooks.PreToolUse[0].hooks[0].type must be a string",
        ),
    ],
)
def test_malformed_hooks_fragment_is_rejected(tmp_path, hooks, message):
    root = _catalog_with(
        tmp_path,
        f"""
id = "bad"
kind = "hook"
version = "1.0.0"
[variants.claude-code]
type = "files"
files = {{ "s.sh" = "hooks/s.sh" }}
[variants.claude-code.settings]
{hooks}
""",
    )
    write(root / "items" / "bad" / "s.sh", "echo\n")
    items, warnings = load_items(root, SourceFormat.CATALOG, "acme")
    assert "bad" not in {i.id for i in items}
    assert any(message in w for w in warnings), warnings
