"""Command-line entry point. `harnessctl` opens the TUI; `harnessctl validate` lints a catalog."""

import argparse
import logging
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


def _setup_logging(paths) -> None:
    paths.state.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=paths.log_file, level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate":
        return _validate(args.path)

    from harnessctl.config import Paths, find_project
    from harnessctl.engine import Engine
    from harnessctl.tui.app import HarnessApp

    paths = Paths.from_env()
    _setup_logging(paths)
    home = paths.home.resolve()
    project = args.project.resolve() if args.project else find_project(Path.cwd().resolve(), home)
    if project == home:
        project = None  # user and project scope would be the same folders
    HarnessApp(Engine(paths, project)).run()
    return 0


def run() -> None:
    sys.exit(main())
