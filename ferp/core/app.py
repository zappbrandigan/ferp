from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Callable, Sequence
import subprocess
import shlex
import sys

from textual.app import App, ComposeResult
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.theme import Theme
from textual import on
from textual.binding import Binding
from textual.widgets import Footer
from textual.css.query import NoMatches

from ferp.core.messages import (
    CreatePathRequest,
    DeletePathRequest,
    DirectorySelectRequest,
    HighlightRequest,
    NavigateRequest,
    RenamePathRequest,
    RunScriptRequest,
    ShowReadmeRequest,
    ShowTerminalRequest,
    TerminalCommandRequest,
)
from ferp.widgets.file_tree import FileTree, FileListingEntry
from ferp.widgets.output_panel import ScriptOutputPanel
from ferp.widgets.scripts import ScriptManager
from ferp.widgets.readme_modal import ReadmeScreen
from ferp.widgets.terminal import TerminalWidget
from ferp.core.script_runner import ScriptResult
from ferp.core.fs_controller import FileSystemController
from ferp.core.fs_watcher import FileTreeWatcher
from ferp.core.script_controller import ScriptLifecycleController
from ferp.core.bundle_installer import ScriptBundleInstaller
from ferp.services.scripts import build_execution_context
from ferp.core.settings_store import SettingsStore
from ferp.core.transcript_logger import TranscriptLogger
from ferp.core.path_actions import PathActionController
from ferp.widgets.top_bar import TopBar
from ferp.widgets.dialogs import InputDialog, ConfirmDialog
from ferp.themes.themes import ALL_THEMES
from ferp import __version__
from ferp.widgets.process_list import ProcessListScreen

from textual.worker import Worker, WorkerState
from ferp.core.command_provider import FerpCommandProvider
from ferp.core.task_store import TaskStore, Task
from ferp.widgets.task_list import TaskListScreen
from ferp.widgets.task_status import TaskStatusIndicator
from ferp.fscp.host.process_registry import ProcessRecord


@dataclass(frozen=True)
class DirectoryListingResult:
    path: Path
    token: int
    entries: list[FileListingEntry]
    error: str | None = None


@dataclass(frozen=True)
class AppPaths:
    app_root: Path
    config_dir: Path
    config_file: Path
    settings_file: Path
    data_dir: Path
    cache_dir: Path
    logs_dir: Path
    tasks_file: Path
    scripts_dir: Path


DEFAULT_SETTINGS: dict[str, Any] = {
    "userPreferences": {
        "theme": "slate-copper",
        "startupPath": str(Path().home())
    },
    "logs": {
        "maxFiles": 50,
        "maxAgeDays": 14
    },
}


