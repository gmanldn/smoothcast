import sandbox_port as sp

HAVE = lambda n: "/usr/bin/" + n


def test_bubblewrap_confines_network_and_paths():
    b = sp.Bubblewrap(which=HAVE, platform="linux")
    assert b.available()[0]
    argv = b.wrap(["yt-dlp", "u"], sp.Policy(read=("/in",), write=("/out",)))
    assert argv[:2] == ["bwrap", "--unshare-all"] and "--share-net" not in argv
    assert argv[argv.index("/in") - 1] == "--ro-bind" and argv[argv.index("/out") - 1] == "--bind"
    assert argv[-3:] == ["--", "yt-dlp", "u"]
    assert "--share-net" in b.wrap(["x"], sp.Policy(network=True))


def test_sandbox_exec_profile_denies_by_default_and_escapes_paths():
    s = sp.SandboxExec(which=HAVE, platform="darwin")
    assert s.available()[0]
    argv = s.wrap(["x"], sp.Policy(write=('/a"b',)))
    assert argv[:2] == ["sandbox-exec", "-p"] and "(deny default)" in argv[2]
    assert '/a\\"b' in argv[2] and "network" not in argv[2]


def test_backends_report_why_they_are_unavailable():
    assert "Linux-only" in sp.Bubblewrap(platform="win32").available()[1]
    assert "not installed" in sp.Bubblewrap(platform="linux").available()[1]
    assert "macOS-only" in sp.SandboxExec(platform="linux").available()[1]
    ok, why = sp.JobObject(platform="win32").available()
    assert not ok and "not implemented" in why


def test_select_degrades_visibly_and_never_silently_unconfined():
    sel = sp.select([sp.Bubblewrap(platform="linux"), sp.SandboxExec(platform="linux"), sp.JobObject(platform="linux")])
    assert sel.chosen is None and sel.reason.startswith("NO SANDBOX") and len(sel.skipped) == 3
    sel = sp.select([sp.Bubblewrap(platform="linux"), sp.Fake()])
    assert sel.chosen.name == "fake" and sel.skipped[0][0] == "bubblewrap"


def test_broken_probe_is_contained_and_fake_satisfies_contract():
    class Boom(sp.Fake):
        def available(self):
            raise RuntimeError("x")
    assert "probe failed" in sp.select([Boom(name="boom")]).reason
    assert sp.Fake().wrap(["a"], sp.Policy()) == ["fake-sandbox", "a"]
