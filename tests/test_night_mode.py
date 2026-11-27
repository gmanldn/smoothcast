import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import night_mode as nm


def test_golden_filter_strings_per_level_and_layout():
    assert nm.night_filter("off") == "" and nm.night_filter("bogus") == "" and nm.night_filter(None) == ""
    assert nm.night_filter("light") == "acompressor=threshold=-26dB:ratio=2.5:attack=20:release=250:makeup=3,equalizer=f=3000:t=q:w=1.2:g=2"
    assert nm.night_filter("strong") == "acompressor=threshold=-32dB:ratio=5:attack=10:release=200:makeup=6,equalizer=f=3000:t=q:w=1.2:g=4"
    sur = nm.night_filter("strong", 6); assert sur.startswith("pan=5.1|") and "FC=1.4*FC" in sur and "acompressor" in sur
    assert nm.night_filter("light", 1) == nm.night_filter("light", 2)


def test_filter_order_downmix_night_eq_limiter_documented_and_enforced():
    assert nm.ORDER == ("downmix", "night", "eq", "limiter")
    c = nm.chain("light", 6, downmix="pan=stereo|FL=FC", eq="equalizer=f=100:g=3")
    i = [c.index(x) for x in ("pan=stereo", "acompressor", "equalizer=f=100", "alimiter")]
    assert i == sorted(i) and "pan=5.1" not in c                 # already downmixed -> no surround chain
    assert nm.chain("off", 2) == nm.LIMITER and nm.chain("off", 2, limiter=False) == "" and nm.chain("strong", 2, limiter=False).startswith("acompressor")


def test_quiet_hours_midnight_safe():
    assert nm.in_quiet_hours(23 * 60, 22 * 60, 7 * 60) and nm.in_quiet_hours(60, 22 * 60, 7 * 60) and not nm.in_quiet_hours(12 * 60, 22 * 60, 7 * 60)
    assert nm.in_quiet_hours(7 * 60 - 1, 22 * 60, 7 * 60) and not nm.in_quiet_hours(7 * 60, 22 * 60, 7 * 60)
    assert nm.in_quiet_hours(13 * 60, 12 * 60, 14 * 60) and not nm.in_quiet_hours(5, 600, 600)


def test_toggle_preserves_position_budget_and_video_copy():
    p = nm.toggle("off", "light", 1234.5, direct_play=True, has_video=True)
    assert p == {"restart": True, "seek_to": 1234.5, "budget_s": 2.0, "reason": "audio_filter_changed", "video": "copy", "audio": "transcode"}
    assert nm.toggle("light", "light", 5, True, True) == {"restart": False}
    assert nm.toggle("strong", "off", 90, True, True)["audio"] == "copy" and nm.toggle("strong", "off", 90, False, True)["audio"] == "transcode"
    assert nm.toggle("off", "strong", 1, False, False)["video"] == "none" and nm.toggle("off", "strong", 1, False, True, audio_only_cast=True)["video"] == "none"
    assert nm.toggle("off", "light", -5, True, True)["seek_to"] == 0.0


def test_fake_streamer_restart_keeps_source_time():
    class Fake:
        def __init__(self): self.pos, self.level, self.starts = 0.0, "off", []
        def apply(self, new):
            plan = nm.toggle(self.level, new, self.pos, True, True)
            if plan["restart"]:
                self.starts.append(plan["seek_to"])
            self.level = new
    f = Fake(); f.pos = 600.25; f.apply("strong"); f.pos = 700; f.apply("off"); f.apply("off")
    assert f.starts == [600.25, 700.0]


def test_room_levels_persist_and_auto_quiet_hours(tmp_path):
    r = nm.Rooms(tmp_path / "n.json"); r.set("Lounge", "strong"); r.set("Bed", auto=(22 * 60, 7 * 60), auto_level="light")
    r2 = nm.Rooms(tmp_path / "n.json")
    assert r2.level("Lounge", 12 * 60) == "strong" and r2.level("Bed", 23 * 60) == "light" and r2.level("Bed", 12 * 60) == "off" and r2.level("Nowhere", 0) == "off"
    r2.set("Bed", "strong"); assert r2.level("Bed", 12 * 60) == "strong"          # manual level beats the schedule
    (tmp_path / "bad.json").write_text("[1]"); assert nm.Rooms(tmp_path / "bad.json").level("x", 0) == "off"
    assert nm.LABEL == "Night mode" and nm.SUBLABEL == "Softer bangs, clearer voices"
