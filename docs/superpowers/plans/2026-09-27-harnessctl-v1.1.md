# harnessctl v1.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gaps v1 left against the spec (plan origin, catalog filters and availability, re-plan after a conflict, local-scope plugins, a Sources snapshot), fix the deferred usability issues found in review, add CI, and ship it as version 0.2.0.

**Architecture:** No new modules. Changes stay in the existing layers: `planner` (plan origin, cumulative diff, backup failure), `engine` (catalog availability, `find_installed`, `reload_sources`, duplicate URLs), `adapters/` (unavailable reasons, local plugins), and `tui/` (a `ConfirmScreen` modal, catalog filters (`s` source, `t` type), re-plan flow, source-removal confirmation, config reload, cursor and editor fixes). A GitHub Actions workflow runs the same checks as local development.

**Tech Stack:** Python 3.14, Textual 8.2+, uv, pytest, pytest-asyncio, pytest-textual-snapshot, ruff, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-24-harnessctl-design.md` (v1 spec; this plan closes its remaining §7, §8, §9 and §10.3 items). v1 plan for context: `docs/superpowers/plans/2026-09-24-harnessctl-v1.md`.

## Global Constraints

- `requires-python = ">=3.14"`; `.python-version` is `3.14`; one uv-managed `.venv` in the repo; run everything with `uv run`.
- Runtime deps: `textual>=8.2,<9`, `pyyaml>=6.0`, `tomli-w>=1.2`, `packaging>=24.0`. No others.
- Work happens on the `develop` branch; never commit to `main`.
- harnessctl **never writes** `~/.config/harnessctl/corporate.toml`.
- File locations are exactly those of spec §4 (`config.toml`, `lock.json`, `sources/`, `backups/`, `disabled/`, `harnessctl.log`), honouring `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, `XDG_STATE_HOME`. Project lock: `<project>/.harnessctl/lock.json`.
- Every change to the user's files goes through `planner.apply` (hash check, backup, rollback). Adapters never write.
- JSON is rewritten with 2-space indent, original key order, trailing newline. A file that cannot be parsed is never written. **A file containing comments (JSONC) is never rewritten**; the plan is refused with the manual edit to make.
- Harness ids are exactly `claude-code` and `opencode`. Scopes are `user`, `project`, `local` (`local` is read-only).
- Provenance labels are exactly `corp`, `public`, `unknown`. Status marks: `↑` update, `±` modified, `✗` broken; nothing for ok.
- The UI thread never runs git or a subprocess. Git timeout 60 s, `claude plugin` timeout 120 s.
- TUI: list + detail at ≥100 columns; list only below 100 (Enter opens the detail full-screen, Esc returns); below 50×15 show `terminal too small — need 50×15`.
- Colour is never the only signal; empty states say what to do next (spec §8).
- Keys follow the `tui-design` skill (gfargo `terminal` plugin): `k`/`j` stay free as navigation aliases; a destructive confirmation never accepts a bare `enter` (use `y`); footers stay at about six keys (extra keys `show=False`, still listed by `?`); long background work (a git fetch) is announced; each fact is signalled once (no toast repeating an open modal).
- Logs go to `~/.local/state/harnessctl/harnessctl.log`, never to the screen.
- Line length 110 (`ruff`); `uv run ruff check .` and `uv run ruff format --check .` must be clean before every commit.
- Snapshot tests must stay deterministic: never pin absolute temp paths or clock times in an SVG.

## Review Focus

1. **Re-plan after the item disappeared** (the agent deleted the skill while the plan modal was open): accepting "re-plan" must say the item is gone and change nothing, never act on a different item. — tested in Task 7.
2. **A broken `config.toml` saved while harnessctl runs**: the reload must show the parse error as a warning and keep the app and corporate sources working. — tested in Task 9.
3. **Catalog filters that leave nothing to show**: the detail pane must say how to change the filters, not claim there are no sources. — tested in Task 4.
4. **Removing a source whose items are installed**: the installed files stay and show as `unknown`, as the confirmation text promises. — tested in Task 8.
5. **The `claude` CLI appears or disappears while harnessctl runs**: plugin availability in the Catalog must follow on the next scan, without a restart. — tested in Task 3.

## Release housekeeping (controller, with the user — not a task)

- Before Task 1: ask the user whether to tag the v1 release: `git tag -a v0.1.0 25a98f0 -m "harnessctl 0.1.0"` then `git push origin v0.1.0`. Pushing a tag is outward-facing; do it only on their yes.
- The user runs the README install check themselves: `uv tool install git+https://github.com/cfrancois7/harnessctl@main && harnessctl --version` → `harnessctl 0.1.0`.
- After Task 11: the controller pushes `develop`, watches the first CI run (`gh run list --branch develop --limit 1`, then `gh run watch <id>`), and asks the user before opening the `develop` → `main` PR.

## Not in this plan (and why)

- **Plan building off the UI thread**: flagged as performance-only and never measured; moving it changes every TUI test's timing. Revisit with a measurement on a large install.
- **A dedicated plugin-update engine test**: an update is `plan_remove` + `plan_install`, and both are already exercised for plugins (`tests/test_engine.py::test_project_scope_plugin_commands_run_in_the_project`); a full update test would need a `claude` stub that also writes `installed_plugins.json`.
- **Rollback tests**: already present (`tests/test_planner.py::test_failure_rolls_back_every_step`, `test_rollback_*`).
- **Hook-group reordering on restore** and **old-format parked hooks**: cosmetic, no behaviour change.
- **Sources filter lower-casing**: source names are always lower case (`config.NAME_RE`), so the comparison is already correct.

---

## File map

```
.github/workflows/ci.yml                 (new)  Task 1
pyproject.toml, uv.lock                          Task 11 (version 0.2.0)
README.md                                        Task 11
src/harnessctl/__init__.py                       Task 11 (__version__)
src/harnessctl/planner.py                        Tasks 2, 6
src/harnessctl/engine.py                         Tasks 2, 3, 7, 8, 9
src/harnessctl/adapters/base.py                  Task 3 (Adapter protocol)
src/harnessctl/adapters/claude_code.py           Tasks 3, 5
src/harnessctl/adapters/opencode.py              Task 3
src/harnessctl/tui/text.py                       Task 3 (reason in detail, `✗` in row)
src/harnessctl/tui/modals.py                     Tasks 2, 7
src/harnessctl/tui/views.py                      Tasks 4, 7, 8, 10
src/harnessctl/tui/app.py                        Tasks 3, 6, 7, 8, 9, 10
tests/test_engine.py                             Tasks 2, 3, 7, 8, 9
tests/test_planner.py                            Task 6
tests/test_claude_scan.py                        Task 5
tests/test_tui_text.py                           Task 3
tests/test_tui.py                                Tasks 4, 9, 10
tests/test_tui_actions.py                        Tasks 2, 3, 6, 7, 10
tests/test_tui_sources.py                        Task 8
tests/test_snapshots.py, tests/__snapshots__/    Tasks 2, 3, 11
tests/test_cli.py                                Task 11
```

Shared test fixtures you will use (already in the repo): `env` (fake `$HOME`, project at `~/projects/api`, `bin/` first on `PATH`), `tui` (acme catalog as corporate source, `api-conventions` installed at project scope, `my-notes` hand-made at user scope; `tui.app()` builds a `HarnessApp` with `fetch=False`), and helpers in `tests/helpers.py`: `write`, `skill`, `make_repo`, `commit_all`, `settle`, `stub_command`, `EXAMPLES`. In the TUI fixture the Installed list is `api-conventions`, `my-notes` (in that order) and the Catalog list is `api-conventions`, `block-secrets-read`, `jira-context`. The `claude` CLI is not on `PATH` in tests unless a test stubs it.

---

### Task 1: CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: a `ci` workflow running lint, format check, tests and catalog validation on pushes to `develop`/`main` and on pull requests.

- [ ] **Step 1: Write the workflow**

`.github/workflows/ci.yml`:

```yaml
name: ci

on:
  push:
    branches: [develop, main]
  pull_request:

jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - name: Install Python and dependencies
        run: uv sync --locked
      - name: Lint
        run: uv run ruff check .
      - name: Format
        run: uv run ruff format --check .
      - name: Tests
        run: uv run pytest -q
      - name: Validate the example catalog
        run: uv run harnessctl validate examples/acme-catalog
```

`setup-uv` reads `.python-version` (3.14); `uv sync` downloads that Python if the runner lacks it. The tests set their own git identity (`tests/helpers.py` `GIT_ENV`), so no git config step is needed.

- [ ] **Step 2: Run the workflow's commands locally, in order**

