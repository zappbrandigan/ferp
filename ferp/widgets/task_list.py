from __future__ import annotations

from datetime import datetime
from typing import Sequence

from rich.markup import escape
from textual import on
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import (
    Footer,
    Input,
    Label,
    ListItem,
    ListView,
    LoadingIndicator,
    Static,
)

from ferp.core.task_store import Task as TodoTask
from ferp.core.task_store import TaskStore
from ferp.widgets.dialogs import ConfirmDialog
from ferp.widgets.task_capture import TaskCaptureModal


class TaskEditModal(ModalScreen[str | None]):
    """Modal editor used for updating an existing task."""

    BINDINGS = [
        Binding("escape", "close", "Cancel", show=True),
        Binding("enter", "submit", "Update", show=True),
    ]

    def __init__(self, initial_text: str) -> None:
        super().__init__()
        self._initial_text = initial_text
        self._area: Input | None = None
        self._status: Static | None = None
        self._clear_timer: Timer | None = None

    def compose(self):
        self._area = Input(id="task_edit_input", placeholder="Edit task")
        self._status = Static("", classes="task_edit_status")
        yield Container(
            Vertical(self._area, self._status, Footer()), id="task_edit_modal"
        )

    def on_mount(self) -> None:
        area = self.query_one(Input)
        container = self.query_one("#task_edit_modal", Container)
        container.border_title = "Edit Task"
        area.value = self._initial_text
        area.focus()
        self._area = area

    @on(Input.Submitted, "#task_edit_input")
    def _handle_submit(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_submit()

    def action_submit(self) -> None:
        area = self._area or self.query_one(Input)
        text = area.value.strip()
        if not text:
            self._set_status("[red]Task text required[/red]")
            return
        self._set_status("")
        self.dismiss(text)

    def action_close(self) -> None:
        self.dismiss(None)

    def _set_status(self, message: str) -> None:
        if self._status is None:
            return
        self._status.update(message)
        if self._clear_timer:
            self._clear_timer.stop()
            self._clear_timer = None
        if message:
            self._clear_timer = self.set_timer(1.5, self._clear_status)

    def _clear_status(self) -> None:
        if self._status:
            self._status.update("")
        if self._clear_timer:
            self._clear_timer.stop()
            self._clear_timer = None


class TaskListItem(ListItem):
    """Visual row representing a task."""

    def __init__(self, task: TodoTask) -> None:
        self._task_model = task
        self._highlighted = False
        classes = ["task_item"]
        if task.completed:
            classes.append("task_item--completed")
        elif self._is_priority(task):
            classes.append("task_item--priority")

        self._text_widget = Label("", classes="task_item_text", markup=True)
        self._meta_widget = Label("", classes="task_item_meta")

        super().__init__(
            Horizontal(
                self._text_widget,
                self._meta_widget,
            ),
            classes=" ".join(classes),
        )

    def on_mount(self) -> None:
        self._text_widget.update(
            self._render_text_markup(self._task_model, highlighted=False)
        )
        self._meta_widget.update(self._render_meta(self._task_model))

    def update_task(self, task: TodoTask) -> None:
        self._task_model = task
        self.set_class(task.completed, "task_item--completed")
        self.set_class(
            not task.completed and self._is_priority(task),
            "task_item--priority",
        )
        self._text_widget.update(
            self._render_text_markup(self._task_model, highlighted=self._highlighted)
        )
        self._meta_widget.update(self._render_meta(self._task_model))

    def set_highlighted(self, highlighted: bool) -> None:
        if self._highlighted == highlighted:
            return
        self._highlighted = highlighted
        self._text_widget.update(
            self._render_text_markup(self._task_model, highlighted=highlighted)
        )

    @property
    def task_model(self) -> TodoTask:
        return self._task_model

    @staticmethod
    def _is_priority(task: TodoTask) -> bool:
        stripped = task.text.lstrip()
        return stripped.startswith("!") or stripped.startswith("[!]")

    @staticmethod
    def _render_text_markup(task: TodoTask, *, highlighted: bool) -> str:
        tokens = task.text.split()
        if not tokens:
            return "[i dim](no text)[/]"

        tag_color = "$text" if highlighted else "$primary"
        parts: list[str] = []
        for token in tokens:
            safe = escape(token)
            if token.startswith("@") and len(token) > 1:
                parts.append(f"[i {tag_color}]{safe}[/]")
            else:
                parts.append(safe)

        text = " ".join(parts)
        if task.completed:
            return f"[strike dim]{text}[/]"
        if TaskListItem._is_priority(task):
            return f"[bold]{text}[/]"
        return text

    @staticmethod
    def _render_meta(task: TodoTask) -> str:
        stamp = task.completed_at or task.created_at
        label = "done" if task.completed else "added"
        return f"{label} {TaskListItem._format_timestamp(stamp)}"

    @staticmethod
    def _format_timestamp(stamp: datetime) -> str:
        local = stamp.astimezone()
        return local.strftime("%b %d %H:%M")


class TaskListScreen(ModalScreen[None]):
    """Full-screen list of tasks with keyboard interactions."""

    BINDINGS = [
        Binding("escape", "close", "Close", show=True),
        Binding("q", "close", "Close", show=False),
        Binding("space", "toggle_task", "Toggle completion", show=True),
        Binding("delete", "delete_task", "Delete task", show=True),
        Binding("e", "edit_task", "Edit task", show=True),
        Binding("t", "capture_task", "Add task", show=True),
        Binding("j", "cursor_down", "Next", show=False),
        Binding("k", "cursor_up", "Previous", show=False),
        Binding("/", "focus_filter", "Filter tags", show=True),
        Binding("C", "clear_completed", "Clear completed", show=True),
    ]

    def __init__(self, store: TaskStore) -> None:
        super().__init__()
        self._store = store
        self._subscription_registered = False
        self._refresh_timer: Timer | None = None
        self._index_assignment_token = 0
        self._filter_input: Input | None = None
        self._active_tag_filter: set[str] = set()
        self._pending_focus_list = True
        self._highlighted_item: TaskListItem | None = None

    def compose(self):
        placeholder = ListItem(
            LoadingIndicator(),
            classes="task_item--loading",
        )
        placeholder.disabled = True
        filter_input = Input(
            id="task_filter_input",
            placeholder="Filter by tags (e.g. @kenny, @cbs)",
        )
        self._filter_input = filter_input
        yield Container(
            Vertical(
                Container(filter_input, id="task_filter_container"),
                ListView(placeholder, id="task_list_view"),
                Footer(),
            ),
            id="task_list_modal",
        )

    def on_mount(self) -> None:
        list_view = self.query_one(ListView)
        list_view.border_title = "Tasks"
        list_view.focus()
        if self._filter_input is None:
            self._filter_input = self.query_one("#task_filter_input", Input)
        if not self._subscription_registered:
            self._store.subscribe(self._handle_store_update)
            self._subscription_registered = True

    def on_show(self) -> None:
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer = None
        self._refresh_task_list(focus_list=True)

    def on_unmount(self) -> None:
        if self._subscription_registered:
            self._store.unsubscribe(self._handle_store_update)
            self._subscription_registered = False
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer = None

    def _handle_store_update(self, _: Sequence[TodoTask]) -> None:
        self._schedule_refresh()

    def _schedule_refresh(
        self, *, focus_list: bool = True, delay: float = 0.05
    ) -> None:
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer = None
        self._pending_focus_list = focus_list
        self._refresh_timer = self.set_timer(
            delay, self._run_scheduled_refresh, name="task-list-refresh"
        )

    def _run_scheduled_refresh(self) -> None:
        self._refresh_timer = None
        self._refresh_task_list(focus_list=self._pending_focus_list)

    def _refresh_task_list(self, *, focus_list: bool = True) -> None:
        list_view = self.query_one(ListView)

        tasks = self._apply_tag_filter(self._store.sorted())
        if not tasks:
            list_view.index = None
            list_view.clear()
            self._highlighted_item = None
            placeholder_message = "No tasks yet"
            if self._active_tag_filter:
                placeholder_message = "No tasks match selected tags"
            placeholder = ListItem(
                Label(placeholder_message, classes="task_item_text"),
                classes="task_item task_item--empty",
            )
            placeholder.disabled = True
            list_view.append(placeholder)
            self._queue_index_assignment(list_view, None, focus_list=focus_list)
            return

        reusable_items = self._reuse_items_if_possible(list_view, tasks)
        if reusable_items is not None:
            for item, task in zip(reusable_items, tasks):
                item.update_task(task)
            if focus_list:
                list_view.focus()
            return

        list_view.index = None
        list_view.clear()
        self._highlighted_item = None
        for task in tasks:
            list_view.append(TaskListItem(task))
        self._queue_index_assignment(list_view, 0, focus_list=focus_list)

    def _selected_task(self) -> TodoTask | None:
        list_view = self.query_one(ListView)
        item = list_view.highlighted_child
        if isinstance(item, TaskListItem):
            return item.task_model
        return None

    @on(ListView.Highlighted, "#task_list_view")
    def _handle_highlighted(self, event: ListView.Highlighted) -> None:
        item = event.item
        if self._highlighted_item is not None and self._highlighted_item is not item:
            self._highlighted_item.set_highlighted(False)
            self._highlighted_item = None

        if isinstance(item, TaskListItem):
            self._highlighted_item = item
            item.set_highlighted(True)

    def _queue_index_assignment(
        self, list_view: ListView, target: int | None, *, focus_list: bool = True
    ) -> None:
        self._index_assignment_token += 1
        token = self._index_assignment_token

        def assign(idx=target, token=token) -> None:
            if token != self._index_assignment_token:
                return
            self._apply_index(list_view, idx)
            if focus_list:
                list_view.focus()

        list_view.call_after_refresh(assign)

    def action_cursor_down(self) -> None:
        list_view = self.query_one(ListView)
        if not self._has_selectable_items(list_view):
            return
        list_view.action_cursor_down()

    def action_cursor_up(self) -> None:
        list_view = self.query_one(ListView)
        if not self._has_selectable_items(list_view):
            return
        list_view.action_cursor_up()

    def _apply_index(self, list_view: ListView, target: int | None) -> None:
        children = list_view.children
        if not children or target is None:
            list_view.index = None
            return
        if not self._has_selectable_items(list_view):
            list_view.index = None
            return
        clamped = max(0, min(target, len(children) - 1))
        child = children[clamped]
        if getattr(child, "disabled", False):
            list_view.index = None
            return
        list_view.index = clamped

    def _has_selectable_items(self, list_view: ListView) -> bool:
        return any(
            not getattr(child, "disabled", False) for child in list_view.children
        )

    def _reuse_items_if_possible(
        self, list_view: ListView, tasks: list[TodoTask]
    ) -> list[TaskListItem] | None:
        items: list[TaskListItem] = []
        for child in list_view.children:
            if not isinstance(child, TaskListItem):
                return None
            items.append(child)
        if len(items) != len(tasks):
            return None
        if any(item.task_model.id != task.id for item, task in zip(items, tasks)):
            return None
        return items

    def action_capture_task(self) -> None:
        def handle_submit(text: str) -> None:
            try:
                self._store.add(text)
            except ValueError:
                self.app.bell()

        self.app.push_screen(TaskCaptureModal(handle_submit))

    def action_toggle_task(self) -> None:
        task = self._selected_task()
        if task:
            self._store.toggle(task.id)

    def action_delete_task(self) -> None:
        task = self._selected_task()
        if task:
            self._store.delete(task.id)

    def action_edit_task(self) -> None:
        task = self._selected_task()
        if not task:
            return

        def after(result: str | None) -> None:
            if result is None:
                return
            self._store.update_text(task.id, result)

        self.app.push_screen(TaskEditModal(task.text), after)

    def action_clear_completed(self) -> None:
        if not any(task.completed for task in self._store.all()):
            return

        def after(choice: bool | None) -> None:
            if choice:
                self._store.clear_completed()

        self.app.push_screen(ConfirmDialog("Clear all completed tasks?"), after)

    def action_close(self) -> None:
        self.dismiss(None)

    def action_focus_filter(self) -> None:
        field = self._filter_input or self.query_one("#task_filter_input", Input)
        field.focus()
        field.cursor_position = len(field.value)

    def _apply_tag_filter(self, tasks: list[TodoTask]) -> list[TodoTask]:
        if not self._active_tag_filter:
            return tasks
        return [task for task in tasks if self._task_matches_filter(task)]

    def _task_matches_filter(self, task: TodoTask) -> bool:
        task_tags = self._extract_tags(task.text)
        for filter_tag in self._active_tag_filter:
            if not self._tag_fuzzy_match(filter_tag, task_tags):
                return False
        return True

    @staticmethod
    def _tag_fuzzy_match(filter_tag: str, task_tags: set[str]) -> bool:
        query = filter_tag.lower()
        for tag in task_tags:
            if query in tag:
                return True
        return False

    @staticmethod
    def _extract_tags(text: str) -> set[str]:
        tags: set[str] = set()
        for token in text.split():
            if token.startswith("@") and len(token) > 1:
                tags.add(token.lower())
        return tags

    @on(Input.Changed, "#task_filter_input")
    def _handle_filter_changed(self, event: Input.Changed) -> None:
        event.stop()
        self._active_tag_filter = self._extract_tags(event.value)
        self._schedule_refresh(focus_list=False, delay=0.15)
