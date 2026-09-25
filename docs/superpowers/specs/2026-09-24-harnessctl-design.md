# harnessctl — design

Date: 2026-09-24 · Status: approved in brainstorming, pending spec review

## 1. Purpose

`harnessctl` is a terminal UI (Textual) that lets a developer see and manage the
configuration of their coding-agent harness — **skills, hooks and plugins** — while the
agent runs next to it in another terminal pane.

Two views drive it:

- **Catalog** — items from *sources*: the company's catalog of authorized skills/hooks/plugins
  (corporate) and public GitHub repos the user adds (superpowers, gfargo/skills, …).
- **Installed** — what is actually configured on this machine and in this project, each item
  labelled with where it came from: `corp`, `public` or `unknown`.

Success for v1: a developer using Claude Code (and soon opencode) can, from one screen,
answer "what is active here and where did it come from?", browse the corporate catalog,
and install/remove/enable/disable/update items at user or project scope without editing
config files by hand — and every change is shown before it is made.

### Decisions taken

| Topic | Decision |
|---|---|
| Role of "authorized" | Discovery + visibility: provenance badges, nothing is blocked. Enforcement is out of v1. |
| Harnesses | Claude Code and opencode, behind an adapter interface. |
| Non-portable items | Each catalog item carries **per-harness variants**; skills share one payload. The tool installs exactly what the author wrote; it never translates hooks between harnesses. |
| Public items | Users can add public git repos as personal sources and install from them. |
| Scopes | User and project. Claude's `local` scope is shown read-only, never an install target. |
| Install mechanics | Hybrid: native harness mechanisms where they exist (Claude plugins), direct file writes otherwise; a lockfile records what harnessctl wrote. |
| TUI layout | Tabs + list/detail (layout A), single pane with Enter/Esc drill-in below ~100 columns. |
| Stack | Python 3.14, Textual 8.x, uv (one project venv), pytest, ruff. Installed with `uv tool install`. |
| Branching | `develop` for work, `main` for stable releases. |

## 2. Domain model