Run: `uv sync --locked && uv run ruff check . && uv run ruff format --check . && uv run pytest -q && uv run harnessctl validate examples/acme-catalog`
Expected: `uv sync --locked` succeeds without changing `uv.lock` (if it fails, the lock is stale: stop and report it); lint and format clean; all tests pass; last line `catalog ok: 3 items`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: lint, format, tests and catalog validation on push and PR"
```

The first real run happens when the controller pushes `develop` after Task 11.

---

### Task 2: The plan modal names the source and commit

Spec §8: "Plan modal: harness, scope, source@commit, step list". Plans that come from a catalog item (install, update) or act on something harnessctl installed (lock entry present: remove, toggle) carry `origin = "<source>@<first 7 chars of commit>"`, or just `<source>` when the commit is unknown. Plans on items of unknown origin have `origin = ""`.

**Files:**
- Modify: `src/harnessctl/planner.py` (`Plan` dataclass and `Plan.build`)
- Modify: `src/harnessctl/engine.py` (`plan_install`, `plan_remove`, `plan_toggle`, `plan_update`)
- Modify: `src/harnessctl/tui/modals.py` (`PlanModal.compose`)
- Test: `tests/test_engine.py`, `tests/test_tui_actions.py`, snapshot `tests/__snapshots__/test_snapshots/test_plan_modal.svg`

**Interfaces:**
- Consumes: `LockEntry.source`, `LockEntry.commit`, `Engine._commit_of(source)`.
- Produces: `Plan.origin: str` (default `""`); `Plan.build(..., warnings=None, origin: str = "")`; the modal's subtitle is a `Static` with `id="plan-where"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine.py`:

```python
def test_plans_name_their_source_and_commit(engine, env):
    commit = engine.sources[0].commit
    item = _item(engine, "api-conventions")
    plan = engine.plan_install(item, "claude-code", Scope.USER)
    assert plan.origin == f"acme@{commit[:7]}"
    assert engine.apply(plan).ok
    inst = _installed(engine, "api-conventions")
    assert engine.plan_toggle(inst).origin == f"acme@{commit[:7]}"
    assert engine.plan_remove(inst).origin == f"acme@{commit[:7]}"
    skill(env.home / ".claude" / "skills" / "mine")
    assert engine.plan_toggle(_installed(engine, "mine")).origin == ""
