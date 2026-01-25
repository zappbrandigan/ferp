# FER​P – For Executing Repetitive Processes

FERP is a terminal-friendly file manager and automation workbench. It combines an interactive file navigator, contextual metadata inspection, and a protocol-driven script runner so you can explore directories and execute repeatable workflows through a TUI—without requiring terminal knowledge.

## Highlights

- **Keyboard-first navigation**
  - A full list of keys are available in the app.
- **Context panes**
  - Script list reads from the user config `config.json` (platformdirs).
  - Output panel streams FSCP results and records transcripts under the user data `logs` directory.
  - README modal (Enter on a script) displays bundled documentation.
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
> This option is intended for users who do not wish to manage scripts manually. It will remove any existing scripts you have installed.
>  
> If you prefer to install scripts individually, create a bundle for the desired script using the source files from
> [ferp-scripts](https://github.com/zappbrandigan/ferp-scripts).

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
FERP_DEV_CONFIG=1 python -m ferp
```

When enabled, FER​P reads the config directly from the repository and skips the one-time copy into the user config directory.

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

- **Script catalog refresh**: Reload the script list after editing config.
- **Default script updates**: Pull the latest default scripts from the release feed.
- **Process list**: View and stop running scripts from the command palette.
- **Tasks**: Capture quick tasks and review them in the task list.
- **Themes**: Switch themes from the command palette.
- **Startup directory**: Set the default path Ferp opens on launch.
- **Logs**: Open the latest transcript log from the command palette.
