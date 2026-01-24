from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, MarkdownViewer


class ReadmeScreen(ModalScreen):
    BINDINGS = [
        Binding("j", "scroll_down", "Scroll down", show=False),
        Binding("down", "scroll_down", "Scroll down", show=False),
        Binding("k", "scroll_up", "Scroll up", show=False),
        Binding("up", "scroll_up", "Scroll up", show=False),
        Binding("escape", "close", "Close README", show=True),
        Binding("q", "close", "Close README", show=False),
    ]

    def __init__(self, title: str, content: str, id: str) -> None:
        super().__init__(id=id)
        self.heading = title
        self._content = content or "*No README available for this script.*"
        self._markdown: MarkdownViewer | None = None

    def compose(self):
        markdown = MarkdownViewer(self._content, id="readme_content")
        self._markdown = markdown
        yield Vertical(
            VerticalScroll(markdown, id="readme_scroll"),
            id="readme_modal",
        )

    def on_mount(self) -> None:
        self.query_one("#readme_scroll", VerticalScroll).focus()

    def action_close(self) -> None:
        self.app.pop_screen()

    def action_scroll_down(self) -> None:
        scroll = self.query_one("#readme_scroll", VerticalScroll)
        scroll.scroll_down()

    def action_scroll_up(self) -> None:
        scroll = self.query_one("#readme_scroll", VerticalScroll)
        scroll.scroll_up()

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
