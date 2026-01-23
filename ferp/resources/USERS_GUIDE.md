# FERP User’s Guide

Welcome to FERP (For Executing Repetitive Processes). FERP is a keyboard‑first file navigator and automation workbench that runs in a terminal window but doesn’t require you to know terminal commands. You browse files, inspect details, and run approved scripts from a simple, structured interface.

This guide covers the essentials to get you comfortable.

---

## 1) What FERP Is For

FERP helps you:

- Navigate folders quickly with the keyboard.
- Run repeatable scripts (automations) against the current folder, highlighted folder, or a highlited file.
- Keep a lightweight task list inside the app.

If you already use file explorers or Finder/File Explorer, think of FERP as a power‑focused version built for repeatable workflows.

---

## 2) Opening FERP

FERP opens inside a terminal window (a black‑or‑white text window). You won’t need to type any extra commands unless someone has given you specific instructions.

To launch FERP, open your terminal application (Terminal on macOS, Command Prompt/PowerShell on Windows) and type `ferp`, then press Enter. The symbols you see before the cursor (like `~>` or `$`) are just the prompt — you do **not** type those.

```bash
~> ferp
```

To update FERP to the latest version (if installed by your team):

```bash
~> pipx upgrade ferp
```

If you’re not sure how FERP was installed on your system, ask your team before updating.

---

## 3) The Main Screen

FERP is split into sections (called "panels"):

- **Title Bar (top)**: Shows the current app version, script runner status, current working directory, and cache file status.
- **File Navigator (left)**: Shows folders and files you can navigate.
- **Scripts List (top-right)**: Shows automations you can run (if any are installed).
- **Output (bottom-right)**: Shows progress and results when a script runs.
- **Footer (bottom)**: Shows the most commonly used commands available from the currently focused panel.

> FERP starts in your Home folder. You can change what directory is loaded on startup using the command palette.

---

## 4) Keyboard Shortcuts

Below is the full list of shortcuts by panel focus. If a shortcut doesn’t work, click or move focus into that panel and try again.

### Everywhere (Global)

- `l`: Show the task list.
- `t`: Add a new task.
- `m`: Maximize/minimize the focused panel.
- `?`: Toggle the on-screen help panel (shows all active keys).

### File Navigator (Left Panel)

- `Arrow keys`: Move selection up/down.
- `Enter`: Open a folder.
- `g / G`: Jump to top / bottom.
- `j / k`: Move down / up.
- `J / K`: Page down / page up (fast move).
- `u`: Go to parent directory.
- `h`: Go to startup (home) directory.
- `r`: Rename selected file or folder.
- `n`: Create a new file.
- `N`: Create a new folder.
- `Delete`: Delete selected file or folder.
- `Ctrl+F`: Open current folder in the system file explorer.
- `Ctrl+O`: Open the selected file with the default app.
- `Ctrl+T`: Open a terminal at the current folder.
- `/`: Filter the file list.
- `[ / ]`: Load previous / next chunk of files.

### Scripts (Top-Right Panel)

- `Arrow keys`: Move selection up/down.
- `Enter`: Open the script README.
- `R`: Run the selected script.
- `g / G`: Jump to top / bottom.
- `j / k`: Move down / up.
- `J / K`: Page down / page up (fast move).

### Output (Bottom-Right Panel)

- No dedicated shortcuts (output is read-only).

---

## 5) Command Palette

The command palette lets you run app-level actions (like changing themes or refreshing your cache file). Open it using `Ctrl+p`, then start typing the command name (arrow up/down).

**Available commands:**

- Install Script Bundle (for advanced users installing custom scripts)
- Install/Update Default Scripts (this is how you update your default FERP script bundle)
- Refresh File Tree
- Reload Script Catalog
- Open Latest Log
- View Running/Past Processes
- Set Startup Directory
- Sync Monday Board Cache

---

## 6) Input Box Editing Shortcuts

When a text input is focused (filter box, rename dialog, task entry, etc.), these shortcuts apply:

```txt
Key(s)             Description
left               Move the cursor left.
shift+left         Move cursor left and select.
ctrl+left          Move the cursor one word to the left.
right              Move the cursor right or accept the completion suggestion.
ctrl+shift+left    Move cursor left a word and select.
shift+right        Move cursor right and select.
ctrl+right         Move the cursor one word to the right.
backspace          Delete the character to the left of the cursor.
ctrl+shift+right   Move cursor right a word and select.
home,ctrl+a        Go to the beginning of the input.
end,ctrl+e         Go to the end of the input.
shift+home         Select up to the input start.
shift+end          Select up to the input end.
delete,ctrl+d      Delete the character to the right of the cursor.
enter              Submit the current value of the input.
ctrl+w             Delete the word to the left of the cursor.
ctrl+u             Delete everything to the left of the cursor.
ctrl+f             Delete the word to the right of the cursor.
ctrl+k             Delete everything to the right of the cursor.
ctrl+x             Cut selected text.
ctrl+c             Copy selected text.
ctrl+v             Paste text from the clipboard.
```

---

## 7) Basic Navigation

FERP is keyboard‑first. Common actions:

- **Arrow keys**: Move selection up/down.
- **Enter**: Open a folder or display a help file for a script.

Tip: You can move quickly without using the mouse.

---

## 8) Running a Script (Automation)

Scripts are pre‑approved tasks like "rename files," "backup a folder," or "convert a file."

**How to run one:**

1. Highlight the folder or file the script needs.
2. Choose a script from the scripts list.
3. Press `Shift+R` to run it.
4. Follow any prompts (yes/no questions, names, destinations, etc.).
5. Watch the output pane for progress and results.

If a script needs a specific file type, FERP will only enable it when a matching file is selected.

---

## 9) Script Help (READMEs)

Each script can include built‑in documentation. To open it:

- Select a script, then press **Enter** to view the script’s README.

Use this to confirm what a script does before you run it.

---

## 10) Task List (Quick Notes)

FERP includes a simple task list for quick capture:

- Press `t` to add a task.
- Press `l` to open your task list.
- Use the `space bar` to mark tasks complete.
- Press `/` to filter by list by tags.
- Press `C` to clear all completed tasks.
- Press `Delete` to delete a task

Tasks can include multiple `@` tags to make them easier to spot and filter (e.g. `@todo`).

---

## 11) Logs and Output

When a script runs, FERP shows:

- **Live output** in the output pane.
- **Transcripts** saved automatically for later review.

If you need to confirm what happened in a past run, open the latest transcript (log file) from the command palette.

---

## 12) Tips for New Users

- Start by browsing a familiar folder to get comfortable.
- Open a script’s README before running it the first time.
- If a script asks a question, read it carefully - it’s usually important.
- If something looks wrong, stop and ask your team before re‑running a script.

---

## 13) Troubleshooting (Basics)

- **No scripts listed**: Scripts may not be installed yet. Install the default scripts using the command palette.
- **Script won’t run**: You may have the wrong file/folder selected. Review the details in the output panel and try selecting the target the script expects.
- **Nothing happens**: Check the output pane for a message or prompt.
