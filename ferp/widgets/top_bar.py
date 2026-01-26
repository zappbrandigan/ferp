from datetime import datetime, timedelta, timezone

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.reactive import reactive
from textual.widgets import Label

from ferp.core.state import AppState, AppStateStore

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class TopBar(Container):
    """Custom application title bar."""

    current_path = reactive("", always_update=True)
    status = reactive("Ready", always_update=True)
    cache_updated_at = reactive(
        datetime(1970, 1, 1, tzinfo=timezone.utc), always_update=True
    )

    def __init__(
        self,
        *,
        app_title: str | None,
        app_version: str,
        state_store: AppStateStore,
    ) -> None:
        super().__init__()
        self._state_store = state_store
        self._state_subscription = self._handle_state_update

        self.title_label = Horizontal(
            Label(
                f"{app_title}",
                id="topbar_app_name",
            ),
            Label(
                f"v{app_version}",
                id="topbar_app_version",
            ),
            id="app_meta_container",
        )
        self.status_label = Label("", id="topbar_script_status")
        self.cache_label = Label("", id="topbar_cache")

    def on_mount(self) -> None:
        self._state_store.subscribe(self._state_subscription)

    def on_unmount(self) -> None:
        self._state_store.unsubscribe(self._state_subscription)

    def watch_current_path(self) -> None:
        self._update_status()

    def watch_status(self) -> None:
        self._update_status()

    def watch_cache_updated_at(self) -> None:
        self._update_cache_status()

    def _update_status(self) -> None:
        if not self.current_path:
            self.status_label.update("")
            return

        status = {
            "ready": f"[dim]Ready - [/dim]{self.current_path}",
            "running": f"[$foreground]Running[/] - {self.current_path}",
        }
        self.status_label.update(
            status["ready"] if self.status == "Ready" else status["running"]
        )

    def _update_cache_status(self) -> None:
        if self.cache_updated_at == EPOCH:
            self.cache_label.update("[dim]Cache: never updated[/dim]")
            return

        relative = self._format_relative_time(self.cache_updated_at)
        self.cache_label.update(f"[dim]Cache updated:[/dim] {relative}")

    def _format_relative_time(self, ts: datetime) -> str:
        now = datetime.now(timezone.utc)
        delta: timedelta = now - ts

        seconds = int(delta.total_seconds())

        if seconds < 30:
            return "just now"
        if seconds < 60:
            return f"{seconds}s ago"
        if seconds < 3600:
            return f"{seconds // 60} min ago"
        if seconds < 86400:
            return f"{seconds // 3600} hr ago"
        if seconds < 172800:
            return "yesterday"

        return f"{seconds // 86400} days ago"

    def _handle_state_update(self, state: AppState) -> None:
        self.current_path = state.current_path
        self.status = state.status
        self.cache_updated_at = state.cache_updated_at

    def compose(self) -> ComposeResult:
        yield self.title_label
        yield self.status_label
        yield self.cache_label