```

Append to `tests/test_tui_actions.py`:

```python
async def test_plan_modal_names_source_and_commit(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("space")
        assert isinstance(app.screen, PlanModal)
        where = str(app.screen.query_one("#plan-where", Static).render())
        assert where.startswith("Claude Code · project scope · acme@")
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_engine.py::test_plans_name_their_source_and_commit tests/test_tui_actions.py::test_plan_modal_names_source_and_commit -v`
Expected: FAIL — `AttributeError: 'Plan' object has no attribute 'origin'` and `NoMatches` for `#plan-where`.

- [ ] **Step 3: Add `origin` to `Plan`**

In `src/harnessctl/planner.py`, add the field right after `warnings` in the `Plan` dataclass:

```python
    warnings: list[str] = field(default_factory=list)
    origin: str = ""  # "<source>@<commit7>" for catalog-backed plans (spec §8), else ""
```

and extend `Plan.build`:

```python
    @classmethod
    def build(
        cls,
        title: str,
        harness: str,
        scope: Scope,
        steps: list[Step],
        reload_hint: str = "",
        warnings: list[str] | None = None,
        origin: str = "",
    ) -> Plan:
        plan = cls(title, harness, scope, list(steps), reload_hint, list(warnings or []), origin)
```

(the rest of `build` is unchanged).

- [ ] **Step 4: Fill it in the engine**

In `src/harnessctl/engine.py`, add under `_commit_of`:

```python
    @staticmethod
    def _origin(source: str, commit: str | None) -> str:
        return f"{source}@{commit[:7]}" if commit else source

    def _origin_of(self, inst: InstalledItem) -> str:
        entry: LockEntry | None = inst.meta.get("lock")
        return self._origin(entry.source, entry.commit) if entry is not None else ""
```

Then pass `origin=` in the four plan builders:

```python
        # plan_install (last line)
        return Plan.build(
            f"Install {item.id} → {scope}",
            harness,
            scope,
            steps,
            adapter.reload_hint,
            origin=self._origin(item.source, self._commit_of(item.source)),
        )
```

```python
        # plan_remove (the existing return, plus origin)
        return Plan.build(
            f"Remove {inst.name} ({inst.scope})",
            inst.harness,
            inst.scope,
            steps,
            adapter.reload_hint,
            warnings=warnings,
            origin=self._origin_of(inst),
        )
```

```python
        # plan_toggle
        return Plan.build(
            f"{verb} {inst.name} ({inst.scope})",
            inst.harness,
            inst.scope,
            steps,
            adapter.reload_hint,
            origin=self._origin_of(inst),
        )
```

```python
        # plan_update (the existing return, plus origin)
        return Plan.build(
            f"Update {inst.name} {entry.version} → {item.version}",
            inst.harness,
            inst.scope,
            [*remove.steps, *install.steps],
            install.reload_hint,
            warnings=[*remove.warnings, *install.warnings],
            origin=install.origin,
        )
```

- [ ] **Step 5: Show it in the modal**

In `src/harnessctl/tui/modals.py`, `PlanModal.compose`, replace the subtitle line

```python
            yield Static(f"{self.harness_label} · {self.plan.scope} scope", classes="dim")
```

with

```python
            where = f"{self.harness_label} · {self.plan.scope} scope"
            if self.plan.origin:
                where += f" · {self.plan.origin}"
            yield Static(where, classes="dim", id="plan-where")
```

- [ ] **Step 6: Run the tests, then refresh the plan-modal snapshot**

Run: `uv run pytest tests/test_engine.py::test_plans_name_their_source_and_commit tests/test_tui_actions.py::test_plan_modal_names_source_and_commit -v`
Expected: PASS.

The plan-modal snapshot now shows the origin, so update it and check it:
Run: `uv run pytest tests/test_snapshots.py::test_plan_modal --snapshot-update && uv run pytest tests/test_snapshots.py -q`
Expected: 4 passed. Open `tests/__snapshots__/test_snapshots/test_plan_modal.svg` text (e.g. `grep -o 'acme@[0-9a-f]*' tests/__snapshots__/test_snapshots/test_plan_modal.svg`) and confirm the subtitle reads `Claude Code · project scope · acme@<7 hex chars>`. The commit is stable because the test repo uses fixed git dates (`GIT_ENV`).

- [ ] **Step 7: Full suite, lint, commit**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass, clean.

```bash
git add src/harnessctl/planner.py src/harnessctl/engine.py src/harnessctl/tui/modals.py \
  tests/test_engine.py tests/test_tui_actions.py tests/__snapshots__
git commit -m "feat: the plan modal names the source and commit a change comes from"
```

---

### Task 3: The Catalog says when and why an item cannot be installed

Spec §7: "if the CLI is missing, plugin variants show as unavailable with the reason." Today only "no variant for this harness" makes an entry unavailable, and a missing `claude` CLI is discovered only when planning fails.

**Files:**
- Modify: `src/harnessctl/adapters/base.py` (`Adapter` protocol)
- Modify: `src/harnessctl/adapters/claude_code.py` (`NO_CLI`, `unavailable_reason`, `_install_plugin`)
- Modify: `src/harnessctl/adapters/opencode.py` (`unavailable_reason`)
- Modify: `src/harnessctl/engine.py` (`CatalogEntry.reason`, `catalog`)
- Modify: `src/harnessctl/tui/text.py` (`catalog_detail`)
- Modify: `src/harnessctl/tui/app.py` (`install`)
- Test: `tests/test_engine.py`, `tests/test_tui_text.py`, `tests/test_tui_actions.py`, snapshot `test_catalog_split.svg`

**Interfaces:**
- Consumes: `ClaudeCodeAdapter._which` (injectable `which`, defaults to `shutil.which`).
- Produces: `Adapter.unavailable_reason(variant: Variant) -> str | None`; `claude_code.NO_CLI = "the claude CLI is not on PATH, so plugins cannot be installed"`; `CatalogEntry(item, trust, available, installed, reason: str | None = None)` where `available is (reason is None)`; the unavailable-install message is `f"{item.id}: {reason}."`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine.py`:

```python
def test_plugin_unavailable_without_the_claude_cli_until_it_appears(engine, env):
    entries = {e.item.id: e for e in engine.catalog("claude-code")}
    assert entries["jira-context"].available is False
    assert entries["jira-context"].reason == "the claude CLI is not on PATH, so plugins cannot be installed"
    assert entries["api-conventions"].available and entries["api-conventions"].reason is None

    stub_command(env.bin, "claude", env.home / "claude-calls.log")  # installed while running
    entries = {e.item.id: e for e in engine.catalog("claude-code")}
    assert entries["jira-context"].available is True and entries["jira-context"].reason is None
```

Append to `tests/test_tui_text.py`:

```python
def test_catalog_detail_says_why_an_item_is_unavailable():
    entry = _entry()
    entry.available = False
    entry.reason = "the claude CLI is not on PATH, so plugins cannot be installed"
    md = catalog_detail(entry)
    assert "*Not available: the claude CLI is not on PATH, so plugins cannot be installed.*" in md


def test_catalog_row_marks_an_unavailable_item_with_a_symbol_not_only_dimming():
    # Colour (dim) is never the only signal, and below 100 columns the detail pane is hidden.
    entry = _entry()
    entry.available = False
    entry.reason = "the claude CLI is not on PATH, so plugins cannot be installed"
    assert catalog_row(entry).plain.startswith(" ✗ jira-context")
    installed = _entry([Scope.USER])
    installed.available = False
    installed.reason = entry.reason
    assert catalog_row(installed).plain.startswith(" ✓ jira-context")  # installed wins
```

Append to `tests/test_tui_actions.py`:

```python
async def test_install_of_an_unavailable_plugin_says_why(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("2", "down", "down", "i")
        assert not isinstance(app.screen, ScopePicker)
        assert app.last_outcome == (
            "jira-context: the claude CLI is not on PATH, so plugins cannot be installed."
        )
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_engine.py::test_plugin_unavailable_without_the_claude_cli_until_it_appears tests/test_tui_text.py -k "unavailable" tests/test_tui_actions.py::test_install_of_an_unavailable_plugin_says_why -v`
Expected: FAIL — `jira-context` is available, `CatalogEntry` has no `reason`, the row has no `✗`, and the TUI opens the scope picker.

- [ ] **Step 3: Adapters report why a variant cannot be installed**

In `src/harnessctl/adapters/base.py`, import `Variant` (`from harnessctl.model import CatalogItem, InstalledItem, Kind, Scope, Variant`) and add to the `Adapter` protocol, after `watched_paths`:

```python
    def unavailable_reason(self, variant: Variant) -> str | None: ...
```

In `src/harnessctl/adapters/claude_code.py`, add `Variant` to the `harnessctl.model` import, add a module constant under the imports:

```python
NO_CLI = "the claude CLI is not on PATH, so plugins cannot be installed"
```

add this method to `ClaudeCodeAdapter` (after `watched_paths`):

```python
    def unavailable_reason(self, variant: Variant) -> str | None:
        """Why this machine cannot install `variant` right now (checked on every scan)."""
        if isinstance(variant, ClaudePluginVariant) and self._which("claude") is None:
            return NO_CLI
        return None
```

and make `_install_plugin` use the constant:

```python
        if self._which("claude") is None:
            raise PlanError(NO_CLI)
```

In `src/harnessctl/adapters/opencode.py`, add `Variant` to the `harnessctl.model` import and add to `OpencodeAdapter` (after `watched_paths`):

```python
    def unavailable_reason(self, variant: Variant) -> str | None:
        return None  # opencode variants need no external tool to install
```

- [ ] **Step 4: The engine records the reason**

In `src/harnessctl/engine.py`, extend `CatalogEntry`:

```python
@dataclass
class CatalogEntry:
    item: CatalogItem
    trust: Trust
    available: bool  # the item can be installed for the harness being viewed
    installed: list[Scope]
    reason: str | None = None  # why it cannot be installed, when it cannot
```

and in `catalog`, compute the reason per entry (replace the lines from `variant = item.variants.get(harness)` to the `entries.append(...)`):

```python
                variant = item.variants.get(harness)
                if isinstance(variant, ClaudePluginVariant) and not scopes:
                    found = native.get(f"claude-plugin:{variant.plugin_id}")
                    scopes = [found] if found else []
                reason = (
                    f"no {adapter.label} variant" if variant is None else adapter.unavailable_reason(variant)
                )
                entries.append(CatalogEntry(item, state.spec.trust, reason is None, scopes, reason))
```

with `adapter = self.adapter(harness)` added as the first line of `catalog`.

- [ ] **Step 5: Show the reason**

In `src/harnessctl/tui/text.py`, `catalog_detail`, replace

```python
    if not entry.available:
        parts.append("*No variant for this harness.*")
```

with

```python
    if entry.reason:
        parts.append(f"*Not available: {entry.reason}.*")
```

In the same file, `catalog_row`, replace the mark cell (`("✓" if entry.installed else " ", "green"),`) so an unavailable item carries a symbol as well as the dimming (spec §8: colour is never the only signal; below 100 columns the reason in the detail pane is not visible):

```python
    if entry.installed:
        mark = ("✓", "green")
    elif not entry.available:
        mark = ("✗", "dim")
    else:
        mark = (" ", "")
```

declared before the `return`, and use `mark,` in place of the old tuple inside `Text.assemble`.

In `src/harnessctl/tui/app.py`, `install`, change only the message of the unavailable branch (keep the `adapter = ...` line above it; the scope picker below uses it):

```python
        if not entry.available:
            self._report(f"{entry.item.id}: {entry.reason}.", "Cannot do that", error=True)
            return
```

- [ ] **Step 6: Run the tests, refresh the catalog snapshot**

Run: `uv run pytest tests/test_engine.py tests/test_tui_text.py tests/test_tui_actions.py -q`
Expected: PASS.

`jira-context` is now dimmed and marked `✗` in the 64-column catalog snapshot:
Run: `uv run pytest tests/test_snapshots.py::test_catalog_split --snapshot-update && uv run pytest tests/test_snapshots.py -q`
Expected: 4 passed. The only visual change is the `jira-context` row (style and `✗`).

- [ ] **Step 7: Full suite, lint, commit**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

```bash
git add src/harnessctl tests
git commit -m "feat: the catalog marks plugins unavailable without the claude CLI and says why"
```

---

### Task 4: Catalog filters by source and type

Spec §8: "Catalog … Filters: source, kind, `/` text." `s` cycles the source filter (all → each source in list order → all), `t` cycles the type (kind) filter (all → skill → hook → plugin → all). `t`, not `k`: `k` is the conventional vim "up" key in lazygit, k9s and yazi, and must stay free for a navigation alias. A one-line status above the list shows the active filters and how many items match (`3/4`); it is hidden when neither filter is active. `esc` clears these filters together with the `/` text.

`s` and `t` are bound with `show=False`: the Catalog footer already carries six keys (quit, harness, rescan, help, filter, install), and a footer past 3–5 keys gets cut at 64–80 columns. They stay discoverable through `?` (Textual's key panel lists every non-system binding, shown or not), the filter status line and the README.

**Files:**
- Modify: `src/harnessctl/tui/views.py` (`CatalogView`)
- Test: `tests/test_tui.py`

**Interfaces:**
- Consumes: `ListDetailView` (`data`, `_refresh_rows`, `action_clear_filter`, `compose`), `CatalogEntry`.
- Produces: `CatalogView.source_filter: str | None`, `CatalogView.kind_filter: Kind | None`; actions `cycle_source` (`s`) and `cycle_kind` (`t`), both `show=False`; a `Static#filters` inside `CatalogView` reading e.g. `source: acme · 3/4   (s source · t type · esc clear)`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_tui.py`, add `make_repo` to the `tests.helpers` import and append:

```python
def _public_source(tui, tmp_path):
    public = tmp_path / "pub"
    skill(public / "skills" / "tdd")
    make_repo(None, public)
    write(tui.env.paths.config_toml, f'[[source]]\nname = "pub"\nurl = "{public.as_uri()}"\n')
    tui.env.engine().load_sources(fetch=True)  # clone it into the shared cache
    return public


async def test_catalog_filters_by_source_and_type(tui, tmp_path):
    _public_source(tui, tmp_path)
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("2")
        view = app.query_one(CatalogView)
        everything = ["api-conventions", "block-secrets-read", "jira-context", "tdd"]
        assert _names(app, CatalogView) == everything
        await pilot.press("s")
        assert _names(app, CatalogView) == ["api-conventions", "block-secrets-read", "jira-context"]
        status = str(view.query_one("#filters", Static).render())
        assert "source: acme" in status and "3/4" in status
        await pilot.press("s")
        assert _names(app, CatalogView) == ["tdd"]
        await pilot.press("s")
        assert _names(app, CatalogView) == everything
        assert view.query_one("#filters").display is False
        await pilot.press("t")
        assert _names(app, CatalogView) == ["api-conventions", "tdd"]
        assert "type: skill" in str(view.query_one("#filters", Static).render())
        await pilot.press("t")
        assert _names(app, CatalogView) == ["block-secrets-read"]
        await pilot.press("t", "t")
        assert _names(app, CatalogView) == everything


async def test_escape_clears_the_source_and_type_filters(tui, tmp_path):
    _public_source(tui, tmp_path)
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("2", "s", "t")
        assert _names(app, CatalogView) == ["api-conventions"]
        await pilot.press("escape")
        view = app.query_one(CatalogView)
        assert view.source_filter is None and view.kind_filter is None
        assert _names(app, CatalogView) == ["api-conventions", "block-secrets-read", "jira-context", "tdd"]
        assert view.query_one("#filters").display is False


async def test_filters_that_match_nothing_say_how_to_change_them(tui, tmp_path):
    _public_source(tui, tmp_path)
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("2", "s", "s", "t", "t")  # source pub, type hook: nothing
        assert _names(app, CatalogView) == []
        detail = app.query_one(CatalogView).query_one(DetailPane).markdown
        assert "No item matches these filters" in detail and "`s`" in detail and "`esc`" in detail
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_tui.py -k "filters" -v`
Expected: FAIL — `s` does nothing, so the first filtered assertion sees all four items.

- [ ] **Step 3: Implement the filters**

In `src/harnessctl/tui/views.py`, add `Static` to the `textual.widgets` import (`from textual.widgets import Input, Markdown, OptionList, Static`), then replace the whole `CatalogView` class with:

```python
class CatalogView(ListDetailView):
    BINDINGS = [
        Binding("i", "install", "install"),
        # Hidden from the footer (already six keys wide); listed by `?` and the filter status line.
        Binding("s", "cycle_source", "filter by source", show=False),
        Binding("t", "cycle_kind", "filter by type", show=False),
    ]
    DEFAULT_CSS = """
    CatalogView > #filters { display: none; margin: 0 1; color: $text-muted; }
    CatalogView > #filters.-shown { display: block; }
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self.source_filter: str | None = None
        self.kind_filter: Kind | None = None
        self._shown = 0

    @property
    def empty_text(self) -> str:
        if self.source_filter or self.kind_filter:
            return (
                "No item matches these filters. Press `s` (source) or `t` (type) to change them, "
                "or `esc` to clear them."
            )
        return "No catalog items. Add a source in the **Sources** tab (press `3`)."

    def compose(self) -> ComposeResult:
        yield Static(id="filters")
        yield from super().compose()

    def groups(self, entries: list[CatalogEntry], text: str) -> Groups:
        by_source: dict[str, list[CatalogEntry]] = {}
        for entry in entries:
            if self.source_filter is not None and entry.item.source != self.source_filter:
                continue
            if self.kind_filter is not None and entry.item.kind is not self.kind_filter:
                continue
            by_source.setdefault(entry.item.source, []).append(entry)
        groups: Groups = []
        for source, group in by_source.items():
            trust = "corp" if group[0].trust is Trust.CORPORATE else "public"
            rows = [
                (catalog_row(e), e)
                for e in group
                if not text
                or text in f"{e.item.id} {e.item.kind} {e.item.source} {e.item.description}".lower()
            ]
            groups.append((f"{source} · {trust}", rows))
        self._shown = sum(len(rows) for _, rows in groups)
        return groups

    def key(self, entry: CatalogEntry) -> Hashable:
        return (entry.item.source, entry.item.id)

    def detail(self, entry: CatalogEntry) -> str:
        return catalog_detail(entry)

    @staticmethod
    def _next(options: list, current: Any) -> Any:
        """None (no filter) → each option in turn → None."""
        chain = [None, *options]
        return chain[(chain.index(current) + 1) % len(chain)] if current in chain else None

    def action_cycle_source(self) -> None:
        sources = list(dict.fromkeys(e.item.source for e in self.data))
        self.source_filter = self._next(sources, self.source_filter)
        self._refresh_rows()

    def action_cycle_kind(self) -> None:
        self.kind_filter = self._next(list(Kind), self.kind_filter)
        self._refresh_rows()

    def action_clear_filter(self) -> None:
        self.source_filter = self.kind_filter = None
        super().action_clear_filter()
        self._refresh_rows()  # the text may already have been empty: no Input.Changed follows

    def _refresh_rows(self) -> None:
        super()._refresh_rows()
        parts = []
        if self.source_filter:
            parts.append(f"source: {self.source_filter}")
        if self.kind_filter:
            parts.append(f"type: {self.kind_filter.value}")
        label = self.query_one("#filters", Static)
        if parts:
            parts.append(f"{self._shown}/{len(self.data)}")
            label.update(" · ".join(parts) + "   (s source · t type · esc clear)")
        label.set_class(bool(parts), "-shown")

    def action_install(self) -> None:
        if self.selected is not None:
            self.app.install(self.selected)
```

`ListDetailView` sets `empty_text` as a class attribute; the property here overrides it for this view only. `_refresh_rows` runs `groups` (which counts the matching rows) before the status line is written, so the count also follows the `/` text.

- [ ] **Step 4: Run the tests; the snapshots must not change**

Run: `uv run pytest tests/test_tui.py -q && uv run pytest tests/test_snapshots.py -q`
Expected: PASS; 4 snapshots passed **without** `--snapshot-update` (the new keys are hidden from the footer and the status line is hidden when no filter is active). If `test_catalog_split` fails, a footer or layout change leaked: fix it, do not update the snapshot.

Check the keys are discoverable: `uv run python -c "from harnessctl.tui.views import CatalogView; print([(b.key, b.description) for b in CatalogView.BINDINGS])"` shows `s` and `t` with their descriptions (these are what `?` lists).

- [ ] **Step 5: Full suite, lint, commit**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

```bash
git add src/harnessctl/tui/views.py tests/test_tui.py
git commit -m "feat: catalog filters by source (s) and type (t), cleared with esc"
```

---

### Task 5: Local-scope Claude plugins are listed, read-only

Claude Code can install a plugin at `local` scope (record `"scope": "local"` with a `projectPath` in `installed_plugins.json`; enabled state in the project's `settings.local.json`). v1 lists local hooks but not local plugins. They must be listed for the current project only, and be read-only like every local item.

**Files:**
- Modify: `src/harnessctl/adapters/claude_code.py` (`scan`, `_scan_plugins`)
- Test: `tests/test_claude_scan.py`

**Interfaces:**
- Consumes: `ClaudeCodeAdapter.settings_path(Scope.LOCAL, project)` (→ `settings.local.json`), `_plugin_items`, `require_writable`.
- Produces: `scan(Scope.LOCAL, project)` returns local hooks and local plugins (plus their children); local plugin items have `readonly == "local scope is read-only"`.

- [ ] **Step 1: Write the failing test**

In `tests/test_claude_scan.py`, add `from harnessctl.planner import PlanError` to the imports (`write` and `skill` are already imported), and append:

```python
def test_local_scope_plugins_are_listed_read_only(claude, env):
    path = env.home / ".claude" / "plugins" / "installed_plugins.json"
    data = json.loads(path.read_text())
    data["plugins"]["scratch@gfargo-skills"] = [
        {"scope": "local", "projectPath": str(env.project), "installPath": str(env.home / "nope")},
        {"scope": "local", "projectPath": "/somewhere/else", "installPath": "/x"},
    ]
    path.write_text(json.dumps(data))
    write(
        env.project / ".claude" / "settings.local.json",
        json.dumps({"enabledPlugins": {"scratch@gfargo-skills": True}}),
    )
    local = _by_name(claude.scan(Scope.LOCAL, env.project))
    assert set(local) == {"scratch"}
    scratch = local["scratch"]
    assert scratch.location == "claude-plugin:scratch@gfargo-skills"
    assert scratch.enabled is True and scratch.scope is Scope.LOCAL
    assert scratch.readonly == "local scope is read-only"
    with pytest.raises(PlanError, match="local scope is read-only"):
        claude.plan_toggle(scratch, env.project)


def test_broken_plugin_files_are_not_reported_a_third_time_for_local_scope(env):
    write(env.home / ".claude" / "plugins" / "installed_plugins.json", "[]")
    adapter = ClaudeCodeAdapter(env.home, env.paths.parking)
    assert [i for i in adapter.scan(Scope.LOCAL, env.project) if i.status is Status.BROKEN] == []
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_claude_scan.py -k "local_scope_plugins or third_time" -v`
Expected: the first FAILS (`set()` — no local plugins); the second passes already (it pins that the fix does not add a duplicate broken item).

- [ ] **Step 3: Scan local plugins**

In `src/harnessctl/adapters/claude_code.py`, `scan`, replace

```python
        if scope is Scope.LOCAL:
            return self._scan_hooks(scope, project)
```

with

```python
        if scope is Scope.LOCAL:
            # A broken plugin file is already reported under user and project scope.
            plugins = [i for i in self._scan_plugins(scope, project) if i.status is not Status.BROKEN]
            for item in plugins:
                item.readonly = item.readonly or "local scope is read-only"
            return self._scan_hooks(scope, project) + plugins
```

and in `_scan_plugins`, make the project filter cover local records too:

```python
                if scope in (Scope.PROJECT, Scope.LOCAL) and Path(str(rec.get("projectPath", ""))) != project:
                    continue
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_claude_scan.py -v`
Expected: PASS, including the existing `test_project_and_local_scopes` (its fixture has no local plugin records).

- [ ] **Step 5: Full suite, lint, commit**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

```bash
git add src/harnessctl/adapters/claude_code.py tests/test_claude_scan.py
git commit -m "feat: list local-scope Claude plugins, read-only"
```

---

### Task 6: Honest diffs and a clean failure when backups cannot be written

Two planner fixes:
1. `plan_diff` compares each step with the file on disk, so an update (remove the old hook, then merge the new one into the same `settings.json`) shows the old hook still present. The diff must show, per file, what is on disk now against what the **whole plan** leaves there.
2. `apply` creates the backup folder and copies files before its rollback guard. An `OSError` there (disk full, permissions) escapes. It must instead return `ApplyResult(ok=False, failed_step=None, error="cannot back up before applying: <error>; nothing was changed")`, remove the partial backup, and change nothing. The TUI must show that message as is (today it would compute `None + 1`).

**Files:**
- Modify: `src/harnessctl/planner.py` (`plan_diff`, `apply`)
- Modify: `src/harnessctl/tui/app.py` (`apply_plan`)
- Test: `tests/test_planner.py`, `tests/test_tui_actions.py`

**Interfaces:**
- Consumes: `WriteFile`, `EditJson`, `DeletePath`, `_copy`, `ApplyResult`.
- Produces: `ApplyResult.failed_step is None` means "failed before any step ran; nothing was changed".

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_planner.py`:

```python
def _append(value):
    def edit(data):
        data = data or {"items": []}
        data["items"] = [*data["items"], value]
        return data

    return edit


def _drop(value):
    def edit(data):
        data = data or {"items": []}
        data["items"] = [x for x in data["items"] if x != value]
        return data

    return edit


def test_plan_diff_shows_what_the_whole_plan_leaves_in_a_file(tmp_path):
    settings = write(tmp_path / "settings.json", '{\n  "items": [\n    "old"\n  ]\n}\n')
    plan = _plan(EditJson(settings, _drop("old"), "−old"), EditJson(settings, _append("new"), "+new"))
    diff = plan_diff(plan)
    assert diff.count("--- ") == 1  # one diff per file, not one per step
    assert '-    "old"' in diff and '+    "new"' in diff
    assert '     "old"' not in diff  # "old" must not survive as a context line


def test_backup_failure_changes_nothing(tmp_path, monkeypatch):
    target = write(tmp_path / "keep.txt", "original")

    def broken_copy(src, dst):
        raise PermissionError(13, "Permission denied", str(dst))

    monkeypatch.setattr(planner, "_copy", broken_copy)
    result = apply(_plan(WriteFile(target, b"changed")), tmp_path / "backups")
    assert not result.ok and result.failed_step is None
    assert result.error.startswith("cannot back up before applying: ")
    assert "Permission denied" in result.error and result.error.endswith("; nothing was changed")
    assert target.read_text() == "original"
    assert list((tmp_path / "backups").iterdir()) == []
```

Append to `tests/test_tui_actions.py`:

```python
async def test_failure_before_any_step_is_reported_as_is(tui, monkeypatch):
    from harnessctl.planner import ApplyResult

    message = "cannot back up before applying: disk full; nothing was changed"
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        monkeypatch.setattr(app.engine, "apply", lambda plan: ApplyResult(False, error=message))
        await pilot.press("space", "enter")
        await settle(pilot)
        assert app.is_running
        assert app.last_outcome == message
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_planner.py -k "whole_plan or backup_failure" tests/test_tui_actions.py::test_failure_before_any_step_is_reported_as_is -v`
Expected: FAIL — two `--- ` headers; `PermissionError` raised out of `apply`; the TUI worker fails with `TypeError` (surfaced by `settle` as `WorkerFailed`).

- [ ] **Step 3: Cumulative diff**

In `src/harnessctl/planner.py`, replace `plan_diff` with:

```python
def plan_diff(plan: Plan) -> str:
    """Unified diff per file, from what is on disk now to what the whole plan leaves there.
    Steps touching the same file (an update's remove, then its install) are applied in order."""
    before: dict[Path, str] = {}
    after: dict[Path, str] = {}

    def current(path: Path) -> str:
        if path not in after:
            before[path] = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
            after[path] = before[path]
        return after[path]

    for step in plan.steps:
        match step:
            case WriteFile(path=p, content=c):
                current(p)
                after[p] = c.decode(errors="replace")
            case EditJson(path=p, edit=edit):
                old = current(p)
                try:
                    after[p] = dumps(edit(copy.deepcopy(loads_jsonc(old) if old.strip() else None)))
                except Exception as exc:  # noqa: BLE001 - a preview must never crash the UI
                    after[p] = f"<cannot preview: {exc}>\n"
            case DeletePath(path=p) if p in after:
                after[p] = ""
    chunks: list[str] = []
    for path, new in after.items():
        chunks.extend(
            difflib.unified_diff(
                before[path].splitlines(keepends=True), new.splitlines(keepends=True), f"a{path}", f"b{path}"
            )
        )
    return "".join(chunks) or "(no file contents change)\n"
```

- [ ] **Step 4: Guard the backup phase**

In `apply`, replace the backup block (from `backup = backup_root / ...` through the `for n, path in enumerate(plan.preimages):` loop) with:

```python
    backup = backup_root / datetime.now().strftime("%Y%m%dT%H%M%S%f")
    saved: dict[Path, Path | None] = {}
    try:
        backup.mkdir(parents=True, mode=0o700)
        for n, path in enumerate(plan.preimages):
            if path.exists() or path.is_symlink():
                _copy(path, backup / str(n))
                saved[path] = backup / str(n)
            else:
                saved[path] = None
    except OSError as exc:
        shutil.rmtree(backup, ignore_errors=True)
        return ApplyResult(False, error=f"cannot back up before applying: {exc}; nothing was changed")
```

- [ ] **Step 5: The TUI shows it as is**

In `src/harnessctl/tui/app.py`, `apply_plan`, replace the `else:` branch body that handles `result`:

```python
        else:
            if result.ok:
                self.call_from_thread(self._report, plan.reload_hint or "Done.", plan.title)
            elif result.failed_step is None:
                self.call_from_thread(self._report, result.error or "Nothing was changed.", plan.title, True)
            else:
                message = (
                    f"Step {result.failed_step + 1} failed: {result.error}\nEvery change was rolled back."
                )
                self.call_from_thread(self._report, message, plan.title, True)
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_planner.py tests/test_tui_actions.py -q`
Expected: PASS, including the existing `test_plan_diff_and_labels` and `test_diff_view`.

- [ ] **Step 7: Full suite, lint, commit**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

```bash
git add src/harnessctl/planner.py src/harnessctl/tui/app.py tests/test_planner.py tests/test_tui_actions.py
git commit -m "fix: diffs show what the whole plan leaves in each file; a failed backup changes nothing"
```

---

### Task 7: Offer to re-plan after a conflict

Spec §9: "Concurrent edit: hash check aborts and offers re-plan." Today the TUI only says "— re-plan?". After a `PlanConflict`, show a `ConfirmScreen` ("re-plan" / cancel). Accepting builds the plan again **from a fresh scan** — the old `InstalledItem` may describe a file that has changed — and opens the plan modal. If the item is gone, say so and change nothing.

**Files:**
- Modify: `src/harnessctl/tui/modals.py` (new `ConfirmScreen`)
- Modify: `src/harnessctl/engine.py` (new `find_installed`)
- Modify: `src/harnessctl/tui/app.py` (`propose`, `_confirmed`, `apply_plan`, new `_conflict`)
- Modify: `src/harnessctl/tui/views.py` (`InstalledView._propose`)
- Test: `tests/test_engine.py`, `tests/test_tui_actions.py`

**Interfaces:**
- Consumes: `PlanConflict`, `Engine.installed`, `InstalledItem.origin_location`.
- Produces:
  - `ConfirmScreen(title: str, message: str, yes: str, yes_key: str = "enter")` — a `ModalScreen[bool]`; `yes_key` (`"enter"` or `"y"`) dismisses `True`; `esc` and `n` dismiss `False`, and so does `enter` when `yes_key` is `"y"` (a reflexive Enter never confirms a destructive action); the message is a `Static` with `id="confirm-message"`. Task 8 reuses it with `yes_key="y"`.
  - While the re-plan question is open, the conflict is shown once, in the modal: `last_outcome` is set but no toast is raised.
  - `Engine.find_installed(item: InstalledItem) -> InstalledItem | None` — the item with the same `(scope, kind, origin_location, enabled)` in a fresh `installed(item.harness)`.
  - `HarnessApp.propose(build, replan=None)` — `replan` defaults to `build`; it is what "re-plan" calls.
  - The vanished-item message: `f"{item.name} is no longer there; nothing to re-plan"` (a `PlanError`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine.py`:

```python
def test_find_installed_returns_the_item_from_a_fresh_scan(engine, env):
    engine.apply(engine.plan_install(_item(engine, "api-conventions"), "claude-code", Scope.USER))
    old = _installed(engine, "api-conventions")
    (env.home / ".claude" / "skills" / "api-conventions" / "SKILL.md").write_text("edited")
    fresh = engine.find_installed(old)
    assert fresh is not old and fresh.status is Status.MODIFIED
    assert engine.apply(engine.plan_toggle(fresh)).ok
    assert engine.find_installed(old) is None  # disabled now: a different item
```

In `tests/test_tui_actions.py`, add `import shutil` at the top, add `ConfirmScreen` to the `harnessctl.tui.modals` import, and append:

```python
def _skill_md(tui):
    return tui.env.project / ".claude" / "skills" / "api-conventions" / "SKILL.md"


async def test_conflict_offers_to_re_plan(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("space")
        _skill_md(tui).write_text("edited by the agent")
        await pilot.press("enter")
        await settle(pilot)
        assert isinstance(app.screen, ConfirmScreen)
        assert "changed since the plan was made" in str(
            app.screen.query_one("#confirm-message", Static).render()
        )
        await pilot.press("enter")
        await settle(pilot)
        assert isinstance(app.screen, PlanModal)
        assert app.screen.plan.title == "Disable api-conventions (project)"
        await pilot.press("enter")
        await settle(pilot)
        assert not _skill_md(tui).exists()
        payload = next((tui.env.paths.parking / "claude-code").glob("*/payload/SKILL.md"))
        assert payload.read_text() == "edited by the agent"


async def test_declining_to_re_plan_changes_nothing(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("space")
        _skill_md(tui).write_text("edited by the agent")
        await pilot.press("enter")
        await settle(pilot)
        await pilot.press("escape")
        await settle(pilot)
        assert not isinstance(app.screen, ConfirmScreen | PlanModal)
        assert _skill_md(tui).read_text() == "edited by the agent"


async def test_re_plan_when_the_item_is_gone_says_so(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("space")
        shutil.rmtree(_skill_md(tui).parent)  # the agent deleted it
        await pilot.press("enter")
        await settle(pilot)
        await pilot.press("enter")  # re-plan
        await settle(pilot)
        assert not isinstance(app.screen, PlanModal)
        assert app.last_outcome == "api-conventions is no longer there; nothing to re-plan"
        assert not (tui.env.paths.parking / "claude-code").exists()
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_engine.py::test_find_installed_returns_the_item_from_a_fresh_scan tests/test_tui_actions.py -k "re_plan or confirm or find_installed" -v`
Expected: FAIL — `ImportError: cannot import name 'ConfirmScreen'` (and `find_installed` missing).

- [ ] **Step 3: `ConfirmScreen`**

Append to `src/harnessctl/tui/modals.py`:

```python
class ConfirmScreen(ModalScreen[bool]):
    """A yes/no question. `yes_key` confirms; Esc and n decline. With yes_key="y" (destructive
    actions), Enter declines too, so a reflexive Enter never confirms."""

    BINDINGS = [
        Binding("enter", "enter", show=False),
        Binding("y", "y", show=False),
        Binding("n", "no", show=False),
        Binding("escape", "no", show=False),
    ]
    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen > Vertical { width: 80; max-width: 100%; height: auto; border: round $accent;
                               background: $surface; padding: 1 2; }
    ConfirmScreen #confirm-message { margin: 1 0; }
    """

    def __init__(self, title: str, message: str, yes: str, yes_key: str = "enter"):
        super().__init__()
        self.title_text = title
        self.message = message
        self.yes = yes
        self.yes_key = yes_key

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(Text(self.title_text, style="bold"))
            yield Static(Text(self.message), id="confirm-message")  # Text: paths may contain [ ]
            hint = Text.assemble((self.yes_key, "bold"), f" {self.yes}   ", ("esc", "bold"), " cancel")
            yield Static(hint)

    def action_enter(self) -> None:
        self.dismiss(self.yes_key == "enter")

    def action_y(self) -> None:
        if self.yes_key == "y":
            self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)
```

Add a unit test for the destructive variant to `tests/test_tui_actions.py` (with the Step 1 tests):

```python
async def test_confirm_with_y_is_never_confirmed_by_enter(tui):
    app = tui.app()
    answers: list[bool | None] = []
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        app.push_screen(ConfirmScreen("Remove?", "gone", "remove", yes_key="y"), answers.append)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        app.push_screen(ConfirmScreen("Remove?", "gone", "remove", yes_key="y"), answers.append)
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
    assert answers == [False, True]
```

- [ ] **Step 4: `Engine.find_installed`**

In `src/harnessctl/engine.py`, add after `installed`:

```python
    def find_installed(self, item: InstalledItem) -> InstalledItem | None:
        """The same item in a fresh scan, matched on scope, kind, original location and state."""
        key = (item.scope, item.kind, item.origin_location, item.enabled)
        return next(
            (
                i
                for i in self.installed(item.harness)
                if (i.scope, i.kind, i.origin_location, i.enabled) == key
            ),
            None,
        )
```

- [ ] **Step 5: The re-plan flow in the app**

In `src/harnessctl/tui/app.py`, add `ConfirmScreen` to the modals import, then replace `propose`, `_confirmed` and `apply_plan` and add `_conflict`:

```python
    def propose(self, build: Callable[[], Plan], replan: Callable[[], Plan] | None = None) -> None:
        # `build` only assembles the plan's steps in memory (no git or harness CLI runs), so it
        # is safe to call straight from the UI thread; only apply_plan() below is a worker.
        try:
            plan = build()
        except (PlanError, ConfigError) as exc:
            self._report(str(exc), "Cannot do that", error=True)
            return
        except Exception as exc:  # noqa: BLE001 - a bad file on disk must not crash the UI
            log.exception("planning failed")
            self._report(f"{type(exc).__name__}: {exc}", "Cannot do that", error=True)
            return
        # Plan-time "left in place" warnings (e.g. a tampered lock entry) travel on the plan
        # itself (see Plan.warnings) and are rendered inside PlanModal — not read off shared
        # engine.lock_errors, which a concurrent rescan thread can reset or consume first.
        again = replan or build
        label = self.engine.adapter(plan.harness).label
        self.push_screen(
            PlanModal(plan, self.engine.paths.home, label), lambda chosen: self._confirmed(chosen, again)
        )

    def _confirmed(self, plan: Plan | None, replan: Callable[[], Plan]) -> None:
        if plan is not None:
            self.apply_plan(plan, replan)

    @work(thread=True, group="apply")
    def apply_plan(self, plan: Plan, replan: Callable[[], Plan] | None = None) -> None:
        try:
            result = self.engine.apply(plan)
        except PlanConflict as exc:
            self.call_from_thread(self._conflict, plan, f"{exc}\nNothing was changed.", replan)
        except Exception as exc:  # noqa: BLE001 - e.g. the backup folder cannot be written
            log.exception("%s: apply failed", plan.title)
            self.call_from_thread(self._report, f"{type(exc).__name__}: {exc}", plan.title, True)
        else:
            if result.ok:
                self.call_from_thread(self._report, plan.reload_hint or "Done.", plan.title)
            elif result.failed_step is None:
                self.call_from_thread(self._report, result.error or "Nothing was changed.", plan.title, True)
            else:
                message = (
                    f"Step {result.failed_step + 1} failed: {result.error}\nEvery change was rolled back."
                )
                self.call_from_thread(self._report, message, plan.title, True)
        self.call_from_thread(self.rescan)

    def _conflict(self, plan: Plan, message: str, replan: Callable[[], Plan] | None) -> None:
        if replan is None:
            self._report(message, plan.title, error=True)
            return
        self.last_outcome = message  # shown once, in the modal below: no toast repeating it

        def answered(yes: bool | None) -> None:
            if yes:
                self.propose(replan)

        self.push_screen(ConfirmScreen(plan.title, message, "re-plan"), answered)
```

- [ ] **Step 6: Installed actions re-plan from a fresh scan**

In `src/harnessctl/tui/views.py`, add `from harnessctl.planner import Plan, PlanError`, then replace `InstalledView._propose` with:

```python
    def _propose(self, method: str) -> None:
        item = self.selected
        if item is None:
            return
        engine = self.app.engine

        def replan() -> Plan:
            # The old item may describe a file that changed: build again from a fresh scan.
            fresh = engine.find_installed(item)
            if fresh is None:
                raise PlanError(f"{item.name} is no longer there; nothing to re-plan")
            return getattr(engine, method)(fresh)

        self.app.propose(lambda: getattr(engine, method)(item), replan)
```

Catalog installs keep calling `self.propose(build)` with no `replan`: re-planning an install from the same catalog item is correct.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/test_engine.py tests/test_tui_actions.py -q`
Expected: PASS, including the existing `test_file_changed_while_modal_open_is_refused` (its `last_outcome` assertion still holds; the confirm screen is simply left open).

- [ ] **Step 8: Full suite, lint, commit**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

```bash
git add src/harnessctl tests/test_engine.py tests/test_tui_actions.py
git commit -m "feat: offer to re-plan after a conflict, from a fresh scan"
```

---

### Task 8: Safer source management

Three fixes on the Sources tab:
1. `d` asks before removing a public source (`ConfirmScreen` with `yes_key="y"`: `y` removes; `enter`, `n` and `esc` cancel), and the removal (which deletes the cached checkout) runs in a worker, not on the UI thread. Corporate sources are refused at once, with the existing message.
2. Adding a repo already configured under another URL form (`git@github.com:o/r.git` vs `https://github.com/o/r`) is refused before anything is written or cloned.
3. Tests for the add-source error paths: a duplicate name and an unreachable URL.

**Files:**
- Modify: `src/harnessctl/engine.py` (`add_source`)
- Modify: `src/harnessctl/tui/app.py` (new `confirm_remove_source`; `remove_source` becomes a worker)
- Modify: `src/harnessctl/tui/views.py` (`SourcesView.action_remove`)
- Test: `tests/test_engine.py`, `tests/test_tui_sources.py`

**Interfaces:**
- Consumes: `ConfirmScreen` (Task 7), `provenance.normalize_url`, `SourceState`, `Trust`.
- Produces: `HarnessApp.confirm_remove_source(state: SourceState)`; `HarnessApp.remove_source(name)` is a `@work(thread=True, group="sources")` worker; duplicate-URL error text `f"{url} is already configured as source '{name}'"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine.py`:

```python
def test_the_same_repo_under_another_url_form_is_refused(engine, env):
    write(env.paths.config_toml, '[[source]]\nname = "tools"\nurl = "git@github.com:acme/tools.git"\n')
    engine.load_sources(fetch=False)
    with pytest.raises(ConfigError, match="already configured as source 'tools'"):
        engine.add_source("https://github.com/acme/tools", name="tools2")
    assert "tools2" not in env.paths.config_toml.read_text()


def test_removing_a_source_keeps_its_installed_items_as_unknown(engine, env, tmp_path):
    other = tmp_path / "pub"
    skill(other / "skills" / "tdd")
    make_repo(None, other)
    engine.add_source(other.as_uri(), name="pub")
    assert engine.apply(engine.plan_install(engine.find_item("pub", "tdd"), "claude-code", Scope.USER)).ok
    engine.remove_source("pub")
    tdd = _installed(engine, "tdd")
    assert tdd.provenance.origin == "unknown"
    assert (env.home / ".claude" / "skills" / "tdd" / "SKILL.md").is_file()
```

(The second test passes already: it pins what the confirmation text below promises.)

In `tests/test_tui_sources.py`, change the imports to

```python
from textual.widgets import Input, Static

from harnessctl.tui.modals import AddSourceScreen, ConfirmScreen
from harnessctl.tui.views import CatalogView, DetailPane, ItemList, SourcesView
from tests.helpers import make_repo, settle, skill, write
```

update the existing `test_add_and_remove_a_public_source` so the removal confirms — replace its line `await pilot.press("down", "d")` with `await pilot.press("down", "d", "y")` — and append:

```python
def _public_source(tui, tmp_path):
    public = tmp_path / "pub"
    skill(public / "skills" / "tdd")
    make_repo(None, public)
    write(tui.env.paths.config_toml, f'[[source]]\nname = "pub"\nurl = "{public.as_uri()}"\n')
    tui.env.engine().load_sources(fetch=True)
    return public


async def test_removing_a_source_asks_first(tui, tmp_path):
    _public_source(tui, tmp_path)
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("3", "down", "d")
        assert isinstance(app.screen, ConfirmScreen)
        assert "show as unknown" in str(app.screen.query_one("#confirm-message", Static).render())
        await pilot.press("escape")
        await settle(pilot)
        assert _sources(app) == ["acme", "pub"]
        await pilot.press("d", "enter")  # a reflexive Enter cancels a removal
        await settle(pilot)
        assert not isinstance(app.screen, ConfirmScreen)
        assert _sources(app) == ["acme", "pub"]
        await pilot.press("d", "y")
        await settle(pilot)
        assert _sources(app) == ["acme"]
        assert app.last_outcome == "pub removed."


async def test_adding_a_duplicate_name_is_reported(tui, tmp_path):
    public = tmp_path / "pub"
    skill(public / "skills" / "tdd")
    make_repo(None, public)
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("3", "a")
        app.screen.query_one("#url", Input).value = public.as_uri()
        app.screen.query_one("#name", Input).value = "acme"
        await pilot.press("enter")
        await settle(pilot)
        assert app.last_outcome == "a source named 'acme' already exists"
        assert _sources(app) == ["acme"]


async def test_adding_an_unreachable_url_is_reported(tui, tmp_path):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("3", "a")
        app.screen.query_one("#url", Input).value = (tmp_path / "missing").as_uri()
        await pilot.press("enter")
        await settle(pilot)
        assert app.last_outcome.startswith("missing: unavailable — ")
        assert _sources(app) == ["acme", "missing"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_engine.py::test_the_same_repo_under_another_url_form_is_refused tests/test_tui_sources.py -v`
Expected: FAIL — no duplicate-URL check; `d` removes without a `ConfirmScreen`; the updated `test_add_and_remove_a_public_source` fails on the extra `y`. `test_adding_a_duplicate_name_is_reported` and `test_adding_an_unreachable_url_is_reported` may already pass (they pin existing behaviour).

- [ ] **Step 3: Refuse a repo configured under another URL**

In `src/harnessctl/engine.py`, add `normalize_url` to the `harnessctl.provenance` import and make `add_source` check before writing anything:

```python
    def add_source(
        self, url: str, name: str | None = None, ref: str | None = None, subdir: str = ""
    ) -> SourceState:
        wanted = normalize_url(url)
        twin = next((s for s in self.specs().values() if normalize_url(s.url) == wanted), None)
        if twin is not None:
            raise ConfigError(f"{url} is already configured as source '{twin.name}'")
        spec = SourceSpec(name or default_source_name(url), url, Trust.PUBLIC, ref or None, subdir)
        add_public_source(self.paths, spec)
        state = sync_source(spec, self.paths.sources_cache, fetch=True)
        self.sources.append(state)
        return state
```

- [ ] **Step 4: Confirm, then remove in a worker**

In `src/harnessctl/tui/app.py`, add `Trust` to the `harnessctl.model` import, and replace `remove_source` with:

```python
    def confirm_remove_source(self, state: SourceState) -> None:
        if state.spec.trust is Trust.CORPORATE:
            self._report("corporate sources are managed in corporate.toml", "Cannot remove source", error=True)
            return
        name = state.spec.name

        def answered(yes: bool | None) -> None:
            if yes:
                self.remove_source(name)

        message = (
            f"{state.spec.url}\n\nIts cached checkout is deleted. "
            "Items you installed from it stay installed and show as unknown."
        )
        self.push_screen(ConfirmScreen(f"Remove source {name}?", message, "remove", yes_key="y"), answered)

    @work(thread=True, group="sources")
    def remove_source(self, name: str) -> None:
        try:
            self.engine.remove_source(name)
        except ConfigError as exc:
            self.call_from_thread(self._report, str(exc), "Cannot remove source", True)
            return
        self.call_from_thread(self._report, f"{name} removed.", "Source removed")
        self.call_from_thread(self.rescan)
```

In `src/harnessctl/tui/views.py`, `SourcesView.action_remove` becomes:

```python
    def action_remove(self) -> None:
        if self.selected is not None:
            self.app.confirm_remove_source(self.selected)
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_engine.py tests/test_tui_sources.py -q`
Expected: PASS, including `test_corporate_source_cannot_be_removed` (same message, no confirm screen).

- [ ] **Step 6: Full suite, lint, commit**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

```bash
git add src/harnessctl tests/test_engine.py tests/test_tui_sources.py
git commit -m "feat: confirm source removal, refuse a repo already added under another URL"
```

---

### Task 9: Editing the source lists reloads the sources

Editing `corporate.toml` or `config.toml` while harnessctl runs triggers a rescan today, but the sources themselves stay as they were at startup until restart. The 2-second poll must notice a change to either file and reload the sources: unchanged sources keep their state, new or changed ones are fetched (in a worker), removed ones disappear, and configuration problems show as warnings. A fetch can take up to the 60 s git timeout, so each one is announced (`Fetching source <name>…`) before it starts; a reload that fetches nothing (e.g. after the TUI itself added a source) shows nothing.

**Files:**
- Modify: `src/harnessctl/engine.py` (new `reload_sources`)
- Modify: `src/harnessctl/tui/app.py` (`__init__`, `on_mount`, `_current_signature`, `poll_changes`, new `_stat`, `_sources_signature`, `reload_sources`, `_sources_reloaded`)
- Test: `tests/test_engine.py`, `tests/test_tui.py`

**Interfaces:**
- Consumes: `config.load_sources`, `sync_source`, `SourceSpec` (frozen, hashable).
- Produces: `Engine.reload_sources(on_fetch: Callable[[str], None] | None = None) -> list[str]` (the configuration problems; also stored in `engine.config_errors`; `on_fetch(name)` is called before each source that must be fetched); `HarnessApp.reload_sources()` worker in group `"sources"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine.py`:

```python
def test_reload_sources_keeps_unchanged_states_and_fetches_new_ones(engine, env, tmp_path):
    acme_state = engine.sources[0]
    other = tmp_path / "pub"
    skill(other / "skills" / "tdd")
    make_repo(None, other)
    write(env.paths.config_toml, f'[[source]]\nname = "pub"\nurl = "{other.as_uri()}"\n')
    fetched: list[str] = []
    assert engine.reload_sources(on_fetch=fetched.append) == []
    assert fetched == ["pub"]
    assert engine.sources[0] is acme_state  # not fetched again
    assert [i.id for i in engine.sources[1].items] == ["tdd"]
    env.paths.config_toml.write_text("")
    engine.reload_sources()
    assert [s.spec.name for s in engine.sources] == ["acme"]
```

In `tests/test_tui.py` (which has `make_repo` in its imports since Task 4), append:

```python
async def test_editing_config_toml_reloads_sources(tui, tmp_path):
    public = tmp_path / "pub"
    skill(public / "skills" / "tdd")
    make_repo(None, public)
    app = tui.app()
    notifications: list[str] = []
    app.notify = lambda message, **kw: notifications.append(message)
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        write(tui.env.paths.config_toml, f'[[source]]\nname = "pub"\nurl = "{public.as_uri()}"\n')
        app.poll_changes()
        await settle(pilot)
        assert "Fetching source pub…" in notifications  # a fetch may take long: say so first
        await pilot.press("2")
        assert "tdd" in _names(app, CatalogView)


async def test_a_broken_config_toml_is_reported_and_the_app_keeps_going(tui):
    app = tui.app()
    notifications: list[str] = []
    app.notify = lambda message, **kw: notifications.append(message)
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        write(tui.env.paths.config_toml, "[[source]\n")
        app.poll_changes()
        await settle(pilot)
        assert app.is_running
        assert any("config.toml" in m for m in notifications)
        await pilot.press("2")
        assert "api-conventions" in _names(app, CatalogView)  # corporate sources still there
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_engine.py::test_reload_sources_keeps_unchanged_states_and_fetches_new_ones tests/test_tui.py -k "config_toml" -v`
Expected: FAIL — `Engine` has no `reload_sources`; the TUI never shows `tdd`; no `config.toml` notification.

- [ ] **Step 3: `Engine.reload_sources`**

In `src/harnessctl/engine.py`, add after `load_sources`:

```python
    def reload_sources(self, on_fetch: Callable[[str], None] | None = None) -> list[str]:
        """Re-read corporate.toml and config.toml. Unchanged sources keep their state; new or
        changed ones are fetched (git: call from a worker), each announced through `on_fetch`
        first; removed ones are dropped."""
        specs, self.config_errors = load_sources(self.paths)
        known = {s.spec: s for s in self.sources}
        states: list[SourceState] = []
        for spec in specs:
            state = known.get(spec)
            if state is None:
                if on_fetch is not None:
                    on_fetch(spec.name)
                state = sync_source(spec, self.paths.sources_cache, fetch=True)
            states.append(state)
        self.sources = states
        return self.config_errors
```

`Callable` comes from `collections.abc`; add it to the imports if `engine.py` does not have it yet.

- [ ] **Step 4: The app polls the source lists separately**

In `src/harnessctl/tui/app.py`:

In `__init__`, add `self._sources_sig: tuple | None = None`.

In `on_mount`, before `self.set_interval(...)`, add `self._sources_sig = self._sources_signature()`.

Replace `_current_signature` and `poll_changes` with:

```python
    @staticmethod
    def _stat(path: Path) -> tuple[str, int | None]:
        try:
            return (str(path), path.stat().st_mtime_ns)
        except OSError:
            return (str(path), None)

    def _current_signature(self) -> tuple:
        return tuple(self._stat(path) for path in self.engine.watched_paths())

    def _sources_signature(self) -> tuple:
        paths = self.engine.paths
        return (self._stat(paths.corporate_toml), self._stat(paths.config_toml))

    def poll_changes(self) -> None:
        sources = self._sources_signature()
        if self._sources_sig is not None and sources != self._sources_sig:
            self._sources_sig = sources
            self.reload_sources()  # it rescans when done
            return
        self._sources_sig = sources
        if self._signature is not None and self._current_signature() != self._signature:
            self.rescan()
```

and add, next to `sync_sources`:

```python
    @work(thread=True, group="sources")
    def reload_sources(self) -> None:
        def fetching(name: str) -> None:
            self.call_from_thread(self.notify, f"Fetching source {name}…", title="Sources", timeout=6)

        errors = self.engine.reload_sources(on_fetch=fetching)
        self.call_from_thread(self._sources_reloaded, errors)

    def _sources_reloaded(self, errors: list[str]) -> None:
        for problem in errors:
            self.notify(problem, title="Configuration", severity="warning", timeout=10)
        self.rescan()
```

Adding or removing a source from the TUI also writes `config.toml`; the next poll then reloads, finds every spec unchanged, and only rescans. That is expected.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_engine.py tests/test_tui.py tests/test_tui_sources.py -q`
Expected: PASS, including `test_file_changes_trigger_a_rescan`.

- [ ] **Step 6: Full suite, lint, commit**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

```bash
git add src/harnessctl/engine.py src/harnessctl/tui/app.py tests/test_engine.py tests/test_tui.py
git commit -m "feat: reload sources when corporate.toml or config.toml changes"
```

---

### Task 10: Installed tab: keep the cursor, open disabled skills

Two fixes found in review:
1. After enabling or disabling an item, the cursor jumps to the first row: a disabled item's `location` is `<original>::parked::<folder>`, so the row key changes. The key must use `origin_location`.
2. `o` on a disabled item opens its old path, which no longer exists (saving there would block re-enabling). A disabled skill (or opencode plugin file) must open its parked copy; a disabled item with no parked copy (a hook, an npm plugin) is refused with a message.

**Files:**
- Modify: `src/harnessctl/tui/views.py` (`InstalledView.key`)
- Modify: `src/harnessctl/tui/app.py` (`edit_item`)
- Test: `tests/test_tui.py`, `tests/test_tui_actions.py`

**Interfaces:**
- Consumes: `InstalledItem.origin_location`, `InstalledItem.meta["park_dir"]` (set by `parking.scan_parked`), parked payloads at `<park_dir>/payload`.
- Produces: row key `(harness, scope, kind, origin_location)`; refusal message `f"{item.name} is disabled; enable it (space) to edit it."`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tui.py`:

```python
async def test_cursor_stays_on_the_item_after_disabling_it(tui):
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("down")
        assert app.query_one(InstalledView).selected.name == "my-notes"
        await pilot.press("space", "enter")
        await settle(pilot)
        selected = app.query_one(InstalledView).selected
        assert selected.name == "my-notes" and selected.enabled is False
```

Append to `tests/test_tui_actions.py`:

```python
async def test_open_a_disabled_skill_opens_its_parked_copy(tui, monkeypatch):
    calls = []
    monkeypatch.setenv("EDITOR", "myeditor")
    monkeypatch.setattr(HarnessApp, "suspend", lambda self: contextlib.nullcontext())
    monkeypatch.setattr("harnessctl.tui.app.run_editor", calls.append)
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("space", "enter")  # disable api-conventions
        await settle(pilot)
        await pilot.press("o")
        opened = calls[-1][-1]
        assert opened.endswith("/payload/SKILL.md")
        assert opened.startswith(str(tui.env.paths.parking))


async def test_open_a_disabled_hook_is_refused(tui, monkeypatch):
    from harnessctl.model import Scope

    engine = tui.env.engine()
    engine.load_sources(fetch=False)
    item = engine.find_item("acme", "block-secrets-read")
    assert engine.apply(engine.plan_install(item, "claude-code", Scope.USER)).ok
    hook = next(i for i in engine.installed("claude-code") if i.name == "block-secrets-read")
    assert engine.apply(engine.plan_toggle(hook)).ok

    calls = []
    monkeypatch.setattr(HarnessApp, "suspend", lambda self: contextlib.nullcontext())
    monkeypatch.setattr("harnessctl.tui.app.run_editor", calls.append)
    app = tui.app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("down", "down")  # Skills: api-conventions, my-notes; Hooks: block-secrets-read
        assert app.query_one(InstalledView).selected.name == "block-secrets-read"
        await pilot.press("o")
        assert calls == []
        assert app.last_outcome == "block-secrets-read is disabled; enable it (space) to edit it."
```

`test_tui_actions.py` must import `InstalledView` (it already imports it for `_items`).

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_tui.py::test_cursor_stays_on_the_item_after_disabling_it tests/test_tui_actions.py -k "disabled" -v`
Expected: FAIL — the cursor lands on `api-conventions`; the editor gets the old skill path; the hook's `settings.json` is opened.

- [ ] **Step 3: Row key on the original location**

In `src/harnessctl/tui/views.py`, `InstalledView.key`:

```python
    def key(self, item: InstalledItem) -> Hashable:
        # A disabled item's location changes (…::parked::…); its original location does not.
        return (item.harness, item.scope, item.kind, item.origin_location)
```

- [ ] **Step 4: Open the parked copy, or refuse**

In `src/harnessctl/tui/app.py`, replace the start of `edit_item` (the `target = Path(...)` assignment) with:

```python
    def edit_item(self, item: InstalledItem) -> None:
        if item.meta.get("park_dir"):
            target = Path(item.meta["park_dir"]) / "payload"
            if not target.exists():
                self._report(
                    f"{item.name} is disabled; enable it (space) to edit it.", "Cannot do that", error=True
                )
                return
        else:
            target = Path(
                item.meta.get("settings")
                or item.meta.get("config")
                or item.meta.get("install_path")
                or item.location
            )
        if target.is_dir() and (target / "SKILL.md").is_file():
            target = target / "SKILL.md"
```

(the rest of `edit_item` is unchanged). Edits made to the parked copy come back when the item is re-enabled, because re-enabling moves `payload` back.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_tui.py tests/test_tui_actions.py -q`
Expected: PASS, including `test_open_in_editor`.

- [ ] **Step 6: Full suite, lint, commit**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

```bash
git add src/harnessctl/tui tests/test_tui.py tests/test_tui_actions.py
git commit -m "fix: keep the cursor on a toggled item; open a disabled skill's parked copy"
```

---

### Task 11: Sources and too-small snapshots, README, version 0.2.0

**Files:**
- Modify: `tests/test_snapshots.py` (new `test_sources_split`, `test_too_small`), `tests/__snapshots__/`
- Modify: `README.md` (Keys table and one paragraph; the README documents behaviour, not history)
- Modify: `pyproject.toml`, `src/harnessctl/__init__.py`, `tests/test_cli.py`, `uv.lock` (version 0.2.0)

**Interfaces:**
- Consumes: everything above.
- Produces: 6 pinned snapshots; README matching the keys; `harnessctl --version` → `harnessctl 0.2.0`.

- [ ] **Step 1: The Sources snapshot (spec §10.3: "the three tabs and the plan modal")**

Append to `tests/test_snapshots.py`:

```python
def test_sources_split(snap_compare, tui):
    # 64 columns: list only. The detail pane would show the source's file:// URL, which contains
    # pytest's temporary path and would differ on every run.
    async def run_before(pilot):
        await settle(pilot)
        await pilot.press("3")
        await settle(pilot)

    assert snap_compare(tui.app(), terminal_size=(64, 30), run_before=run_before)


def test_too_small(snap_compare, tui):
    # One cell under the 50×15 floor: the only thing on screen is the message naming it.
    assert snap_compare(tui.app(), terminal_size=(49, 14), run_before=settle)
```

Also update the module docstring's first line to `"""Pinned frames at the sizes the spec names (120×30 wide, 80×24 standard, 64×30 split, and just under the 50×15 floor)."""` (wrap it to 110 columns).

Run: `uv run pytest tests/test_snapshots.py -k "sources_split or too_small" --snapshot-update`, then run `uv run pytest tests/test_snapshots.py -q` **three times as separate commands**.
Expected: 6 passed each time. `grep -c 'terminal too small' tests/__snapshots__/test_snapshots/test_too_small.svg` → at least 1 (the SVG may split text into spans; if it gives 0, grep for `too small` instead). Check the SVG text (`grep -o 'acme[^<]*' tests/__snapshots__/test_snapshots/test_sources_split.svg`): one `acme` row with `corp`, `ok`, `3 items`, and no `/tmp` anywhere (`grep -c /tmp …` → 0).

- [ ] **Step 2: README keys**

In `README.md`, replace the Keys table rows for Catalog, Sources and plan with:

```markdown
| Catalog | `i` install (then pick user or project scope) · `s` filter by source · `t` filter by type · `esc` clear filters. `✗` marks an item that cannot be installed here; the detail says why. |
| Sources | `a` add · `r` refresh (replaces rescan here) · `d` remove (asks first; `y` confirms) |
| plan | `enter` apply · `v` view diff · `esc` cancel. If a file changed since the plan was made, nothing is changed and you are offered to re-plan. |
```

and add this paragraph right after the table's "Below 100 columns…" sentence:

```markdown
Editing `corporate.toml` or `config.toml` while harnessctl runs reloads the sources within a
couple of seconds. Claude plugins show as unavailable (`✗`) in the Catalog when the `claude` CLI
is not on `PATH`. Press `?` for every key, including those not shown in the footer.
```

Check every key you wrote against the code: `grep -n 'Binding(' src/harnessctl/tui/*.py`.

- [ ] **Step 3: Version 0.2.0**

- `pyproject.toml`: `version = "0.2.0"`
- `src/harnessctl/__init__.py`: `__version__ = "0.2.0"`
- `tests/test_cli.py`: the version test expects `"harnessctl 0.2.0"`
- Run `uv lock` so `uv.lock` records the new project version.

Run: `uv run harnessctl --version`
Expected: `harnessctl 0.2.0`

- [ ] **Step 4: Final verification**

Run each and read the output:
- `uv sync --locked` → no changes (the lock is current).
- `uv run pytest -q` → all pass, 0 failures, no warnings.
- `uv run ruff check . && uv run ruff format --check .` → clean.
- `uv run harnessctl validate examples/acme-catalog` → `catalog ok: 3 items`.

Manual run (the controller hands this to the user; a subagent cannot drive a terminal): in a sandbox `HOME` as in the v1 test, check `s`/`t`/`esc` on the Catalog and that `?` lists them, the plan modal's `acme@…`, a conflict → re-plan, `d` on a public source → `enter` cancels and `y` removes, editing `config.toml` while running (a `Fetching source …` toast), and a 60-column tmux split (`tmux split-window -h`).

- [ ] **Step 5: Commit (do not push)**

```bash
git add tests/test_snapshots.py tests/__snapshots__ README.md pyproject.toml uv.lock \
  src/harnessctl/__init__.py tests/test_cli.py
git commit -m "docs: README keys for v0.2.0; test: Sources and too-small snapshots; chore: version 0.2.0"
```

The controller pushes `develop` and checks the first CI run (see Release housekeeping).
