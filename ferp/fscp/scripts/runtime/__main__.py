#!/usr/bin/env python3
"""
FSCP reference script executable.

This module is intentionally thin:
- No protocol logic
- No business logic
- No error recovery

It exists only to bootstrap ScriptRuntime and exit cleanly.
"""

import sys
import traceback

from ferp.fscp.scripts.runtime.errors import ScriptError
from ferp.fscp.scripts.runtime.script import ScriptRuntime


def main() -> int:
    runtime = ScriptRuntime()

    try:
        runtime.run()
        return 0

    except ScriptError as exc:
        # ScriptError means we violated the FSCP contract or hit a fatal state.
        # Best effort: emit to stderr only (never stdout).
        print(f"[FSCP SCRIPT ERROR] {exc}", file=sys.stderr)
        return 2

    except Exception:
        # Truly unexpected failure.
        traceback.print_exc(file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
