from textual.widgets import Static


class TaskStatusIndicator(Static):
    """Displays a minimal task completion indicator."""

    def __init__(self, id: str | None = None) -> None:
        super().__init__("", id=id or "task_status")
        self._completed = 0
        self._total = 0
        self.update_counts(0, 0)

    def update_counts(self, completed: int, total: int) -> None:
        self._completed = completed
        self._total = total
        self.update(f"✓ {completed} / {total}")

    @property
    def totals(self) -> tuple[int, int]:
        return self._completed, self._total
