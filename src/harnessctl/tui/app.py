"""The harnessctl Textual application: header, three tabs, footer."""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.widgets import Footer, Static, TabbedContent, TabPane
from textual.worker import get_current_worker

from harnessctl.config import ConfigError
from harnessctl.engine import CatalogEntry, Engine
from harnessctl.model import InstalledItem, Scope, Trust
from harnessctl.planner import Plan, PlanConflict, PlanError
from harnessctl.sources.cache import SourceState
from harnessctl.tui.modals import ConfirmScreen, PlanModal, ScopePicker
from harnessctl.tui.text import short_path, sync_summary
from harnessctl.tui.views import CatalogView, InstalledView, ItemList, ListDetailView, SourcesView

log = logging.getLogger(__name__)
MIN_WIDTH, MIN_HEIGHT, NARROW_BELOW = 50, 15, 100


def run_editor(argv: list[str]) -> None:
    subprocess.run(argv, check=False)


@dataclass
class Snapshot:
    installed: list[InstalledItem] = field(default_factory=list)
    catalog: list[CatalogEntry] = field(default_factory=list)
    sources: list[SourceState] = field(default_factory=list)


class HeaderBar(Horizontal):
    DEFAULT_CSS = """
    HeaderBar { height: 1; background: $panel; }
    HeaderBar > Static { width: auto; padding: 0 1; }
    HeaderBar > #brand { text-style: bold; }
    HeaderBar > #harness { background: $boost; }
    HeaderBar > #where { width: 1fr; color: $text-muted; }
    HeaderBar > #sync { color: $text-muted; }
    """

    def compose(self) -> ComposeResult:
        yield Static("harnessctl", id="brand")
        yield Static(id="harness")
        yield Static(id="where")
        yield Static(id="sync")

    def update_from(self, harness: str, where: str, sync: str) -> None:
        self.query_one("#harness", Static).update(f"{harness} ▾")
        self.query_one("#where", Static).update(where)
        self.query_one("#sync", Static).update(sync)


