# fMP4 HLS prototype evaluation

Evaluation for [issue #246](https://github.com/gmanldn/smoothcast/issues/246).

## Decision

Keep MPEG-TS as the default. Provide fMP4 as an opt-in prototype with
`SMOOTHCAST_HLS_SEGMENT_TYPE=fmp4` so device testing can compare the formats
without changing existing users' streams. Google Cast documents HLS and MP4
media support and lists fMP4 video segments as supporting AVC and HEVC. Its
receiver defaults unspecified HLS segment metadata to transport stream, so
SmoothCast declares both HLS audio and video segment formats when casting an
fMP4 playlist. This establishes protocol-level compatibility, not tested
compatibility on SmoothCast's physical receiver matrix.

## Prototype behavior

- fMP4 playlists use `movie-<generation>-fmp4.m3u8`; fragments use
  `segment-<generation>-NNNNN.m4s`; the initialization section is
  `init-<generation>.mp4`.
- The HTTP server exposes only these generation-bound files. `.m4s` and `.mp4`
  responses use `video/mp4`; HLS recovery accepts an fMP4 session only when its
  playlist names the expected, non-empty init section and same-generation
  non-empty fragments.
- Existing MPEG-TS URLs, `.ts` content type, server allowlist, and recovery path
  remain supported for existing sessions. MPEG-TS remains the default.

## Local FFmpeg comparison

On the development host, generated a 640x360 24 fps test pattern with a 48 kHz
sine track, H.264/AAC, a four-second source duration, and one-second HLS target
segments. FFmpeg used `libx264` with the `ultrafast` preset. One run per format
produced:

| Format | First fragment available | First media fragment | Init section | Fragment + init |
| --- | ---: | ---: | ---: | ---: |
| MPEG-TS | 1.634 s | 49,068 bytes | — | 49,068 bytes |
| fMP4 | 1.223 s | 43,930 bytes | 1,335 bytes | 45,265 bytes |

In this synthetic run, fMP4's first fragment appeared 0.411 seconds earlier;
the first fragment plus init data totalled 7.7% fewer bytes. This is one local
measurement, not a performance claim. It does not include network variance,
receiver buffering, or another hardware encoder. Repeat on the target hardware
and Cast devices before drawing a production conclusion.

## Validation and open qualification

Portable tests cover generation-bound FFmpeg arguments, fMP4 URL recovery,
the init-section requirement, HTTP content types and the server allowlist.
The real FFmpeg run produced a playlist with `EXT-X-MAP`, a non-empty init
section, and media fragments for both formats.

Receiver load/seek/startup compatibility across device models remains pending
under [issue #208](https://github.com/gmanldn/smoothcast/issues/208). Keep the
opt-in path until that device matrix confirms playback and restart recovery.

## References

- [Google Cast supported media](https://developers.google.com/cast/docs/media)
- [Google Cast HLS segment format fields and defaults](https://developers.google.com/cast/docs/media/streaming_protocols)
- [Google Cast HLS format enums](https://developers.google.com/cast/docs/reference/web_receiver/cast.framework.messages)
