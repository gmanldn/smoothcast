# SmoothCast synthetic video capability matrix (#513)

**Not a direct/remux/transcode/playability matrix.** This tests only
whether source video descriptors fit documented fake Cast decoder
limits. It does not test audio, containers, subtitles, output encoding,
player selection or real playback.

Legend: `fit` = source video fits decoder; `adapt` = source video
needs conversion or an explicit refusal; `unknown` = no model.

| Source (video / audio / subs / pixels / fps) | generic | chromecast-gen2 | chromecast-gen3 | chromecast-ultra | chromecast-with-google-tv | google-tv-streamer |
| --- | --- | --- | --- | --- | --- | --- |
| sample-mp4-00 (h264 / aac / none / 1920x1080 / 30) | unknown | fit | fit | fit | fit | fit |
| sample-mp4-01 (hevc / ac3 / subrip / 3840x2160 / 60) | unknown | adapt | adapt | fit | fit | fit |
| sample-mp4-02 (vp9 / eac3 / ass / 1920x1080 / 30) | unknown | adapt | adapt | fit | adapt | adapt |
| sample-mp4-03 (av1 / dts / hdmv_pgs_subtitle / 3840x2160 / 60) | unknown | adapt | adapt | adapt | adapt | fit |
| sample-mp4-04 (mpeg2video / flac / mov_text / 1920x1080 / 30) | unknown | adapt | adapt | adapt | adapt | adapt |
| sample-mp4-05 (mpeg4 / opus / none / 1920x1080 / 30) | unknown | adapt | adapt | adapt | adapt | adapt |
| sample-mp4-06 (h264 / mp3 / subrip / 1920x1080 / 30) | unknown | fit | fit | fit | fit | fit |
| sample-mp4-07 (hevc / aac / ass / 1920x1080 / 30) | unknown | adapt | adapt | fit | fit | fit |
| sample-mkv-00 (h264 / ac3 / subrip / 1920x1080 / 30) | unknown | fit | fit | fit | fit | fit |
| sample-mkv-01 (hevc / eac3 / ass / 3840x2160 / 60) | unknown | adapt | adapt | fit | fit | fit |
| sample-mkv-02 (vp9 / dts / hdmv_pgs_subtitle / 1920x1080 / 30) | unknown | adapt | adapt | fit | adapt | adapt |
| sample-mkv-03 (av1 / flac / mov_text / 3840x2160 / 60) | unknown | adapt | adapt | adapt | adapt | fit |
| sample-mkv-04 (mpeg2video / opus / none / 1920x1080 / 30) | unknown | adapt | adapt | adapt | adapt | adapt |
| sample-mkv-05 (mpeg4 / mp3 / subrip / 1920x1080 / 30) | unknown | adapt | adapt | adapt | adapt | adapt |
| sample-mkv-06 (h264 / aac / ass / 1920x1080 / 30) | unknown | fit | fit | fit | fit | fit |
| sample-mkv-07 (hevc / aac / none / 1920x1080 / 30) | unknown | adapt | adapt | fit | fit | fit |
| sample-webm-00 (h264 / eac3 / ass / 1920x1080 / 30) | unknown | fit | fit | fit | fit | fit |
| sample-webm-01 (hevc / dts / hdmv_pgs_subtitle / 3840x2160 / 60) | unknown | adapt | adapt | fit | fit | fit |
| sample-webm-02 (vp9 / flac / mov_text / 1920x1080 / 30) | unknown | adapt | adapt | fit | adapt | adapt |
| sample-webm-03 (av1 / opus / none / 3840x2160 / 60) | unknown | adapt | adapt | adapt | adapt | fit |
| sample-webm-04 (mpeg2video / mp3 / subrip / 1920x1080 / 30) | unknown | adapt | adapt | adapt | adapt | adapt |
| sample-webm-05 (mpeg4 / aac / ass / 1920x1080 / 30) | unknown | adapt | adapt | adapt | adapt | adapt |
| sample-webm-06 (h264 / aac / none / 1920x1080 / 30) | unknown | fit | fit | fit | fit | fit |
| sample-webm-07 (hevc / ac3 / subrip / 1920x1080 / 30) | unknown | adapt | adapt | fit | fit | fit |
| sample-avi-00 (h264 / dts / hdmv_pgs_subtitle / 1920x1080 / 30) | unknown | fit | fit | fit | fit | fit |
| sample-avi-01 (hevc / flac / mov_text / 3840x2160 / 60) | unknown | adapt | adapt | fit | fit | fit |
| sample-avi-02 (vp9 / opus / none / 1920x1080 / 30) | unknown | adapt | adapt | fit | adapt | adapt |
| sample-avi-03 (av1 / mp3 / subrip / 3840x2160 / 60) | unknown | adapt | adapt | adapt | adapt | fit |
| sample-avi-04 (mpeg2video / aac / ass / 1920x1080 / 30) | unknown | adapt | adapt | adapt | adapt | adapt |
| sample-avi-05 (mpeg4 / aac / none / 1920x1080 / 30) | unknown | adapt | adapt | adapt | adapt | adapt |
| sample-avi-06 (h264 / ac3 / subrip / 1920x1080 / 30) | unknown | fit | fit | fit | fit | fit |
| sample-avi-07 (hevc / eac3 / ass / 1920x1080 / 30) | unknown | adapt | adapt | fit | fit | fit |
| sample-ts-00 (h264 / flac / mov_text / 1920x1080 / 30) | unknown | fit | fit | fit | fit | fit |
| sample-ts-01 (hevc / opus / none / 3840x2160 / 60) | unknown | adapt | adapt | fit | fit | fit |
| sample-ts-02 (vp9 / mp3 / subrip / 1920x1080 / 30) | unknown | adapt | adapt | fit | adapt | adapt |
| sample-ts-03 (av1 / aac / ass / 3840x2160 / 60) | unknown | adapt | adapt | adapt | adapt | fit |
| sample-ts-04 (mpeg2video / aac / none / 1920x1080 / 30) | unknown | adapt | adapt | adapt | adapt | adapt |
| sample-ts-05 (mpeg4 / ac3 / subrip / 1920x1080 / 30) | unknown | adapt | adapt | adapt | adapt | adapt |
| sample-ts-06 (h264 / eac3 / ass / 1920x1080 / 30) | unknown | fit | fit | fit | fit | fit |
| sample-ts-07 (hevc / dts / hdmv_pgs_subtitle / 1920x1080 / 30) | unknown | adapt | adapt | fit | fit | fit |
| sample-mov-00 (h264 / opus / none / 1920x1080 / 30) | unknown | fit | fit | fit | fit | fit |
| sample-mov-01 (hevc / mp3 / subrip / 3840x2160 / 60) | unknown | adapt | adapt | fit | fit | fit |
| sample-mov-02 (vp9 / aac / ass / 1920x1080 / 30) | unknown | adapt | adapt | fit | adapt | adapt |
| sample-mov-03 (av1 / aac / none / 3840x2160 / 60) | unknown | adapt | adapt | adapt | adapt | fit |
| sample-mov-04 (mpeg2video / ac3 / subrip / 1920x1080 / 30) | unknown | adapt | adapt | adapt | adapt | adapt |
| sample-mov-05 (mpeg4 / eac3 / ass / 1920x1080 / 30) | unknown | adapt | adapt | adapt | adapt | adapt |
| sample-mov-06 (h264 / dts / hdmv_pgs_subtitle / 1920x1080 / 30) | unknown | fit | fit | fit | fit | fit |
| sample-mov-07 (hevc / flac / mov_text / 1920x1080 / 30) | unknown | adapt | adapt | fit | fit | fit |

Generated from 48 synthetic sources and 6 fake receiver profiles.
Regenerate: `python3 scripts/ci/render_playback_matrix.py --write`.
Verify: `python3 scripts/ci/render_playback_matrix.py --check`.

**Outstanding #513:** actual direct/remux/transcode/refusal planner
outcomes, all output codec/subtitle checks, six real FFmpeg fixtures
and physical receiver validation. This table is capability evidence
only, not playable-or-typed-refusal evidence.
