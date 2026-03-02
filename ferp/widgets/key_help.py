from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static

_HELP_DATA_PATH = Path(__file__).resolve().parent.parent / "resources" / "key_help.json"


@dataclass(frozen=True)
class HelpRow:
    keys: str
    shortcut: str
    context: str


@dataclass(frozen=True)
class HelpSection:
    title: str
    subtitle: str
    rows: tuple[HelpRow, ...]


@dataclass(frozen=True)
class HelpDocument:
    intro: str
    sections: tuple[HelpSection, ...]


def _load_help_document() -> HelpDocument:
    try:
        payload = json.loads(_HELP_DATA_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return HelpDocument(
            intro="Unable to load shortcut reference.",
            sections=(
                HelpSection(
                    title="Error",
                    subtitle="The help data file could not be loaded.",
                    rows=(
                        HelpRow(
                            keys="N/A",
                            shortcut=str(exc),
                            context=str(_HELP_DATA_PATH),
                        ),
                    ),
                ),
            ),
        )

    sections_data = payload.get("sections", [])
    sections: list[HelpSection] = []
    if isinstance(sections_data, list):
        for section_item in sections_data:
            if not isinstance(section_item, dict):
                continue
            title = str(section_item.get("title", "")).strip()
            subtitle = str(section_item.get("subtitle", "")).strip()
            rows_data = section_item.get("rows", [])
            rows: list[HelpRow] = []
            if isinstance(rows_data, list):
                for row_item in rows_data:
                    if not isinstance(row_item, dict):
                        continue
                    rows.append(
                        HelpRow(
                            keys=str(row_item.get("keys", "")).strip(),
                            shortcut=str(row_item.get("shortcut", "")).strip(),
                            context=str(row_item.get("context", "")).strip(),
                        )
                    )
            if title and rows:
                sections.append(
                    HelpSection(
                        title=title,
                        subtitle=subtitle,
                        rows=tuple(rows),
                    )
                )

    intro = str(payload.get("intro", "")).strip() or "Press ? to close."
    return HelpDocument(intro=intro, sections=tuple(sections))


class KeyHelpScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape,q,?", "close", "Close", show=False),
        Binding("j,down", "scroll_down", "Scroll down", show=False),
        Binding("k,up", "scroll_up", "Scroll up", show=False),
        Binding("g", "scroll_top", "Top", show=False),
        Binding("G", "scroll_bottom", "Bottom", key_display="G", show=False),
    ]

    def __init__(self) -> None:
        super().__init__(id="key_help_screen")
        self._document = _load_help_document()

    def compose(self) -> ComposeResult:
        yield Vertical(
            VerticalScroll(
                Static(self._document.intro, classes="key_help_intro"),
                *self._compose_sections(),
                id="key_help_scroll",
            ),
            id="key_help_modal",
        )

    def on_mount(self) -> None:
        modal = self.query_one("#key_help_modal", Vertical)
        modal.border_title = "Keyboard Shortcuts"
        modal.border_subtitle = "Compact reference sheet"
        scroll = self.query_one("#key_help_scroll", VerticalScroll)
        scroll.focus()

    def action_close(self) -> None:
        self.dismiss(None)

    def action_scroll_down(self) -> None:
        self._scroll_by(4)

    def action_scroll_up(self) -> None:
        self._scroll_by(-4)

    def action_scroll_top(self) -> None:
        scroll = self.query_one("#key_help_scroll", VerticalScroll)
        scroll.scroll_to(y=0, animate=False)

    def action_scroll_bottom(self) -> None:
        scroll = self.query_one("#key_help_scroll", VerticalScroll)
        max_y = max(0, scroll.virtual_size.height - scroll.size.height)
        scroll.scroll_to(y=max_y, animate=False)

    def _scroll_by(self, delta: int) -> None:
        scroll = self.query_one("#key_help_scroll", VerticalScroll)
        current = getattr(scroll, "scroll_y", 0.0)
        scroll.scroll_to(y=max(0, current + delta), animate=False)

    def _compose_sections(self) -> list[Static | DataTable]:
        widgets: list[Static | DataTable] = []
        for index, section in enumerate(self._document.sections):
            widgets.append(Static(section.title, classes="key_help_section_title"))
            if section.subtitle:
                widgets.append(
                    Static(section.subtitle, classes="key_help_section_subtitle")
                )
            widgets.append(self._build_table(section.rows, index))
        return widgets

    def _build_table(self, rows: tuple[HelpRow, ...], index: int) -> DataTable:
        table = DataTable(
            id=f"key_help_table_{index}",
            classes="key_help_table",
            show_cursor=False,
            zebra_stripes=True,
            disabled=True,
        )
        table.add_column("Keys", width=18)
        table.add_column("Shortcut", width=60)
        table.add_column("Context", width=34)
        table.add_rows([(row.keys, row.shortcut, row.context) for row in rows])
        table.styles.height = len(rows) + 3
        return table
