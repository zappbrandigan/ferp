# FER​P – For Executing Repetitive Processes

FERP is a terminal-friendly file manager and automation workbench. It combines an interactive file navigator, contextual metadata inspection, and a protocol-driven script runner so you can explore directories and execute repeatable workflows through a TUI—without requiring terminal knowledge.

## Highlights

- **Keyboard-first navigation**
  - `j/k` to move, `g/G` jump to top/bottom, `J/K` fast-scroll.
  - `n` / `Shift+N` create files or folders, `d` / `Delete` removes them.
  - `Ctrl+F` opens the current directory in the system file manager.
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
pipx install git+https://github.com/zappbrandigan/ferp.git
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

- `script.script["other"/"windows"]`: path to the executable (e.g. `scripts/ferp.zip_dir/script.py`).
- `args`: command-line args (supports `{target}` substitution).
- `target`: `current_directory`, `highlighted_file`, or `highlighted_directory`.
- `file_extensions`: optional list of suffixes (for `highlighted_file` targets).
- Optional README at `scripts/<id>/readme.md`.

Each script lives under `scripts/<id>/` (the directory name matches the fully-qualified ID, such as `ferp.zip_dir`). Inside the directory:

- `script.py` contains the executable FSCP script.
- `readme.md` provides the optional documentation shown inside FER​P.

## Authoring FSCP Scripts

Python scripts executed from FER​P speak the [FSCP](./ferp/fscp) protocol. Use the bundled SDK to avoid boilerplate:

```python
from ferp.fscp.scripts import sdk

@sdk.script
def main(ctx: sdk.ScriptContext, api: sdk.ScriptAPI) -> None:
    api.log("info", f"Current target: {ctx.target_path}")
    choice = api.request_input("Enter a label", default="example")
    api.emit_result({"label": choice, "args": ctx.args})

if __name__ == "__main__":
    main()
```

SDK essentials:

- `ctx` exposes `target_path`, `target_kind`, params, and environment overrides.
- `api.log`, `api.progress`, and `api.emit_result` stream structured messages to FER​P.
- `api.request_input` suspends execution until the user replies inside FER​P.
- `api.confirm` displays a Yes/No dialog—use it before running destructive operations.

Add your script to the config file, drop a README if desired, and FER​P will handle transport, prompting, and transcript logging for you.

## Packaging & Sharing Scripts

When you’re ready to distribute a script, bundle everything FER​P needs into a single `.ferp` archive:

```bash
ferp bundle path/to/script.py path/to/README.md \
  --id "acme.extractor" \
  --name "My Script" \
  --target highlighted_directory \
  --dependency requests \
  --dependency "rich>=13" \
  --requires-input \
```

The `bundle` command writes `my_script.ferp` containing:

- `manifest.json` – metadata (`id` such as `vendor.script`, `name`, `version`, `target`, args, etc.).
- Your Python script (the manifest `entrypoint`).
- Optional README rendered inside FER​P.
- Dependency list (pip specifiers) installed automatically when users import the bundle.

Users can install bundles by opening the command palette (`Ctrl+P`) and choosing **Install Script Bundle…**—FERP copies the script into `scripts/`, updates your user `config.json`, and stores the README automatically.

## Terminal Commands

FERP includes an integrated terminal panel for quick shell commands.

- Open the terminal panel from the command palette.
- Commands run in the current directory shown in the top bar.
- Output is captured and shown in the output panel with exit codes.
- Interactive TUI tools (vim, less, etc.) are blocked; use your system terminal for those.

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
