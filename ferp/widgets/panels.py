from textual.widgets import Static


class ContentPanel(Static):
    def __init__(self, content: str, id: str, title: str) -> None:
        super().__init__(content, id=id)
        self.title = title

    def on_mount(self) -> None:
        self.border_title = self.title

    def update_content(self, content: str) -> None:
        self.update(content)
