import hw_port as hp


def test_vaapi_uses_probed_node_not_a_fixed_path():
    v = hp.Vaapi(nodes=lambda: ["/dev/dri/renderD129"], platform="linux")
    assert v.available()[0]
    assert "/dev/dri/renderD129" in v.input_args() and v.encoder() == "h264_vaapi"


def test_vaapi_unavailable_off_linux_and_without_nodes():
    assert "Linux-only" in hp.Vaapi(platform="win32").available()[1]
    assert "no /dev/dri" in hp.Vaapi(nodes=lambda: [], platform="linux").available()[1]


def test_select_degrades_to_next_ranked_with_visible_reasons():
    ranked = [hp.Vaapi(nodes=lambda: [], platform="linux"),
              hp.Nvenc(has_encoder=lambda n: n == "h264_nvenc")]
    sel = hp.select(ranked)
    assert sel.chosen.name == "nvenc" and sel.skipped[0][0] == "vaapi"


def test_nothing_available_gives_software_with_reasons_and_probe_errors_are_contained():
    class Boom(hp.Fake):
        def available(self):
            raise RuntimeError("driver crashed")
    sel = hp.select([Boom(name="boom"), hp.Fake(name="f", ok=False, why="nope")])
    assert sel.chosen is None
    assert "boom: probe failed" in sel.reason and "f: nope" in sel.reason


def test_contract_every_backend_has_the_port_surface():
    for b in (hp.Vaapi(), hp.Nvenc(), hp.Fake()):
        assert isinstance(b.name, str) and isinstance(b.input_args(), list) and b.encoder()
