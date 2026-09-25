"""Screens pushed over the main view."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer, Markdown, Static


class DetailScreen(Screen[None]):
    """Full-screen detail used when the terminal is too narrow for the side pane."""

    BINDINGS = [Binding("escape", "back", "back")]

    def __init__(self, markdown: str):
        super().__init__()
        self.markdown = markdown

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Markdown(self.markdown)
        yield Footer()

    def action_back(self) -> None:
        self.app.pop_screen()


class TextScreen(ModalScreen[None]):
    """Scrollable plain text (diffs)."""

    BINDINGS = [Binding("escape", "close", "close")]
    DEFAULT_CSS = """
    TextScreen { align: center middle; }
    TextScreen > VerticalScroll {
        width: 90%; height: 80%; border: round $accent; background: $surface; padding: 0 1;
    }
    """

    def __init__(self, title: str, text: str):
        super().__init__()
        self.title_text = title
        self.body = text

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(Text(self.title_text, style="bold"))
            yield Static(Text(self.body))

    def action_close(self) -> None:
        self.dismiss(None)
