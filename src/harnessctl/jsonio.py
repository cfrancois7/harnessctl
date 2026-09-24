"""JSON / JSONC reading, order-preserving JSON writing, and hashing."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

_STRING = r'"(?:\\.|[^"\\])*"'
_COMMENT = re.compile(rf"{_STRING}|//[^\n]*|/\*.*?\*/", re.S)
_TRAILING_COMMA = re.compile(rf"{_STRING}|,(?=\s*[}}\]])")


class JsonFileError(Exception):
    """A JSON file that exists but cannot be parsed."""

    def __init__(self, path: Path, message: str):
        super().__init__(f"{path}: {message}")
        self.path = path


def strip_comments(text: str) -> tuple[str, bool]:
    """Remove // and /* */ comments outside strings. Returns (text, whether any were found)."""
    found = False

    def replace(match: re.Match[str]) -> str:
        nonlocal found
        token = match.group(0)
        if token.startswith('"'):
            return token
        found = True
        return "" if token.startswith("//") else " "

    return _COMMENT.sub(replace, text), found


def has_comments(text: str) -> bool:
    return strip_comments(text)[1]


def loads_jsonc(text: str) -> Any:
    clean, _ = strip_comments(text)
    clean = _TRAILING_COMMA.sub(lambda m: m.group(0) if m.group(0).startswith('"') else "", clean)
    return json.loads(clean)


def read_json(path: Path, default: Any = None) -> Any:
    """Read JSON or JSONC. A missing file gives `default`; an invalid one raises JsonFileError."""
    if not path.exists():
        return default
    try:
        return loads_jsonc(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise JsonFileError(path, str(exc)) from exc


def dumps(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.is_file() else None
