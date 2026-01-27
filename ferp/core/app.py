from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from platformdirs import user_cache_path, user_config_path, user_data_path
from rich.markup import escape
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.theme import Theme
from textual.widgets import Footer
from textual.worker import Worker, WorkerState

from ferp import __version__
from ferp.core.bundle_installer import ScriptBundleInstaller
from ferp.core.command_provider import FerpCommandProvider
from ferp.core.dependency_manager import ScriptDependencyManager
from ferp.core.fs_controller import FileSystemController
from ferp.core.fs_watcher import FileTreeWatcher
from ferp.core.messages import (
    CreatePathRequest,
    DeletePathRequest,
    DirectorySelectRequest,
    HighlightRequest,
    NavigateRequest,
    RenamePathRequest,
    RunScriptRequest,
    ShowReadmeRequest,
)
from ferp.core.path_actions import PathActionController
from ferp.core.paths import APP_AUTHOR, APP_NAME, SCRIPTS_REPO_URL
from ferp.core.script_controller import ScriptLifecycleController
from ferp.core.script_runner import ScriptResult
from ferp.core.settings_store import SettingsStore
from ferp.core.state import AppStateStore, FileTreeStateStore, TaskListStateStore
from ferp.core.task_store import Task, TaskStore
from ferp.core.transcript_logger import TranscriptLogger
from ferp.fscp.host.process_registry import ProcessRecord
from ferp.services.file_listing import (
    DirectoryListingResult,
    collect_directory_listing,
    snapshot_directory,
)
from ferp.services.monday_sync import sync_monday_board
from ferp.services.releases import update_scripts_from_release
from ferp.services.scripts import build_execution_context
from ferp.themes.themes import ALL_THEMES
from ferp.widgets.dialogs import ConfirmDialog, InputDialog
from ferp.widgets.file_tree import FileTree, FileTreeFilterWidget
from ferp.widgets.output_panel import ScriptOutputPanel
from ferp.widgets.process_list import ProcessListScreen
from ferp.widgets.readme_modal import ReadmeScreen
from ferp.widgets.scripts import ScriptManager
from ferp.widgets.task_list import TaskListScreen
from ferp.widgets.top_bar import TopBar


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


@dataclass(frozen=True)
class DeletePathResult:
    target: Path
    error: str | None = None


DEFAULT_SETTINGS: dict[str, Any] = {
    "userPreferences": {"theme": "slate-copper", "startupPath": str(Path().home())},
    "logs": {"maxFiles": 50, "maxAgeDays": 14},
    "integrations": {
        "monday": {
            "apiToken": "",
            "boardId": "9752384724",
        }
    },
}


