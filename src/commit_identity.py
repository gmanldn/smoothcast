"""Canonical commit display identity: committer date plus a stable weapon alias.

The web room, screen and nodes headers show ``vX.Y.Z - YYYY-MM-DD HHMM - Codename``
for the commit the running process was loaded from. The date and time come from the
commit object in its recorded timezone and the codename is derived
deterministically from the full SHA, so both stay bound to that commit.

Everything here is offline and bounded: loose objects and non-delta packed
commit objects are read directly, without a Git subprocess or network. Anything
malformed, oversized, delta-packed or unreadable fails closed to ``None`` so a
caller never displays an invented identity.

The codename is a disposable mnemonic, not canonical data: it is two weapons
from :data:`WEAPON_NAMES` joined by ``-``, so consecutive commits almost never
repeat. The committer date remains the authoritative high-water mark, and
nothing depends on an alias staying stable across releases.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import mmap
from pathlib import Path
import re
import zlib

WEAPON_NAMES = (
    "Adze", "Arbalest", "Atlatl", "Bardiche", "Battleaxe", "Bayonet", "Bill",
    "Bola", "Broadsword", "Cestus", "Chakram", "Claymore", "Crossbow",
    "Cutlass", "Dagger", "Dao", "Dirk", "Falchion", "Flail", "Glaive",
    "Gladius", "Guisarme", "Halberd", "Harpoon", "Javelin", "Kama", "Kanabo",
    "Katana", "Katar", "Khopesh", "Kukri", "Kusarigama", "Lance", "Longbow",
    "Longsword", "Mace", "Macuahuitl", "Machete", "Maul", "Morningstar",
    "Nodachi", "Partisan", "Pata", "Pike", "Poleaxe", "Quarterstaff", "Rapier",
    "Sabre", "Sai", "Scimitar", "Shamshir", "Shortsword", "Sickle", "Sling",
    "Spear", "Spontoon", "Stiletto", "Tabar", "Talwar", "Tanto", "Tomahawk",
    "Trident", "Warhammer", "Yatagan",
)

ADJECTIVE_NAMES = (
    "Gawping", "Rustic", "Naked", "Fissile", "Blazing", "Savage", "Silent",
    "Howling", "Crimson", "Iron", "Glass", "Shadow", "Frozen", "Burning",
    "Hollow", "Jagged", "Lethal", "Molten", "Noisy", "Pale", "Quaking",
    "Roaring", "Sharp", "Tangled", "Vicious", "Wicked", "Ancient", "Broken",
    "Cursed", "Dusty", "Eager", "Feral", "Grim", "Heavy", "Idle", "Jolly",
    "Keen", "Lone", "Mad", "Nimble", "Old", "Proud", "Quick", "Ragged",
    "Stark", "Tired", "Unholy", "Vast", "Wild", "Young", "Zealous", "Bitter",
    "Calm", "Daring", "Eerie", "Fierce", "Gentle", "Happy", "Icy", "Jumpy",
    "Kind", "Loud", "Meek", "Nervous",
)

_SHA = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?: [0-9]{4})?\Z")
_OFFSET = re.compile(rb"[+-]\d{4}\Z")
_OBJECT_LIMIT = 4 * 1024 * 1024
_INDEX_LIMIT = 64 * 1024 * 1024
_MARKER_LIMIT = 128
_MARKER = Path("src") / ".smoothcast-build"


def codename(revision: str | None) -> str | None:
    """Disposable two-weapon alias for a commit; ``None`` without a valid SHA.

    Two words are drawn from :data:`WEAPON_NAMES` by independent digest bytes
    (``64 * 64`` combinations) and joined by ``-``, so consecutive commits
    almost never repeat. The alias is a pure function of the commit SHA but is
    disposable: unlike the committer date it carries no canonical meaning.
    """
    if not revision or not _SHA.fullmatch(revision):
        return None
    digest = hashlib.sha256(revision.lower().encode("ascii")).digest()
    adj_size = len(ADJECTIVE_NAMES)
    weapon_size = len(WEAPON_NAMES)
    adjective = ADJECTIVE_NAMES[digest[0] % adj_size]
    weapon = WEAPON_NAMES[digest[1] % weapon_size]
    return f"{adjective}-{weapon}"


def _valid_date(value: str) -> bool:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value[:10])
        # Legacy installed markers have a date only; never invent midnight.
        if len(value) > 10:
            if int(value[11:13]) > 23 or int(value[13:15]) > 59:
                return False
    except ValueError:
        return False
    return True


def display_label(version_label: str, revision: str | None,
                  commit_date: str | None) -> str:
    """Version label plus proven commit date and codename; omit unknown parts."""
    word = codename(revision)
    if word is None:
        return version_label
    parts = [version_label]
    if commit_date and _valid_date(commit_date):
        parts.append(commit_date)
    parts.append(word)
    return " - ".join(parts)


def _read_small(path: Path, size: int = _MARKER_LIMIT) -> str | None:
    try:
        with path.open("rb") as fh:
            raw = fh.read(size + 1)
        return raw.decode("ascii") if len(raw) <= size else None
    except (OSError, UnicodeError):
        return None


def _marker_date(repo: Path, revision: str) -> str | None:
    marker = Path(repo) / _MARKER
    if marker.is_symlink() or not marker.is_file():
        return None
    raw = _read_small(marker)
    if raw is None:
        return None
    lines = raw.splitlines()
    if len(lines) < 2 or lines[0].strip().lower() != revision.lower():
        return None
    value = lines[1].strip()
    return value if _valid_date(value) else None


def _git_dirs(repo: Path) -> tuple[Path, Path] | None:
    dot_git = Path(repo) / ".git"
    if dot_git.is_file():
        pointer = _read_small(dot_git, 1024)
        if not pointer or not pointer.startswith("gitdir: "):
            return None
        folder = Path(pointer[8:].strip())
        gitdir = (folder if folder.is_absolute()
                  else dot_git.parent / folder).resolve()
    elif dot_git.is_dir():
        gitdir = dot_git
    else:
        return None
    common = gitdir
    common_text = _read_small(gitdir / "commondir", 1024)
    if common_text:
        folder = Path(common_text.strip())
        common = (folder if folder.is_absolute() else gitdir / folder).resolve()
    return gitdir, common


def _read_bytes(path: Path, limit: int) -> bytes | None:
    try:
        with path.open("rb") as fh:
            raw = fh.read(limit + 1)
    except (OSError, ValueError):
        return None
    return raw if len(raw) <= limit else None


def _inflate(data: bytes, limit: int, *, trailing_ok: bool) -> bytes | None:
    inflater = zlib.decompressobj()
    try:
        out = inflater.decompress(data, limit + 1)
    except zlib.error:
        return None
    if len(out) > limit or inflater.unconsumed_tail or not inflater.eof:
        return None
    if inflater.unused_data and not trailing_ok:
        return None
    return out


def _inflate_stream(fh, limit: int) -> bytes | None:
    inflater = zlib.decompressobj()
    out = bytearray()
    pending = b""
    while not inflater.eof:
        chunk = pending or fh.read(64 * 1024)
        pending = b""
        if not chunk:
            return None
        try:
            out += inflater.decompress(chunk, limit + 1 - len(out))
        except zlib.error:
            return None
        if len(out) > limit:
            return None
        pending = inflater.unconsumed_tail
    return bytes(out)


def _loose_commit(objects: Path, sha: str) -> bytes | None:
    raw = _read_bytes(objects / sha[:2] / sha[2:], 16 * 1024 * 1024)
    if raw is None:
        return None
    data = _inflate(raw, _OBJECT_LIMIT + 64, trailing_ok=False)
    if data is None:
        return None
    header, separator, content = data.partition(b"\0")
    kind, space, size = header.partition(b" ")
    if not separator or not space or kind != b"commit" or not size.isdigit():
        return None
    if len(size) > 12 or int(size) != len(content):
        return None
    return content if len(content) <= _OBJECT_LIMIT else None


def _be(view: mmap.mmap, start: int, width: int) -> int | None:
    if start < 0 or start + width > len(view):
        return None
    return int.from_bytes(view[start:start + width], "big")


def _idx_offset(view: mmap.mmap, sha: str, hash_size: int) -> int | None:
    """Locate *sha* in a version-2 pack index without loading the whole file."""
    if len(view) < 8 + 1024 + 4 or view[:4] != b"\xfftOc":
        return None
    if _be(view, 4, 4) != 2:
        return None
    fanout = 8
    previous = 0
    for bucket in range(256):
        value = _be(view, fanout + bucket * 4, 4)
        if value is None or value < previous:
            return None
        previous = value
    count = previous
    if count < 1:
        return None
    hashes = fanout + 1024
    crc_start = hashes + count * hash_size
    offsets = crc_start + count * 4
    large = offsets + count * 4
    if large > len(view):
        return None
    first = int(sha[:2], 16)
    lo = _be(view, fanout + (first - 1) * 4, 4) if first else 0
    hi = _be(view, fanout + first * 4, 4)
    if lo is None or hi is None or lo > hi:
        return None
    target = bytes.fromhex(sha)
    while lo < hi:
        middle = (lo + hi) // 2
        start = hashes + middle * hash_size
        if start + hash_size > len(view):
            return None
        candidate = view[start:start + hash_size]
        if candidate < target:
            lo = middle + 1
        elif candidate > target:
            hi = middle
        else:
            value = _be(view, offsets + middle * 4, 4)
            if value is None:
                return None
            if value & 0x80000000:
                value = _be(view, large + (value & 0x7FFFFFFF) * 8, 8)
                if value is None:
                    return None
            return value if value >= 12 else None
    return None


def _pack_header(fh) -> tuple[int, int] | None:
    raw = fh.read(1)
    if not raw:
        return None
    value = raw[0]
    kind = (value >> 4) & 7
    size = value & 15
    shift = 4
    while value & 0x80:
        raw = fh.read(1)
        if not raw:
            return None
        value = raw[0]
        size |= (value & 0x7F) << shift
        shift += 7
        if shift > 63:
            return None
    return kind, size


def _pack_object(pack: Path, offset: int) -> bytes | None:
    try:
        with pack.open("rb") as fh:
            header = fh.read(12)
            if len(header) != 12 or header[:4] != b"PACK":
                return None
            if int.from_bytes(header[4:8], "big") not in (2, 3):
                return None
            fh.seek(0, 2)
            if offset < 12 or offset >= fh.tell():
                return None
            fh.seek(offset)
            kind_size = _pack_header(fh)
            if kind_size is None:
                return None
            kind, declared = kind_size
            if kind != 1 or declared > _OBJECT_LIMIT:  # 1 == non-delta commit
                return None
            content = _inflate_stream(fh, _OBJECT_LIMIT)
            if content is None or len(content) != declared:
                return None
            return content
    except (OSError, ValueError):
        return None


def _packed_commit(objects: Path, sha: str) -> bytes | None:
    try:
        indexes = sorted((objects / "pack").glob("*.idx"))
    except OSError:
        return None
    hash_size = len(sha) // 2
    for index in indexes:
        if index.is_symlink():
            continue
        offset = None
        try:
            if index.stat().st_size <= _INDEX_LIMIT:
                with index.open("rb") as fh:
                    with mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as view:
                        offset = _idx_offset(view, sha, hash_size)
        except (OSError, ValueError, BufferError):
            offset = None
        if offset is None:
            continue
        pack = index.with_suffix(".pack")
        if pack.is_symlink() or not pack.is_file():
            return None
        return _pack_object(pack, offset)
    return None


def _commit_content(objects: Path, sha: str) -> bytes | None:
    loose = objects / sha[:2] / sha[2:]
    if loose.is_file() or loose.is_symlink():
        return _loose_commit(objects, sha)
    return _packed_commit(objects, sha)


def _commit_date(content: bytes) -> str | None:
    header = content.split(b"\n\n", 1)[0]
    for line in header.split(b"\n"):
        if not line.startswith(b"committer "):
            continue
        parts = line.rsplit(b" ", 2)
        if len(parts) != 3:
            return None
        stamp, zone = parts[1], parts[2]
        if not stamp.isdigit() or len(stamp) > 12 or not _OFFSET.fullmatch(zone):
            return None
        sign = -1 if zone[:1] == b"-" else 1
        hours, minutes = int(zone[1:3]), int(zone[3:5])
        if hours > 23 or minutes > 59:
            return None
        offset = sign * (hours * 3600 + minutes * 60)
        if abs(offset) >= 86_400:
            return None
        try:
            moment = datetime.fromtimestamp(
                int(stamp), timezone(timedelta(seconds=offset)))
        except (OverflowError, OSError, ValueError):
            return None
        return f"{moment.date().isoformat()} {moment:%H%M}"
    return None


def read_checkout_commit_date(repo: Path, revision: str | None) -> str | None:
    """Committer date and HHMM (commit's own timezone); legacy marker date allowed."""
    if not revision or not _SHA.fullmatch(revision):
        return None
    rev = revision.lower()
    dirs = _git_dirs(repo)
    if dirs is None:
        if (Path(repo) / ".git").exists():
            return None
        return _marker_date(repo, rev)
    content = _commit_content(dirs[1] / "objects", rev)
    return None if content is None else _commit_date(content)