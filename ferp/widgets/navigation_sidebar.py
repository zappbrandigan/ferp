from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, cast

from textual import on
from textual.binding import Binding
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from ferp.core.messages import NavigateRequest
from ferp.core.path_navigation import is_navigable_directory
from ferp.core.state import AppState, AppStateStore


class NavigationSidebar(OptionList):
    """Quick-jump sidebar for common locations, pinned items, and drives."""

    LABEL_MAX_WIDTH = 20

    BINDINGS = [
        Binding("g", "first", "Top", show=False),
        Binding("G", "last", "Bottom", key_display="G", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("j", "cursor_down", "Down", show=False),
    ]

    def __init__(
        self,
        *,
        state_store: AppStateStore,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._state_store = state_store
        self._state_subscription = self._handle_state_update
        self._option_paths: dict[str, Path] = {}
        self._current_path: Path | None = None

    def on_mount(self) -> None:
        self.border_title = "Quick Nav"
        self._state_store.subscribe(self._state_subscription)

    def on_unmount(self) -> None:
        self._state_store.unsubscribe(self._state_subscription)

    @on(OptionList.OptionSelected)
    def _handle_selection(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option_id
        if not option_id:
            return
        target = self._option_paths.get(option_id)
        if target is None:
            return
        if not is_navigable_directory(target):
            pruner = cast(
                Callable[[], int] | None,
                getattr(self.app, "prune_stale_pinned_entries", None),
            )
            removed = pruner() if callable(pruner) else 0
            self.refresh_items()
            notify = getattr(self.app, "notify", None)
            if callable(notify):
                message = (
                    "Pinned folder no longer exists."
                    if removed <= 1
                    else f"Removed {removed} stale pinned folders."
                )
                notify(message)
            return
        self.post_message(NavigateRequest(target))

    def refresh_items(self) -> None:
        sections = [
            ("Places", self._known_places()),
            ("Pinned", self._pinned_places()),
            ("Drives", self._drives()),
        ]

        content: list[Option | None] = []
        option_paths: dict[str, Path] = {}
        highlight_id: str | None = None
        best_depth = -1
        option_index = 0

        for title, items in sections:
            if not items:
                continue
            if content:
                content.append(None)
            content.append(Option(f"[b]{title}[/b]", disabled=True))

            for label, path in items:
                option_id = f"nav_{option_index}"
                option_index += 1
                content.append(Option(self._truncate_label(label), id=option_id))
                option_paths[option_id] = path
                depth = self._match_depth(path)
                if depth > best_depth:
                    best_depth = depth
                    highlight_id = option_id

        self._option_paths = option_paths
        self.set_options(content)

        if highlight_id is None:
            self.highlighted = None
            return
        try:
            self.highlighted = self.get_option_index(highlight_id)
        except Exception:
            self.highlighted = None

    def _handle_state_update(self, state: AppState) -> None:
        self._current_path = Path(state.current_path) if state.current_path else None
        self.refresh_items()

    def _known_places(self) -> list[tuple[str, Path]]:
        home = Path.home()
        candidates = [
            ("Home", home),
            ("Desktop", home / "Desktop"),
            ("Documents", home / "Documents"),
            ("Downloads", home / "Downloads"),
        ]
        return self._normalize_entries(candidates)

    def _pinned_places(self) -> list[tuple[str, Path]]:
        pinned_getter = cast(
            Callable[[], list[Path]] | None,
            getattr(self.app, "pinned_paths", None),
        )
        if not callable(pinned_getter):
            return []
        candidates: list[tuple[str, Path]] = []
        for path in pinned_getter():
            if not is_navigable_directory(path):
                continue
            label = path.name or str(path)
            candidates.append((label, path))
        return self._normalize_entries(candidates)

    def _drives(self) -> list[tuple[str, Path]]:
        entries: list[tuple[str, Path]] = []
        if sys.platform == "win32":
            for code in range(ord("A"), ord("Z") + 1):
                drive = Path(f"{chr(code)}:/")
                if drive.exists():
                    entries.append((str(drive), drive))
            return self._normalize_entries(entries)

        entries.append(("/", Path("/")))
        for root in (Path("/Volumes"), Path("/mnt"), Path("/media")):
            if not is_navigable_directory(root):
                continue
            try:
                mounts = sorted(
                    (entry for entry in root.iterdir() if entry.is_dir()),
                    key=lambda path: path.name.casefold(),
                )
            except OSError:
                continue
            for mount in mounts:
                entries.append((mount.name, mount))
        return self._normalize_entries(entries)

    def _normalize_entries(
        self,
        entries: list[tuple[str, Path]],
    ) -> list[tuple[str, Path]]:
        normalized: list[tuple[str, Path]] = []
        seen: set[str] = set()
        for label, path in entries:
            try:
                resolved = path.expanduser().resolve()
            except OSError:
                continue
            if not is_navigable_directory(resolved):
                continue
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            normalized.append((label, resolved))
        return normalized

    def _match_depth(self, candidate: Path) -> int:
        current = self._current_path
        if current is None:
            return -1
        try:
            current.relative_to(candidate)
        except ValueError:
            return -1
        return len(candidate.parts)

    @classmethod
    def _truncate_label(cls, label: str) -> str:
        if len(label) <= cls.LABEL_MAX_WIDTH:
            return label
        if cls.LABEL_MAX_WIDTH <= 3:
            return label[: cls.LABEL_MAX_WIDTH]
        return f"{label[: cls.LABEL_MAX_WIDTH - 3]}..."
