#!/usr/bin/env python3
"""Reference Linux launcher for isolated YouTube downloads (#588).

Usage (the contract SMOOTHCAST_LINK_SANDBOX expects)::

    link_sandbox_bwrap.py EXECUTABLE ARGV...      # cwd = the job's staging dir

The tool runs inside bubblewrap with NO network namespace access: no loopback
to the host, no LAN, no metadata service, an empty home and /tmp, write access
only to the staging directory, a new PID namespace that dies with this
process, and file-size/CPU limits. Its only way out is HTTP(S) through a
filtering proxy on a private UNIX socket (``link_egress``): public unicast IPs
only, the proxy resolves and pins addresses itself, every connection (so every
redirect) is re-checked, ports 80/443 only. BitTorrent needs peer traffic that
cannot be proxied, so ``aria2c`` is refused here: torrents need a different
launcher. No inbound port is ever opened.
Run ``smoothcast --link-check --tools-only --qualify`` to attack-test it.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import link_egress  # noqa: E402

PROXY_PORT = 3128
INSIDE = r"""
import os, resource, socket, subprocess, sys, threading
SOCK = "/run/smoothcast-egress/e.sock"
def pipe(a, b):
    try:
        while data := a.recv(65536):
            b.sendall(data)
    except OSError:
        pass
    finally:
        for s in (a, b):
            try: s.shutdown(socket.SHUT_RDWR)
            except OSError: pass
def relay(client):
    up = socket.socket(socket.AF_UNIX)
    try:
        up.connect(SOCK)
    except OSError:
        client.close(); return
    threading.Thread(target=pipe, args=(client, up), daemon=True).start()
    threading.Thread(target=pipe, args=(up, client), daemon=True).start()
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", %(port)d)); srv.listen(16)
def accept():
    while True:
        c, _ = srv.accept(); relay(c)
threading.Thread(target=accept, daemon=True).start()
env = dict(os.environ)
for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    env[k] = "http://127.0.0.1:%(port)d"
env["NO_PROXY"] = env["no_proxy"] = ""
def limits():
    resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024**3, 2 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (1800, 1800))
    os.setsid()
sys.exit(subprocess.call(sys.argv[1:], env=env, preexec_fn=limits))
""" % {"port": PROXY_PORT}


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: link_sandbox_bwrap.py EXECUTABLE ARGV...", file=sys.stderr)
        return 2
    exe = Path(argv[0])
    if exe.name.startswith("aria2"):
        print("link_sandbox_bwrap: BitTorrent peers cannot be proxied; use a torrent-capable launcher",
              file=sys.stderr)
        return 2
    bwrap = shutil.which("bwrap")
    if bwrap is None or not exe.is_absolute():
        print("link_sandbox_bwrap: bubblewrap missing or executable path not absolute", file=sys.stderr)
        return 2
    staging = Path.cwd().resolve()
    home = Path.home().resolve()
    run = Path(tempfile.mkdtemp(prefix="smoothcast-egress-"))
    run.chmod(0o700)
    proxy = link_egress.EgressProxy(run / "e.sock")
    command = [bwrap, "--ro-bind", "/", "/", "--tmpfs", str(home), "--tmpfs", "/tmp", "--tmpfs", "/run",
               "--dev", "/dev", "--proc", "/proc", "--unshare-net", "--unshare-pid", "--unshare-ipc",
               "--die-with-parent", "--new-session", "--bind", str(staging), str(staging),
               "--bind", str(run), "/run/smoothcast-egress", "--chdir", str(staging)]
    for folder in {exe.parent.resolve(), *(Path(a).parent.resolve() for a in argv[1:]
                                           if a.startswith("/") and Path(a).is_file())}:
        if folder != staging and str(folder).startswith(str(home) + os.sep):
            command += ["--ro-bind", str(folder), str(folder)]  # the tool itself lives under $HOME
    command += ["--", sys.executable, "-c", INSIDE, *argv]
    child = subprocess.Popen(command, start_new_session=True, stdin=subprocess.DEVNULL)

    def stop(*_: object) -> None:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except OSError:
            pass

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        return child.wait()
    finally:
        stop()
        proxy.close()
        shutil.rmtree(run, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