class HarnessApp(App[None]):
    CSS_PATH = "app.tcss"
    TITLE = "harnessctl"
    BINDINGS = [
        Binding("q", "quit", "quit"),
        Binding("h", "switch_harness", "harness"),
        Binding("r", "rescan", "rescan"),
        Binding("1", "show_tab('installed')", "installed", show=False),
        Binding("2", "show_tab('catalog')", "catalog", show=False),
        Binding("3", "show_tab('sources')", "sources", show=False),
        Binding("question_mark", "show_help_panel", "help"),
    ]

    def __init__(self, engine: Engine, fetch: bool = True, poll_interval: float = 2.0):
        super().__init__()
        self.engine = engine
        self.fetch = fetch
        self.poll_interval = poll_interval
        self.harness = engine.detected()[0].id
        self.snapshot = Snapshot()
        self.syncing = True
        self.narrow = False
        self.last_outcome = ""
        self._signature: tuple | None = None
        self._sources_sig: tuple | None = None
        self._shown_lock_errors: set[str] = set()
        self._shown_config_errors: set[str] = set()

    def compose(self) -> ComposeResult:
        with Vertical(id="main"):
            yield HeaderBar()
            with TabbedContent(initial="installed", id="tabs"):
                with TabPane("Installed", id="installed"):
                    yield InstalledView()
                with TabPane("Catalog", id="catalog"):
                    yield CatalogView()
                with TabPane("Sources", id="sources"):
                    yield SourcesView()
            yield Footer()
        yield Static(f"terminal too small — need {MIN_WIDTH}×{MIN_HEIGHT}", id="too-small")

    def on_mount(self) -> None:
        self._layout(self.size.width, self.size.height)
        self._update_header()
        self.query_one(InstalledView).query_one(ItemList).focus()
        self.rescan()
        self.sync_sources()
        self._sources_sig = self._sources_signature()
        self.set_interval(self.poll_interval, self.poll_changes)

    # --- layout ------------------------------------------------------------------------------

    def on_resize(self, event: Resize) -> None:
        self._layout(event.size.width, event.size.height)

    def _layout(self, width: int, height: int) -> None:
        small = width < MIN_WIDTH or height < MIN_HEIGHT
        self.query_one("#main").display = not small
        self.query_one("#too-small").display = small
        self.narrow = width < NARROW_BELOW
        for view in self.query(ListDetailView):
            view.set_narrow(self.narrow)

    @on(TabbedContent.TabActivated)
    def _tab_changed(self, event: TabbedContent.TabActivated) -> None:
        # A TabActivated event can still be queued for a pane that a later tab switch has
        # already superseded (e.g. two presses in quick succession). Focusing that stale
        # pane's list would post a TabPane.Focused, which TabbedContent uses to set
        # `active` back to it — silently reverting the newer switch. Only act on the event
        # that matches the tab currently active.
        if event.pane.id == event.tabbed_content.active:
            event.pane.query_one(ItemList).focus()

    # --- data --------------------------------------------------------------------------------

    @work(thread=True, exclusive=True, group="sources")
    def sync_sources(self) -> None:
        self.engine.load_sources(fetch=False)
        self.call_from_thread(self.rescan)
        if self.fetch:
            self.engine.load_sources(fetch=True)
        self.syncing = False
        self.call_from_thread(self._after_sync)

    def _after_sync(self) -> None:
        self._notify_config_errors(self.engine.config_errors)
        self.rescan()

    @work(thread=True, group="sources")
    def reload_sources(self) -> None:
        def fetching(name: str) -> None:
            self.call_from_thread(self.notify, f"Fetching source {name}…", title="Sources", timeout=6)

        errors = self.engine.reload_sources(on_fetch=fetching)
        self.call_from_thread(self._sources_reloaded, errors)

    def _sources_reloaded(self, errors: list[str]) -> None:
        self._notify_config_errors(errors)
        self.rescan()

    def _notify_config_errors(self, errors: list[str]) -> None:
        # Only surface a configuration problem the first time it appears; once it clears (the
        # file is fixed) forget it, so it is announced again if it comes back.
        unique_errors = list(dict.fromkeys(errors))
        for problem in unique_errors:
            if problem not in self._shown_config_errors:
                self.notify(problem, title="Configuration", severity="warning", timeout=10)
        self._shown_config_errors = set(unique_errors)

    @work(thread=True, exclusive=True, group="scan")
    def rescan(self) -> None:
        # Capture the harness up front: if the user switches harnesses while this scan is
        # in flight, self.harness may already point at the new one by the time we finish.
        harness = self.harness
        signature = self._current_signature()
        try:
            snap = Snapshot(
                self.engine.installed(harness), self.engine.catalog(harness), list(self.engine.sources)
            )
        except Exception as exc:  # noqa: BLE001 - a scan must never take the app down
            log.exception("rescan failed")
            if not get_current_worker().is_cancelled:
                self._signature = signature  # don't re-fail on every poll until something changes
                self.call_from_thread(self._report, f"{type(exc).__name__}: {exc}", "Scan failed", True)
            return
        lock_errors = list(self.engine.lock_errors)
        # A newer rescan (harness switch, poll, manual `r`) may have superseded this one
        # while installed()/catalog() were running on this thread — cancellation of a
        # thread worker doesn't stop the thread, it only marks it cancelled. Don't paint
        # stale data over whatever the newer scan already showed.
        if get_current_worker().is_cancelled:
            return
        self._signature = signature
        self.call_from_thread(self._show, snap, lock_errors)

    def _show(self, snap: Snapshot, lock_errors: list[str]) -> None:
        self.snapshot = snap
        self._update_header()
        self.query_one(InstalledView).show(snap.installed)
        self.query_one(CatalogView).show(snap.catalog)
        self.query_one(SourcesView).show(snap.sources)
        # `Engine.lock_errors` is refilled by any concurrently-running scan (it's shared,
        # unsynchronized engine state), so the same message can show up twice in one capture;
        # de-duplicate within this call as well as against what was last shown.
        unique_errors = list(dict.fromkeys(lock_errors))
        for error in unique_errors:
            if error not in self._shown_lock_errors:
                self.notify(error, title="Lock file", severity="warning", timeout=10)
        self._shown_lock_errors = set(unique_errors)

    def _update_header(self) -> None:
        home = self.engine.paths.home
        project = self.engine.project
        where = short_path(project, home) if project else "no project · user scope only"
        sync = sync_summary(self.engine.sources, datetime.now(UTC), self.syncing)
        self.query_one(HeaderBar).update_from(self.engine.adapter(self.harness).label, where, sync)

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

    # --- actions -----------------------------------------------------------------------------

    def action_show_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab

    def action_rescan(self) -> None:
        self.rescan()

    def action_switch_harness(self) -> None:
        ids = [a.id for a in self.engine.detected()]
        if len(ids) < 2:
            self.notify("Only one harness is set up on this machine.", timeout=3)
            return
        self.harness = ids[(ids.index(self.harness) + 1) % len(ids)] if self.harness in ids else ids[0]
        self._update_header()
        self.rescan()

    # --- changes -----------------------------------------------------------------------------

    def _report(self, message: str, title: str, error: bool = False) -> None:
        self.last_outcome = message
        self.notify(
            message, title=title, severity="error" if error else "information", timeout=12 if error else 6
        )

    def propose(self, build: Callable[[], Plan], replan: Callable[[], Plan] | None = None) -> None:
        # `build` only assembles the plan's steps in memory, and `replan` (when given) only
        # re-scans the filesystem to find the item fresh (see e.g. ItemList._propose) — neither
        # runs git or a harness CLI, so both are safe to call straight from the UI thread; only
        # apply_plan() below is a worker.
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

    def install(self, entry: CatalogEntry) -> None:
        adapter = self.engine.adapter(self.harness)
        if not entry.available:
            self._report(f"{entry.item.id}: {entry.reason}.", "Cannot do that", error=True)
            return
        scopes = self.engine.scopes()
        if len(scopes) == 1:
            self.propose(lambda: self.engine.plan_install(entry.item, self.harness, Scope.USER))
            return
        home = self.engine.paths.home
        choices = [(s, short_path(adapter.scope_dir(s, self.engine.project), home)) for s in scopes]

        def chosen(scope: Scope | None) -> None:
            if scope is not None:
                self.propose(lambda: self.engine.plan_install(entry.item, self.harness, scope))

        self.push_screen(ScopePicker(entry.item.id, choices), chosen)

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
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
        try:
            with self.suspend():
                run_editor([*shlex.split(editor), str(target)])
        except SuspendNotSupported:
            self._report("Opening an editor is not supported in this terminal.", "Cannot do that", error=True)
            return
        self.rescan()

    # --- sources -----------------------------------------------------------------------------

    @staticmethod
    def _source_outcome(state: SourceState) -> str:
        if state.error:
            return f"{state.spec.name}: {state.status} — {state.error}"
        return f"{state.spec.name}: {state.status}, {len(state.items)} items"

    def add_source(self, answer: dict | None) -> None:
        if answer:
            self._add_source(answer)

    @work(thread=True, group="sources")
    def _add_source(self, answer: dict) -> None:
        try:
            state = self.engine.add_source(answer["url"], name=answer["name"], ref=answer["ref"])
        except ConfigError as exc:
            self.call_from_thread(self._report, str(exc), "Cannot add source", True)
            return
        self.call_from_thread(self._report, self._source_outcome(state), "Source added", state.status != "ok")
        self.call_from_thread(self.rescan)

    @work(thread=True, group="sources")
    def refresh_source(self, name: str) -> None:
        try:
            state = self.engine.refresh_source(name)
        except ConfigError as exc:
            self.call_from_thread(self._report, str(exc), "Cannot refresh source", True)
            return
        self.call_from_thread(
            self._report, self._source_outcome(state), "Source refreshed", state.status != "ok"
        )
        self.call_from_thread(self.rescan)

    def confirm_remove_source(self, state: SourceState) -> None:
        if state.spec.trust is Trust.CORPORATE:
            self._report(
                "corporate sources are managed in corporate.toml", "Cannot remove source", error=True
            )
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
