"""Command-line entry point. `harnessctl` opens the TUI (wired in Task 14)."""

import argparse
import sys
from pathlib import Path

from harnessctl import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harnessctl",
        description="Manage skills, hooks and plugins for Claude Code and opencode.",
    )
    parser.add_argument("--version", action="version", version=f"harnessctl {__version__}")
    parser.add_argument("--project", type=Path, help="project directory (default: nearest git root)")
    return parser


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    return 0


def run() -> None:
    sys.exit(main())
