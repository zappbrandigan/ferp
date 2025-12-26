from textual.screen import ModalScreen
from textual.widgets import MarkdownViewer, Footer
from textual.containers import Vertical, VerticalScroll
from textual.binding import Binding

class ReadmeScreen(ModalScreen):

    BINDINGS = [
        Binding("j", "scroll_down", "Scroll down", show=False),
        Binding("down", "scroll_down", "Scroll down", show=False),
        Binding("k", "scroll_up", "Scroll up", show=False),
        Binding("up", "scroll_up", "Scroll up", show=False),
        Binding("escape", "close", "Close README", show=True),
        Binding("q", "close", "Close README", show=False),
    ]

    def __init__(self, title: str, content: str) -> None:
        super().__init__()
        self.heading = title
        self.content = content or "*No README available for this script.*"

    def compose(self):
        markdown = MarkdownViewer(self.content, id="readme_content")
        scroll = VerticalScroll(markdown, id="readme_scroll")
        yield Vertical(
            scroll,
            Footer(id="readme_footer"),
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
