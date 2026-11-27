import equalizer as eq


def test_flat_and_unknown_emit_no_filter():
    assert eq.filter_args("flat") == []
    assert eq.filter_args("nonsense") == []
    assert eq.filter_args(None) == []


def test_bass_preset_preamps_against_clipping():
    chain = eq.filter_args("bass")
    assert chain[0] == "volume=-6.0dB"
    assert "equalizer=f=31:t=o:w=1:g=6.0" in chain
    assert not any("f=1000:" in c for c in chain)


def test_custom_curve_is_clamped_and_validated():
    assert eq.gains_for("custom", [99] + [0] * 9)[0] == eq.MAX_GAIN_DB
    assert eq.gains_for("custom", [0] * 3) == (0,) * 10
    assert eq.gains_for("custom", [float("nan")] * 10) == (0,) * 10
    assert eq.gains_for("custom", "abc") == (0,) * 10


def test_cut_only_curve_needs_no_preamp():
    chain = eq.filter_args("custom", [-4] + [0] * 9)
    assert chain == ["equalizer=f=31:t=o:w=1:g=-4.0"]


def test_every_preset_has_ten_bands():
    assert all(len(g) == len(eq.BANDS_HZ) for _, g in eq.PRESETS.values())
