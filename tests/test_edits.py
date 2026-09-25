from pathlib import Path

from harnessctl.edits import (
    add_plugin_spec_edit,
    expand_placeholders,
    merge_hooks_edit,
    plugin_spec_name,
    remove_hooks_edit,
    remove_plugin_spec_edit,
)

THEIRS = {
    "theme": "dark",
    "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "mine.sh"}]}]},
}
OURS = {
    "PreToolUse": [{"matcher": "Read", "hooks": [{"type": "command", "command": "/h/.claude/hooks/x.sh"}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "/h/.claude/hooks/x.sh"}]}],
}


def _copy(d):
    import copy

    return copy.deepcopy(d)


def test_merge_hooks_keeps_foreign_entries():
    data = merge_hooks_edit(OURS)(_copy(THEIRS))
    assert data["theme"] == "dark"
    assert [g["matcher"] for g in data["hooks"]["PreToolUse"]] == ["Bash", "Read"]
    assert data["hooks"]["Stop"] == OURS["Stop"]


def test_merge_into_missing_file():
    assert merge_hooks_edit(OURS)(None) == {"hooks": OURS}


def test_remove_hooks_only_removes_ours_and_prunes_empties():
    data = merge_hooks_edit(OURS)(_copy(THEIRS))
    data = remove_hooks_edit("PreToolUse", "Read", "/h/.claude/hooks/x.sh")(data)
    data = remove_hooks_edit("Stop", None, "/h/.claude/hooks/x.sh")(data)
    assert data == THEIRS
    data = remove_hooks_edit("PreToolUse", "Bash", "mine.sh")(data)
    assert data == {"theme": "dark"}


def test_plugin_spec_edits():
    data = add_plugin_spec_edit("@acme/jira@1.2.0")(None)
    assert data == {"$schema": "https://opencode.ai/config.json", "plugin": ["@acme/jira@1.2.0"]}
    data = add_plugin_spec_edit("@acme/jira@1.2.0")(data)
    assert data["plugin"] == ["@acme/jira@1.2.0"]
    data["plugin"].append(["opencode-bar", {"k": "v"}])
    data = remove_plugin_spec_edit("opencode-bar")(data)
    assert data["plugin"] == ["@acme/jira@1.2.0"]


def test_plugin_spec_name():
    assert plugin_spec_name("superpowers@git+https://github.com/obra/superpowers.git") == "superpowers"
    assert plugin_spec_name("@acme/opencode-jira@1.2.0") == "@acme/opencode-jira"
    assert plugin_spec_name("opencode-foo") == "opencode-foo"


def test_expand_placeholders():
    value = {"a": ["{scope_dir}/x.sh", 3], "b": "{scope_dir}"}
    assert expand_placeholders(value, Path("/h/.claude")) == {"a": ["/h/.claude/x.sh", 3], "b": "/h/.claude"}
