import pytest

from harnessctl.jsonio import JsonFileError, dumps, has_comments, loads_jsonc, read_json, sha256_file
from tests.helpers import write

JSONC = """{
  // line comment
  "$schema": "https://opencode.ai/config.json", /* block */
  "plugin": ["a", "b",],
}
"""


def test_loads_jsonc_strips_comments_and_trailing_commas():
    assert loads_jsonc(JSONC) == {"$schema": "https://opencode.ai/config.json", "plugin": ["a", "b"]}


def test_comment_markers_inside_strings_are_kept():
    assert loads_jsonc('{"u": "http://x/*y*/", "c": "a,]"}') == {"u": "http://x/*y*/", "c": "a,]"}
    assert has_comments('{"u": "http://x"}') is False


def test_has_comments():
    assert has_comments(JSONC) is True
    assert has_comments('{"a": 1}') is False


def test_read_json_missing_returns_default(tmp_path):
    assert read_json(tmp_path / "nope.json", default={"x": 1}) == {"x": 1}


def test_read_json_invalid_raises_with_path(tmp_path):
    bad = write(tmp_path / "settings.json", "{not json")
    with pytest.raises(JsonFileError) as exc:
        read_json(bad)
    assert exc.value.path == bad
    assert "settings.json" in str(exc.value)


def test_dumps_keeps_order_and_indent():
    assert dumps({"b": 1, "a": {"c": [1]}}) == '{\n  "b": 1,\n  "a": {\n    "c": [\n      1\n    ]\n  }\n}\n'


def test_sha256_file(tmp_path):
    f = write(tmp_path / "f", "x")
    assert sha256_file(f) == "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881"
    assert sha256_file(tmp_path / "missing") is None
