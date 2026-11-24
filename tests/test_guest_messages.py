"""#600: guest-visible failures are worded once, plainly, with a next step."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import guest_messages

SRC = Path(__file__).resolve().parents[1] / "src"
JARGON = re.compile(r"\b(hosts?|receivers?|acquisitions?|acquire|worker|token|origin|offset|chunk)\b", re.I)
RETIRED = (
    "Session expired or request token invalid", "Room access was revoked",
    "Request origin is not allowed", "isolated YouTube worker",
    "external media acquisition", "Not enough space on the SmoothCast host",
    "Upload storage is unavailable", "Upload timed out. Resume from the saved position",
    "Seek position is out of range",
)


def test_every_message_is_plain_complete_and_actionable():
    names = [n for n in dir(guest_messages) if n.isupper() and n != "ALL"]
    assert sorted(names) == sorted(n for n in names if getattr(guest_messages, n) in guest_messages.ALL)
    assert len(set(guest_messages.ALL)) == len(guest_messages.ALL) == len(names)
    for message in guest_messages.ALL:
        assert not JARGON.search(message), message
        assert message[0].isupper() and message.endswith("."), message
        # what happened + what to do: at least two sentences
        assert len([s for s in message.split(". ") if s]) >= 2, message


def test_each_message_is_used_and_old_wording_is_gone():
    code = {p.name: p.read_text("utf-8") for p in SRC.glob("*.py") if p.name != "guest_messages.py"}
    for name in (n for n in dir(guest_messages) if n.isupper() and n != "ALL"):
        assert any(f"guest_messages.{name}" in text for text in code.values()), name
    for old in RETIRED:
        offenders = [file for file, text in code.items() if old in text]
        assert offenders == [], (old, offenders)
