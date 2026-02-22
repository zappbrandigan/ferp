from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widgets import Static


class MetadataPanel(VerticalScroll):
    def __init__(self) -> None:
        super().__init__(id="metadata_panel", can_maximize=True)
        self._content = Static(
            "Select a file to view metadata.", id="metadata_panel_content"
        )
        self.border_title = "Metadata"

    def compose(self):
        yield self._content

    def show_info(self, title: str, lines: list[str]) -> None:
        self._content.update("\n".join(lines))
        self.border_title = title
        self.scroll_to(y=0, animate=False)

    def show_error(self, message: str) -> None:
        self._content.update(message)
        self.border_title = "Metadata"
        self.scroll_to(y=0, animate=False)
