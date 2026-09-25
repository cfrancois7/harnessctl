"""Screens pushed over the main view."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer, Input, Markdown, OptionList, Static
from textual.widgets.option_list import Option

from harnessctl.model import Scope
from harnessctl.planner import Plan, plan_diff
from harnessctl.tui.text import plan_text


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


class PlanModal(ModalScreen[Plan | None]):
    """Shows every step of a plan; Enter applies it, Esc cancels."""

    BINDINGS = [
        Binding("enter", "apply", "apply"),
        Binding("v", "diff", "view diff"),
        Binding("escape", "cancel", "cancel"),
    ]
    DEFAULT_CSS = """
    PlanModal { align: center middle; }
    PlanModal > Vertical { width: 96; max-width: 100%; height: auto; max-height: 90%;
                           border: round $accent; background: $surface; padding: 1 2; }
    PlanModal .dim { color: $text-muted; }
    PlanModal #plan-steps { margin: 1 0; }
    PlanModal #plan-warnings { margin: 1 0; }
    """

    def __init__(self, plan: Plan, home: Path, harness_label: str):
        super().__init__()
        self.plan = plan
        self.home = home
        self.harness_label = harness_label

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(Text(self.plan.title, style="bold"))
            yield Static(f"{self.harness_label} · {self.plan.scope} scope", classes="dim")
            if self.plan.warnings:
                yield Static(
                    Text("\n".join(f"⚠ {w}" for w in self.plan.warnings), style="bold #ff8a65"),
                    id="plan-warnings",
                )
            yield Static(
                plan_text(self.plan, self.home) if self.plan.steps else "Nothing to do.", id="plan-steps"
            )
            if self.plan.reload_hint:
                yield Static(self.plan.reload_hint, classes="dim")
            yield Static(
                Text.assemble(
                    ("enter", "bold"),
                    " apply   ",
                    ("v", "bold"),
                    " view diff   ",
                    ("esc", "bold"),
                    " cancel",
                )
            )

    def action_apply(self) -> None:
        self.dismiss(self.plan)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_diff(self) -> None:
        self.app.push_screen(TextScreen("Diff", plan_diff(self.plan)))


class ScopePicker(ModalScreen[Scope | None]):
    BINDINGS = [Binding("escape", "cancel", "cancel")]
    DEFAULT_CSS = """
    ScopePicker { align: center middle; }
    ScopePicker > Vertical { width: 70; max-width: 100%; height: auto; border: round $accent;
                             background: $surface; padding: 1 2; }
    ScopePicker OptionList { height: auto; border: none; margin-top: 1; }
    """

    def __init__(self, item_id: str, choices: list[tuple[Scope, str]]):
        super().__init__()
        self.item_id = item_id
        self.choices = choices

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(Text(f"Install {self.item_id} where?", style="bold"))
            yield OptionList(
                *[Option(f"{scope.value:<8} {where}", id=scope.value) for scope, where in self.choices]
            )

    def on_mount(self) -> None:
        self.query_one(OptionList).highlighted = 0

    @on(OptionList.OptionSelected)
    def _chosen(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(Scope(event.option.id))

    def action_cancel(self) -> None:
        self.dismiss(None)


class AddSourceScreen(ModalScreen[dict | None]):
    BINDINGS = [Binding("escape", "cancel", "cancel")]
    DEFAULT_CSS = """
    AddSourceScreen { align: center middle; }
    AddSourceScreen > Vertical { width: 80; max-width: 100%; height: auto; border: round $accent;
                                 background: $surface; padding: 1 2; }
    AddSourceScreen .dim { color: $text-muted; }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(Text("Add a public source", style="bold"))
            yield Static(
                "A git URL: a harnessctl catalog, a Claude plugin marketplace or a skills repo.",
                classes="dim",
            )
            yield Input(placeholder="https://github.com/owner/repo", id="url")
            yield Input(placeholder="name (optional)", id="name")
            yield Input(placeholder="branch or tag (optional)", id="ref")
            yield Static(
                Text.assemble(("enter", "bold"), " add   ", ("esc", "bold"), " cancel"), classes="dim"
            )

    @on(Input.Submitted)
    def _submit(self) -> None:
        url = self.query_one("#url", Input).value.strip()
        if not url:
            self.query_one("#url", Input).focus()
            return
        self.dismiss(
            {
                "url": url,
                "name": self.query_one("#name", Input).value.strip() or None,
                "ref": self.query_one("#ref", Input).value.strip() or None,
            }
        )

    def action_cancel(self) -> None:
        self.dismiss(None)
