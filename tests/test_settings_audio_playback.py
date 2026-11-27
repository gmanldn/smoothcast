import settings as st


def test_defaults_match_the_documented_defaults():
    s = st.Settings.from_config({})
    assert (s.audio.gain, s.audio.loudness, s.audio.music_autogain) == (6.0, "off", False)
    assert (s.playback.speed, s.playback.sleep_fade_seconds, s.playback.loop) == (1.0, 30, False)


def test_corrupt_values_fall_back_instead_of_crashing():
    s = st.Settings.from_config({"audio_gain": "loud", "audio_loudness": "extreme", "music_autogain": "yes",
                                 "playback_speed": float("nan"), "sleep_fade_seconds": None, "loop": 1})
    assert s.audio == st.AudioSettings() and s.playback == st.PlaybackSettings()


def test_out_of_range_values_are_clamped():
    s = st.Settings.from_config({"playback_speed": 99, "audio_gain": -5, "sleep_fade_seconds": 9999})
    assert (s.playback.speed, s.audio.gain, s.playback.sleep_fade_seconds) == (4.0, 0.0, 600)


def test_valid_values_pass_through():
    s = st.Settings.from_config({"audio_loudness": "album", "playback_speed": 1.5, "loop_all": True})
    assert (s.audio.loudness, s.playback.speed, s.playback.loop_all) == ("album", 1.5, True)
