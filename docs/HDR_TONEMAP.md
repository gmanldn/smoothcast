# HDR10-to-SDR conversion (#26 / SC-019)

On an HLS or DLNA transcode, SmoothCast uses FFprobe's **selected motion-video stream**
to recognise HDR10 only when its transfer (`smpte2084`), primaries (`bt2020`),
and matrix (`bt2020nc` or `bt2020c`) are all explicitly signalled.
Recognised HDR10 is decoded to linear light, tone-mapped with FFmpeg's Hable
operator, then converted to BT.709/8-bit 4:2:0 before SDR H.264 encoding.
Tone mapping runs before subtitle overlays, so captions are not colour-shifted.

The selected FFmpeg must provide `zscale` and `tonemap`. If either is missing,
the attempt fails clearly **before replacing an owned receiver session**.
SDR sources are unchanged and never incur the probe. Unknown or contradictory
colour metadata are *not guessed* to be HDR10; HLG and Dolby Vision need
separate treatment. Hardware encoding is bypassed for the HDR10 filter chain.

Headless tests: `pytest -q tests/test_hdr_tonemap.py`; real synthetic
FFmpeg integration: `SMOOTHCAST_REAL_FFMPEG=1 pytest -q tests/test_hdr_tonemap.py`.
The synthetic clip checks codec/colour signalling, **not** reference-video
perceptual fidelity or TV compatibility. Real SDR receiver comparison,
CPU/GPU throughput and real HDR10 reference clips remain to be qualified and
recorded in #208 and this issue before claiming full hardware support.
