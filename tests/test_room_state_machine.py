"""Property-based shared-room state machine over real GTK-free production logic.

Hypothesis shrinks a failing action history and prints a reproduction blob.
Rerun with --hypothesis-seed=<seed> or @reproduce_failure from the report.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

from hypothesis import HealthCheck, settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cast_portal_queue import PortalQueueMixin, portal_queue_id
from portal_commands import (
    CommandDispatcher, CommandError, CommandFence, CommandReceipt, MutationEnvelope,
)
from portal_room import PortalRoom


class ModelHost(PortalQueueMixin):
    """Only GTK adapters are stubbed; the public room queue algorithm is real."""

    def __init__(self):
        self.queue = []
        self.queue_durations = {}
        self.selected_index = None
        self.now_playing = None
        self.busy = False
        self._portal_queue_revision = 0
        self._portal_observe_queue()
        self.played = []

    def _enqueue(self, paths):
        for path in paths:
            if path not in self.queue:
                self.queue.append(path)

    def _remove_queue(self, index):
        self.queue.pop(index)

    def _rebuild_queue(self):
        pass

    def clear_queue(self):
        self.queue.clear()

    def _cast_path(self, path, offset):
        self.now_playing = str(path)
        self.played.append((str(path), offset))


class SharedRoomMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.now = [1000.0]
        self.room = PortalRoom(clock=lambda: self.now[0])
        self.host = ModelHost()
        self.model_queue = []
        self.participants = []
        self.model_votes = {}
        self.sequence = 0
        self.media_number = 0
        self.fence = CommandFence(clock=lambda: self.now[0])
        self.effects = 0
        self.dispatcher = CommandDispatcher(self._apply, fence=self.fence,
                                            clock=lambda: self.now[0])

    def _apply(self, command):
        self.fence.check(command.expected_session_id, command.expected_revision)
        self.effects += 1
        session, revision, _ = self.fence.snapshot()
        return CommandReceipt(command.command_id, session, revision, "accepted")

    def _live_ids(self):
        return {portal_queue_id(path) for path in self.host.queue}

    @rule()
    def join(self):
        if len(self.participants) >= 8:
            return
        self.sequence += 1
        person = self.room.join(f"Person {self.sequence}")
        self.participants.append(person.id)

    @precondition(lambda self: bool(self.participants))
    @rule(index=st.integers(min_value=0, max_value=1000))
    def leave(self, index):
        person = self.participants.pop(index % len(self.participants))
        self.room.leave(person)
        for voters in self.model_votes.values():
            voters.discard(person)

    @rule()
    def add(self):
        self.media_number += 1
        item = f"/media/{self.media_number}.mp4"
        self.host._enqueue([item])
        self.model_queue.append(item)
        self.host._portal_observe_queue()

    @precondition(lambda self: bool(self.model_queue))
    @rule(index=st.integers(0, 1000))
    def remove(self, index):
        position = index % len(self.model_queue)
        item = self.model_queue.pop(position)
        self.host._portal_queue_action("queue_remove", {
            "id": portal_queue_id(item),
            "queue_revision": self.host._portal_observe_queue(),
        })
        self.room.prune(self._live_ids())
        self.model_votes.pop(portal_queue_id(item), None)

    @precondition(lambda self: len(self.model_queue) > 1)
    @rule(source=st.integers(0, 1000), destination=st.integers(0, 1000))
    def move(self, source, destination):
        old = source % len(self.model_queue)
        new = destination % len(self.model_queue)
        item = self.model_queue.pop(old)
        self.model_queue.insert(new, item)
        self.host._portal_queue_action("queue_move", {
            "id": portal_queue_id(item),
            "position": new,
            "queue_revision": self.host._portal_observe_queue(),
        })

    @precondition(lambda self: bool(self.model_queue))
    @rule(index=st.integers(0, 1000))
    def play_now(self, index):
        item = self.model_queue[index % len(self.model_queue)]
        assert self.host._portal_queue_action("queue_play", {
            "id": portal_queue_id(item),
        }) == "Playing now."
        assert self.host.played[-1] == (item, 0.0)

    @precondition(lambda self: bool(self.participants) and bool(self.model_queue))
    @rule(person=st.integers(0, 1000), item=st.integers(0, 1000),
          value=st.booleans())
    def vote(self, person, item, value):
        participant = self.participants[person % len(self.participants)]
        media_id = portal_queue_id(self.model_queue[item % len(self.model_queue)])
        self.room.vote(participant, media_id, value)
        voters = self.model_votes.setdefault(media_id, set())
        if value:
            voters.add(participant)
        else:
            voters.discard(participant)

    @rule()
    def generation_changed(self):
        self.fence.rotate()

    @rule()
    def stale_command(self):
        before, revision, _ = self.fence.snapshot()
        self.fence.rotate()
        try:
            self.fence.check(before, revision)
        except CommandError as exc:
            assert exc.status == 409
        else:
            raise AssertionError("Stale generation accepted a mutation")

    @rule()
    def replay_command(self):
        self.sequence += 1
        session, revision, _ = self.fence.snapshot()
        command = MutationEnvelope(
            client_id=f"client{self.sequence % 4}",
            command_id=f"command{self.sequence}",
            expected_session_id=session, expected_revision=revision,
            action="play_pause", payload={},
        )
        previous_effects = self.effects
        first = self.dispatcher.execute(command)
        second = self.dispatcher.execute(command)
        assert first == second
        assert self.effects == previous_effects + 1
        changed = MutationEnvelope(
            client_id=command.client_id,
            command_id=command.command_id,
            expected_session_id=command.expected_session_id,
            expected_revision=command.expected_revision,
            action="play_pause", payload={"different": True},
        )
        try:
            self.dispatcher.execute(changed)
        except CommandError as exc:
            assert exc.status == 409
        else:
            raise AssertionError("Reused request ID with changed payload succeeded")

    @invariant()
    def queue_and_votes_match_reference(self):
        assert self.host.queue == self.model_queue
        assert len(self.host.queue) == len(set(self.host.queue))
        assert len(self._live_ids()) == len(self.host.queue)
        live = set(self.participants)
        assert set(self.room.participants) == live
        assert set(self.room.votes).issubset(self._live_ids())
        for item_id, voters in self.room.votes.items():
            assert voters == self.model_votes.get(item_id, set())
            assert voters.issubset(live)

    def teardown(self):
        self.dispatcher.close()


TestSharedRoomStateMachine = SharedRoomMachine.TestCase
TestSharedRoomStateMachine.settings = settings(
    max_examples=750 if os.getenv("SMOOTHCAST_MODEL_DEEP") == "1" else 45,
    stateful_step_count=80 if os.getenv("SMOOTHCAST_MODEL_DEEP") == "1" else 22,
    deadline=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
