# Doppelganger Finder

> Find files with identical content and safely remove the extra copies – always keeping at least one.

A small desktop tool (Python + tkinter, no external dependencies) that scans a folder, groups files by content hash and lets you clean up duplicates.

<!-- Add a screenshot: ![Screenshot](docs/screenshot.png) -->

## Features

- Folder picker, recursive scan (optional)
- Hash algorithms: MD5, SHA-1, **SHA-256 (default)**, SHA-512
- Minimum file size filter
- Groups of identical files with approximate wasted space
- Runs in a background thread – the window stays responsive, scan can be cancelled
- Graceful handling of permission errors
- Double-click a file to open its containing folder
- **Safe deletion**
  - *Delete All Duplicates (keep 1 each)* – keeps the first file (alphabetically) per group
  - *Delete Selected* – deletes only what you select
  - At least one copy per group is always protected
  - Confirmation dialog shows number of files and space to be freed

## Requirements

- Python 3.8+ (tkinter is included in the standard Windows/macOS installers; on some Linux distros install `python3-tk`)

## Usage

```bash
python doppelganger_finder_gui.py
```

1. Choose a folder.
2. Pick options (hash algorithm, subfolders, min. size).
3. Click **Scan for Doppelgangers**.
4. Review the groups, then delete duplicates.

> ⚠️ **Deletion is permanent.** Review the list before confirming. Use at your own risk – see the [license](LICENSE).

## Build a Windows `.exe`

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "DoppelgangerFinder" doppelganger_finder_gui.py
```

The executable is created in `dist/`.

## Contributing

Issues and pull requests are welcome.

## License

[MIT](LICENSE)
