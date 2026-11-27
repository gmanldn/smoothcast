import device_presets as dp


def test_clean_drops_unsafe_values():
    assert dp.clean({"codec": "av1", "subtitles": "burn", "bitrate_kbps": 10**9,
                     "volume": 1.5, "evil": 1}) == {"subtitles": "burn"}
    assert dp.clean({"bitrate_kbps": True, "volume": float("nan")}) == {}
    assert dp.clean("x") == {}


def test_remember_merges_and_get_returns_validated():
    cfg = {}
    dp.remember(cfg, "Living Room", codec="h264", bitrate_kbps=8000)
    dp.remember(cfg, "Living Room", subtitles="sidecar", volume=0.4)
    assert dp.get(cfg, "Living Room") == {
        "codec": "h264", "bitrate_kbps": 8000, "subtitles": "sidecar", "volume": 0.4}
    assert dp.get(cfg, "Kitchen") == {}


def test_reset_is_obvious_and_idempotent():
    cfg = {}
    dp.remember(cfg, "tv", codec="hevc")
    assert dp.reset(cfg, "tv") is True and dp.get(cfg, "tv") == {}
    assert dp.reset(cfg, "tv") is False


def test_corrupt_config_and_entry_cap():
    assert dp.get({"device_presets": "junk"}, "tv") == {}
    cfg = {"device_presets": "junk"}
    dp.remember(cfg, "tv", codec="h264")
    assert dp.get(cfg, "tv") == {"codec": "h264"}
    for i in range(dp.MAX_ENTRIES + 5):
        dp.remember(cfg, f"r{i}", codec="h264")
    assert len(cfg["device_presets"]) == dp.MAX_ENTRIES
