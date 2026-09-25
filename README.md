# harnessctl

A terminal UI to see and manage what your coding agent is configured with: **skills, hooks
and plugins** for **Claude Code** and **opencode**. Run it in a pane next to your agent.

- **Installed**: everything active for this machine (user scope) and this repo (project scope),
  each item labelled `corp` (from your company's catalog), `public` (from a public repo) or
  `unknown`, with `↑` when an update is available and `±` when you edited it locally.
- **Catalog**: browse the corporate catalog and the public sources you added; install with `i`.
- **Sources**: add public git repos (harnessctl catalogs, Claude plugin marketplaces, skills repos).

Every change is shown as a plan first (files written, settings keys merged, commands run) and
applied all-or-nothing, with a backup under `~/.local/state/harnessctl/backups/`.

## Install

```bash
uv tool install git+https://github.com/cfrancois7/harnessctl@main
harnessctl                # opens the TUI for the current repo
harnessctl --project DIR  # or for another one
```

## Keys

| Where | Keys |
|---|---|
| everywhere | `1` `2` `3` tabs · `h` switch harness · `r` rescan · `/` filter · `?` help · `q` quit |
| Installed | `space` enable/disable · `u` update · `d` remove · `o` open in `$EDITOR` |
| Catalog | `i` install (then pick user or project scope) |
| Sources | `a` add · `r` refresh (replaces rescan here) · `d` remove |
| plan | `enter` apply · `v` view diff · `esc` cancel |

Below 100 columns the detail pane is hidden: `enter` opens it full-screen, `esc` goes back.

## Configuration

`~/.config/harnessctl/corporate.toml` lists the corporate sources. harnessctl never writes this
file; your company distributes it:

```toml
[[source]]
name = "acme"
url  = "git@gitlab.acme.io:platform/agent-catalog.git"
ref  = "main"
```

Public sources you add from the TUI go to `~/.config/harnessctl/config.toml`. Git uses your own
credentials (SSH agent or credential helper).

What harnessctl installed is recorded in `~/.config/harnessctl/lock.json` (user scope) and
`<repo>/.harnessctl/lock.json` (project scope, commit it so your team sees the same provenance).

## Writing a catalog

See [`examples/acme-catalog/`](examples/acme-catalog/README.md). Check a catalog with:

```bash
harnessctl validate path/to/catalog   # exit 1 and one line per problem; use it in the catalog's CI
```

## Limits

- harnessctl never rewrites a JSON file that contains comments (such as a commented
  `opencode.jsonc`); it tells you the edit to make instead.
- Claude Code's `settings.local.json` is shown but never changed.
- Hooks are never translated between harnesses: a catalog item ships one variant per harness.

## Development

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run harnessctl
```
