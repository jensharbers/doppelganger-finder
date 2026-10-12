# Doppelganger Finder

> Find files with identical content and safely remove the extra copies – always keeping at least one.

A small desktop tool (Python + tkinter) that scans a folder, groups files by content hash and lets you clean up duplicates. Works on Windows, macOS and Linux.

<!-- Add a screenshot: ![Screenshot](docs/screenshot.png) -->

## Features

- Folder picker, recursive scan (optional)
- **Fast:** only files with the same size are hashed
- Hash algorithms: MD5, SHA-1, **SHA-256 (default)**, SHA-512
- Minimum file size filter
- Groups of identical files with approximate wasted space
- **Symlinks are ignored**, and **hardlinks** to the same file are counted once (deleting them would not free any space)
- Runs in a background thread – the window stays responsive, the scan can be cancelled
- Graceful handling of permission errors
- Double-click a file to open its containing folder
- **Safe deletion**
  - At least one copy per group is always protected
  - **Choose which copy to keep:** alphabetical (first path), oldest, newest or shortest path – the copy that will be kept is marked with `★ keep`
  - *Delete All Duplicates (keep 1 each)* and *Delete Selected*
  - Files are moved to the **recycle bin / trash** (with `send2trash`), so deletions can be undone
  - Confirmation dialog shows number of files and size

## Requirements

- Python 3.8+ (tkinter is included in the standard Windows/macOS installers; on some Linux distros install `python3-tk`)
- Optional but recommended: [`send2trash`](https://pypi.org/project/Send2Trash/) for recycle bin support

## Installation & usage

```bash
git clone https://github.com/YOUR_USERNAME/doppelganger-finder.git
cd doppelganger-finder
pip install -r requirements.txt   # optional, enables recycle bin
python doppelganger_finder_gui.py
```

1. Choose a folder.
2. Pick options (hash algorithm, subfolders, min. size, which copy to keep).
3. Click **Scan for Doppelgangers**.
4. Expand the groups, review them, then delete duplicates.

> ⚠️ Without `send2trash` (the option is greyed out in the app), deletion is **permanent**. Always review the list before confirming. Use at your own risk – see the [license](LICENSE).

## Build a Windows `.exe`

```bash
pip install pyinstaller send2trash
pyinstaller --onefile --windowed --name "DoppelgangerFinder" doppelganger_finder_gui.py
```

The executable is created in `dist/`.

## Contributing

Issues and pull requests are welcome.

## License

[MIT](LICENSE)
