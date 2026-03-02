from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, MarkdownViewer


class _ReadmeMarkdown(MarkdownViewer):
    BINDINGS = [
        Binding("j,down", "scroll_down", "Scroll down", show=False),
        Binding("k,up", "scroll_up", "Scroll up", show=False),
        Binding("g", "scroll_top", "Top", show=False),
        Binding("G", "scroll_bottom", "Bottom", key_display="G", show=False),
        Binding("escape", "close", "Close README", show=True),
        Binding("q", "close", "Close README", show=False),
    ]

    def action_scroll_down(self) -> None:
        self._scroll_by(4)

    def action_scroll_up(self) -> None:
        self._scroll_by(-4)

    def action_scroll_top(self) -> None:
        self.scroll_to(y=0, animate=False)

    def action_scroll_bottom(self) -> None:
        max_y = max(0, self.virtual_size.height - self.size.height)
        self.scroll_to(y=max_y, animate=False)

    def action_close(self) -> None:
        self.app.pop_screen()

    def _scroll_by(self, delta: int) -> None:
        current = getattr(self, "scroll_y", 0.0)
        self.scroll_to(y=max(0, current + delta), animate=False)


class ReadmeScreen(ModalScreen):
    def __init__(self, title: str, content: str, id: str) -> None:
        super().__init__(id=id)
        self.heading = title
        self._content = content or "*No README available for this script.*"
        self._markdown: MarkdownViewer | None = None

    def compose(self):
        markdown = _ReadmeMarkdown(
            self._content, id="readme_content", show_table_of_contents=False
        )
        self._markdown = markdown
        yield Vertical(
            markdown,
            id="readme_modal",
        )

    def on_mount(self) -> None:
        self.query_one("#readme_content", _ReadmeMarkdown).focus()

    def action_close(self) -> None:
        self.app.pop_screen()

    def update_content(self, title: str, content: str) -> None:
        self.heading = title
        self._content = content or "*No README available for this script.*"
        if self._markdown is not None:
            setter = getattr(self._markdown, "set_markdown", None)
            if callable(setter):
                setter(self._content)
            else:
                updater = getattr(self._markdown, "update", None)
                if callable(updater):
                    updater(self._content)
        try:
            self.query_one("#readme_title", Label).update(self.heading)
        except Exception:
            pass
