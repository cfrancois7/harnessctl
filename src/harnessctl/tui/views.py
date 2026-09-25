"""The three tabs: a grouped list on the left, a markdown detail pane on the right."""

from __future__ import annotations

from collections.abc import Callable, Hashable
from datetime import UTC, datetime
from typing import Any

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Markdown, OptionList
from textual.widgets.option_list import Option

from harnessctl.engine import CatalogEntry, group_of
from harnessctl.model import InstalledItem, Kind, Trust
from harnessctl.sources.cache import SourceState
from harnessctl.tui.modals import DetailScreen
from harnessctl.tui.text import (
    catalog_detail,
    catalog_row,
    installed_detail,
    installed_row,
    source_detail,
    source_row,
)

Groups = list[tuple[str, list[tuple[Text, Any]]]]


class ItemList(OptionList):
    """Grouped rows with disabled group headers; every other row maps to an object."""

    DEFAULT_CSS = "ItemList { border: none; height: 1fr; width: 1fr; min-width: 40; padding: 0; }"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.objects: list[Any] = []

    @property
    def selected(self) -> Any | None:
        if self.highlighted is None or not self.objects:
            return None
        option = self.get_option_at_index(self.highlighted)
        return self.objects[int(option.id)] if option.id is not None else None

    def set_rows(self, groups: Groups, key: Callable[[Any], Hashable]) -> None:
        current = self.selected
        wanted = key(current) if current is not None else None
        options: list[Option | None] = []
        self.objects = []
        keep_id: str | None = None
        for title, rows in groups:
            if not rows:
                continue
            if options:
                options.append(None)
            options.append(Option(Text(f" {title} {len(rows)}", style="bold"), disabled=True))
            for text, obj in rows:
                option_id = str(len(self.objects))
                if wanted is not None and key(obj) == wanted:
                    keep_id = option_id
                options.append(Option(text, id=option_id))
                self.objects.append(obj)
        self.clear_options()
        self.add_options(options)
        if self.objects:
            self.highlighted = self.get_option_index(keep_id or "0")


class DetailPane(VerticalScroll):
    DEFAULT_CSS = "DetailPane { width: 1fr; border-left: solid $panel-lighten-2; padding: 0 1; }"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.markdown = ""

    def compose(self) -> ComposeResult:
        yield Markdown()

    def show(self, markdown: str) -> None:
        self.markdown = markdown
        self.query_one(Markdown).update(markdown)
        self.scroll_home(animate=False)


class ListDetailView(Vertical):
    BINDINGS = [
        Binding("slash", "filter", "filter"),
        Binding("escape", "clear_filter", "clear filter", show=False),
    ]
    DEFAULT_CSS = """
    ListDetailView { height: 1fr; }
    ListDetailView > Input { display: none; margin: 0 1; }
    ListDetailView > Input.-shown { display: block; }
    ListDetailView > Horizontal { height: 1fr; }
    """
    empty_text = "Nothing here yet."

    def __init__(self, **kw):
        super().__init__(**kw)
        self.data: list[Any] = []

    def compose(self) -> ComposeResult:
        yield Input(placeholder="filter…")
        with Horizontal():
            yield ItemList()
            yield DetailPane()

    # --- hooks for subclasses ----------------------------------------------------------------

    def groups(self, data: list[Any], text: str) -> Groups:
        raise NotImplementedError

    def key(self, obj: Any) -> Hashable:
        return id(obj)

    def detail(self, obj: Any) -> str:
        raise NotImplementedError

    # --- behaviour ---------------------------------------------------------------------------

    @property
    def selected(self) -> Any | None:
        return self.query_one(ItemList).selected

    def show(self, data: list[Any]) -> None:
        self.data = data
        self._refresh_rows()

    def set_narrow(self, narrow: bool) -> None:
        self.query_one(DetailPane).display = not narrow

    def _refresh_rows(self) -> None:
        # Named to not collide with Widget._render(), which paints this widget itself.
        text = self.query_one(Input).value.strip().lower()
        self.query_one(ItemList).set_rows(self.groups(self.data, text), self.key)
        self._update_detail()

    def _update_detail(self) -> None:
        obj = self.selected
        self.query_one(DetailPane).show(self.detail(obj) if obj is not None else self.empty_text)

    def action_filter(self) -> None:
        box = self.query_one(Input)
        box.add_class("-shown")
        box.focus()

    def action_clear_filter(self) -> None:
        box = self.query_one(Input)
        box.value = ""
        box.remove_class("-shown")
        self.query_one(ItemList).focus()

    @on(Input.Changed)
    def _filter_changed(self) -> None:
        self._refresh_rows()

    @on(Input.Submitted)
    def _filter_done(self) -> None:
        self.query_one(ItemList).focus()

    @on(OptionList.OptionHighlighted)
    def _highlighted(self) -> None:
        self._update_detail()

    @on(OptionList.OptionSelected)
    def _selected(self) -> None:
        obj = self.selected
        if obj is not None and not self.query_one(DetailPane).display:
            self.app.push_screen(DetailScreen(self.detail(obj)))


GROUPS = [("Skills", Kind.SKILL), ("Hooks", Kind.HOOK), ("Plugins", Kind.PLUGIN)]


class InstalledView(ListDetailView):
    empty_text = "Nothing installed yet. Open the **Catalog** tab (press `2`) to install something."

    def groups(self, items: list[InstalledItem], text: str) -> Groups:
        def keep(i: InstalledItem) -> bool:
            haystack = f"{i.name} {i.provenance.label} {i.provenance.source or ''}".lower()
            return not text or text in haystack

        return [
            (title, [(installed_row(i), i) for i in items if group_of(i) is kind and keep(i)])
            for title, kind in GROUPS
        ]

    def key(self, item: InstalledItem) -> Hashable:
        return (item.harness, item.scope, item.location)

    def detail(self, item: InstalledItem) -> str:
        return installed_detail(item, self.app.engine.paths.home)


class CatalogView(ListDetailView):
    empty_text = "No catalog items. Add a source in the **Sources** tab (press `3`)."

    def groups(self, entries: list[CatalogEntry], text: str) -> Groups:
        by_source: dict[str, list[CatalogEntry]] = {}
        for entry in entries:
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
        return groups

    def key(self, entry: CatalogEntry) -> Hashable:
        return (entry.item.source, entry.item.id)

    def detail(self, entry: CatalogEntry) -> str:
        return catalog_detail(entry)


class SourcesView(ListDetailView):
    empty_text = (
        "No sources. Press `a` to add a public git repo, or ask IT for `~/.config/harnessctl/corporate.toml`."
    )

    def groups(self, states: list[SourceState], text: str) -> Groups:
        def rows(trust: Trust) -> list[tuple[Text, SourceState]]:
            return [
                (source_row(s), s)
                for s in states
                if s.spec.trust is trust and (not text or text in s.spec.name)
            ]

        return [("Corporate", rows(Trust.CORPORATE)), ("Public", rows(Trust.PUBLIC))]

    def key(self, state: SourceState) -> Hashable:
        return state.spec.name

    def detail(self, state: SourceState) -> str:
        return source_detail(state, datetime.now(UTC))
