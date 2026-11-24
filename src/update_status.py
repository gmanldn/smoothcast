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
_COMMIT = re.compile(r"[0-9a-f]{7,64}")
_EXACT_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
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
    staged_commit: str | None = None      # independently verified staged generation


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


def _exact(commit: str | None) -> str | None:
    """Only a complete object ID can establish build identity."""
    value = (commit or "").strip().lower()
    return value if _EXACT_COMMIT.fullmatch(value) else None


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
    running_id, active_id, candidate_id, previous_id, staged_id = (
        _exact(value) for value in
        (f.running_commit, f.active_commit, f.candidate, f.previous_commit, f.staged_commit)
    )

    def make(state: str, headline: str, detail: str, *actions: str, new: bool = False) -> UpdateStatus:
        return UpdateStatus(state, headline, detail, running, channel_line, actions, new)

    if f.fault in FAULTS:
        retry = ("check_now",) if f.fault == "bad_signature" else ("retry", "check_now")
        return make("fault", "Update not installed", FAULTS[f.fault], *retry)
    if f.journal_state == "rolled_back" and f.phase == "idle":
        # active.json's previous is the pre-existing rollback reference,
        # not necessarily the generation that was just restored.
        detail = (
            f"The previous build {short(running_id)} is running again."
            if active_id is not None and active_id == running_id
            else "The previous generation was selected, but its running build is not confirmed."
        )
        return make("rolled_back", "Update rolled back", detail, "check_now")
    if f.journal_state == "aborted" and f.phase == "idle":
        return make("aborted", "Update cancelled", "Nothing was changed. The current version keeps running.",
                    "check_now")
    if f.journal_state in {"planned", "probed"}:
        return make("preparing", "Preparing the switch…", "The current version keeps running until it is ready.",
                    "cancel")
    if f.journal_state == "switched":
        return make("confirming", "Waiting for the new version to confirm…",
                    "If it does not confirm, SmoothCast returns to the previous version.")
    if f.journal_state == "acked":
        if active_id is not None and active_id != running_id:
            return make("activation_mismatch", "Running build differs from the activated build",
                        "The activated generation is not the one reporting this status.", "check_now")
        # A durable terminal journal outlives its transaction; it must not
        # mask a newer check, download or staged candidate.
        if (f.phase == "idle" and candidate_id in (None, running_id)
                and active_id is not None and active_id == running_id
                and previous_id and previous_id != running_id):
            return make("running_new", "Updated",
                        f"SmoothCast is running {short(running_id)}.", "rollback", "check_now", new=True)
    if not f.checks_enabled:
        return make("off", "Update checks are off",
                    "SmoothCast will not look for updates until you turn checks on.", "enable_checks")
    if f.phase == "checking":
        return make("checking", "Checking for updates…", "This does not interrupt playback.", "cancel")
    # A relaxed read-only check policy never authorises an unsigned activation.
    untrusted = (f.require_signature or f.phase == "staged") and f.candidate and f.candidate_signed is not True
    if untrusted and (f.phase != "idle" or f.candidate_signed is False):
        if f.candidate_signed is False:
            return make("untrusted", "Update not trusted", FAULTS["bad_signature"], "check_now")
        return make("verifying", "Verifying the update signature…", "It stays unused until it is trusted.", "cancel")
    if f.phase == "staged":
        # Staging never changes active.json. Bind the signature to the exact
        # independently verified staged generation, not the active reference.
        if candidate_id is None or staged_id != candidate_id or running_id is None:
            return make("unconfirmed", "Staged update not confirmed",
                        "The candidate, staged generation and running build must be identified before restarting.",
                        "check_now")
        if active_id is not None and active_id != running_id:
            return make("activation_mismatch", "Running build differs from the activated build",
                        "The activated generation is not the one reporting this status.", "check_now")
        if staged_id == running_id:
            return make("current", "SmoothCast is running the staged build",
                        f"The running build is {short(running_id)}.", "check_now")
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
    if candidate_id is None or running_id is None:
        return make("unchecked", "Update status not confirmed",
                    "Check for updates to compare the running build with the selected channel.", "check_now")
    if candidate_id != running_id:
        return make("available", "Update available",
                    f"Build {short(candidate_id)} is available on {channel}. Nothing is installed yet.",
                    "check_now")
    return make("current", "SmoothCast is up to date", f"You are running the latest {channel} build.", "check_now")
