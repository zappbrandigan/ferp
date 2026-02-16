<p align="center">
<img style="width: 50%" src="https://raw.githubusercontent.com/zappbrandigan/ferp/refs/heads/main/ferp/resources/ferp-logo.png">
</p>

<p align="center" style="display:flex; justify-content:center; gap:6px; flex-wrap:wrap;">
  <img alt="Release" src="https://img.shields.io/pypi/v/ferp?label=release&style=for-the-badge&color=olive">
  <img alt="Python" src="https://img.shields.io/pypi/pyversions/ferp?style=for-the-badge">
  <img alt="License" src="https://img.shields.io/pypi/l/ferp?style=for-the-badge">
  <img alt="CI" src="https://img.shields.io/github/actions/workflow/status/zappbrandigan/ferp/publish.yml?style=for-the-badge">
  <img alt="Status" src="https://img.shields.io/badge/scope-internal-orange?style=for-the-badge">
</p>


---

## About

**FERP** is a terminal-friendly file manager and automation workbench. It combines an interactive file navigator and a protocol-driven script runner so you can explore directories and execute repeatable workflows through a TUI—without requiring terminal knowledge.

## Highlights

- **Keyboard-first navigation**
  - A full list of keys are available in the app.
- **Context panes**
  - Script list reads from the user config `config.json` (platformdirs).
  - Output panel streams FSCP results and records transcripts under the user data `logs` directory.
  - README modal (Enter on a script) displays bundled documentation.
- **Visual mode (multi-select)**
  - Select multiple items in the file navigator, including range selection.
  - Copy, move, paste, and delete selected files or folders without running scripts.
  - Scripts/output panels are disabled while visual mode is active.
- **Managed script runtime**
  - Scripts execute via the FSCP host ↔ script protocol.
  - Interactive prompts, confirmations, progress, and structured results are supported.
  - Logs are timestamped and automatically pruned (default 50 files / 14 days).

## Quick Start

```bash
pipx install ferp
```

> [!NOTE]
> To use the default scripts, open the command palette (`Ctrl+P`) and select **Install/Update Default Scripts**.

> [!WARNING]
> This option is intended for specific users. It will remove any existing scripts you have installed.
>  
> If you prefer to install scripts individually, or to use your own custom scripts, see [FSCP](./ferp/fscp).

## Configuring Scripts

Scripts are declared in your user config `config.json` (created on first script install). Each entry defines:

- `script`: path to the executable (e.g. `scripts/ferp.zip_dir/script.py`).
- `target`: `current_directory`, `highlighted_file`, or `highlighted_directory`.
- `file_extensions`: optional list of suffixes (for `highlighted_file` targets).
- Optional README at `scripts/<id>/readme.md`.

Each script lives under `scripts/<id>/` (the directory name matches the fully-qualified ID, such as `ferp.zip_dir`). Inside the directory:

- `script.py` contains the executable FSCP script.
- `readme.md` provides the optional documentation shown inside FER​P.

### Dev toggle for script config

During development you can point FER​P at the repo copy of `ferp/scripts/config.json` instead of the user config file:

```bash
FERP_DEV_CONFIG=1 textual run --dev ferp/app.py
```

When enabled, FER​P reads the config directly from the repository and skips the one-time copy into the user config directory.
Script update notifications are suppressed while `FERP_DEV_CONFIG=1` is set.

Scripts that log data with `debug` level are skipped by default. You can enable these logs by adding the debug flag:

```bash
FERP_DEV_CONFIG=1 FERP_SCRIPT_LOG_LEVEL=debug textual run --dev ferp/app.py
```

## Authoring FSCP Scripts

Python scripts executed from FER​P speak the [FSCP](./ferp/fscp) protocol. See
`SCRIPT_AUTHORS.md` for the SDK guide, examples, logging, cancellation, cleanup,
and packaging details.

## Terminal Commands

FERP opens your system terminal in the current directory (shown in the top bar).

- Open a terminal using `Ctrl+t`.
- The spawned terminal inherits the current working directory.
- On Windows system, prefers PowerShell and falls back to CommandPrompt.

## Task List

FERP includes a lightweight task list for quick capture and review.

- Press `t` to add a task from anywhere in the UI.
- Press `l` to open the task list and review or mark tasks as complete.
- Tag tasks with `@` for text highlighting and filtering.
- Toggle completion status with the space bar.
- The task status indicator updates automatically as tasks are completed.

## Other Features

- **Default script updates**: Pull the latest default scripts from the release feed (suppressed in dev mode).
- **Process list**: View and stop running scripts from the command palette.
- **Tasks**: Capture quick tasks and review them in the task list.
- **Themes**: Switch themes from the command palette.
- **Startup directory**: Set the default path Ferp opens on launch.
- **Logs**: Open the latest transcript log from the command palette.