class Ferp(App):
    TITLE = "FERP"
    CSS_PATH = Path(__file__).parent.parent / "styles" / "index.tcss"
    COMMANDS = App.COMMANDS | {FerpCommandProvider}

    _INTERACTIVE_DENYLIST = {
        "vi",
        "vim",
        "nvim",
        "nano",
        "less",
        "more",
        "top",
        "htop",
        "man",
        "watch",
    }

    BINDINGS = [
        Binding("l", "show_task_list", "Show tasks", show=True),
        Binding("t", "capture_task", "Add task", show=True),
        Binding("?", "toggle_help", "Show all keys", show=True),
        # Binding("ctrl+q", "quit", "Quit the application", show=True),
    ]

    def __init__(self, start_path: Path | None = None) -> None:
        self._paths = self._prepare_paths()
        self.app_root = self._paths.app_root
        self.settings_store = SettingsStore(self._paths.settings_file)
        self.settings = self.settings_store.load()
        self.current_path = self._resolve_start_path(start_path)
        self.highlighted_path: Path | None = None
        self.scripts_dir = self._paths.scripts_dir
        self.task_store = TaskStore(self._paths.tasks_file)
        self._task_status_indicator: TaskStatusIndicator | None = None
        self._pending_task_totals: tuple[int, int] = (0, 0)
        self._directory_listing_token = 0
        super().__init__()
        self.fs_controller = FileSystemController()
        self._file_tree_watcher = FileTreeWatcher(
            call_from_thread=self.call_from_thread,
            refresh_callback=self.refresh_listing,
            snapshot_func=self._snapshot_directory,
            timer_factory=self.set_timer,
        )
        self.script_controller = ScriptLifecycleController(self)
        self.transcript_logger = TranscriptLogger(
            self.app_root,
            lambda: self.settings_store.log_preferences(self.settings),
        )
        self.bundle_installer = ScriptBundleInstaller(self)
        self.path_actions = PathActionController(
            present_input=self._present_input_dialog,
            present_confirm=self._present_confirm_dialog,
            show_error=self.show_error,
            refresh_listing=self.refresh_listing,
            fs_controller=self.fs_controller,
        )

    def _prepare_paths(self) -> AppPaths:
        app_root = Path(__file__).parent.parent
        config_dir = app_root / "config"
        config_file = config_dir / "config.json"
        settings_file = config_dir / "settings.json"
        data_dir = app_root / "data"
        cache_dir = data_dir / "cache"
        logs_dir = data_dir / "logs"
        tasks_file = cache_dir / "tasks.json"
        scripts_dir = app_root / "scripts"

        for directory in (config_dir, data_dir, cache_dir, logs_dir, scripts_dir):
            directory.mkdir(parents=True, exist_ok=True)

        if not tasks_file.exists():
            tasks_file.write_text("[]", encoding="utf-8")
        if not settings_file.exists():
            settings_file.write_text(json.dumps(DEFAULT_SETTINGS, indent=4), encoding="utf-8")

        return AppPaths(
            app_root=app_root,
            config_dir=config_dir,
            config_file=config_file,
            settings_file=settings_file,
            data_dir=data_dir,
            cache_dir=cache_dir,
            logs_dir=logs_dir,
            tasks_file=tasks_file,
            scripts_dir=scripts_dir,
        )

    def _resolve_start_path(self, start_path: Path | None) -> Path:
        def normalize(candidate: Path | str | None) -> Path | None:
            if candidate is None:
                return None
            try:
                return Path(candidate).expanduser()
            except (TypeError, ValueError):
                return None

        preferences = self.settings.get("userPreferences", {})
        candidates = [
            normalize(start_path),
            normalize(preferences.get("startupPath")),
            Path.home(),
        ]

        for candidate in candidates:
            if candidate and candidate.exists():
                return candidate

        return Path.home()

    def compose(self) -> ComposeResult:
        output_panel = ScriptOutputPanel()
        scroll_container = VerticalScroll(
            output_panel,
            can_focus=True,
            id="output_panel_container",
            can_maximize=True
        )
        scroll_container.border_title = "Process Output"
        with Vertical(id="app_main_container"):
            yield TopBar(app_title=Ferp.TITLE, app_version=__version__)
            yield Horizontal(
                FileTree(id="file_list"),
                Vertical(
                    ScriptManager(self._paths.config_file, id="scripts_panel"),
                    scroll_container,
                    id="details_pane",
                ),
                id="main_pane",
            )
            yield TaskStatusIndicator()
            yield TerminalWidget(id="terminal_widget")
        yield Footer()

    def on_mount(self) -> None:
        for theme in ALL_THEMES:
            self.register_theme(theme)
        self.console.set_window_title("FERP")
        self.theme_changed_signal.subscribe(self, self.on_theme_changed)
        self.theme = self.settings.get("userPreferences", {}).get("theme", "textual-dark")
        topbar = self.query_one(TopBar)
        topbar.current_path = str(self.current_path)
        topbar.status = "Idle"
        self.update_cache_timestamp()
        self.refresh_listing()
        file_tree = self.query_one("#file_list", FileTree)
        file_tree.index = 1
        self._start_file_tree_watch()
        self._task_status_indicator = self.query_one(TaskStatusIndicator)
        self.task_store.subscribe(self._handle_task_update)

    def on_theme_changed(self, theme: Theme) -> None:
        self.settings_store.update_theme(self.settings, theme.name)

    def _command_install_script_bundle(self) -> None:
        prompt = "Path to the script bundle (.ferp)"
        default_value = str(self.current_path)

        def after(value: str | None) -> None:
            if not value:
                return
            try:
                bundle_path = Path(value).expanduser()
            except Exception as exc:
                self.show_error(exc)
                return
            self.bundle_installer.start_install(bundle_path)

        self.push_screen(
            InputDialog(prompt, default=default_value),
            after,
        )

    def _command_refresh_file_tree(self) -> None:
        self.refresh_listing()

    def _command_reload_scripts(self) -> None:
        scripts_panel = self.query_one(ScriptManager)
        scripts_panel.load_scripts()

    def _command_open_latest_log(self) -> None:
        logs_dir = self._paths.logs_dir
        candidates = [entry for entry in logs_dir.glob("*.log") if entry.is_file()]

        if not candidates:
            self.show_error(RuntimeError("No log files found."))
            return

        try:
            latest = max(candidates, key=lambda entry: entry.stat().st_mtime)
        except OSError as exc:
            self.show_error(exc)
            return

        try:
            if sys.platform == "darwin":
                subprocess.run(["open", str(latest)], check=False)
            elif sys.platform == "win32":
                subprocess.run(["cmd", "/c", "start", "", str(latest)], check=False)
            else:
                subprocess.run(["xdg-open", str(latest)], check=False)
        except Exception as exc:
            self.show_error(exc)

    def _command_show_processes(self) -> None:
        screen = ProcessListScreen(
            self.script_controller.process_registry,
            self._request_process_abort,
        )
        self.push_screen(screen)

    def _request_process_abort(self, record: ProcessRecord) -> bool:
        active_handle = self.script_controller.active_process_handle
        if not active_handle or record.handle != active_handle:
            return False
        return self.script_controller.abort_active("Termination requested from process list.")

    @on(ShowTerminalRequest)
    def show_terminal(self, _: ShowTerminalRequest) -> None:
        terminal = self.query_one(TerminalWidget)
        terminal.show(self.current_path)

    @on(TerminalCommandRequest)
    def handle_terminal_command(self, event: TerminalCommandRequest) -> None:
        self.run_worker(
            lambda: self._execute_terminal_command(event.command, event.cwd),
            group="terminal",
            exclusive=False,
            thread=True,
        )

    def _present_input_dialog(
        self,
        dialog: InputDialog,
        callback: Callable[[str | None], None],
    ) -> None:
        self.push_screen(dialog, callback)

    def _present_confirm_dialog(
        self,
        dialog: ConfirmDialog,
        callback: Callable[[bool | None], None],
    ) -> None:
        self.push_screen(dialog, callback)

    @on(NavigateRequest)
    def handle_navigation(self, event: NavigateRequest) -> None:
        if event.path.exists() and event.path.is_dir():
            self.current_path = event.path
            self.refresh_listing()
            self._start_file_tree_watch()

    @on(DirectorySelectRequest)
    def handle_directory_selection(self, event: DirectorySelectRequest) -> None:
        path = event.path
        if path.exists() and path.is_dir():
            self.current_path = path
            self.refresh_listing()
            self._start_file_tree_watch()

    @on(HighlightRequest)
    def handle_highlight(self, event: HighlightRequest) -> None:
        if event.path:
            self.highlighted_path = event.path

    @on(CreatePathRequest)
    def handle_create_path(self, event: CreatePathRequest) -> None:
        self.path_actions.create_path(event.base, is_directory=event.is_directory)

    @on(DeletePathRequest)
    def handle_delete_path(self, event: DeletePathRequest) -> None:
        self.path_actions.delete_path(event.target)

    @on(RenamePathRequest)
    def handle_rename_path(self, event: RenamePathRequest) -> None:
        self.path_actions.rename_path(event.target)

    @on(ShowReadmeRequest)
    def show_readme(self, event: ShowReadmeRequest) -> None:
        if not event.readme_path:
            content = "_No README found for this script._"
        else:
            content = event.readme_path.read_text(encoding="utf-8")

        self.push_screen(ReadmeScreen(event.script.name, content))

    @on(RunScriptRequest)
    def handle_script_run(self, event: RunScriptRequest) -> None:
        if self.script_controller.is_running:
            return  # ignore silently for now

        try:
            context = build_execution_context(
                app_root=self.app_root,
                current_path=self.current_path,
                highlighted_path=self.highlighted_path,
                script=event.script,
            )
            self.script_controller.run_script(event.script, context)
        except Exception as e:
            self.show_error(e)
    def render_script_output(
        self,
        script_name: str,
        result: ScriptResult,
    ) -> None:
        panel = self.query_one(ScriptOutputPanel)
        target = self.script_controller.active_target or self.current_path

        transcript_path = None
        if result.transcript:
            transcript_path = self.transcript_logger.write(
                script_name,
                target,
                result,
            )

        panel.show_result(script_name, target, result, transcript_path)

    def on_exit(self) -> None:
        self._stop_file_tree_watch()

    def show_error(self, error: BaseException) -> None:
        panel = self.query_one(ScriptOutputPanel)
        panel.show_error(error)

    def _execute_terminal_command(self, command: str, cwd: Path) -> dict[str, object]:
        command = command.strip()
        if not command:
            return {
                "command": "",
                "cwd": str(cwd),
                "stdout": "",
                "stderr": "",
                "returncode": 0,
            }

        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = command.split()

        if tokens and tokens[0] in self._INTERACTIVE_DENYLIST:
            return {
                "command": command,
                "cwd": str(cwd),
                "stdout": "",
                "stderr": f'"{tokens[0]}" requires a full terminal. Please use your system terminal.',
                "returncode": 1,
            }

        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                shell=True,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return {
                "command": command,
                "cwd": str(cwd),
                "stdout": "",
                "stderr": "Command timed out after 30 seconds.",
                "returncode": -1,
            }

        return {
            "command": command,
            "cwd": str(cwd),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "returncode": completed.returncode,
        }

    def _render_terminal_output(self, payload: dict[str, Any]) -> None:
        panel = self.query_one(ScriptOutputPanel)
        command = payload.get("command", "")
        cwd = payload.get("cwd", "")
        stdout = payload.get("stdout", "")
        stderr = payload.get("stderr", "")
        returncode = payload.get("returncode", 0)

        lines = [
            f"[bold $primary]Command:[/bold $primary] {command}",
            f"[bold $primary]Directory:[/bold $primary] {cwd}",
            f"[bold $primary]Exit Code:[/bold $primary] {returncode}",
        ]

        if stdout:
            lines.append("\n[bold]stdout[/bold]\n" + stdout.strip())

        if stderr:
            lines.append("\n[bold $error]stderr[/bold $error]\n" + stderr.strip())

        panel.update_content("\n".join(lines))

    def refresh_listing(self) -> None:
        topbar = self.query_one(TopBar)
        topbar.current_path = str(self.current_path)

        file_tree = self.query_one(FileTree)
        file_tree.show_loading(self.current_path)

        self._directory_listing_token += 1
        token = self._directory_listing_token
        path = self.current_path

        self.run_worker(
            lambda directory=path, token=token: self._collect_directory_listing(directory, token),
            group="directory_listing",
            exclusive=True,
            thread=True,
        )

    def _collect_directory_listing(self, directory: Path, token: int) -> DirectoryListingResult:
        try:
            entries = sorted(directory.iterdir())
        except OSError as exc:
            return DirectoryListingResult(directory, token, [], str(exc))

        rows: list[FileListingEntry] = []
        for entry in entries:
            if entry.name.startswith("."):
                continue
            listing_entry = self._build_listing_entry(entry)
            if listing_entry is not None:
                rows.append(listing_entry)

        return DirectoryListingResult(directory, token, rows)

    def _build_listing_entry(self, path: Path) -> FileListingEntry | None:
        try:
            stat = path.stat()
        except OSError:
            return None

        created = datetime.strftime(datetime.fromtimestamp(stat.st_ctime), "%x %I:%S %p")
        modified = datetime.strftime(datetime.fromtimestamp(stat.st_mtime), "%x %I:%S %p")

        raw_name = path.stem if not path.is_dir() else f"{path.stem}/"
        display_name = raw_name if len(raw_name) < 80 else raw_name[:73] + "..."

        type_label = "dir" if path.is_dir() else path.suffix.lstrip(".").lower()
        if not type_label:
            type_label = "file"

        return FileListingEntry(
            path=path,
            display_name=display_name,
            char_count=len(path.stem),
            type_label=type_label,
            modified_label=modified,
            created_label=created,
            is_dir=path.is_dir(),
        )

    def _handle_directory_listing_result(self, result: DirectoryListingResult) -> None:
        if result.token != self._directory_listing_token:
            return

        file_tree = self.query_one(FileTree)
        if result.error:
            file_tree.show_error(result.path, f"Unable to load directory: {result.error}")
            return

        file_tree.show_listing(result.path, result.entries)

        if self._file_tree_watcher is not None:
            self._file_tree_watcher.update_snapshot(result.path)

    def _start_file_tree_watch(self) -> None:
        if self._file_tree_watcher is not None:
            self._file_tree_watcher.start(self.current_path)

    def _stop_file_tree_watch(self) -> None:
        if self._file_tree_watcher is not None:
            self._file_tree_watcher.stop()

    def _handle_task_update(self, tasks: Sequence[Task]) -> None:
        completed = sum(1 for task in tasks if task.completed)
        total = len(tasks)
        self._pending_task_totals = (completed, total)
        if self._task_status_indicator is not None:
            self._task_status_indicator.update_counts(completed, total)

    def action_capture_task(self) -> None:
        TaskListScreen(self.task_store).action_capture_task()

    def action_show_task_list(self) -> None:
        self.push_screen(TaskListScreen(self.task_store))

    def action_toggle_help(self) -> None:
        try:
            self.screen.query_one("HelpPanel")
        except NoMatches:
            self.action_show_help_panel()
        else:
            self.action_hide_help_panel()

    def update_cache_timestamp(self) -> None:
        cache_path = self._paths.cache_dir / "publishers_cache.json"
        assert cache_path.exists()

        if cache_path.exists():
            updated_at = datetime.fromtimestamp(cache_path.stat().st_mtime, tz=timezone.utc)
        else:
            updated_at = datetime(1970, 1, 1, tzinfo=timezone.utc)

        self.query_one(TopBar).cache_updated_at = updated_at

    def _snapshot_directory(self, path: Path) -> tuple[str, ...]:
        try:
            entries = sorted(entry.name for entry in path.iterdir())
        except OSError:
            entries = []
        return tuple(entries)

    @on(Worker.StateChanged)
    def _on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        worker = event.worker
        if worker.group == "terminal":
            if event.state is WorkerState.SUCCESS:
                result = worker.result
                if isinstance(result, dict):
                    self._render_terminal_output(result)
            elif event.state is WorkerState.ERROR:
                error = worker.error or RuntimeError("Terminal command failed.")
                self.show_error(error)
            return
        if worker.group == "directory_listing":
            if event.state is WorkerState.SUCCESS:
                result = worker.result
                if isinstance(result, DirectoryListingResult):
                    self._handle_directory_listing_result(result)
            elif event.state is WorkerState.ERROR:
                error = worker.error or RuntimeError("Directory listing failed.")
                file_tree = self.query_one(FileTree)
                file_tree.show_error(self.current_path, str(error))
            return
        if self.bundle_installer.handle_worker_state(event):
            return
        if self.script_controller.handle_worker_state(event):
            return
