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

> This section assumes FERP was installed using `pipx`. 
> The built-in update command also assumes FERP was installed using `pipx`. 
> If you installed using a different method, you will need to manually manage launching and updating the app.

FERP opens inside a terminal window (a black‑or‑white text window). You won’t need to type any extra commands unless someone has given you specific instructions.

To launch FERP, open your terminal application (Terminal on macOS, Command Prompt/PowerShell on Windows) and type `ferp`, then press Enter. The symbols you see before the cursor (like `~>` or `$`) are just the prompt — you do **not** type those.

```bash
~> ferp
```

To update FERP to the latest version, select "Upgrade FERP" from the command palette. Alternatively, you can run the following command in the terminal:

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

## 4) Command Palette

The command palette lets you run app-level actions (like changing themes or refreshing your cache file). Open it using `Ctrl+p`, then start typing the command name (arrow up/down).

---

## 5) Input Box Editing Shortcuts

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
ctrl+d      Delete the character to the right of the cursor.
ctrl+w             Delete the word to the left of the cursor.
ctrl+u             Delete everything to the left of the cursor.
ctrl+f             Delete the word to the right of the cursor.
ctrl+k             Delete everything to the right of the cursor.
```

---

## 6) Basic Navigation

FERP is keyboard‑first. Common actions:

- **Arrow keys**: Move selection up/down.
- **Enter**: Open a folder or display a help file for a script.
- **i**: Show metadata for the highlighted file in the output panel.

Tip: You can move quickly without using the mouse. The full list of navigation keys are available in the app.

---

## 6b) Visual Mode (Multi‑Select)

Visual mode lets you select multiple items in the File Navigator without running scripts.

- **v**: Toggle visual mode (scripts and output panels are disabled while active).
- **s**: Toggle selection for the highlighted item.
- **Shift+s**: Select a range from the last anchor to the highlighted item.
- **c**: Copy selected items.
- **x**: Move selected items (cut).
- **p**: Paste into the current directory.
- **delete**: Delete selected items.
- **a**: Select all visible items.
- **Shift+a**: Deselect all items.
- **escape**: Clear staged items.

> Note: If the File Navigator is maximized, the first `escape` will un‑maximize it. Press `escape` again to clear staged items.

Selections are cleared when you exit visual mode.

---

## 6c) Filter Widget

Use the filter widget to quickly narrow the File Navigator list.

- Press `/` in the File Navigator to open the filter box.
- Text search matches the name and type column (e.g., `dir`, `pdf`, `report`).
- Prefix with `!` to exclude matches (e.g., `!dir` to hide directories).
- Prefix with `/` to use a regex (regex searches file names only).
- Use `pattern/replacement` to batch-rename files matching the filter (file extensions will not be modified).
- Use `/regex/replacement` for regex-based renames (regex runs on file stems).

> Note: Use `\g<1>` notation to reference the first captured group.

---

## 6d) Favorites (Quick Jumps)

Favorites let you mark locations and jump back quickly.

- **f**: Toggle favorite for the highlighted item (or current directory).
- **Shift+f**: Open the favorites list and jump to a saved path.

---

## 7) Running a Script (Automation)

Scripts are pre‑approved tasks like "rename files," "backup a folder," or "convert a file."

**How to run one:**

1. Highlight the folder or file the script needs.
2. Choose a script from the scripts list.
3. Press `Shift+R` to run it.
4. Follow any prompts (yes/no questions, names, destinations, etc.).
5. Watch the output pane for progress and results.

If a script needs a specific file type, FERP will only enable it when a matching file is selected.

---

## 8) Script Help (READMEs)

Each script can include built‑in documentation. To open it:

- Select a script, then press **Enter** to view the script’s README.

Use this to confirm what a script does before you run it.

---

## 9) Task List (Quick Notes)

FERP includes a simple task list for quick capture. Tasks can include multiple `@` tags to make them easier to spot and filter (e.g. `@todo`).

---

## 10) Logs and Output

When a script runs, FERP shows:

- **Live output** in the output pane.
- **Transcripts** saved automatically for later review.

If you need to confirm what happened in a past run, open the latest transcript (log file) from the command palette.
