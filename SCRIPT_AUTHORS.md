# FERP Script Author Guide

This document describes the FSCP SDK used by FERP scripts: entrypoints, runtime
behavior, logging, progress, inputs, results, and cancellation/cleanup.

## Quick Start

```python
from ferp.fscp.scripts import sdk

@sdk.script
def main(ctx: sdk.ScriptContext, api: sdk.ScriptAPI) -> None:
    api.log("info", f"Current target: {ctx.target_path}")
    choice = api.request_input("Enter a label", default="example")
    api.emit_result({"label": choice})

if __name__ == "__main__":
    main()
```

## SDK Concepts

### Script Context

`ctx` provides the target and environment:

- `ctx.target_path`: path selected in the UI.
- `ctx.target_kind`: `"file"` or `"directory"`.
- `ctx.params`: script config payload from `config.json`.
- `ctx.environment`: app + host metadata and paths.

### Logging

Use `api.log(level, message)` to emit structured log entries.

Supported levels: `debug`, `info`, `warn`, `error`.

Log filtering happens in the SDK. Set an environment variable to control it:

```bash
FERP_SCRIPT_LOG_LEVEL=debug python -m ferp
```

Default is `info`, which filters out `debug`.

### Progress

Use `api.progress(current=..., total=..., unit=..., every=...)` to emit
progress updates to the UI.

### Structured Results

`api.emit_result(payload)` sends result blocks to the output panel. Use
`_title` and `_status` in the payload to control rendering:

- `_title`: section title.
- `_status`: `success`, `ok`, `warn`, `error` (controls color).
- `_format: "json"` to render payload as formatted JSON.

### Input & Confirmations

Use these to pause execution until the user responds in the UI:

- `api.request_input(...)`
- `api.request_input_json(...)`
- `api.confirm(...)`

### Cancellation & Cleanup

FERP supports graceful cancellation. Use these patterns:

- `api.check_cancel()` in long-running loops.
- `api.register_cleanup(fn)` for cleanup tasks.

Cleanup hooks run automatically when:

- the script is cancelled, or
- the script exits normally, or
- the script errors.

Only cleanup failures are logged by default (at `error`).

Example:

```python
temp_paths: list[str] = []

def cleanup() -> None:
    for temp in temp_paths:
        api.log("info", f"Cleaning {temp}")

api.register_cleanup(cleanup)

for path in files:
    api.check_cancel()
    ...
```

## Runtime Notes

- Scripts run in a separate process (FSCP runtime).
- The SDK handles protocol IO and input waits.
- Transcripts are written to the logs directory.

## Packaging & Sharing Scripts

When you’re ready to distribute a script, bundle everything FER​P needs into a
single `.ferp` archive:

```bash
ferp bundle path/to/script.py path/to/README.md \
  --id "acme.extractor" \
  --name "My Script" \
  --target highlighted_directory \
  --dependency requests \
  --dependency "rich>=13" \
```

The `bundle` command writes `my_script.ferp` containing:

- `manifest.json` – metadata (`id` such as `vendor.script`, `name`, `version`, `target`, etc.).
- Your Python script (the manifest `entrypoint`).
- Optional README rendered inside FER​P.
- Dependency list (pip specifiers) installed automatically when users import the bundle.

Users can install bundles by opening the command palette (`Ctrl+P`) and choosing
**Install Script Bundle…**—FERP copies the script into `scripts/`, updates your
user `config.json`, and stores the README automatically.

Dependency installs run through the same Python interpreter that launched FERP.
When you install FERP via `pipx`, that means bundle dependencies land in the
pipx-managed virtual environment alongside the app.

## Troubleshooting

- If a script seems unresponsive during long work, add `api.check_cancel()`.
- Use `FERP_SCRIPT_LOG_LEVEL=debug` to surface debug logs in transcripts.
