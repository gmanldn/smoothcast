"""Release gate for GPLv3-or-later distribution (#538): notices, corresponding-source pin and FFmpeg disclosure.

Pure: callers pass file text and the release facts; nothing is fetched. Returns a list of failures (empty = pass).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = "https://github.com/gmanldn/smoothcast"
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def check(license_text: str, notice_text: str, offer: dict, *, version: str, tag_sha: str, about_text: str = "") -> list[str]:
    bad: list[str] = []
    if "GNU GENERAL PUBLIC LICENSE" not in license_text or "Version 3, 29 June 2007" not in license_text:
        bad.append("LICENSE is not the unmodified GNU GPL version 3 text")
    if "SPDX-License-Identifier: GPL-3.0-or-later" not in notice_text:
        bad.append("NOTICE lacks 'SPDX-License-Identifier: GPL-3.0-or-later'")
    if "GPL-3.0-only" in notice_text or "GPL-3.0-only" in about_text:
        bad.append("GPL-3.0-only is not the project licence")
    if "WITHOUT ANY" not in notice_text or "WARRANTY" not in notice_text:
        bad.append("NOTICE lacks the no-warranty statement")
    if "Third-party components" not in notice_text:
        bad.append("NOTICE lacks the third-party licence statement")
    if REPO not in notice_text:
        bad.append("NOTICE does not name the source repository")
    if about_text and REPO not in about_text:
        bad.append("About/help does not expose the source repository")
    if not isinstance(offer, dict):
        return bad + ["source offer is missing"]
    if offer.get("repo") != REPO:
        bad.append("source offer names a different repository")
    if offer.get("tag") != f"v{version}":
        bad.append(f"source offer tag {offer.get('tag')!r} does not match v{version}")
    sha = offer.get("sha")
    if not (isinstance(sha, str) and _SHA.match(sha)):
        bad.append("source offer SHA is not a full 40-character commit")
    elif sha != tag_sha:
        bad.append("source offer SHA does not match the release tag commit")
    ff = offer.get("ffmpeg")
    if ff:                                                    # a binary FFmpeg is shipped: it needs its own disclosure (#529)
        if ff.get("licence") not in ("GPL-2.0-or-later", "GPL-3.0-or-later", "LGPL-2.1-or-later", "LGPL-3.0-or-later"):
            bad.append("FFmpeg licence is not declared as a known GPL/LGPL variant")
        if not str(ff.get("source_url", "")).startswith("https://"):
            bad.append("FFmpeg corresponding-source URL is missing or not https")
        if not _SHA256.match(str(ff.get("source_sha256", ""))):
            bad.append("FFmpeg source archive SHA-256 is missing")
        if not ff.get("build_flags"):
            bad.append("FFmpeg build configuration is not recorded")
    return bad


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(".")
    try:
        offer = json.loads((root / "source-offer.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        offer = None
    sys.path.insert(0, str(root / "src"))
    from version import __version__ as version
    problems = check((root / "LICENSE").read_text(encoding="utf-8"), (root / "packaging" / "SmoothCast-NOTICE.txt").read_text(encoding="utf-8"),
                     offer, version=version, tag_sha=argv[2] if len(argv) > 2 else "")  # argv[2] = `git rev-parse vX.Y.Z^{commit}`
    for p in problems:
        print("FAIL:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
