# FER​P – Federated Execution & Run-time Protocol

FER​P is a terminal-friendly file manager and automation workbench. It combines a fast navigator, contextual metadata panes, and a protocol-driven script runner so you can inspect directories and run repeatable workflows without leaving the keyboard.

## Highlights

- **Keyboard-first navigation**
  - `j/k` to move, `g/G` jump to top/bottom, `J/K` fast-scroll.
  - `n` / `Shift+N` create files or folders, `Delete` removes them.
  - `Ctrl+Enter` opens the current directory in the system file manager.
- **Context panes**
  - Script list reads from `config/config.json`.
  - Output panel streams FSCP results and records transcripts under `data/logs`.
  - README modal (Enter on a script) displays bundled documentation.
- **Managed script runtime**
  - Scripts execute via the FSCP host ↔ script protocol.
  - Interactive prompts, confirmations, progress, and structured results are supported.
  - Logs are timestamped and automatically pruned (default 50 files / 14 days).

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install .
ferp                       # or python -m ferp
```

FER​P launches with the file tree on the left, automation and output panes on the right, and a top bar displaying status plus cache metadata.

## Configuring Scripts

Scripts are declared in `ferp/config/config.json`. Each entry defines:

- `script.script["other"/"windows"]`: path to the executable (e.g. `scripts/ferp.zip_dir/script.py`).
- `args`: command-line args (supports `{target}` substitution).
- `target`: `current_directory` or `highlighted_file`.
- Optional README at `scripts/<id>/readme.md`.

Each script lives under `ferp/scripts/<id>/` (the directory name matches the fully-qualified ID, such as `ferp.zip_dir`). Inside the directory:

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
  --target highlighted_file \
  --dependency requests \
  --dependency "rich>=13" \
  --requires-input \
  --input-prompt "Provide a case number"
```

The `bundle` command writes `my_script.ferp` (a zip file) containing:

- `manifest.json` – metadata (`id` such as `vendor.script`, `name`, `version`, `target`, args, prompts, etc.).
- Your Python script (the manifest `entrypoint`).
- Optional README rendered inside FER​P.
- Dependency list (pip specifiers) installed automatically when users import the bundle.

Users can install bundles by opening the command palette (`Ctrl+P`) and choosing **Install Script Bundle…**—FER​P copies the script into `scripts/`, updates `config/config.json`, and stores the README automatically.