class Ferp(App):
    TITLE = "ferp"
    CSS_PATH = Path(__file__).parent.parent / "styles" / "index.tcss"
    COMMANDS = App.COMMANDS | {FerpCommandProvider}

    BINDINGS = [
        Binding(
            "l", "show_task_list", "Show tasks", show=False, tooltip="Show task list"
        ),
        Binding(
            "t", "capture_task", "Add task", show=False, tooltip="Capture new task"
        ),
        Binding(
            "m",
            "toggle_maximize",
            "Maximize",
            show=False,
            tooltip="Maximize/minimize the focused widget",
        ),
        Binding(
            "?",
            "toggle_help",
            "Toggle all keys",
            show=True,
            tooltip="Show/hide help panel",
        ),
    ]

    @property
    def current_path(self) -> Path:
        value = self.state_store.state.current_path
        return Path(value) if value else Path()

    @current_path.setter
    def current_path(self, value: Path) -> None:
        self.state_store.set_current_path(str(value))

    def __init__(self, start_path: Path | None = None) -> None:
        self._paths = self._prepare_paths()
        self.app_root = self._paths.app_root
        self.settings_store = SettingsStore(self._paths.settings_file)
        self.settings = self.settings_store.load()
        self.state_store = AppStateStore()
        initial_path = self._resolve_start_path(start_path)
        self.state_store.set_current_path(str(initial_path))
        self.file_tree_store = FileTreeStateStore()
        self.task_list_store = TaskListStateStore()
        self.scripts_dir = self._paths.scripts_dir
        self.task_store = TaskStore(self._paths.tasks_file)
        self._pending_task_totals: tuple[int, int] = (0, 0)
        self._directory_listing_token = 0
        self._listing_in_progress = False
        self._pending_navigation_path: Path | None = None
        self._pending_refresh = False
        self._task_list_screen: TaskListScreen | None = None
        self._process_list_screen: ProcessListScreen | None = None
        super().__init__()
        self.fs_controller = FileSystemController()
        self._file_tree_watcher = FileTreeWatcher(
            call_from_thread=self.call_from_thread,
            refresh_callback=self._refresh_listing_from_watcher,
            missing_callback=self._handle_missing_directory,
            snapshot_func=snapshot_directory,
            timer_factory=self.set_timer,
        )
        self.script_controller = ScriptLifecycleController(self)
        self.transcript_logger = TranscriptLogger(
            self._paths.logs_dir,
            lambda: self.settings_store.log_preferences(self.settings),
        )
        self.bundle_installer = ScriptBundleInstaller(self)
        self.path_actions = PathActionController(
            present_input=self._present_input_dialog,
            present_confirm=self._present_confirm_dialog,
            show_error=self.show_error,
            refresh_listing=self.refresh_listing,
            fs_controller=self.fs_controller,
            delete_handler=self._start_delete_path,
        )

    def _prepare_paths(self) -> AppPaths:
        app_root = Path(__file__).parent.parent
        config_dir = Path(user_config_path(APP_NAME, APP_AUTHOR))
        dev_config_enabled = os.environ.get("FERP_DEV_CONFIG") == "1"
        config_file = (
            app_root / "scripts" / "config.json"
            if dev_config_enabled
            else config_dir / "config.json"
        )
        settings_file = config_dir / "settings.json"
        data_dir = Path(user_data_path(APP_NAME, APP_AUTHOR))
        cache_dir = Path(user_cache_path(APP_NAME, APP_AUTHOR))
        logs_dir = data_dir / "logs"
        tasks_file = cache_dir / "tasks.json"
        scripts_dir = app_root / "scripts"

        for directory in (config_dir, data_dir, cache_dir, logs_dir, scripts_dir):
            directory.mkdir(parents=True, exist_ok=True)

        default_config_file = app_root / "scripts" / "config.json"

        if not config_file.exists() and not dev_config_enabled:
            if default_config_file.exists():
                config_file.write_text(
                    default_config_file.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            else:
                config_file.write_text(
                    json.dumps({"scripts": []}, indent=2) + "\n",
                    encoding="utf-8",
                )
        if not tasks_file.exists():
            tasks_file.write_text("[]", encoding="utf-8")
        if not settings_file.exists():
            settings_file.write_text(
                json.dumps(DEFAULT_SETTINGS, indent=4),
                encoding="utf-8",
            )

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

    def resolve_startup_path(self) -> Path:
        return self._resolve_start_path(None)

    def compose(self) -> ComposeResult:
        output_panel = ScriptOutputPanel(state_store=self.state_store)
        scroll_container = VerticalScroll(
            output_panel, can_focus=True, id="output_panel_container", can_maximize=True
        )
        scroll_container.border_title = "Process Output"
        yield TopBar(
            app_title=Ferp.TITLE,
            app_version=__version__,
            state_store=self.state_store,
        )
        with Vertical(id="app_main_container"):
            yield Horizontal(
                FileTree(id="file_list", state_store=self.file_tree_store),
                Vertical(
                    ScriptManager(
                        self._paths.config_file,
                        scripts_root=self._paths.scripts_dir,
                        id="scripts_panel",
                    ),
                    scroll_container,
                    id="details_pane",
                ),
                id="main_pane",
            )
            yield FileTreeFilterWidget(
                id="file_tree_filter",
                state_store=self.file_tree_store,
            )
        yield Footer(id="app_footer")

    def on_mount(self) -> None:
        for theme in ALL_THEMES:
            self.register_theme(theme)
        self.console.set_window_title("FERP")
        self.theme_changed_signal.subscribe(self, self.on_theme_changed)
        self.theme = self.settings.get("userPreferences", {}).get(
            "theme", "textual-dark"
        )
        self.state_store.set_current_path(str(self.current_path))
        self.state_store.set_status("Ready")
        self.update_cache_timestamp()
        self.refresh_listing()
        file_tree = self.query_one("#file_list", FileTree)
        file_tree.index = 1
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
                if not bundle_path.is_absolute():
                    bundle_path = (self.current_path / bundle_path).resolve()
            except Exception as exc:
                self.notify(f"{exc}", severity="error", timeout=4)
                return
            if not bundle_path.exists():
                self.notify(
                    f"No bundle found at {bundle_path}",
                    severity="error",
                    timeout=4,
                )
                return
            if not bundle_path.is_file():
                self.notify(
                    f"Bundle path must point to a file: {bundle_path}",
                    severity="error",
                    timeout=4,
                )
                return
            if bundle_path.suffix.lower() != ".ferp":
                self.notify(
                    "Bundles must be supplied as .ferp archives.",
                    severity="error",
                    timeout=4,
                )
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
            self.notify("No log files found.", severity="error", timeout=3)
            return

        try:
            latest = max(candidates, key=lambda entry: entry.stat().st_mtime)
        except OSError as exc:
            self.notify(f"{exc}", severity="error", timeout=3)
            return

        try:
            if sys.platform == "darwin":
                subprocess.run(["open", str(latest)], check=False)
            elif sys.platform == "win32":
                subprocess.run(["cmd", "/c", "start", "", str(latest)], check=False)
            else:
                subprocess.run(["xdg-open", str(latest)], check=False)
        except Exception as exc:
            self.notify(f"{exc}", severity="error", timeout=3)

    def _command_open_user_guide(self) -> None:
        guide_path = self.app_root / "resources" / "USERS_GUIDE.md"
        if not guide_path.exists():
            self.notify("User guide not found.", severity="error", timeout=3)
            return
        try:
            content = guide_path.read_text(encoding="utf-8")
        except Exception as exc:
            self.notify(f"{exc}", severity="error", timeout=3)
            return
        screen = ReadmeScreen("FERP User Guide", content, id="readme_screen")
        self.push_screen(screen)

    def _command_show_processes(self) -> None:
        self._ensure_process_list_screen()
        self.push_screen("process_list")

    def _command_set_startup_directory(self) -> None:
        prompt = "Startup directory"
        preferences = self.settings.get("userPreferences", {})
        default_value = str(preferences.get("startupPath") or self.current_path)

        def after(value: str | None) -> None:
            if not value:
                return
            try:
                path = Path(value).expanduser()
                if not path.is_absolute():
                    path = (self.current_path / path).resolve()
            except Exception as exc:
                self.notify(f"{exc}", severity="error", timeout=3)
                return
            if not path.exists() or not path.is_dir():
                self.notify(
                    f"{path} is not a valid directory.", severity="error", timeout=3
                )
                return
            self.settings_store.update_startup_path(self.settings, path)
            self.notify(f"Startup directory updated: {path}", timeout=3)

        self.push_screen(InputDialog(prompt, default=default_value), after)

    def _command_install_default_scripts(self) -> None:
        prompt = (
            "Replace your script catalog with the default FERP scripts?\n"
            "This will overwrite config.json and fully replace scripts/ from the latest release."
        )

        def after(value: bool | None) -> None:
            if not value:
                return
            dev_config_enabled = os.environ.get("FERP_DEV_CONFIG") == "1"
            if dev_config_enabled:
                self.notify("Updating default scripts (dry run)...", timeout=5)
            else:
                self.notify("Updating default scripts...", timeout=5)
            self.run_worker(
                self._install_default_scripts,
                group="default_scripts_update",
                exclusive=True,
                thread=True,
            )

        self.push_screen(ConfirmDialog(prompt), after)

    def _command_sync_monday_board(self) -> None:
        monday_settings = self.settings.get("integrations", {}).get("monday", {})
        token = str(monday_settings.get("apiToken") or "").strip()
        board_id = monday_settings.get("boardId")
        try:
            board_id_value = int(board_id)
        except (TypeError, ValueError):
            self.notify(
                "Monday board id missing. Set integrations.monday.boardId in settings.json.",
                severity="error",
                timeout=4,
            )
            return

        def start_sync(api_token: str) -> None:
            self.notify("Syncing Monday board...", timeout=5)
            self.run_worker(
                lambda token=api_token, board=board_id_value: self._sync_monday_board(
                    token, board
                ),
                group="monday_sync",
                exclusive=True,
                thread=True,
            )

        if not token:
            prompt = "Monday API token"

            def after(value: str | None) -> None:
                if not value:
                    return
                token_value = value.strip()
                if not token_value:
                    return
                self.settings.setdefault("integrations", {}).setdefault("monday", {})[
                    "apiToken"
                ] = token_value
                self.settings_store.save(self.settings)
                start_sync(token_value)

            self.push_screen(InputDialog(prompt), after)
            return

        start_sync(token)

    def _install_default_scripts(self) -> dict[str, str | bool]:
        try:
            dev_config_enabled = os.environ.get("FERP_DEV_CONFIG") == "1"
            release_version = update_scripts_from_release(
                SCRIPTS_REPO_URL, self.scripts_dir, dry_run=dev_config_enabled
            )

            if dev_config_enabled:
                return {
                    "release_status": "Default scripts update skipped (dry run).",
                    "release_detail": "FERP_DEV_CONFIG=1; no files were modified.",
                    "release_version": release_version,
                }

            scripts_config_file = self.scripts_dir / "config.json"
            if not scripts_config_file.exists():
                raise FileNotFoundError(
                    f"No default config found at {scripts_config_file}"
                )

            if scripts_config_file.resolve() != self._paths.config_file.resolve():
                self._paths.config_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(scripts_config_file, self._paths.config_file)
                config_status = "Updated user config from bundled defaults."
            else:
                config_status = "Default config already in use; skipping copy."

            dependency_manager = ScriptDependencyManager(
                self._paths.config_file, python_executable=sys.executable
            )
            dependency_manager.install_for_scripts()
        except Exception as exc:
            return {
                "error": str(exc),
                "release_status": "Default scripts update failed.",
            }

        return {
            "config_path": str(self._paths.config_file),
            "release_status": "Scripts updated to latest release.",
            "release_detail": config_status,
            "release_version": release_version,
        }

    def _sync_monday_board(self, api_token: str, board_id: int) -> dict[str, object]:
        cache_path = self._paths.cache_dir / "publishers_cache.json"
        try:
            return sync_monday_board(api_token, board_id, cache_path)
        except Exception as exc:
            return {"error": str(exc)}

    def _request_process_abort(self, record: ProcessRecord) -> bool:
        active_handle = self.script_controller.active_process_handle
        if not active_handle or record.handle != active_handle:
            return False
        return self.script_controller.request_abort(
            "Termination requested from process list."
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
        self._request_navigation(event.path)

    @on(DirectorySelectRequest)
    def handle_directory_selection(self, event: DirectorySelectRequest) -> None:
        self._request_navigation(event.path)

    @on(HighlightRequest)
    def handle_highlight(self, event: HighlightRequest) -> None:
        self.state_store.set_highlighted_path(event.path)

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

        screen = ReadmeScreen(event.script.name, content, id="readme_screen")
        self.push_screen(screen)

    @on(RunScriptRequest)
    def handle_script_run(self, event: RunScriptRequest) -> None:
        if self.script_controller.is_running:
            return  # ignore silently for now

        try:
            context = build_execution_context(
                app_root=self.app_root,
                current_path=self.current_path,
                highlighted_path=self.state_store.state.highlighted_path,
                script=event.script,
            )
            self.script_controller.run_script(event.script, context)
        except Exception as e:
            self.state_store.update_script_run(
                phase="error",
                script_name=event.script.name,
                target_path=self.current_path,
                input_prompt=None,
                progress_message="",
                progress_line="",
                progress_current=None,
                progress_total=None,
                progress_unit="",
                result=None,
                transcript_path=None,
                error=str(e),
            )

    def render_script_output(
        self,
        script_name: str,
        result: ScriptResult,
    ) -> None:
        target = self.script_controller.active_target or self.current_path

        transcript_path = None
        if result.transcript:
            transcript_path = self.transcript_logger.write(
                script_name,
                target,
                result,
            )

        self.state_store.update_script_run(
            phase="result",
            script_name=script_name,
            target_path=target,
            input_prompt=None,
            progress_message="",
            progress_line="",
            progress_current=None,
            progress_total=None,
            progress_unit="",
            result=result,
            transcript_path=transcript_path,
            error=None,
        )

    def on_exit(self) -> None:
        self._stop_file_tree_watch()

    def show_error(self, error: BaseException) -> None:
        self.notify(f"{error}", severity="error", timeout=4)

    def _start_delete_path(self, target: Path) -> None:
        file_tree = self.query_one(FileTree)
        file_tree.set_pending_delete_index(file_tree.index)
        label = target.name or str(target)
        self.notify(f"Deleting '{escape(label)}'...", timeout=2)
        self._stop_file_tree_watch()
        self.run_worker(
            lambda: self._delete_path_worker(target),
            group="delete_path",
            thread=True,
        )

    def _delete_path_worker(self, target: Path) -> DeletePathResult:
        try:
            self.fs_controller.delete_path(target)
        except OSError as exc:
            return DeletePathResult(target=target, error=str(exc))
        return DeletePathResult(target=target, error=None)

    def _render_default_scripts_update(self, payload: dict[str, Any]) -> None:
        error = payload.get("error")
        if error:
            self.notify(
                f"Default scripts update failed: {error}",
                severity="error",
                timeout=4,
            )
            return
        config_path = payload.get("config_path", "")
        release_status = payload.get("release_status", "")
        release_detail = payload.get("release_detail", "")
        release_version = payload.get("release_version", "")

        summary = "Default scripts updated."
        if release_version:
            summary = f"{summary} {release_version}"
        if release_status:
            summary = f"{summary} ({release_status})"
        if config_path:
            summary = f"{summary} Config: {config_path}"
        if release_detail:
            summary = f"{summary} {release_detail}"
        self.notify(summary, timeout=4)

        scripts_panel = self.query_one(ScriptManager)
        scripts_panel.load_scripts()

    def _render_monday_sync(self, payload: dict[str, Any]) -> None:
        error = payload.get("error")
        if error:
            self.notify(
                f"Monday sync failed: {escape(str(error))}",
                severity="error",
                timeout=4,
            )
            return
        board_name = payload.get("board_name", "")
        group_count = payload.get("group_count", 0)
        publisher_count = payload.get("publisher_count", 0)
        skipped = payload.get("skipped", 0)

        details = (
            f"\nGroups {group_count}\nPublishers {publisher_count}\nSkipped {skipped}"
        )
        title = (
            f"Monday sync updated ({escape(str(board_name))})"
            if board_name
            else "Monday sync updated"
        )
        self.notify(f"{title}. {details}", timeout=5)
        self.update_cache_timestamp()

    def refresh_listing(self) -> None:
        if self._listing_in_progress:
            self._pending_refresh = True
            return

        self._listing_in_progress = True
        self.state_store.set_current_path(str(self.current_path))

        file_tree = self.query_one(FileTree)
        file_tree.show_loading(self.current_path)

        self._directory_listing_token += 1
        token = self._directory_listing_token
        path = self.current_path

        self.run_worker(
            lambda directory=path, token=token: collect_directory_listing(
                directory, token
            ),
            group="directory_listing",
            exclusive=True,
            thread=True,
        )

    def _refresh_listing_from_watcher(self) -> None:
        if self._listing_in_progress:
            return
        self.refresh_listing()

    def _handle_directory_listing_result(self, result: DirectoryListingResult) -> None:
        if result.token != self._directory_listing_token:
            return

        file_tree = self.query_one(FileTree)
        if result.error:
            if not result.path.exists():
                self._handle_missing_directory(result.path)
                self._finalize_directory_listing()
                return
            file_tree.show_error(
                result.path, f"Unable to load directory: {result.error}"
            )
            self._finalize_directory_listing()
            return

        file_tree.show_listing(result.path, result.entries)

        if self._file_tree_watcher is not None:
            self._file_tree_watcher.update_snapshot(result.path)
            self._start_file_tree_watch()
        self._finalize_directory_listing()

    def _finalize_directory_listing(self) -> None:
        self._listing_in_progress = False
        pending_path = self._pending_navigation_path
        if pending_path is not None:
            self._pending_navigation_path = None
            self._begin_navigation(pending_path)
            return
        if self._pending_refresh:
            self._pending_refresh = False
            self.refresh_listing()

    def _request_navigation(self, path: Path) -> None:
        if not path.exists() or not path.is_dir():
            if not self.current_path.exists():
                self._handle_missing_directory(self.current_path)
            return
        if self._listing_in_progress:
            self._pending_navigation_path = path
            return
        self._begin_navigation(path)

    def _handle_missing_directory(self, missing: Path) -> None:
        target = self._nearest_existing_parent(missing)
        if target is None:
            target = self.resolve_startup_path()

        if target.exists() and target != self.current_path:
            self.notify(
                f"Directory removed. Jumped to '{escape(str(target))}'.",
                timeout=3,
            )

        if self._listing_in_progress:
            self._pending_navigation_path = target
            return

        self._begin_navigation(target)

    def _nearest_existing_parent(self, missing: Path) -> Path | None:
        candidate = missing
        while True:
            parent = candidate.parent
            if parent == candidate:
                return None
            if parent.exists():
                return parent
            candidate = parent

    def _begin_navigation(self, path: Path) -> None:
        self._pending_navigation_path = None
        self._pending_refresh = False
        self.current_path = path
        self.state_store.set_current_path(str(self.current_path))
        self._stop_file_tree_watch()
        self.refresh_listing()

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

    def action_capture_task(self) -> None:
        screen = self._ensure_task_list_screen()
        screen.action_capture_task()

    def action_show_task_list(self) -> None:
        self._ensure_task_list_screen()
        self.push_screen("task_list")

    def _ensure_task_list_screen(self) -> TaskListScreen:
        if self._task_list_screen is None:
            screen = TaskListScreen(self.task_store, state_store=self.task_list_store)
            self.install_screen(screen, name="task_list")
            self._task_list_screen = screen
        return self._task_list_screen

    def _ensure_process_list_screen(self) -> ProcessListScreen:
        if self._process_list_screen is None:
            screen = ProcessListScreen(
                self.script_controller.process_registry,
                self._request_process_abort,
            )
            self.install_screen(screen, name="process_list")
            self._process_list_screen = screen
        return self._process_list_screen

    def action_toggle_help(self) -> None:
        try:
            self.screen.query_one("HelpPanel")
        except NoMatches:
            self.action_show_help_panel()
        else:
            self.action_hide_help_panel()

    def action_toggle_maximize(self) -> None:
        screen = self.screen
        if screen.maximized is not None:
            screen.action_minimize()
            return
        focused = screen.focused
        if focused is not None and focused.allow_maximize:
            screen.action_maximize()

    def update_cache_timestamp(self) -> None:
        cache_path = self._paths.cache_dir / "publishers_cache.json"

        if cache_path.exists():
            updated_at = datetime.fromtimestamp(
                cache_path.stat().st_mtime, tz=timezone.utc
            )
        else:
            updated_at = datetime(1970, 1, 1, tzinfo=timezone.utc)

        self.state_store.set_cache_updated_at(updated_at)

    @on(Worker.StateChanged)
    def _on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        worker = event.worker
        if worker.group == "directory_listing":
            if event.state is WorkerState.SUCCESS:
                result = worker.result
                if isinstance(result, DirectoryListingResult):
                    self._handle_directory_listing_result(result)
            elif event.state is WorkerState.ERROR:
                error = worker.error or RuntimeError("Directory listing failed.")
                file_tree = self.query_one(FileTree)
                file_tree.show_error(self.current_path, str(error))
                self._finalize_directory_listing()
            return
        if self.bundle_installer.handle_worker_state(event):
            return
        if self.script_controller.handle_worker_state(event):
            return
        if worker.group == "default_scripts_update":
            if event.state is WorkerState.SUCCESS:
                result = worker.result
                if isinstance(result, dict):
                    self._render_default_scripts_update(result)
            elif event.state is WorkerState.ERROR:
                error = worker.error or RuntimeError("Default script update failed.")
                self.notify(
                    f"Default scripts update failed: {error}",
                    severity="error",
                    timeout=4,
                )
            return
        if worker.group == "delete_path":
            if event.state is WorkerState.SUCCESS:
                result = worker.result
                if isinstance(result, DeletePathResult):
                    if result.error:
                        self.notify(
                            f"Delete failed: {result.error}",
                            severity="error",
                            timeout=3,
                        )
                        file_tree = self.query_one(FileTree)
                        file_tree.set_pending_delete_index(None)
                        self._start_file_tree_watch()
                        return
                    label = result.target.name or str(result.target)
                    self.notify(f"Deleted '{escape(label)}'.", timeout=3)
                    self.refresh_listing()
            elif event.state is WorkerState.ERROR:
                error = worker.error or RuntimeError("Delete failed.")
                self.notify(f"Delete failed: {error}", severity="error", timeout=3)
                file_tree = self.query_one(FileTree)
                file_tree.set_pending_delete_index(None)
                self._start_file_tree_watch()
            return
        if worker.group == "bulk_rename":
            if event.state is WorkerState.SUCCESS:
                result = worker.result
                if isinstance(result, dict):
                    errors = (
                        result.get("errors")
                        if isinstance(result.get("errors"), list)
                        else []
                    )
                    count = result.get("count", 0)
                    if errors:
                        self.notify(
                            f"Rename completed with errors ({len(errors)} issue(s)).",
                            severity="warning",
                            timeout=3,
                        )
                    else:
                        self.notify(f"Rename complete: {count} file(s).", timeout=3)
                self.refresh_listing()
            elif event.state is WorkerState.ERROR:
                error = worker.error or RuntimeError("Bulk rename failed.")
                self.notify(
                    f"Bulk rename failed: {error}", severity="warning", timeout=3
                )
                self.refresh_listing()
            return
        if worker.group == "monday_sync":
            if event.state is WorkerState.SUCCESS:
                result = worker.result
                if isinstance(result, dict):
                    self._render_monday_sync(result)
            elif event.state is WorkerState.ERROR:
                error = worker.error or RuntimeError("Monday sync failed.")
                self.notify(f"Monday sync failed: {error}", severity="error", timeout=4)
            return
