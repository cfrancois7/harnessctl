"""Command-line entry point. `harnessctl` opens the TUI (wired in Task 14)."""

import argparse
import sys
from pathlib import Path

from harnessctl import __version__
from harnessctl.validate import validate_catalog


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harnessctl",
        description="Manage skills, hooks and plugins for Claude Code and opencode.",
    )
    parser.add_argument("--version", action="version", version=f"harnessctl {__version__}")
    parser.add_argument("--project", type=Path, help="project directory (default: nearest git root)")
    sub = parser.add_subparsers(dest="command")
    check = sub.add_parser("validate", help="check a catalog checkout (use it in the catalog's CI)")
    check.add_argument("path", type=Path)
    return parser


def _validate(path: Path) -> int:
    from harnessctl.sources.formats import detect_format, load_items

    problems = validate_catalog(path)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"{len(problems)} problem{'s' if len(problems) > 1 else ''} found")
        return 1
    fmt = detect_format(path)
    items, _ = load_items(path, fmt, source="validate")
    print(f"catalog ok: {len(items)} items")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate":
        return _validate(args.path)
    return 0


def run() -> None:
    sys.exit(main())
