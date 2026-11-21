"""Library folders a node indexes and shares with the house (issue #407).

Pure, GTK-free model for the ``library_folders`` config list described in
docs/MESH_SEARCH.md section 1.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import secrets

KINDS = ("auto", "video", "music", "photos")
MAX_FOLDERS = 32
MAX_LABEL = 40


@dataclass(frozen=True)
class LibraryFolder:
    id: str
    path: str
    label: str
    kind: str = "auto"
    shared: bool = True

    def to_config(self) -> dict:
        return {"id": self.id, "path": self.path, "label": self.label,
                "kind": self.kind, "shared": self.shared}


def clean_label(value: object) -> str:
    text = " ".join(str(value or "").split())
    return "".join(ch for ch in text if ch.isprintable())[:MAX_LABEL]


def _resolved(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _inside(child: str, parent: str) -> bool:
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:  # different drives
        return False


def load(cfg: dict) -> list[LibraryFolder]:
    """Valid folders from config; malformed rows are dropped, never raised."""
    rows = cfg.get("library_folders") if isinstance(cfg, dict) else None
    folders: list[LibraryFolder] = []
    seen_ids: set[str] = set()
    seen_labels: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or len(folders) >= MAX_FOLDERS:
            continue
        path, label = row.get("path"), clean_label(row.get("label"))
        raw_kind = row.get("kind")
        kind = raw_kind if isinstance(raw_kind, str) and raw_kind in KINDS else "auto"
        ident = row.get("id")
        if not isinstance(path, str) or not os.path.isabs(path) or not label:
            continue
        if not isinstance(ident, str) or not ident or ident in seen_ids:
            ident = "f_" + secrets.token_hex(6)
        if label.casefold() in seen_labels:
            continue
        seen_ids.add(ident)
        seen_labels.add(label.casefold())
        folders.append(LibraryFolder(ident, path, label, kind, bool(row.get("shared", True))))
    return folders


def to_config(folders: list[LibraryFolder]) -> list[dict]:
    return [folder.to_config() for folder in folders]


def validate_new(existing: list[LibraryFolder], path: str, label: str) -> str | None:
    """Return a user-facing error, or None when the folder may be added."""
    if len(existing) >= MAX_FOLDERS:
        return f"You can share at most {MAX_FOLDERS} folders."
    if not isinstance(path, str) or not os.path.isabs(path) or not os.path.isdir(path):
        return "Choose an existing folder."
    resolved = _resolved(path)
    if resolved == _resolved(os.sep) or os.path.splitdrive(resolved)[1] in ("", os.sep):
        return "Choose a folder, not a whole drive."
    if resolved == _resolved(str(Path.home())):
        return "Choose a folder inside your home folder, not the home folder itself."
    name = clean_label(label)
    if not name:
        return "Give the folder a name."
    if any(folder.label.casefold() == name.casefold() for folder in existing):
        return f"There is already a folder called “{name}”."
    for folder in existing:
        other = _resolved(folder.path)
        if resolved == other or _inside(resolved, other):
            return f"That folder is already inside “{folder.label}”."
        if _inside(other, resolved):
            return f"That folder contains “{folder.label}”. Remove it first."
    return None


def add(existing: list[LibraryFolder], path: str, label: str = "",
        kind: str = "auto", shared: bool = True) -> tuple[list[LibraryFolder], str | None]:
    """Validate and append; returns (new list, error)."""
    name = clean_label(label) or clean_label(Path(path).name)
    error = validate_new(existing, path, name)
    if error:
        return existing, error
    folder = LibraryFolder("f_" + secrets.token_hex(6), os.path.realpath(path), name,
                           kind if kind in KINDS else "auto", shared)
    return [*existing, folder], None


def update(folders: list[LibraryFolder], folder_id: str, **changes) -> list[LibraryFolder]:
    out = []
    for folder in folders:
        if folder.id != folder_id:
            out.append(folder)
            continue
        label = clean_label(changes.get("label", folder.label)) or folder.label
        if any(other.id != folder_id and other.label.casefold() == label.casefold()
               for other in folders):
            label = folder.label
        kind = changes.get("kind", folder.kind)
        out.append(LibraryFolder(folder.id, folder.path, label,
                                 kind if kind in KINDS else folder.kind,
                                 bool(changes.get("shared", folder.shared))))
    return out


def remove(folders: list[LibraryFolder], folder_id: str) -> list[LibraryFolder]:
    return [folder for folder in folders if folder.id != folder_id]