- **Source** — a git repo cloned into the cache. Fields: `name`, `url`, `ref`, optional
  `subdir`, `trust` (`corporate` | `public`), and a detected `format`:
  - `catalog` — has `catalog.toml` (harnessctl's own format; §5).
  - `claude-marketplace` — has `.claude-plugin/marketplace.json`; each listed plugin becomes a
    plugin item with a single `claude-plugin` variant.
  - `skills-repo` — has `skills/*/SKILL.md`; each becomes a skill item available to both harnesses.
  Detection order is the order above; the first match wins.
- **CatalogItem** — `id`, `kind` (`skill` | `hook` | `plugin`), `version`, `description`,
  `tags`, `source`, and `variants: {harness_id: Variant}`.
- **Variant** — how to install the item for one harness. Types: `skill` (a skill folder),
  `files` (files + JSON settings fragment), `claude-plugin` (marketplace + plugin name),
  `npm-plugin` (an npm spec added to opencode's `plugin` array).
- **InstalledItem** — `harness`, `scope` (`user` | `project` | `local`), `kind`, `name`,
  `location` (path or config key), `enabled`, `parent` (plugin it belongs to, if any),
  `provenance`, `status` (`ok` | `modified` | `update` | `broken`), `detail` (parsed content
  for the detail pane).
- **Provenance** — `corp(source, item, commit)` | `public(source-or-repo)` | `unknown`.
- **Plan** — ordered `Step`s (`WriteFile`, `DeleteFile`, `MergeJson`, `RemoveJson`,
  `MoveToParking`, `RestoreFromParking`, `RunCommand`, `WriteLock`), each carrying the
  expected pre-image hash of the file it touches.

## 3. Architecture

```
src/harnessctl/
  model.py          dataclasses of §2
  config.py         corporate.toml + config.toml loading, paths (XDG)
  sources/
    cache.py        git clone/fetch into ~/.cache/harnessctl/sources/<name>/
    formats.py      format detection + the three parsers → CatalogItem
  adapters/
    base.py         Adapter Protocol: detect(), scan(scope), plan_install/remove/toggle/update
    claude_code.py
    opencode.py
  provenance.py     lockfile read/write + provenance resolution (§6)
  planner.py        Plan/Step types, apply with backup, hash check and rollback
  validate.py       catalog linting (shared by the `validate` command and source loading)
  cli.py            entry point: TUI by default, `validate <path>` headless
  tui/
    app.py          App, harness switcher, header/footer, rescan timer
    installed.py    Installed tab
    catalog.py      Catalog tab
    sources.py      Sources tab
    plan_modal.py   plan confirmation modal
    widgets.py      item list, detail pane
```

The core (everything outside `tui/`) has no Textual dependency and is tested headless.
Adapters only read/describe; all writes go through `planner.apply`.

**Adapter interface** (sketch):

```python
class Adapter(Protocol):
    id: str                      # "claude-code" | "opencode"
    def detect(self) -> bool: ...
    def scope_dir(self, scope: Scope, project: Path | None) -> Path: ...
    def scan(self, scope: Scope, project: Path | None) -> list[InstalledItem]: ...
    def plan_install(self, item: CatalogItem, variant: Variant, scope: Scope) -> Plan: ...
    def plan_remove(self, item: InstalledItem) -> Plan: ...
    def plan_toggle(self, item: InstalledItem, enabled: bool) -> Plan: ...
```

`plan_update` is `plan_remove` of the installed version followed by `plan_install` of the new
one, merged into one Plan.

## 4. Files harnessctl reads and writes

| Path | Owner | Purpose |
|---|---|---|
| `~/.config/harnessctl/corporate.toml` | company (IT/dotfiles); **never written by harnessctl** | Corporate sources |
| `~/.config/harnessctl/config.toml` | harnessctl | Public sources, preferences |
| `~/.cache/harnessctl/sources/<name>/` | harnessctl | Shallow clones |
| `~/.config/harnessctl/lock.json` | harnessctl | User-scope installs |
| `<project>/.harnessctl/lock.json` | harnessctl; committed | Project-scope installs |
| `~/.local/state/harnessctl/backups/<timestamp>/` | harnessctl | Pre-apply backups (last 20 kept) |
| `~/.local/state/harnessctl/disabled/<harness>/<scope-key>/<name>/` | harnessctl | Parked (disabled) skills and hooks |

XDG variables (`XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, `XDG_STATE_HOME`) are honoured.

Source declaration (same shape in both files; `trust` is forced to `corporate` for entries in
`corporate.toml` and to `public` for entries in `config.toml`):

```toml
[[source]]
name = "acme"
url  = "git@gitlab.acme.io:platform/agent-catalog.git"
ref  = "main"          # optional
subdir = ""            # optional
```

Project root = nearest ancestor containing `.git`, else no project (user scope only).
`--project <dir>` overrides.

## 5. Catalog format (`format = catalog`)

```
catalog.toml                 name = "acme"; items = ["items/*"]   (globs allowed)
items/<id>/item.toml
items/<id>/...               payload files referenced by the variants
```

`item.toml`:

```toml
id = "block-secrets-read"
kind = "hook"                 # skill | hook | plugin
version = "2.0.1"             # semver; drives "update available"
description = "Blocks reading .env, *.pem and secrets/."
tags = ["security"]

[variants.claude-code]
type = "files"
files = { "claude/secrets.sh" = "hooks/block-secrets-read/secrets.sh" }   # source → path under scope_dir
[variants.claude-code.settings]                                            # merged into settings.json
hooks.PreToolUse = [{ matcher = "Read|Grep", hooks = [{ type = "command", command = "{scope_dir}/hooks/block-secrets-read/secrets.sh" }] }]

[variants.opencode]
type = "files"
files = { "opencode/block-secrets.ts" = "plugins/block-secrets-read.ts" }
```

Skill items use one payload for every harness:

```toml
id = "api-conventions"
kind = "skill"
version = "1.4.0"
[skill]
path = "skill"                # folder containing SKILL.md
harnesses = ["claude-code", "opencode"]
```

The loader expands `[skill]` into one `skill` variant per listed harness, all pointing at the same
folder; a skill item must not also declare `[variants.*]`.

Plugin items:

```toml
[variants.claude-code]
type = "claude-plugin"
marketplace = "https://github.com/acme/claude-plugins"   # added via `claude plugin marketplace add` if missing
plugin = "jira-context"
[variants.opencode]
type = "npm-plugin"
package = "@acme/opencode-jira@1.2.0"
```

Rules (enforced by `validate` and at load): `id` matches `[a-z0-9][a-z0-9-]*`; every `files`
source exists in the item folder; every destination is relative, has no `..`, and resolves inside
`scope_dir`; `{scope_dir}` is the only placeholder; settings fragments may only contain
`hooks`; `version` is valid semver.

`scope_dir` per harness: Claude Code `~/.claude` / `<project>/.claude`; opencode
`~/.config/opencode` / `<project>/.opencode`. Skills install to `<scope_dir>/skills/<id>/`.

## 6. Scanning and provenance

**Claude Code adapter scans:**
- Skills: `~/.claude/skills/*/SKILL.md`, `<project>/.claude/skills/*/SKILL.md`.
- Hooks: `hooks` in `~/.claude/settings.json`, `<project>/.claude/settings.json`, and
  `<project>/.claude/settings.local.json` (scope `local`, read-only). One InstalledItem per
  matcher group entry; name = the lockfile's item id, else `<event>:<command basename>`.
- Plugins: `~/.claude/plugins/installed_plugins.json`, `enabledPlugins` in the settings files,
  `~/.claude/plugins/known_marketplaces.json` for each plugin's marketplace repo. A plugin's own
  skills and hooks are listed as children.

**opencode adapter scans:**
- Skills: `~/.config/opencode/skills/`, `<project>/.opencode/skills/`. Skills it also loads from
  `.claude/skills` / `~/.claude/skills` are not duplicated; the Claude item's detail shows
  "also in opencode".
- Plugins/hooks: `plugin` array of `~/.config/opencode/opencode.json` and `<project>/opencode.json`;
  files in `~/.config/opencode/plugins/` and `<project>/.opencode/plugins/`. A plugin file installed
  from a catalog `hook` item is shown as a hook.

**Provenance resolution**, first match wins:
1. A lockfile entry matches the item's location → trust of that entry's source; `modified` if any
   recorded file hash differs; `update` if the source cache has a higher `version`.
2. Claude plugin whose marketplace repo URL matches a configured source → that source's trust.
3. Claude plugin from any other git-hosted marketplace → `public(<repo>)`.
4. Otherwise → `unknown`.

URLs are compared after normalisation (scheme, `git@host:` vs `https://host/`, trailing `.git`).

**Rescan**: every 2 s the app stats the watched files and directories; a changed mtime triggers a
rescan in a worker. `r` forces one.

## 7. Changes: plan and apply

Every action (install, remove, enable, disable, update) builds a Plan, shows it in the plan modal,
and applies only on confirmation.

- **files / skill variants**: write files, merge the settings fragment (append to the event's
  array; never replace existing entries), record lockfile entry with file hashes.
- **claude-plugin**: `claude plugin marketplace add <url>` if the marketplace is unknown, then
  `claude plugin install <plugin>@<marketplace> --scope <user|project>`. Remove/toggle use the
  matching `claude plugin uninstall|enable|disable` commands. Exact CLI syntax is verified against
  the installed Claude Code version during implementation; if the CLI is missing, plugin variants
  show as unavailable with the reason.
- **npm-plugin**: add/remove the spec in the `plugin` array of the scope's `opencode.json`.
- **Enable/disable**: native where it exists (`enabledPlugins`, `claude plugin enable|disable`;
  opencode plugin array entries). Standalone skills and hooks are **parked**: the skill folder or
  hook entry (+ its script) moves to the parking area and is restored on re-enable. Parked items
  remain listed as `○`.
- **Apply**: before each step, the target's current hash must equal the plan's pre-image hash,
  else abort ("`settings.json` changed since the plan was made — re-plan?"). Every touched file is
  backed up first; any failed step rolls back all previous steps. JSON is rewritten preserving key
  order and 2-space indentation. Files the tool could not parse are never written.
- After apply: rescan, and show the harness-specific reload hint (e.g. restart Claude Code, `/hooks`).

## 8. TUI

Layout A (see the mockup canvas "harnessctl TUI layouts"): header, tabs, list + detail, footer.

- **Header**: `harnessctl`, harness switcher (only detected harnesses), project path, catalog sync state.
- **Tabs**: `Installed | Catalog | Sources`, switched with `tab` / `1`-`3`.
- **Installed**: grouped Skills / Hooks / Plugins; rows `●/○ name scope provenance [status] note`.
  Status mark only when not `ok` (`↑` update, `±` modified, `✗` broken). Keys: `space` toggle,
  `u` update, `d` remove, `o` open in `$EDITOR` (via `App.suspend()`, rescan after), `/` filter.
- **Catalog**: grouped by source with trust label; rows `✓(installed) name kind harness-support`.
  Filters: source, kind, `/` text. Detail: description, per-harness variants, where installed,
  payload preview. `i` install → scope picker → plan modal.
- **Sources**: list with trust, format, last sync, errors. `a` add public source (URL, optional
  ref/subdir), `r` refresh, `d` remove (public only). Corporate sources are read-only here.
- **Detail pane**: rendered SKILL.md (Markdown), hook command/script, plugin contents.
- **Plan modal**: harness, scope, source@commit, step list (`+` write, `~` merge, `−` remove,
  `$` command), `v` view diff, `enter` apply, `esc` cancel; defaults to cancel.
- **Responsive**: ≥100 cols list + detail; <100 cols list only, `enter` opens detail full-screen,
  `esc` back; below 50×15 show "terminal too small — need 50×15".
- Colour is never the only signal: provenance is a word, status is a glyph. `NO_COLOR` honoured.
- Empty states say what to do next ("No sources. Press `a` to add one, or ask IT for corporate.toml").

## 9. Error handling

- **Source fetch fails**: use cache, mark `stale · last synced <age> · <git error>`; no cache →
  `unavailable`, its items hidden from Catalog. Git uses the user's own credentials; no auth is
  handled by harnessctl.
- **Malformed catalog item**: skipped with a warning on the source row; other items load.
- **Unparseable harness config**: its items show `✗ broken` with the parse error; plans touching
  that file are refused.
- **Apply failure**: roll back; modal shows the failed step and, for commands, stderr verbatim.
- **Concurrent edit**: hash check aborts and offers re-plan.
- All git and CLI calls run in workers with a timeout (git 60 s, `claude plugin` 120 s); the UI never blocks.
- Logs go to `~/.local/state/harnessctl/harnessctl.log`, never to the screen.

## 10. Testing

1. **Unit**: format detection and parsers, `validate` rules, provenance resolution, URL
   normalisation, planner step construction, apply/rollback/hash-check — against fixture trees
   used as fake `$HOME` and project.
2. **Adapter**: realistic Claude Code and opencode fixture trees (plugins with nested skills,
   local-scope hooks, broken JSON, parked items).
3. **TUI**: Textual `Pilot` flows at 120×30, 80×24 and 64×30; `pytest-textual-snapshot` for the
   three tabs and the plan modal.
4. **End-to-end smoke**: a local git repo built from `examples/acme-catalog/` as corporate source,
   temp `$HOME` and project; install, toggle, update, remove; assert files, lockfile and rescan.
   The `claude` CLI is replaced by a stub script on `PATH`.

`examples/acme-catalog/` doubles as documentation of the catalog format.

## 11. Out of scope for v1

Policy/enforcement, Codex/Gemini/Cursor adapters, managing MCP servers directly (only as part of a
plugin), editing items inside the TUI, Claude `local` scope as an install target, hook translation
between harnesses, Windows support (best effort only).
