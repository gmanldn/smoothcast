# Remote link acquisition: LAN smoke test (#589)

Trusted home LAN only. No router configuration, port mapping or UPnP is used or
needed; DLNA/SSDP discovery is unrelated. Nothing here changes `main`.

## 1. Automated, one computer (real UDP + HTTP, fake downloader)

```sh
python3 -m pytest -q tests/test_mesh_acquisition_lan_smoke.py          # loopback
SMOOTHCAST_LAN_SMOKE=192.168.x.y python3 -m pytest -q tests/test_mesh_acquisition_lan_smoke.py   # real LAN interface
```

Two real `MeshService` nodes discover each other, the host assigns a YouTube
source to the opted-in worker over the authenticated `acquisition_job` RPC, the
worker's fake provider "downloads" bytes, the host pulls them through the
one-job ticket transfer, verifies size and SHA-256, and the worker releases its
copy. No external download or GUI is involved. It also checks that a worker that
has withdrawn its opt-in declines without downloading.

## 2. Manual, two computers (real downloader, lawful content only)

Use only media you are entitled to download: an authorised video, or a small
seeded torrent you created yourself.

On the **worker** computer (has the isolated download tools; run
`smoothcast --link-check` first and fix anything it reports):

```json
{"mesh_enabled": true, "mesh_accept_acquisition": true}
```

On the **room host** (no local tools needed once the portal change for hosts
without tools has landed; otherwise keep tools disabled by choosing a kind the
host lacks):

```json
{"mesh_enabled": true, "mesh_remote_acquisition": true}
```

(or flip both switches in the Network popover). Start SmoothCast on both,
join the host's room from a phone, and submit the link.

Expect, in order: the host row "Waiting for worker", the worker row
"running for another room" with real progress in Live Mesh on the host, then the
file appears in Up Next once, with no second download on either computer.

Checks to record in the issue:

- worker log shows exactly one acquisition; host shows none
- Up Next contains the item once; replaying the submission adds nothing
- unplug the worker mid-download: the job fails as ambiguous, nothing is
  re-assigned, nothing is queued
- cancel on the host mid-download: the worker stops and its folder under
  `~/.config/cast-control/mesh-acquisition/worker/remote/` disappears
- turn off "Download links for other devices" on the worker: the next
  submission is declined and nothing downloads

## 3. Firewall / guest Wi-Fi isolation

The worker needs inbound TCP from the host on two ports: the mesh HTTP port
(shown in diagnostics) and the one-job transfer port (chosen by the OS). Guest
or "client isolation" Wi-Fi blocks both; if the nodes see each other in
Network but a transfer fails, allow LAN traffic between the two computers or
put them on the same non-isolated network. Receiver reachability for casting is
separate.
