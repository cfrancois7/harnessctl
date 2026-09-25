"""The harnessctl Textual application: header, three tabs, footer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.widgets import Footer, Static, TabbedContent, TabPane

from harnessctl.engine import CatalogEntry, Engine
from harnessctl.model import InstalledItem
from harnessctl.sources.cache import SourceState
from harnessctl.tui.text import short_path, sync_summary
from harnessctl.tui.views import CatalogView, InstalledView, ItemList, ListDetailView, SourcesView

MIN_WIDTH, MIN_HEIGHT, NARROW_BELOW = 50, 15, 100


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
        for problem in self.engine.config_errors:
            self.notify(problem, title="Configuration", severity="warning", timeout=10)
        self.rescan()

    @work(thread=True, exclusive=True, group="scan")
    def rescan(self) -> None:
        signature = self._current_signature()
        snap = Snapshot(
            self.engine.installed(self.harness), self.engine.catalog(self.harness), list(self.engine.sources)
        )
        self._signature = signature
        self.call_from_thread(self._show, snap)

    def _show(self, snap: Snapshot) -> None:
        self.snapshot = snap
        self._update_header()
        self.query_one(InstalledView).show(snap.installed)
        self.query_one(CatalogView).show(snap.catalog)
        self.query_one(SourcesView).show(snap.sources)

    def _update_header(self) -> None:
        home = self.engine.paths.home
        project = self.engine.project
        where = short_path(project, home) if project else "no project · user scope only"
        sync = sync_summary(self.engine.sources, datetime.now(UTC), self.syncing)
        self.query_one(HeaderBar).update_from(self.engine.adapter(self.harness).label, where, sync)

    def _current_signature(self) -> tuple:
        signature = []
        for path in self.engine.watched_paths():
            try:
                signature.append((str(path), path.stat().st_mtime_ns))
            except OSError:
                signature.append((str(path), None))
        return tuple(signature)

    def poll_changes(self) -> None:
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
