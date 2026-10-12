"""Doppelganger Finder - find files with identical content and safely remove duplicates.

A tkinter GUI (Windows / macOS / Linux). Files are compared by hash (SHA-256 by
default). Duplicates can be removed while at least one copy of every file is
always kept.

Highlights
    * Fast: only files with the same size are hashed
    * Symlinks are ignored; hardlinks to the same file are counted once
    * Choose which copy to keep (alphabetical / oldest / newest / shortest path)
    * Duplicates go to the recycle bin / trash (needs the optional "send2trash"
      package; without it files are deleted permanently)

Run:
    python doppelganger_finder_gui.py
"""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import sys
import threading
import tkinter as tk
from collections import defaultdict
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    from send2trash import send2trash

    HAS_TRASH = True
except ImportError:  # optional dependency
    send2trash = None
    HAS_TRASH = False


KEEP_ALPHABETICAL = "Alphabetical (first path)"
KEEP_OLDEST = "Oldest file"
KEEP_NEWEST = "Newest file"
KEEP_SHORTEST = "Shortest path"
KEEP_OPTIONS = [KEEP_ALPHABETICAL, KEEP_OLDEST, KEEP_NEWEST, KEEP_SHORTEST]


def compute_file_hash(
    filepath: Path,
    algorithm: str = "sha256",
    chunk_size: int = 1024 * 1024,
    cancel=None,
) -> str | None:
    """Compute the hash of a file in chunks.

    Returns None on error or if ``cancel()`` returns True while reading.
    """
    try:
        hasher = hashlib.new(algorithm)
        with open(filepath, "rb") as f:
            while chunk := f.read(chunk_size):
                if cancel is not None and cancel():
                    return None
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError:
        return None


