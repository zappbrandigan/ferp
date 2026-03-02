# FERP User's Guide

FERP is a keyboard-first workspace for browsing files, running approved scripts, and tracking long-running work. This guide covers the core workflows most users actually need.

---

## 1) File Navigation

The file tree is the center of the app. It reflects the current folder and everything else builds on that context.

### Move Around

- Use `j` / `k` to move the highlight.
- Use `J` / `K` to move faster.
- Use `g` / `G` to jump to the top or bottom.
- Press `Enter` to open the highlighted directory.
- Press `u` to go to the parent directory.
- Press `~` to return to your configured start path.
- Press `h` / `l` to move backward or forward through folder history.

### Open Things Outside FERP

- Press `o` to open the current folder in your system file explorer.
- Press `O` to open the highlighted file with its default application.
- Press `Ctrl+t` to open a terminal in the current directory.

### Work With Multiple Files

FERP has a visual selection mode for batch file operations.

- Press `v` to enter or leave visual mode.
- Press `s` to toggle the highlighted item into or out of the selection.
- Press `S` to select a range from the current anchor (last selected item).
- Press `a` to select all items in the current folder.
- Press `A` to clear the current selection.
- Press `Escape` to clear staged copy or move items.

### Copy / Move / Rename / Delete

- Press `y` or `Ctrl+c` to stage the current selection for copy.
- Press `x` or `Ctrl+x` to stage the current selection for move.
- Press `p` or `Ctrl+v` to paste staged items into the current folder.
- Press `r` or `F2` to rename the highlighted item.
- Press `Delete` to delete the highlighted item.
- Press `n` to create a new file.
- Press `N` to create a new folder.

### Filter the Current Folder

Press `/` to open the file-tree filter.

- Plain text filters the visible list as you type.
- Prefix with `!` to exclude matches.
- Prefix with `/` to use regex matching.
- Use `find/replace` to prepare a bulk rename.
- Use `/regex/replace` for regex-based bulk rename.

Press `Enter` in the filter to apply the current filter text. If the input is a valid `find/replace` pattern, FERP will open a bulk-rename confirmation instead. Press `Escape` to close the filter.

### Sort the Current Folder

Press `,` to open the sort-order dialog.

- Press `a` for `Name` sort.
- Press `n` for `Natural` sort.
- Press `e` for `Extension` sort.
- Press `s` for `Size` sort.
- Press `c` for `Created` sort.
- Press `m` for `Modified` sort.
- Press `d` to toggle descending order.

`Name` sort compares filenames as plain text, so values like `file10` come before `file2`. It also pushes directories whose names start with `_` to the top of the list. `Natural` sort compares numeric parts as numbers, so `file2` comes before `file10`.

### Large Folders

Very large folders are chunked so the UI stays responsive.

- Press `[` / `]` to move to the previous or next chunk.
- Press `{` / `}` to jump to the first or last chunk.

---

## 2) Archives and Extraction

FERP can both create archives from the file tree and extract supported archives back into the current folder.

### Create an Archive

1. Highlight one file or folder, or use visual mode to select multiple items.
2. Press `E`.
3. In the archive dialog, confirm or edit the output name.
4. Choose the archive format (`.zip` or `.7z`).
5. Choose the compression level.
6. Press `Enter` in the name field to start.

FERP creates the archive in the current folder unless you enter an absolute path. If the destination already exists, FERP will ask before overwriting it.

### Extract an Archive

1. Highlight exactly one `.zip` or `.7z` file.
2. Press `Ctrl+e`.
3. Enter the destination folder name.
4. Press `Enter` to start.

Extraction creates a folder inside the current directory unless you enter an absolute path. If that folder already exists, FERP will ask before overwriting it.

### Important Limits

- Extraction only supports `.zip` and `.7z`.
- Archive creation will not let you write the archive on top of a selected source.
- Archive creation will not let you create an archive inside one of the selected folders.

---

## 3) Running Scripts and Viewing READMEs

The scripts panel lists the approved automations available in your current setup. Scripts run against the file or folder you currently have selected in the file tree.

### Read a Script README First

- Move focus to the scripts panel with `Tab` or `Space` then `s`.
- Highlight a script.
- Press `Enter`.

FERP opens the script's bundled README in a modal. Use:

- `j` / `k` or arrow keys to scroll.
- `Escape` or `q` to close the README.

If a script does not include a README, FERP will tell you that directly.

### Run a Script

1. In the file tree, highlight the file or folder the script should use.
2. Move to the scripts panel.
3. Highlight the script you want.
4. Press `R`.
5. Respond to any prompts shown by the script.

When a script starts, FERP sends its live output to the output panel and adds a record to the process panel.

### What to Expect

- Some scripts only make sense for certain file types or folders.
- Many scripts will ask for confirmation, names, or destinations before they continue.
- Only one script run is started at a time from the main UI.

---

## 4) The Process Panel

The process panel is your running-history view. It shows tracked script runs, their current state, and the target each run is working on.

### What It Shows

Each entry includes:

- The script name
- A friendly status such as `Running`, `Waiting for input`, `Finished`, `Canceled`, or `Error`
- The process ID when available
- A shortened target path label

The newest process appears at the top.

### Process Panel Actions

- Press `Space` then `p` to focus the process panel.
- Press `r` to refresh the list.
- Press `p` to prune finished process records.
- Press `x` to request termination of the highlighted process.

If no processes are currently tracked, the panel will show a placeholder message instead of an empty list.

### Relationship to the Output Panel

The output panel shows the live transcript for the active work. The process panel is the summary list.

Use the output panel when you need detail.
Use the process panel when you need status, history, or a quick cancel action.

---

## 5) Focus Shortcuts

These shortcuts help you move between the main panels quickly:

- `Tab` / `Shift+Tab`: switch primary focus between file tree and scripts
- `Space` then `f`: focus file tree
- `Space` then `s`: focus scripts panel
- `Space` then `b`: focus sidebar
- `Space` then `g`: focus path navigator
- `Space` then `o`: focus output panel
- `Space` then `m`: focus metadata panel
- `Space` then `p`: focus process panel

If you forget a shortcut, press `?` to open the in-app key reference.
