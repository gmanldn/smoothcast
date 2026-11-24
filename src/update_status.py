"""GTK-free update status model for Preferences and the room remote (#582).

One pure function turns what is *known* about an update (running build, channel,
candidate, signature, activation journal, playback) into plain words and the
actions that are safe right now. Core rule: fetching files never means an update
is running; "Running" is shown only when the running commit is the activated
generation, and a staged update never restarts the app during playback.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

CHANNELS = ("develop", "main")
_COMMIT = re.compile(r"[0-9a-f]{7,40}")
# Faults map to a civil sentence plus the ordered next step (docs/UX_COPY.md).
FAULTS = {
    "offline": "SmoothCast could not reach the update source. Check your network connection, then check again.",
    "timeout": "The update source did not answer in time. Check again on a steadier connection.",
    "bad_signature": "The update is not signed by a trusted key, so it was not installed. Keep the current version.",
    "verification_failed": "The downloaded update did not match its checksum and was discarded. Check again.",
    "disk_full": "There is not enough disk space to stage the update. Free some space, then retry.",
}
PHASES = ("idle", "checking", "downloaded", "verified", "staged")


@dataclass(frozen=True)
class UpdateFacts:
    running_version: str = ""
    running_commit: str | None = None
    channel: str = "develop"
    checks_enabled: bool = False
    require_signature: bool = True
    candidate: str | None = None          # commit found by the last check
    candidate_signed: bool | None = None  # None: not checked yet
    phase: str = "idle"                   # one of PHASES
    active_commit: str | None = None      # activation reference (managed install)
    previous_commit: str | None = None
    journal_state: str | None = None      # planned|probed|switched|acked|rolled_back|aborted
    playing: bool = False
    fault: str | None = None


@dataclass(frozen=True)
class UpdateStatus:
    state: str
    headline: str
    detail: str
    running_line: str
    channel_line: str
    actions: tuple[str, ...] = field(default=())
    running_new_version: bool = False

    @property
    def accessible_label(self) -> str:
        return f"{self.headline}. {self.detail}"


def short(commit: str | None) -> str:
    text = (commit or "").strip().lower()
    return text[:7] if _COMMIT.fullmatch(text) else "unknown"


def _channel(value: str) -> tuple[str, str]:
    if value == "main":
        return "main", "Channel: main (released builds only)"
    if value == "develop":
        return "develop", "Channel: develop (default)"
    return "develop", "Channel: develop (default); the saved channel was not recognised"


def describe(f: UpdateFacts) -> UpdateStatus:
    """Plain-language state and the safe actions for it."""
    channel, channel_line = _channel(f.channel)
    version = f.running_version.strip() or "unknown version"
    running = f"SmoothCast {version} ({short(f.running_commit)}) on {channel}"

    def make(state: str, headline: str, detail: str, *actions: str, new: bool = False) -> UpdateStatus:
        return UpdateStatus(state, headline, detail, running, channel_line, actions, new)

    if f.fault in FAULTS:
        retry = ("check_now",) if f.fault == "bad_signature" else ("retry", "check_now")
        return make("fault", "Update not installed", FAULTS[f.fault], *retry)
    if f.journal_state == "rolled_back":
        return make("rolled_back", "Update rolled back",
                    f"The new version did not confirm, so {short(f.previous_commit)} is running again. "
                    "Your queue and settings are unchanged.", "check_now")
    if f.journal_state == "aborted":
        return make("aborted", "Update cancelled", "Nothing was changed. The current version keeps running.",
                    "check_now")
    if f.journal_state in {"planned", "probed"}:
        return make("preparing", "Preparing the switch…", "The current version keeps running until it is ready.",
                    "cancel")
    if f.journal_state == "switched":
        return make("confirming", "Waiting for the new version to confirm…",
                    "If it does not confirm, SmoothCast returns to the previous version.")
    if (f.journal_state == "acked" and f.active_commit and f.active_commit == f.running_commit
            and f.previous_commit and f.previous_commit != f.running_commit):
        return make("running_new", "Updated",
                    f"SmoothCast is running {short(f.running_commit)}.", "rollback", "check_now", new=True)
    if not f.checks_enabled:
        return make("off", "Update checks are off",
                    "SmoothCast will not look for updates until you turn checks on.", "enable_checks")
    if f.phase == "checking":
        return make("checking", "Checking for updates…", "This does not interrupt playback.", "cancel")
    untrusted = f.require_signature and f.candidate and f.candidate_signed is not True
    if untrusted and f.phase != "idle":
        if f.candidate_signed is False:
            return make("untrusted", "Update not trusted", FAULTS["bad_signature"], "check_now")
        return make("verifying", "Verifying the update signature…", "It stays unused until it is trusted.", "cancel")
    if f.active_commit and f.active_commit != f.running_commit and f.phase in {"staged", "verified"}:
        if f.playing:
            return make("awaiting_idle", "Update staged, waiting for playback to end",
                        "It is downloaded and verified but not running. SmoothCast will not restart during "
                        "playback.", "restart_when_idle")
        return make("ready", "Update staged, not yet running",
                    "Restart SmoothCast when you are ready. Nothing changes until you do.", "restart_now",
                    "restart_when_idle")
    if f.phase == "downloaded":
        return make("downloaded", "Update downloaded, not yet verified",
                    "It is not used until it has been verified.", "cancel")
    if f.phase == "verified":
        return make("verified", "Update verified, not yet staged",
                    "It will be prepared in the background. It is not running.", "cancel")
    if f.candidate and short(f.candidate) != short(f.running_commit):
        return make("available", "Update available",
                    f"Version {short(f.candidate)} is available on {channel}. Nothing is installed yet.",
                    "check_now")
    return make("current", "SmoothCast is up to date", f"You are running the latest {channel} build.", "check_now")
