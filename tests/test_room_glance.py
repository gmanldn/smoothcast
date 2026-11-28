"""The desktop player keeps target, Up Next and room presence in view."""
from types import SimpleNamespace

import cast_ui
import ui_tokens


class Label:
    def __init__(self):
        self.text = ""
        self.updates = 0

    def get_text(self):
        return self.text

    def set_text(self, text):
        self.text = text
        self.updates += 1


def _owner(**values):
    state = {"room_glance_values": {
                 field["key"]: Label() for field in ui_tokens.ROOM_GLANCE_FIELDS
                 if field["gtk_slot"] == "summary"
             }, "cfg": {}, "queue": [],
             "now_playing": None, "portal_guest_ids": ()}
    state.update(values)
    return SimpleNamespace(**state)


def test_room_glance_shows_next_item_without_the_current_queue_entry():
    owner = _owner(
        cfg={"device": "Living Room TV"},
        queue=["/media/current_film.mkv", "/media/next_episode_02.mkv", "/media/last.mp4"],
        now_playing="/media/current_film.mkv",
        portal_guest_online_names=("Sam", "Jo"),
    )

    cast_ui.UiMixin._sync_room_glance(owner)

    assert owner.room_glance_values["target"].text == "Living Room TV"
    assert owner.room_glance_values["next"].text == "next episode 02 · +1 more"
    assert owner.room_glance_values["people"].text == "You, Sam, Jo"


def test_room_glance_handles_empty_target_queue_and_guests_and_skips_redundant_redraw():
    owner = _owner()

    cast_ui.UiMixin._sync_room_glance(owner)
    cast_ui.UiMixin._sync_room_glance(owner)

    assert owner.room_glance_values["target"].text == "No screen selected"
    assert owner.room_glance_values["next"].text == "Nothing waiting"
    assert owner.room_glance_values["people"].text == "Just you"
    assert all(label.updates == 1 for label in owner.room_glance_values.values())


def test_room_glance_uses_first_item_when_nothing_is_currently_playing():
    owner = _owner(queue=["/media/first_song.flac", "/media/second_song.flac"])

    cast_ui.UiMixin._sync_room_glance(owner)

    assert owner.room_glance_values["next"].text == "first song · +1 more"
