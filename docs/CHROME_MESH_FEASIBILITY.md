# Native Chrome Cast receiver feasibility — decision record

**Status: UNVERIFIED — native clean-Chrome connection not yet demonstrated.**

**Reviewed:** 23 November 2026. **Decision owner:** the maintainer of [Chrome feasibility gate #559](https://github.com/gmanldn/smoothcast/issues/559), with native platform specialists and physical evidence under [#208](https://github.com/gmanldn/smoothcast/issues/208). **Research ticket:** [#576](https://github.com/gmanldn/smoothcast/issues/576).

## Scope and evidence quality

The proposed promise is that **unmodified Chrome** displays *Cast Via SmoothCast Mesh* in its native **Cast…** destination picker and completes an authenticated media session. This is **not** delivered by the existing SmoothCast LAN mesh, ordinary browser room links, or the project's fake Cast receiver.

Source URLs below were read on **23 November 2026**. The Chromium Open Screen pages were served from **HEAD/main (un-pinned)**; no exact upstream Git commit revision was confirmed. The claims are therefore a dated reading, **not a reproducible pinned source audit**. Pin the upstream tree SHA and archive native test logs before a GO decision. The Google Cast overview is a live vendor documentation page, not a source-code revision.

Primary sources:

- [Open Screen: Using the Standalone Sender and Receiver](https://chromium.googlesource.com/openscreen/+/HEAD/cast/docs/USING.md) (HEAD, **un-pinned**), specifically steps 2–6 and the Chrome developer-certificate option.
- [Open Screen root BUILD.gn](https://github.com/chromium/openscreen/blob/main/BUILD.gn) (main, **un-pinned**), notably `gn_all` build conditions for Windows and standalone components.
- [Open Screen libcast overview](https://github.com/chromium/openscreen/blob/main/cast/README.md) (main, **un-pinned**) describes test sender/receiver implementations, not a Google-certified shipping identity.
- [Google Cast architecture](https://developers.google.com/cast/docs/overview) (live page): sender/receiver roles, receiver applications and app IDs.
- In this repository, [src/peer_discovery.py](../src/peer_discovery.py) uses `_smoothcast._tcp.local.`; [fakecast/discovery.py](../fakecast/discovery.py) advertises `_googlecast._tcp.local.` for **test fakes only**. The latter is **not** proof of Chrome trust.

## Evidence matrix

Every **UNVERIFIED** row requires native evidence; discovery alone is not authentication.

| Question | Current evidence | Source URL / revision | Required native test | Status |
| --- | --- | --- | --- | --- |
| DNS-SD receiver discovery | Production SmoothCast uses its own `_smoothcast._tcp.local.` service; the fake uses `_googlecast._tcp.local.` on a test interface | Repository paths above, `develop` reviewed 23 Nov; Open Screen USING, HEAD un-pinned | Clean Chrome lists the test receiver by its intended human-readable name; log service type and actual discovered endpoint without publishing private addresses | UNVERIFIED |
| Cast TLS, certificate and device trust | Open Screen directs its Chrome test to `--cast-developer-certificate-path`; this is extra trust configuration | Open Screen USING, §6, HEAD un-pinned | Without any flags, custom trust store or extension: capture socket, handshake and authenticity outcome | **BLOCKED** pending clean-profile proof |
| Browser without modifications | Upstream documents a **developer-mode control**, not a clean-profile production compatibility proof | Open Screen USING, §6, HEAD un-pinned | Fresh stock Chrome profile; no command-line trust flags; verify full Cast session | UNVERIFIED |
| Receiver app ID and negotiation | Google differentiates sender and receiver and requires an appropriate registered receiver app ID for non-default apps; Open Screen demos are not a grant of production identity | Google Cast overview; Open Screen libcast README, main un-pinned | Record app/namespace selection, launch response and compatible route without fabricated IDs | UNVERIFIED |
| Tab capture / screen mirroring | Libcast includes reference streaming sender/receiver, but that does not prove browser tab or desktop mirroring mode will negotiate on SmoothCast | Open Screen libcast README and USING, HEAD/main un-pinned | Test `Cast tab` and `Cast screen` **separately** with first frame, sound, stop and error outcome | UNVERIFIED |
| Local file / media route | Open Screen's standalone sender accepts a media filename; this does not imply Chrome's file picker or a SmoothCast-origin file route works through native Cast | Open Screen USING, §5, HEAD un-pinned | Test a permitted, local fixture without reading arbitrary host files; capture first video/audio frame and cleanup | UNVERIFIED |
| Protected content / custom receiver apps | App IDs constrain which sender can control a receiver; protected streaming services may have independent constraints | Google Cast overview, live | Run separately with explicitly permitted test content; log refusal as a valid result, never bypass DRM | UNVERIFIED |
| Linux standalone receiver | Open Screen documents Linux/macOS binary use, not shipping Chromium identity/trust | Open Screen USING, §6, HEAD un-pinned; BUILD.gn, main un-pinned | Build pinned receiver; verify native receiver lifecycle and clean Chrome connection on Linux | Build guidance exists; Chrome trust UNVERIFIED |
| macOS standalone receiver | Same upstream documented demo platforms; no clean-Chrome assurance | Open Screen USING, §6, HEAD un-pinned | Repeat lifecycle + clean Chrome test on macOS, with separately archived results | Build guidance exists; Chrome trust UNVERIFIED |
| Windows standalone receiver | Open Screen explicitly says standalone sender/receiver binaries currently run on Linux/macOS only; BUILD.gn excludes Windows standalone sender and receiver in relevant build groups | Open Screen USING, §6; BUILD.gn, main un-pinned | Establish a separately maintained Windows receiver implementation/build or mark unavailable; never assume existing demo builds | **BLOCKED** for upstream standalone Windows build |
| Chrome **sender** on Windows/Linux/macOS | Sender OS is separate from the **Open Screen standalone receiver** build OS. Google documents Chrome as a Cast sender, not guaranteed acceptance of third-party receivers | Google Cast overview; Open Screen USING, §6 | On each Chrome sender OS, repeat the unchanged-profile test against the same isolated native receiver | UNVERIFIED |

## Mandatory seven-stage clean-Chrome experiment (ship gate)

**Owner:** native Cast protocol specialist; final acceptance by #559 maintainer. Use an isolated, non-production LAN/namespace, a test account, and *only* synthetic or otherwise licensed test media. No household TV, ordinary user browser profile, private hostname, key, PIN or certificate is to be committed.

1. **Prepare receiver.** Pin Open Screen commit SHA and build manifest, receiver source/OS and binary hash; launch an isolated test receiver. Record `stage=receiver-setup; result; redacted-log-ref`.
2. **Prepare stock sender.** Record the exact Chrome version, OS, clean temporary profile directory, flags and policies. **No extension, `--cast-developer-certificate-path`, custom CA or device approval.** Record `stage=clean-profile; result; redacted-log-ref`.
3. **Discover.** Open native Chrome **Cast…** UI, capture visible destination and DNS-SD advertisements, including whether the expected device is absent. Record `stage=discovery; result; redacted-log-ref`.
4. **Connect socket.** Select the destination and verify TCP connection, TLS initiation and bounds/timeouts. Record `stage=socket; result; redacted-log-ref`.
5. **Authenticate and negotiate.** Inspect certificate/device trust outcome, Cast app ID, namespace selection and launch/session response. Do not forge credentials, substitute a debug trust store, or call discovery alone success. Record `stage=auth-app; result; redacted-log-ref`.
6. **Play representative media.** Try separately: a local permitted file, a tab, and a screen (where Chrome offers them). Confirm actual first decoded video **and** audio frame, measurable startup, seek/pause where applicable and explicit failures. Record `stage=first-av-frame; result; redacted-log-ref`.
7. **Stop and clean up.** Stop via Chrome; observe receiver teardown, no orphan streams/ports, app exit and clean profile disposal. Record `stage=stop-cleanup; result; redacted-log-ref`.

Archive a structured table `stage | result (PASS/FAIL/NOT RUN) | redacted-log-reference | browser/OS/build SHA | note` on **#559**, with native artefacts/status matrix under **#208**. A successful discovery, socket, or developer-mode run is not enough: the complete *clean-profile* sequence must pass for the promised modes and supported sender/receiver OSes.

## Separate developer-mode control — **NOT the ship gate**

Use only an isolated, disposable test machine and receiver. The Open Screen USING instructions describe building `cast_receiver`/`cast_sender`, generating a developer certificate with the test receiver, starting that receiver on a selected interface, and launching Chrome with:

```text
chrome --cast-developer-certificate-path=/absolute/path/to/test-receiver.crt
```

That flag **adds developer trust**. Even if discovery, TLS, app launch, streaming and stop succeed, **this does not meet the unmodified-Chrome requirement**. Capture only sanitised stage outcomes and references; never check generated keys/certificates into SmoothCast, install them system-wide, use production devices, or generalise the result to Windows. The control is useful for isolating protocol/codec bugs **after** the clean-profile path is documented as blocked or failed.

## Binary decision and blocker

- **GO** only if the clean-Chrome experiment proves receiver discovery, trusted authenticated session, receiver-app negotiation, first video/audio frame, stop/cleanup and the specifically advertised Cast modes, **without** a browser flag, extension, user-installed trust anchor or unauthorised vendor identity. Also document a legally supportable production receiver identity/trust route and per-platform evidence. Approval belongs to **#559**.
- **NO-GO / BLOCKED** if normal Chrome cannot authenticate a third-party native receiver, there is no documented lawful production trust/identity path, or one or more mandatory stages fail. Obtain authoritative vendor/platform clarification rather than inventing a Google certification programme or extracting vendor secrets. Keep the conventional room web UI and mesh controls truthful; do not advertise an entry in Chrome's native Cast menu.

**Current decision: BLOCKED for shipping; technically UNVERIFIED.** No clean-Chrome handshake or vendor-supported production identity has been demonstrated. **#559 remains OPEN**. This document completes *research and the specialist experiment design*, not the native feature.