def human_size(num_bytes: int) -> str:
    """Return a human-readable size string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num_bytes) < 1024:
            return f"{num_bytes:3.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} PB"


def order_by_keep(paths: list[Path], strategy: str) -> list[Path]:
    """Sort paths so that the file to KEEP comes first."""

    def mtime(p: Path, missing: float) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return missing

    def name(p: Path) -> str:
        return str(p).lower()

    if strategy == KEEP_OLDEST:
        return sorted(paths, key=lambda p: (mtime(p, float("inf")), name(p)))
    if strategy == KEEP_NEWEST:
        return sorted(paths, key=lambda p: (-mtime(p, float("-inf")), name(p)))
    if strategy == KEEP_SHORTEST:
        return sorted(paths, key=lambda p: (len(str(p)), name(p)))
    return sorted(paths, key=name)


class DoppelgangerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Doppelganger Finder")
        self.geometry("950x700")
        self.minsize(750, 540)

        # State
        self.scanning = False
        self.cancel_requested = False
        # hash -> list of Path (only groups with 2+ files)
        self.doppelgangers: dict[str, list[Path]] = {}
        # tree item id -> Path (only for file rows, not group headers)
        self.item_to_path: dict[str, Path] = {}
        # tree item id -> hash (for group headers and their children)
        self.item_to_hash: dict[str, str] = {}

        self._build_ui()
        self._center_window()

    def _center_window(self):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        # ---- Top frame: folder selection ----
        top = ttk.Frame(self, padding=10)
        top.pack(fill=tk.X)

        ttk.Label(top, text="Folder:").pack(side=tk.LEFT)
        self.folder_var = tk.StringVar()
        self.folder_entry = ttk.Entry(top, textvariable=self.folder_var, width=60)
        self.folder_entry.pack(side=tk.LEFT, padx=(5, 5), fill=tk.X, expand=True)
        ttk.Button(top, text="Browse…", command=self._browse_folder).pack(side=tk.LEFT)

        # ---- Options frame ----
        opts = ttk.LabelFrame(self, text="Options", padding=10)
        opts.pack(fill=tk.X, padx=10, pady=(0, 5))

        ttk.Label(opts, text="Hash:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.algo_var = tk.StringVar(value="sha256")
        ttk.Combobox(
            opts,
            textvariable=self.algo_var,
            values=["md5", "sha1", "sha256", "sha512"],
            state="readonly",
            width=10,
        ).grid(row=0, column=1, sticky=tk.W, padx=(0, 15))

        self.recursive_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Scan subfolders", variable=self.recursive_var).grid(
            row=0, column=2, sticky=tk.W, padx=(0, 15)
        )

        ttk.Label(opts, text="Min size (bytes):").grid(row=0, column=3, sticky=tk.W, padx=(0, 5))
        self.min_size_var = tk.StringVar(value="0")
        ttk.Entry(opts, textvariable=self.min_size_var, width=10).grid(row=0, column=4, sticky=tk.W)

        ttk.Label(opts, text="Keep:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5), pady=(8, 0))
        self.keep_var = tk.StringVar(value=KEEP_ALPHABETICAL)
        keep_box = ttk.Combobox(
            opts,
            textvariable=self.keep_var,
            values=KEEP_OPTIONS,
            state="readonly",
            width=24,
        )
        keep_box.grid(row=1, column=1, columnspan=2, sticky=tk.W, pady=(8, 0))
        keep_box.bind("<<ComboboxSelected>>", self._on_keep_change)

        self.trash_var = tk.BooleanVar(value=HAS_TRASH)
        trash_text = "Move deleted files to recycle bin / trash"
        if not HAS_TRASH:
            trash_text += "  (pip install send2trash to enable)"
        trash_check = ttk.Checkbutton(opts, text=trash_text, variable=self.trash_var)
        trash_check.grid(row=1, column=3, columnspan=2, sticky=tk.W, pady=(8, 0))
        if not HAS_TRASH:
            trash_check.state(["disabled"])

        # ---- Action buttons ----
        btn_frame = ttk.Frame(self, padding=(10, 5))
        btn_frame.pack(fill=tk.X)

        self.scan_btn = ttk.Button(btn_frame, text="▶  Scan for Doppelgangers", command=self._start_scan)
        self.scan_btn.pack(side=tk.LEFT)

        self.cancel_btn = ttk.Button(btn_frame, text="Cancel", command=self._cancel_scan, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Button(btn_frame, text="Clear Results", command=self._clear_results).pack(side=tk.LEFT, padx=(8, 0))

        # Delete buttons (right side)
        self.delete_selected_btn = ttk.Button(
            btn_frame, text="Delete Selected", command=self._delete_selected, state=tk.DISABLED
        )
        self.delete_selected_btn.pack(side=tk.RIGHT)

        self.delete_all_dupes_btn = ttk.Button(
            btn_frame,
            text="Delete All Duplicates (keep 1 each)",
            command=self._delete_all_duplicates,
            state=tk.DISABLED,
        )
        self.delete_all_dupes_btn.pack(side=tk.RIGHT, padx=(0, 8))

        # ---- Progress / status ----
        status_frame = ttk.Frame(self, padding=(10, 0))
        status_frame.pack(fill=tk.X)

        self.status_var = tk.StringVar(value="Select a folder and click Scan.")
        ttk.Label(status_frame, textvariable=self.status_var).pack(side=tk.LEFT)

        self.progress = ttk.Progressbar(status_frame, mode="indeterminate", length=200)
        self.progress.pack(side=tk.RIGHT)

        # ---- Results area ----
        results_frame = ttk.LabelFrame(
            self, text="Results  (expand a group • select files • double-click opens folder)", padding=5
        )
        results_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        columns = ("group", "copies", "size", "hash", "path")
        self.tree = ttk.Treeview(
            results_frame,
            columns=columns,
            show="tree headings",  # "tree" shows the expand/collapse arrows for groups
            selectmode="extended",  # multi-select
        )
        self.tree.heading("#0", text="")
        self.tree.heading("group", text="Group")
        self.tree.heading("copies", text="Copies")
        self.tree.heading("size", text="Size each")
        self.tree.heading("hash", text="Hash (short)")
        self.tree.heading("path", text="File path")

        self.tree.column("#0", width=75, minwidth=75, stretch=False)
        self.tree.column("group", width=55, anchor=tk.CENTER)
        self.tree.column("copies", width=55, anchor=tk.CENTER)
        self.tree.column("size", width=85, anchor=tk.E)
        self.tree.column("hash", width=130)
        self.tree.column("path", width=480)

        vsb = ttk.Scrollbar(results_frame, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(results_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        results_frame.rowconfigure(0, weight=1)
        results_frame.columnconfigure(0, weight=1)

        self.tree.bind("<Double-1>", self._open_containing_folder)
        self.tree.bind("<<TreeviewSelect>>", self._on_selection_change)

        # Summary
        self.summary_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.summary_var, padding=(10, 5)).pack(fill=tk.X)

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="Select folder to scan")
        if folder:
            self.folder_var.set(folder)

    def _clear_results(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.doppelgangers.clear()
        self.item_to_path.clear()
        self.item_to_hash.clear()
        self.summary_var.set("")
        self.status_var.set("Results cleared.")
        self.delete_all_dupes_btn.config(state=tk.DISABLED)
        self.delete_selected_btn.config(state=tk.DISABLED)

    def _on_selection_change(self, _event=None):
        selected = self.tree.selection()
        # Enable "Delete Selected" only if at least one real file row is selected
        has_file = any(item in self.item_to_path for item in selected)
        self.delete_selected_btn.config(state=tk.NORMAL if has_file else tk.DISABLED)

    def _on_keep_change(self, _event=None):
        """Re-order the results when the 'keep' strategy changes."""
        if self.doppelgangers:
            self._populate_tree()
            self.delete_selected_btn.config(state=tk.DISABLED)

    def _cancel_scan(self):
        self.cancel_requested = True
        self.status_var.set("Cancelling…")

    def _use_trash(self) -> bool:
        return HAS_TRASH and self.trash_var.get()

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def _start_scan(self):
        folder = self.folder_var.get().strip()
        if not folder:
            messagebox.showwarning("No folder", "Please select a folder first.")
            return

        root = Path(folder).expanduser().resolve()
        if not root.is_dir():
            messagebox.showerror("Invalid folder", f"Not a valid directory:\n{root}")
            return

        try:
            min_size = int(self.min_size_var.get().strip() or "0")
            if min_size < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid size", "Min size must be a non-negative integer.")
            return

        self._clear_results()
        self.scanning = True
        self.cancel_requested = False
        self.scan_btn.config(state=tk.DISABLED)
        self.cancel_btn.config(state=tk.NORMAL)
        self.progress.start(15)
        self.status_var.set("Scanning…")

        thread = threading.Thread(
            target=self._scan_worker,
            args=(root, self.algo_var.get(), self.recursive_var.get(), min_size),
            daemon=True,
        )
        thread.start()

    def _scan_worker(self, root: Path, algorithm: str, recursive: bool, min_size: int):
        """Two phases: (1) index files by size, (2) hash only files that share a size."""
        error_count = 0

        def cancelled() -> bool:
            return self.cancel_requested

        def finish_cancelled():
            self.after(0, self._scan_finished, None, 0, 0, 0, True)

        try:
            # ---- Phase 1: index by size --------------------------------
            by_size: dict[int, list[Path]] = defaultdict(list)
            seen_files: set[tuple[int, int]] = set()  # (device, inode) → skip hardlinks
            indexed = 0

            for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
                for name in filenames:
                    if cancelled():
                        finish_cancelled()
                        return

                    path = Path(dirpath) / name
                    try:
                        if path.is_symlink():
                            continue  # symlinks are not real copies
                        st = path.stat()
                    except OSError:
                        error_count += 1
                        continue

                    if not stat.S_ISREG(st.st_mode) or st.st_size < min_size:
                        continue

                    if st.st_ino:
                        key = (st.st_dev, st.st_ino)
                        if key in seen_files:
                            continue  # hardlink to a file we already have
                        seen_files.add(key)

                    by_size[st.st_size].append(path)
                    indexed += 1
                    if indexed % 200 == 0:
                        self.after(0, lambda c=indexed: self.status_var.set(f"Indexing… {c} files found"))

                if not recursive:
                    break

            # ---- Phase 2: hash only candidates -------------------------
            candidates = [paths for paths in by_size.values() if len(paths) > 1]
            total = sum(len(paths) for paths in candidates)
            hash_to_files: dict[str, list[Path]] = defaultdict(list)
            hashed = 0

            for paths in candidates:
                for path in paths:
                    if cancelled():
                        finish_cancelled()
                        return

                    file_hash = compute_file_hash(path, algorithm, cancel=cancelled)
                    if file_hash is None:
                        if cancelled():
                            finish_cancelled()
                            return
                        error_count += 1
                        continue

                    hash_to_files[file_hash].append(path)
                    hashed += 1
                    if hashed % 5 == 0 or hashed == total:
                        self.after(
                            0,
                            lambda h=hashed, t=total: self.status_var.set(f"Hashing… {h} / {t} candidate files"),
                        )

            doppelgangers = {h: paths for h, paths in hash_to_files.items() if len(paths) > 1}
            self.after(0, self._scan_finished, doppelgangers, indexed, hashed, error_count, False)

        except Exception as e:
            # Capture the message now: "e" is not available once the except block ends.
            error_message = str(e)
            self.after(0, lambda m=error_message: messagebox.showerror("Error", m))
            self.after(0, self._scan_finished, None, 0, 0, 0, True)

    def _scan_finished(self, doppelgangers, indexed, hashed, error_count, cancelled):
        self.scanning = False
        self.progress.stop()
        self.scan_btn.config(state=tk.NORMAL)
        self.cancel_btn.config(state=tk.DISABLED)

        if cancelled:
            self.status_var.set("Scan cancelled.")
            return

        stats = f"{indexed} files checked, {hashed} hashed"
        if error_count:
            stats += f", {error_count} skipped"

        if not doppelgangers:
            self.status_var.set(f"Done. {stats}. No doppelgangers found.")
            self.summary_var.set("All files are unique.")
            return

        self.doppelgangers = doppelgangers
        self._populate_tree()

        total_groups = len(doppelgangers)
        total_files = sum(len(p) for p in doppelgangers.values())
        wasted = self._calc_wasted()

        self.status_var.set(f"Done. {stats}.")
        self.summary_var.set(
            f"Found {total_groups} group(s)  •  {total_files} files  •  "
            f"Approx. redundant space: {human_size(wasted)}"
        )
        self.delete_all_dupes_btn.config(state=tk.NORMAL)

    def _populate_tree(self):
        """Fill the tree from self.doppelgangers (keeper listed first in each group)."""
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.item_to_path.clear()
        self.item_to_hash.clear()

        strategy = self.keep_var.get()

        for i, (file_hash, paths) in enumerate(
            sorted(self.doppelgangers.items(), key=lambda x: -len(x[1])), 1
        ):
            try:
                size_str = human_size(paths[0].stat().st_size)
            except OSError:
                size_str = "?"

            parent = self.tree.insert(
                "",
                tk.END,
                values=(f"#{i}", len(paths), size_str, file_hash[:16] + "…", f"{len(paths)} identical files"),
                tags=("group",),
                open=False,
            )
            self.item_to_hash[parent] = file_hash

            for n, p in enumerate(order_by_keep(paths, strategy)):
                is_keeper = n == 0
                child = self.tree.insert(
                    parent,
                    tk.END,
                    text="★ keep" if is_keeper else "",
                    values=("", "", "", "", str(p)),
                    tags=("keeper",) if is_keeper else (),
                )
                self.item_to_path[child] = p
                self.item_to_hash[child] = file_hash

        self.tree.tag_configure("group", background="#e8f0fe")
        self.tree.tag_configure("keeper", foreground="#1a7f37")

    def _calc_wasted(self) -> int:
        wasted = 0
        for paths in self.doppelgangers.values():
            if len(paths) < 2:
                continue
            try:
                size = paths[0].stat().st_size
                wasted += size * (len(paths) - 1)
            except OSError:
                pass
        return wasted

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------

    def _delete_all_duplicates(self):
        """Keep one file per group (according to the 'Keep' option), delete the rest."""
        if not self.doppelgangers:
            return

        strategy = self.keep_var.get()
        to_delete: list[Path] = []
        keep_list: list[Path] = []

        for paths in self.doppelgangers.values():
            ordered = order_by_keep(paths, strategy)
            keep_list.append(ordered[0])
            to_delete.extend(ordered[1:])

        if not to_delete:
            messagebox.showinfo("Nothing to delete", "No duplicate files to remove.")
            return

        space = self._total_size(to_delete)

        if self._use_trash():
            action = (
                f"This will move {len(to_delete)} file(s) to the recycle bin / trash\n"
                f"(approx. {human_size(space)}, freed once the bin is emptied)."
            )
        else:
            action = (
                f"This will PERMANENTLY delete {len(to_delete)} file(s)\n"
                f"and free approximately {human_size(space)}."
            )

        msg = (
            f"{action}\n\n"
            f"One copy of each file will be kept ({len(keep_list)} file(s)).\n"
            f"Keep rule: {strategy}\n\n"
            f"Continue?"
        )
        if not messagebox.askyesno("Confirm Delete Duplicates", msg, icon="warning"):
            return

        deleted, failed = self._perform_deletes(to_delete)
        self._after_delete(deleted, failed)

    def _delete_selected(self):
        """Delete only the currently selected file rows, but never the last file of a group."""
        selected = self.tree.selection()
        candidates = [self.item_to_path[item] for item in selected if item in self.item_to_path]

        if not candidates:
            messagebox.showinfo("Nothing selected", "Select one or more file rows (not group headers) first.")
            return

        strategy = self.keep_var.get()
        to_delete: list[Path] = []
        blocked: list[Path] = []

        # Group selected paths by hash
        by_hash: dict[str, list[Path]] = defaultdict(list)
        path_to_hash = {}
        for h, paths in self.doppelgangers.items():
            for p in paths:
                path_to_hash[p] = h

        for p in candidates:
            h = path_to_hash.get(p)
            if h:
                by_hash[h].append(p)

        for h, selected_paths in by_hash.items():
            remaining = list(self.doppelgangers.get(h, []))
            remaining_after = [p for p in remaining if p not in selected_paths]
            if len(remaining_after) < 1:
                # The selection would wipe the whole group: protect one copy
                # (chosen by the keep rule) and delete the rest of the selection.
                ordered = order_by_keep(selected_paths, strategy)
                blocked.append(ordered[0])
                to_delete.extend(ordered[1:])
            else:
                to_delete.extend(selected_paths)

        if blocked and not to_delete:
            messagebox.showwarning(
                "Cannot delete",
                "You selected the only remaining copy (or all copies) of a file.\n"
                "At least one copy of each file must be kept.",
            )
            return

        if blocked:
            messagebox.showinfo(
                "Partial protection",
                f"{len(blocked)} file(s) were protected (would have been the last copy).\n"
                f"The other selected files can still be deleted.",
            )

        if not to_delete:
            return

        space = self._total_size(to_delete)

        if self._use_trash():
            action = f"Move {len(to_delete)} selected file(s) to the recycle bin / trash?"
        else:
            action = f"PERMANENTLY delete {len(to_delete)} selected file(s)? This cannot be undone."

        msg = f"{action}\nApprox. size: {human_size(space)}"
        if not messagebox.askyesno("Confirm Delete", msg, icon="warning"):
            return

        deleted, failed = self._perform_deletes(to_delete)
        self._after_delete(deleted, failed)

    @staticmethod
    def _total_size(paths: list[Path]) -> int:
        total = 0
        for p in paths:
            try:
                total += p.stat().st_size
            except OSError:
                pass
        return total

    def _perform_deletes(self, paths: list[Path]) -> tuple[list[Path], list[tuple[Path, str]]]:
        deleted = []
        failed = []
        use_trash = self._use_trash()
        for p in paths:
            try:
                if use_trash:
                    send2trash(str(p))
                else:
                    p.unlink()
                deleted.append(p)
            except Exception as e:  # send2trash can raise various OSError subclasses
                failed.append((p, str(e)))
        return deleted, failed

    def _after_delete(self, deleted: list[Path], failed: list[tuple[Path, str]]):
        # Update self.doppelgangers
        deleted_set = set(deleted)
        new_doppelgangers = {}
        for h, paths in self.doppelgangers.items():
            remaining = [p for p in paths if p not in deleted_set]
            if len(remaining) > 1:
                new_doppelgangers[h] = remaining
            # if only 0 or 1 left → group disappears (no longer a doppelganger)

        self.doppelgangers = new_doppelgangers
        self._populate_tree()

        # Update summary
        if self.doppelgangers:
            total_groups = len(self.doppelgangers)
            total_files = sum(len(p) for p in self.doppelgangers.values())
            wasted = self._calc_wasted()
            self.summary_var.set(
                f"Remaining: {total_groups} group(s)  •  {total_files} files  •  "
                f"Redundant space: {human_size(wasted)}"
            )
            self.delete_all_dupes_btn.config(state=tk.NORMAL)
        else:
            self.summary_var.set("No more doppelgangers.")
            self.delete_all_dupes_btn.config(state=tk.DISABLED)

        self.delete_selected_btn.config(state=tk.DISABLED)

        # Status message
        where = "Moved" if self._use_trash() else "Deleted"
        target = " to the recycle bin" if self._use_trash() else ""
        msg = f"{where} {len(deleted)} file(s){target}."
        if failed:
            msg += f"  {len(failed)} failed."
            details = "\n".join(f"{p}: {err}" for p, err in failed[:8])
            if len(failed) > 8:
                details += f"\n… and {len(failed) - 8} more"
            messagebox.showwarning("Some deletions failed", details)

        self.status_var.set(msg)

    # ------------------------------------------------------------------
    # Open folder
    # ------------------------------------------------------------------

    def _open_containing_folder(self, event):
        item = self.tree.focus()
        if not item or item not in self.item_to_path:
            return
        folder = self.item_to_path[item].parent
        try:
            if sys.platform == "win32":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open folder:\n{e}")


def main():
    if sys.platform == "win32":
        try:
            from ctypes import windll

            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    app = DoppelgangerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
