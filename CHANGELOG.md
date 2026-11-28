# SmoothCast changelog

A chronological record of changes shipped to `develop`, newest first. Dates and times are UTC. Entries describe the actual commit subject; they do not imply release qualification or ticket closure.

🟩 Feature · 🟥 Fix · 🟦 Performance/refactor · 🟪 Tests/CI · 🟨 Documentation · ⬜ Maintenance/integration

Initial history: 300 recent commits plus intervening changes before this file was introduced (25–27 November 2026). Older history remains in [GitHub commits](https://github.com/gmanldn/smoothcast/commits/develop/). New entries accumulate; this is not a rolling window.

A provisional entry describes the current publication before its own SHA exists; the next refresh replaces it with the actual committed timestamp and link.

<!-- sc-changelog-through: 081ea3db194793c681e52d11ba3b0b1986949a59 -->

## 2026-11-28 · UTC

- ⬜ **03:56:44 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] <!-- sc-changelog-pending -->

- ⬜ **03:56:44 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`081ea3db1947`](https://github.com/gmanldn/smoothcast/commit/081ea3db194793c681e52d11ba3b0b1986949a59)

- 🟦 **03:56:44 · Performance** — perf: run receiver discovery protocols concurrently (Refs #718) · [`567f44c2ab5a`](https://github.com/gmanldn/smoothcast/commit/567f44c2ab5ae9aa31e97b005b3432a1106c78e7)

- ⬜ **03:56:33 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`99b173037272`](https://github.com/gmanldn/smoothcast/commit/99b173037272e1947a1939f31ae78835ca207734)

- 🟥 **03:56:33 · Fix** — fix: explain stalled encoder failures (Refs #207) · [`a71bf6755805`](https://github.com/gmanldn/smoothcast/commit/a71bf67558058924b7caf3121bef9dfca3c21b3d)

- ⬜ **03:56:33 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`b16145f8978a`](https://github.com/gmanldn/smoothcast/commit/b16145f8978a4313a112b5d1d650e5ff764f0da6)

- ⬜ **03:53:24 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`20a66e817c26`](https://github.com/gmanldn/smoothcast/commit/20a66e817c26e665c7bf9b71b4afed964b25038c)

- ⬜ **03:53:23 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`c3e3b077d66e`](https://github.com/gmanldn/smoothcast/commit/c3e3b077d66e9d77ac3d1df462ea23aab486fa6e)

- 🟥 **03:53:21 · Fix** — fix: keep core import-light and re-pin the parallel cast preflight · [`edbfc86000cf`](https://github.com/gmanldn/smoothcast/commit/edbfc86000cf2309c198a754eb0a26c1d110527b)

- ⬜ **03:46:18 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`64fa1f47ae04`](https://github.com/gmanldn/smoothcast/commit/64fa1f47ae046480cbe4d3fe2c7292ef97ce10bb)

- ⬜ **03:46:18 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`ad6080eb4eae`](https://github.com/gmanldn/smoothcast/commit/ad6080eb4eae93bf08f15d840549b334bfd5911b)

- 🟥 **03:46:11 · Fix** — fix: type host-setting errors, follow #708 in the portal harness, budget cast\_portal growth · [`9c185e36bea5`](https://github.com/gmanldn/smoothcast/commit/9c185e36bea52b67497d06cdca7c3127efde5891)

- 🟥 **03:46:11 · Fix** — fix(tests): treat an unreaped zombie as gone in the link-worker lifecycle tests · [`a0e68bff79fb`](https://github.com/gmanldn/smoothcast/commit/a0e68bff79fbe7c17e5639febec3a8d406346e8e)

- 🟥 **03:44:29 · Fix** — fix(runtime): fence cancelled tasks and serialize shutdown admission (Refs #696) · [`5f99735a98fb`](https://github.com/gmanldn/smoothcast/commit/5f99735a98fbec020f7436029319ab9f93a1e2ba)

- ⬜ **03:42:28 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`9d966f8df015`](https://github.com/gmanldn/smoothcast/commit/9d966f8df0159d3703b5c5475f91cd324adc47d2)

- ⬜ **03:42:28 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`68136a11aa13`](https://github.com/gmanldn/smoothcast/commit/68136a11aa13abc6258e17f8ebcc8f240263ac73)

- 🟩 **03:41:13 · Feature** — feat: extend host queue and appearance settings (Refs #708) · [`92da50590939`](https://github.com/gmanldn/smoothcast/commit/92da5059093943c51cfe7f3781455fe021052e79)

- ⬜ **03:41:08 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`9432b3db35e2`](https://github.com/gmanldn/smoothcast/commit/9432b3db35e2a489a211a8f451cf42b5738f2ef4)

- ⬜ **03:41:08 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`a9c6bccfa3cf`](https://github.com/gmanldn/smoothcast/commit/a9c6bccfa3cf3461697ec3cbcde3917fc6fe0934)

- 🟦 **03:39:08 · Performance** — perf: parallelize independent cast preflight checks (Refs #207) · [`1dea034efe5a`](https://github.com/gmanldn/smoothcast/commit/1dea034efe5aab2124e879d50788461ca0626e4a)

- ⬜ **03:32:04 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`1481395504bf`](https://github.com/gmanldn/smoothcast/commit/1481395504bf59f5f59967dbae2bfc98b2c85323)

- 🟩 **03:32:04 · Feature** — feat: add host-only appearance settings to web remote (Refs #708) · [`93b9953d5b15`](https://github.com/gmanldn/smoothcast/commit/93b9953d5b15aea97c402783101203d4e32a225c)

- ⬜ **03:32:04 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`5e86a42c19e8`](https://github.com/gmanldn/smoothcast/commit/5e86a42c19e8676d1afebc459becc3cb41fd0313)

- ⬜ **03:31:33 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`3063866a099d`](https://github.com/gmanldn/smoothcast/commit/3063866a099d413a7048f1f32a175c7f360601fd)

- ⬜ **03:31:33 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`98f8be2cc989`](https://github.com/gmanldn/smoothcast/commit/98f8be2cc989726841611fb3b48ffebd0929421a)

- 🟥 **03:31:31 · Fix** — fix(tests): follow the #708 settings copy and the #568 upload checkpoint writer · [`7e66cc4ea486`](https://github.com/gmanldn/smoothcast/commit/7e66cc4ea4862b5214ad2efbc6fbb108d8baf789)

- ⬜ **03:28:52 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`85b08e0c4b3c`](https://github.com/gmanldn/smoothcast/commit/85b08e0c4b3c9a9656f93e97d078107fd85d001e)

- ⬜ **03:28:52 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`76fab1844f88`](https://github.com/gmanldn/smoothcast/commit/76fab1844f88bbf7eeb629bf91916aa54e314959)

- 🟥 **03:28:49 · Fix** — fix: keep endpoint coalescing within module budget (Refs #723) · [`19015e13e9e7`](https://github.com/gmanldn/smoothcast/commit/19015e13e9e78480a7c1d363d5dfdb7328eb37c4)

- 🟥 **03:25:57 · Fix** — fix: coalesce manual Cast connections by endpoint (Refs #723) · [`816f33dc549a`](https://github.com/gmanldn/smoothcast/commit/816f33dc549a4fc6bc68481e6772cca48e211629)

- ⬜ **03:20:57 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`f0a7fbd357af`](https://github.com/gmanldn/smoothcast/commit/f0a7fbd357af7a8b164b3f957cc224b25a2d5163)

- 🟦 **03:20:57 · Performance** — perf: return warm Cast scan snapshot immediately (Refs #719) · [`5aba068b655e`](https://github.com/gmanldn/smoothcast/commit/5aba068b655e63c081f981f7f2efb836a6907d9e)

- ⬜ **03:20:57 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`f3b2b35af162`](https://github.com/gmanldn/smoothcast/commit/f3b2b35af16248d751284e562b783c17260705b9)

- ⬜ **03:19:40 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`724b0a1e039a`](https://github.com/gmanldn/smoothcast/commit/724b0a1e039a3a007b6cffdf823b6d4df149c00e)

- ⬜ **03:19:40 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`4f4d41d1498f`](https://github.com/gmanldn/smoothcast/commit/4f4d41d1498f349de390e00a90b277536ce7e8b9)

- 🟩 **03:19:34 · Feature** — feat: map desktop preferences in web settings (Refs #708) · [`6d23410aab7e`](https://github.com/gmanldn/smoothcast/commit/6d23410aab7eb7fc7715f0e0925d86ddfd5a73ba)

- ⬜ **03:17:02 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`435853806cd6`](https://github.com/gmanldn/smoothcast/commit/435853806cd61992276c0ad05aaeabf2c8ccacee)

- ⬜ **03:17:02 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`09bcb624a87f`](https://github.com/gmanldn/smoothcast/commit/09bcb624a87f1011f5b5a51dd91dace8d67bb787)

- 🟥 **03:16:57 · Fix** — fix: share target observation freshness cutoff (Refs #744) · [`25ceb3225693`](https://github.com/gmanldn/smoothcast/commit/25ceb32256937d83ba3a2377c99e9695a8c4863d)

- ⬜ **03:15:40 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`eba94749b9c9`](https://github.com/gmanldn/smoothcast/commit/eba94749b9c9fc837acbbec56ce23fed54a8fca4)

- ⬜ **03:15:40 · Maintenance** — chore(ci): refresh complexity baseline after shipped #568 and #710 growth (Refs #704) · [`29289debc5c7`](https://github.com/gmanldn/smoothcast/commit/29289debc5c741bc8aceb772567629bef9fbadce)

- 🟥 **03:15:40 · Fix** — fix(cast): show the receiver reported total length (Refs #704) · [`933146abf9bc`](https://github.com/gmanldn/smoothcast/commit/933146abf9bcc7ff9d6dd9b668d6fac43930a1d6)

- ⬜ **03:15:40 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`bea91e3e32db`](https://github.com/gmanldn/smoothcast/commit/bea91e3e32db7a8dcfc90778bb4a5d502d3aca05)

- ⬜ **03:14:13 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`76cd100ef827`](https://github.com/gmanldn/smoothcast/commit/76cd100ef82714943d65ba72fc4d238b7f49b055)

- 🟥 **03:14:13 · Fix** — fix: cancel stale screen queue advances (Refs #749) · [`2feb4aa970c9`](https://github.com/gmanldn/smoothcast/commit/2feb4aa970c924695bbc06cc2faef9c282607509)

- ⬜ **03:14:13 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`d0b4ffe4afbd`](https://github.com/gmanldn/smoothcast/commit/d0b4ffe4afbd84e6579fef4f39ab77ce5d612b18)

- ⬜ **03:11:37 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`60b0b0731d29`](https://github.com/gmanldn/smoothcast/commit/60b0b0731d291b8bd2cee632c205b381d63f7eb6)

- ⬜ **03:11:36 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`2ee595562ae6`](https://github.com/gmanldn/smoothcast/commit/2ee595562ae64ef5c003ae8a1491831c3b1b0a3b)

- 🟥 **03:11:36 · Fix** — fix: announce confirmed queue move position (Refs #324) · [`f5133d631c12`](https://github.com/gmanldn/smoothcast/commit/f5133d631c125629403b4d33485840a019cf32d2)

- ⬜ **03:07:34 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`bd3f39958f54`](https://github.com/gmanldn/smoothcast/commit/bd3f39958f54aca9fa415634f4d50a33bfd5b9f1)

- ⬜ **03:07:34 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`c9ce3458304a`](https://github.com/gmanldn/smoothcast/commit/c9ce3458304ae6a4c4602f9dadc69a81f79cd29f)

- 🟥 **03:06:27 · Fix** — fix: tag the two attempt-recording re-raise handlers in streamer; lower broad-except baseline 6-&gt;5 (comment-only, no behaviour change) (Refs #706, #694) · [`0777c854b602`](https://github.com/gmanldn/smoothcast/commit/0777c854b6028a38ceb1ec2e81aecd104ff1381c)

- ⬜ **03:03:58 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`0cb5753522f0`](https://github.com/gmanldn/smoothcast/commit/0cb5753522f037679b3212c6f52b07281db90512)

- 🟪 **03:03:58 · Tests** — test: protect active playback during queue contributions (Refs #325) · [`59e528e1891d`](https://github.com/gmanldn/smoothcast/commit/59e528e1891dc39b1237159923d592c1d7cabc29)

- ⬜ **03:03:58 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`f591bf7c4bcc`](https://github.com/gmanldn/smoothcast/commit/f591bf7c4bccb0794bbc4735da07f356a94cb57d)

- ⬜ **03:00:07 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`d829cd4044a1`](https://github.com/gmanldn/smoothcast/commit/d829cd4044a1f4e85304db1ed3aa523982eb802f)

- 🟥 **03:00:07 · Fix** — fix(screen): retain the active transcode route for seek and recovery (Refs #753) · [`c29c05b56909`](https://github.com/gmanldn/smoothcast/commit/c29c05b569098a36b5eebfe2c33d3b69cd3485ac)

- ⬜ **03:00:07 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`c6f3d93ed432`](https://github.com/gmanldn/smoothcast/commit/c6f3d93ed432444e682b7159e1a590a1923ed69d)

- ⬜ **02:56:53 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`145e7daf1492`](https://github.com/gmanldn/smoothcast/commit/145e7daf14929a219da703231d3c064bd9e83985)

- ⬜ **02:56:53 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`a16ed1c934c4`](https://github.com/gmanldn/smoothcast/commit/a16ed1c934c42db7a11b263fd44288a71ef04955)

- 🟩 **02:56:52 · Feature** — feat: show room people in network map (Refs #710) · [`8e4db8da9518`](https://github.com/gmanldn/smoothcast/commit/8e4db8da95189a9141a51b5e42a0da5980be87d5)

- ⬜ **02:56:37 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`89ae42174b18`](https://github.com/gmanldn/smoothcast/commit/89ae42174b18a6982b91cf02f953a24583cf4867)

- ⬜ **02:56:37 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`187e84097259`](https://github.com/gmanldn/smoothcast/commit/187e84097259f0fe9e6c7509da6689efacd86b0a)

- 🟥 **02:56:36 · Fix** — fix: reject Windows reparse points when staging sources (Refs #580) · [`a7d7095a8943`](https://github.com/gmanldn/smoothcast/commit/a7d7095a8943c74493245f18ef9a991d59c32576)

- ⬜ **02:54:31 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`84c2bdced15a`](https://github.com/gmanldn/smoothcast/commit/84c2bdced15a0c33e54871920fc3be799530197d)

- 🟩 **02:54:31 · Feature** — feat: recover durable queue upload checkpoints (Refs #568) · [`585993241694`](https://github.com/gmanldn/smoothcast/commit/5859932416947872a5951f8bb0f91afb8a3ae5fa)

- ⬜ **02:54:31 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`13123e587401`](https://github.com/gmanldn/smoothcast/commit/13123e5874012557ebefa4d27fdc7361ef4554a7)

- 🟥 **02:51:36 · Fix** — fix(mesh): reject malformed or stale playback eligibility observations (Refs #740) · [`3997fdbd55bc`](https://github.com/gmanldn/smoothcast/commit/3997fdbd55bc09bdf4f46aac5cb0c88cb9d2ef6a)

- ⬜ **02:50:50 · Maintenance** — Merge branch 'main' into develop · [`f363d78f1030`](https://github.com/gmanldn/smoothcast/commit/f363d78f10306f334e151b5d244c6178334358a2)

- ⬜ **02:50:31 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`b94b18f08647`](https://github.com/gmanldn/smoothcast/commit/b94b18f086475557bd2743a176e9b46701e984ae)

- ⬜ **02:50:31 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`0658ad562c0a`](https://github.com/gmanldn/smoothcast/commit/0658ad562c0aae7f1e1c9fea220d4658c745ae10)

- 🟥 **02:50:26 · Fix** — fix(cast): serialize status mirror connection teardown per receiver (Refs #202) · [`7ba24a007d6a`](https://github.com/gmanldn/smoothcast/commit/7ba24a007d6a1b2759b032784142ac050810d797)

- ⬜ **02:47:08 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`a3b8fe9548ad`](https://github.com/gmanldn/smoothcast/commit/a3b8fe9548adbf441da8836c7459758287cc2e73)

- ⬜ **02:47:08 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`2bc1f8957063`](https://github.com/gmanldn/smoothcast/commit/2bc1f8957063a3b2e7382f98933872815b9e07e1)

- 🟥 **02:46:53 · Fix** — fix(errors): distinct codes for TV status-unavailable and playback-unconfirmed (#207) · [`326d9cb47be5`](https://github.com/gmanldn/smoothcast/commit/326d9cb47be5bc03c029a75aab2c51694c369f9a)

- 🟥 **02:46:53 · Fix** — fix(errors): distinct codes for TV status-unavailable and playback-unconfirmed (#207) · [`7ef343a99c0e`](https://github.com/gmanldn/smoothcast/commit/7ef343a99c0eb6cba81dcc76c814f34c709ce6bf)

- ⬜ **02:44:16 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`4a30fac827e8`](https://github.com/gmanldn/smoothcast/commit/4a30fac827e8be060c7013dfb835d2eb9a1c2b6b)

- ⬜ **02:44:16 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`29d7c98e86d9`](https://github.com/gmanldn/smoothcast/commit/29d7c98e86d97d4168b54f5372cff4cf828df4d3)

- 🟥 **02:44:15 · Fix** — fix: declare demo\_cast\_helper in the wheel module manifest (Refs #706) · [`77a16b611ce1`](https://github.com/gmanldn/smoothcast/commit/77a16b611ce1e0abfba3bf56e54a1819201e7a64)

- ⬜ **02:42:30 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`0dac5fcabf78`](https://github.com/gmanldn/smoothcast/commit/0dac5fcabf7870e4ffa3c875bf3df11c1e2a68f5)

- 🟥 **02:42:30 · Fix** — fix(cast): keep the existing stream alive until a remote URL handoff is confirmed (Refs #746) · [`c403a59c6913`](https://github.com/gmanldn/smoothcast/commit/c403a59c6913cb9dfb2d0bf2478a0d7b1f17c034)

- ⬜ **02:42:30 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`4055693df29e`](https://github.com/gmanldn/smoothcast/commit/4055693df29e80c080723ef68e0dadf16b75eb8e)

- ⬜ **02:41:44 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`17725f6c2cdf`](https://github.com/gmanldn/smoothcast/commit/17725f6c2cdf58ba4b6f815b4c1f4c5d46e7433c)

- ⬜ **02:41:43 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`f0718a1aa6ad`](https://github.com/gmanldn/smoothcast/commit/f0718a1aa6ad01e28844d6fb028b5a5c51dbcbe6)

- 🟥 **02:41:43 · Fix** — fix(ui,tests): mirror the real card/chip spacing in density; skip GTK tests without PyGObject · [`4889bab99138`](https://github.com/gmanldn/smoothcast/commit/4889bab991384ee97bde373e8be63be1b6efa7ec)

- ⬜ **02:40:44 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`b0b031d597bd`](https://github.com/gmanldn/smoothcast/commit/b0b031d597bd95355d09ecc30bf9d6535f3f0d04)

- ⬜ **02:40:44 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`72f3ce9eea92`](https://github.com/gmanldn/smoothcast/commit/72f3ce9eea92a5c70d0a5cd65cbee13c5c176acd)

- 🟥 **02:40:43 · Fix** — fix(node-targets): fence delayed releases to the exact node/session/epoch claim (Refs #738) · [`914d57ad7406`](https://github.com/gmanldn/smoothcast/commit/914d57ad740637b0f74062ceea36499b47f99bae)

- 🟥 **02:39:57 · Fix** — fix(node-targets): fence delayed releases to the exact node/session/epoch claim (Refs #738) · [`2835e75cbe0c`](https://github.com/gmanldn/smoothcast/commit/2835e75cbe0c459a76dd0177bbc6aab60de0febc)

- 🟥 **02:39:46 · Fix** — fix(node-targets): fence delayed releases to the exact node/session/epoch claim (Refs #738) · [`c47836ad40cc`](https://github.com/gmanldn/smoothcast/commit/c47836ad40cca0a1e26345f81c36f0710f7e284e)

- ⬜ **02:08:03 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`cfae34f502f8`](https://github.com/gmanldn/smoothcast/commit/cfae34f502f8f5a5034e156dcde13298b0aa854b)

- 🟥 **02:08:03 · Fix** — fix(tests): repair test harnesses and assertions that drifted after refactors · [`72c1836e076b`](https://github.com/gmanldn/smoothcast/commit/72c1836e076b163274e2813e15fcdd78a242b515)

- ⬜ **02:08:03 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`1abaa1ba1faa`](https://github.com/gmanldn/smoothcast/commit/1abaa1ba1faa200e3dd4f373f664a69ba9791ac8)

- ⬜ **02:06:00 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`75ffd8e19f20`](https://github.com/gmanldn/smoothcast/commit/75ffd8e19f20fce80e09958ccfe83ca15fc410cf)

- ⬜ **02:06:00 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`04ecee0024d6`](https://github.com/gmanldn/smoothcast/commit/04ecee0024d64c1fc0f90faf53199d82b844c84c)

- 🟥 **02:05:52 · Fix** — fix: record the commit time in staged generation markers so both UIs show 'vX - date time - Codename' (Refs #580) · [`4cda66959625`](https://github.com/gmanldn/smoothcast/commit/4cda669596253e7784335cc5842420d8d025d9d2)

- ⬜ **02:04:11 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`bc22a4096f33`](https://github.com/gmanldn/smoothcast/commit/bc22a4096f3346598b503e1fd8b2a2d02e016abe)

- ⬜ **02:04:11 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`125500ceb482`](https://github.com/gmanldn/smoothcast/commit/125500ceb482268e2d80077261eb899b1494cc6f)

- 🟪 **02:04:09 · Tests** — test(join-slate): follow the switch wiring into preferences\_room\_ui (stale since #706 split) · [`a2f06c36f740`](https://github.com/gmanldn/smoothcast/commit/a2f06c36f740b6b7f15868c3581fb2d6aaa74a8a)

- 🟪 **02:02:28 · Tests** — test(gui): keep the demo target cache from leaking between tests (Refs #449) · [`5d84fa6a9d63`](https://github.com/gmanldn/smoothcast/commit/5d84fa6a9d63778f453b2924eee2ba382ba45545)

- ⬜ **02:02:28 · Maintenance** — chore(budget): complexity baseline for the demo cast helper (+37 lines), demo\_mode target caching and castctl demo routing · [`36a7ff959803`](https://github.com/gmanldn/smoothcast/commit/36a7ff9598032a6038c536d02adda4b9256eaf43)

- 🟪 **02:02:28 · Tests** — test(gui): scripted open→cast→pause→seek→stop journey against the loopback demo receiver; demo cast helper replaces catt in demo mode, fake receiver mirrors status to other senders (Refs #449, #524) · [`e5d34a3c9fd8`](https://github.com/gmanldn/smoothcast/commit/e5d34a3c9fd8a790238424ca596575577d7de3e7)

- ⬜ **01:57:27 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`c85e1321b54b`](https://github.com/gmanldn/smoothcast/commit/c85e1321b54b20b59bcd7bd64e8d76151b4cbd24)

- 🟪 **01:57:27 · Tests** — test: de-flake retry-push SHA assertion; make fake scan hermetic (Refs #698) · [`ec77ca9c1883`](https://github.com/gmanldn/smoothcast/commit/ec77ca9c188357c9661ad7fb197f2e88b3418932)

- 🟪 **01:57:27 · Tests** — test: skip GTK-only warmup test when PyGObject is unusable (Refs #698) · [`28abd3991111`](https://github.com/gmanldn/smoothcast/commit/28abd39911119b975ccf12cc11b762dfd9822bee)

- 🟥 **01:57:27 · Fix** — fix(ship): discard generated PATCH/changelog commits when a gate stops the push (Refs #700, #698) · [`9ddf1070c122`](https://github.com/gmanldn/smoothcast/commit/9ddf1070c12272987aac14ee08ac2b29292c2afb)

- 🟪 **01:57:27 · Tests** — test: supply settings to the preview-meter harness (Refs #698, #693) · [`3dc4cc6e2156`](https://github.com/gmanldn/smoothcast/commit/3dc4cc6e21566c8d07073ad761b3d600882f908b)

- 🟩 **01:57:27 · Feature** — feat(diagnostics): every encoder start keeps its own attempt folder; fix GUI test harness imports (settings, QueueComponent) (Refs #698, #693, #691) · [`c9355796ae08`](https://github.com/gmanldn/smoothcast/commit/c9355796ae0838289d8e53d9366dc9669fa3e588)

- 🟩 **01:57:27 · Feature** — feat(diagnostics): every encoder start keeps its own attempt folder (argv, plan, ffmpeg stderr, outcome); start errors name the plan (Refs #698) · [`6e983d0dc183`](https://github.com/gmanldn/smoothcast/commit/6e983d0dc183d63ffecb8322270953624bbb56c2)

- ⬜ **01:57:27 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`a7b82343f60f`](https://github.com/gmanldn/smoothcast/commit/a7b82343f60f2b52538f375436a5a68a80f72216)

- ⬜ **01:54:52 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`4a0a1274230e`](https://github.com/gmanldn/smoothcast/commit/4a0a1274230ec44ec90204af23e356ffa2a92d7f)

- ⬜ **01:54:52 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`6144a258a7fc`](https://github.com/gmanldn/smoothcast/commit/6144a258a7fcbff375dd1037b04eb36076cac3b0)

- 🟥 **01:54:32 · Fix** — fix: stale Chromecast status link; instant, ordered scrub preview · [`622f5c9627d0`](https://github.com/gmanldn/smoothcast/commit/622f5c9627d08c9c5a46175fc797eedf729d3ceb)

- ⬜ **01:42:20 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`e198c5a2a7ff`](https://github.com/gmanldn/smoothcast/commit/e198c5a2a7fff544a93b3e27831b7b39907f036d)

- ⬜ **01:42:20 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`940ad47b3530`](https://github.com/gmanldn/smoothcast/commit/940ad47b3530f056352e8826d25d5ad1301b4b9a)

- 🟥 **01:42:06 · Fix** — fix: persist latency stats via store.Store; restore docs wording and stale known\_nodes test expectation (Refs #706) · [`ddaa8b10ec99`](https://github.com/gmanldn/smoothcast/commit/ddaa8b10ec9974a955edad5474aa8ee028a82361)

- ⬜ **01:37:11 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`ea51015d177d`](https://github.com/gmanldn/smoothcast/commit/ea51015d177da1b0185866846d678784666f401b)

- ⬜ **01:37:11 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`29c19a04f88a`](https://github.com/gmanldn/smoothcast/commit/29c19a04f88a719240e1cd84f9c439aa1314893e)

- 🟥 **01:36:56 · Fix** — fix(tests): repair stale portal test harnesses that were red on develop · [`0a723171d78d`](https://github.com/gmanldn/smoothcast/commit/0a723171d78d03a67b1686811586cc1b6e8f3b5c)

- ⬜ **01:35:49 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`ab3c72b5db51`](https://github.com/gmanldn/smoothcast/commit/ab3c72b5db516d1fecbc8fa2b34d013614636bf8)

- ⬜ **01:35:49 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`a9e8f6f2f2dc`](https://github.com/gmanldn/smoothcast/commit/a9e8f6f2f2dc59bc730e575cf494104f1a8d3ac2)

- 🟥 **01:35:43 · Fix** — fix(agent): version.py is a release lane; a feature lease can no longer block or be blocked by a shipment's PATCH bump (Refs #700) · [`1e32671a4dea`](https://github.com/gmanldn/smoothcast/commit/1e32671a4dea875161e21454b07ad36550be5fb7)

- ⬜ **01:34:31 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`25a17f1d6d64`](https://github.com/gmanldn/smoothcast/commit/25a17f1d6d6434946ebe94ffd33478ce56ee07a4)

- ⬜ **01:34:30 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`c6db5e134ba7`](https://github.com/gmanldn/smoothcast/commit/c6db5e134ba7b0c8e2fa1c12c5764f38dc64ac7f)

- 🟪 **01:34:29 · Tests** — test(agent): repair 7 stale lifecycle tests for scope check and per-shipment PATCH; drop their quarantine entries (Refs #700) · [`fd0ab522d431`](https://github.com/gmanldn/smoothcast/commit/fd0ab522d4311a86e2ba3ebdd45a2e24a2ed022f)

- 🟩 **01:22:24 · Feature** — feat(portal): say what to do next in empty room screens · [`fd9cd4205530`](https://github.com/gmanldn/smoothcast/commit/fd9cd4205530065026883ba1d15103523082e0d8)

- ⬜ **01:19:24 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`aac4685e9b73`](https://github.com/gmanldn/smoothcast/commit/aac4685e9b7382d70ccb58537924b533c139cb15)

- ⬜ **01:19:24 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`ebeea3a2639d`](https://github.com/gmanldn/smoothcast/commit/ebeea3a2639d0fab91621eed7f1b1eac9dc117c8)

- 🟥 **01:19:18 · Fix** — fix(tests): quarantine GUI size ratchet to #706 with owner/expiry; skip GTK settings test without a usable PyGObject (Refs #700) · [`95271e5cc427`](https://github.com/gmanldn/smoothcast/commit/95271e5cc42782979ee1022d423e649f32078b7b)

- 🟥 **01:19:18 · Fix** — fix(ci): ship stops on unowned pre-existing red; quarantine entries need owner, ticket and live expiry (Refs #700) · [`25d7cee07bc5`](https://github.com/gmanldn/smoothcast/commit/25d7cee07bc51ac4050d09b21938bd6ae099080d)

- ⬜ **00:28:35 · Maintenance** — Merge branch 'develop' of https://github.com/gmanldn/smoothcast into develop · [`c7914ca82b25`](https://github.com/gmanldn/smoothcast/commit/c7914ca82b2519c319bbf4dca2eb092a4795b008)

- ⬜ **00:28:14 · Maintenance** — 1 · [`ad3fbb284d57`](https://github.com/gmanldn/smoothcast/commit/ad3fbb284d57744b95640c894cff50677ac1bba6)

- ⬜ **00:09:31 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`a02430cbc51d`](https://github.com/gmanldn/smoothcast/commit/a02430cbc51d75465211433f05ebf2079f681f56)

- ⬜ **00:09:31 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`a50944c94891`](https://github.com/gmanldn/smoothcast/commit/a50944c9489135fd29f2ea922c822821c9bd7c22)

- 🟩 **00:09:23 · Feature** — feat(ui): show elapsed / total on external-stream label (Refs #588) · [`b0e5992e1ed9`](https://github.com/gmanldn/smoothcast/commit/b0e5992e1ed966150bf9e6b9e71e23acacccae39)

---

## 2026-11-27 · UTC

- ⬜ **21:27:20 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`7d50c4558f71`](https://github.com/gmanldn/smoothcast/commit/7d50c4558f712b65b5f14ad16be3d13d9ee18b8e)

- ⬜ **21:27:20 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`767b5a35a55b`](https://github.com/gmanldn/smoothcast/commit/767b5a35a55b27ac113c4cb6a00dd9d44ee21569)

- 🟦 **21:27:16 · Refactor** — refactor(portal): dispatch session and status GET routes through the route table (Refs #689) · [`46034fb11be8`](https://github.com/gmanldn/smoothcast/commit/46034fb11be8394f714787565907edde1373aafe)

- ⬜ **21:26:15 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`92c71549aa6b`](https://github.com/gmanldn/smoothcast/commit/92c71549aa6b7fbdd86c15ce9920d498379d0207)

- ⬜ **21:26:15 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`b698e0f841a8`](https://github.com/gmanldn/smoothcast/commit/b698e0f841a83ac6b08883be2b0a552de6697b98)

- 🟦 **21:26:12 · Refactor** — refactor(portal): dispatch library, search and mesh GET routes through the route table (Refs #689) · [`7fc3c52273ee`](https://github.com/gmanldn/smoothcast/commit/7fc3c52273ee4d11c37f417fdb4385d2f2243ebd)

- ⬜ **21:24:44 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`5f787ef9cb3d`](https://github.com/gmanldn/smoothcast/commit/5f787ef9cb3de7820b10d49d38b1bb982b8d4104)

- ⬜ **21:24:44 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`957cca08d6b8`](https://github.com/gmanldn/smoothcast/commit/957cca08d6b8de23cc0039a724ae685497373bb4)

- 🟦 **21:24:40 · Refactor** — refactor(portal): serve the public GET routes through the route table (Refs #689) · [`82673d65062c`](https://github.com/gmanldn/smoothcast/commit/82673d65062c8058feee97bacb10835a5ac2b9aa)

- 🟨 **21:23:24 · Documentation** — docs(ports): per-OS evidence table for the platform ports, stating which are not yet wired (Refs #703) · [`93a465723d96`](https://github.com/gmanldn/smoothcast/commit/93a465723d96b12670d8585fdc33d8bb93210f25)

- ⬜ **21:23:01 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`dcb9ac8c4535`](https://github.com/gmanldn/smoothcast/commit/dcb9ac8c45359f42af796174a83936aa8ac9eda3)

- ⬜ **21:23:01 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`d1ebb3e08e48`](https://github.com/gmanldn/smoothcast/commit/d1ebb3e08e486bd1f0df07b4415a512bd991832e)

- 🟪 **21:22:58 · Tests** — test(portal): pin the anonymous-caller auth gate for every authenticated route (Refs #689) · [`7240539ef1f1`](https://github.com/gmanldn/smoothcast/commit/7240539ef1f1d3ecb8adb5fea9894f942a0eeaef)

- 🟪 **21:22:08 · Tests** — test(room): property tests for replay, retry idempotence, no duplicates, rejoin convergence and gap refusal (Refs #695) · [`796dbb1214a4`](https://github.com/gmanldn/smoothcast/commit/796dbb1214a43c1b23426047c0ad2d4e5c65e637)

- ⬜ **21:21:19 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`3a375d32cca4`](https://github.com/gmanldn/smoothcast/commit/3a375d32cca42d647528bcec875287fe2c1f151f)

- 🟩 **21:21:19 · Feature** — feat(doctor): SSDP self-test check (Refs #211) · [`be44db5dfb80`](https://github.com/gmanldn/smoothcast/commit/be44db5dfb80ec98686a5d9ee3a002ebd86a37f7)

- ⬜ **21:21:19 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`b8045ac4cc30`](https://github.com/gmanldn/smoothcast/commit/b8045ac4cc30d7e2fde47383799f22675909c385)

- ⬜ **21:21:04 · Maintenance** — chore(ci): rebaseline complexity for design\_tokens, ffmpeg\_compat, latency\_stats, ui\_tokens (Refs #700) · [`ed530e9cb9d9`](https://github.com/gmanldn/smoothcast/commit/ed530e9cb9d992a18eff208b30961fcfae61e2da)

- ⬜ **21:20:16 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`ad3ac76ddf7b`](https://github.com/gmanldn/smoothcast/commit/ad3ac76ddf7b2f5cf38a74df2a79814a232302ed)

- ⬜ **21:20:16 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`88cd9a2a9390`](https://github.com/gmanldn/smoothcast/commit/88cd9a2a93906177c01dd0a6fce56cf7a82692c7)

- 🟩 **21:20:13 · Feature** — feat(doctor): run the firewall check in smoothcast doctor (Refs #211) · [`105201d5f863`](https://github.com/gmanldn/smoothcast/commit/105201d5f863b87a8929eb4b1b1febc1cca233ac)

- 🟩 **21:19:33 · Feature** — feat(diagnostics): shutdown total and per-step timings accumulate in latency.json (Refs #698) · [`c9c0340a5532`](https://github.com/gmanldn/smoothcast/commit/c9c0340a5532f82d07e921e05c57dbf6a37fbe63)

- ⬜ **21:18:41 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`e9db5fe14e5d`](https://github.com/gmanldn/smoothcast/commit/e9db5fe14e5d8f575f3d37c4f183552ffaf979bf)

- ⬜ **21:18:40 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`89d6ba2be641`](https://github.com/gmanldn/smoothcast/commit/89d6ba2be641c222bf0f63052d498ef5e93021d6)

- 🟦 **21:18:06 · Refactor** — refactor(errors): justify boundary catches in fifteen freed modules (Refs #694) · [`5a1bab5dda9d`](https://github.com/gmanldn/smoothcast/commit/5a1bab5dda9dcbbb8438e676911ad69b3328f6b1)

- ⬜ **21:18:01 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`a32a77297f58`](https://github.com/gmanldn/smoothcast/commit/a32a77297f580ce98ebbfb6abbfeff407a847795)

- 🟪 **21:18:01 · Tests** — test(link): real-process worker crash, quota, deadline, cancel and no-residual-child coverage (Refs #588) · [`0687dca1152d`](https://github.com/gmanldn/smoothcast/commit/0687dca1152deed0125b2be3fb2ebf07cd9057cc)

- ⬜ **21:18:01 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`af265caf986b`](https://github.com/gmanldn/smoothcast/commit/af265caf986b35d676a946a7f0964e7af88c34b9)

- ⬜ **21:17:50 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`55bf2c6ed0a8`](https://github.com/gmanldn/smoothcast/commit/55bf2c6ed0a86411fbd4a792526ad2eddbe0ce50)

- 🟦 **21:17:50 · Performance** — perf(stream): casts start sooner - the first 10 s encode at full speed (-readrate\_initial\_burst, FFmpeg 6.1+) instead of 8 s of real-time reading before the first two segments; guest uploads that may still be arriving keep plain -readrate (Refs #686) · [`0988c0ee3133`](https://github.com/gmanldn/smoothcast/commit/0988c0ee31335b0791cfa8791a84175150240eba)

- ⬜ **21:17:50 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`7d81743fdd11`](https://github.com/gmanldn/smoothcast/commit/7d81743fdd11bfbe5581a32f0c178dc263e79850)

- 🟩 **21:17:25 · Feature** — feat(ui): mesh joins the shared room layout model with a web/GTK parity check (Refs #708) · [`18cc6a4a2716`](https://github.com/gmanldn/smoothcast/commit/18cc6a4a271685c1ae9f196cd3a5d86691ece512)

- 🟩 **21:16:09 · Feature** — feat(ui): GTK padding and margins snap onto the shared spacing scale, with a parity test (Refs #708) · [`16e210790bfe`](https://github.com/gmanldn/smoothcast/commit/16e210790bfeeff81076762b0a105e98d08c78f5)

- 🟥 **21:15:44 · Fix** — fix(diag): the jank\_watchdog preference was never read (and stripped on load); wire it through so UI stall data can be collected without an env var (Refs #442) · [`4ca5bb23adee`](https://github.com/gmanldn/smoothcast/commit/4ca5bb23adeefccb430c6ef1b8135cefbf6eda1b)

- ⬜ **21:14:19 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`71ec1ab1513f`](https://github.com/gmanldn/smoothcast/commit/71ec1ab1513f5387c455a17fc9d547b2f5eb2570)

- 🟩 **21:14:19 · Feature** — feat(web): one unified queue — uploads, now-playing and queued items share rows with live status chips · [`effdb22384d9`](https://github.com/gmanldn/smoothcast/commit/effdb22384d957e1536bdb3db2c53094499813e9)

- 🟦 **21:11:44 · Refactor** — refactor(arch): GTK-free QueueComponent owns queue add/remove/selection rules; QueueMixin uses it (Refs #691) · [`4f79d8f5eff8`](https://github.com/gmanldn/smoothcast/commit/4f79d8f5eff8fecc3520a65d110e08fb7076a510)

- ⬜ **19:42:25 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`f0a2d173d275`](https://github.com/gmanldn/smoothcast/commit/f0a2d173d275fd962d4ceba6e856758596dd5d6d)

- 🟥 **19:42:25 · Fix** — fix: publish external cast length labels (Refs #704) · [`15595858c540`](https://github.com/gmanldn/smoothcast/commit/15595858c540de0469be9b7310d060f8a46cecd9)

- ⬜ **19:42:25 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`c1572cd83883`](https://github.com/gmanldn/smoothcast/commit/c1572cd8388396cca84d1fca3a36160b2a331cea)

- ⬜ **19:40:06 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`13557b1a572e`](https://github.com/gmanldn/smoothcast/commit/13557b1a572eea6c3a78f9b21b37eacca8b74811)

- 🟪 **19:40:06 · Tests** — test: cover concurrent guest queue contributions (Refs #325) · [`1dffa2c7e84d`](https://github.com/gmanldn/smoothcast/commit/1dffa2c7e84d3a8955c860f36b24eb26475a6db5)

- ⬜ **19:40:06 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`1dddab208c84`](https://github.com/gmanldn/smoothcast/commit/1dddab208c841a02ef2068eaeccd28278f9df0ba)

- ⬜ **19:39:42 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`4e4fe6709c43`](https://github.com/gmanldn/smoothcast/commit/4e4fe6709c433880434803d47eead660feef2ffa)

- 🟥 **19:39:42 · Fix** — fix(update): report saved playback handoff deferral clearly (Refs #626) · [`afc2b4dd3a58`](https://github.com/gmanldn/smoothcast/commit/afc2b4dd3a5810372fa7a8b34b5da1169159f68c)

- ⬜ **19:39:42 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`7e9004f414d0`](https://github.com/gmanldn/smoothcast/commit/7e9004f414d0aed74757562f37b6f9f6e4d68eba)

- ⬜ **19:36:07 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`29a911f88aae`](https://github.com/gmanldn/smoothcast/commit/29a911f88aaea4d705320cddc209ef6d53316566)

- ⬜ **19:36:06 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`08fbeb200f0f`](https://github.com/gmanldn/smoothcast/commit/08fbeb200f0f18190bbf73381823923e81ffdb55)

- 🟩 **19:36:06 · Feature** — feat: clarify web room home and settings (Refs #709) · [`554bf68dfc57`](https://github.com/gmanldn/smoothcast/commit/554bf68dfc57d48457e0de55f1bdb1f5c3409ba7)

- ⬜ **19:35:08 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`b11c02fdd4a9`](https://github.com/gmanldn/smoothcast/commit/b11c02fdd4a906d67710cb172cbfe74ba2f83574)

- ⬜ **19:35:08 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`5c81d07319a0`](https://github.com/gmanldn/smoothcast/commit/5c81d07319a0671eedb7e302cda03d55b07d106b)

- 🟥 **19:35:03 · Fix** — fix(update): defer bounce when a saved playback session exists (Refs #626) · [`e3c710b938d1`](https://github.com/gmanldn/smoothcast/commit/e3c710b938d1079dfded5421e52895250d643005)

- ⬜ **19:28:40 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`99f203f663d9`](https://github.com/gmanldn/smoothcast/commit/99f203f663d90b4d3f131653c6238713fc0a30bf)

- 🟩 **19:28:40 · Feature** — feat: share visual tokens between gtk and web (Refs #708) · [`6deffbec7d29`](https://github.com/gmanldn/smoothcast/commit/6deffbec7d2937323a425ea8a3eee9752dd9e1d0)

- ⬜ **19:28:40 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`bff51b906ced`](https://github.com/gmanldn/smoothcast/commit/bff51b906ced2f32c474a3f5cb6b7c709ca76311)

- ⬜ **19:24:35 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`736fa00815b9`](https://github.com/gmanldn/smoothcast/commit/736fa00815b902783f74b2835aedd3f9b4303179)

- ⬜ **19:24:35 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`ea5be954f74e`](https://github.com/gmanldn/smoothcast/commit/ea5be954f74e0e68531b85a1840fce98d9f2497e)

- 🟥 **19:24:18 · Fix** — fix: resolve portal media through MediaSource (Refs #702) · [`e65202c14210`](https://github.com/gmanldn/smoothcast/commit/e65202c142101b004ce34cd3caca67e5282a4b10)

- ⬜ **19:20:02 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`06c65e1fcac2`](https://github.com/gmanldn/smoothcast/commit/06c65e1fcac2797ee007888ba1706aaf8c2ee8e9)

- ⬜ **19:20:02 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`bf2f07d57000`](https://github.com/gmanldn/smoothcast/commit/bf2f07d5700007981cecc2d720c88c3a2cbad436)

- 🟩 **19:20:01 · Feature** — feat: add host-authorized room rename to web dashboard (Refs #709) · [`017c1fd321ab`](https://github.com/gmanldn/smoothcast/commit/017c1fd321ab5b405036b62058668ee8b524fadd)

- ⬜ **19:17:41 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`028b23cc1604`](https://github.com/gmanldn/smoothcast/commit/028b23cc16045b0e0db5e26cf043cc15e84f342f)

- 🟩 **19:17:41 · Feature** — feat: persist headless CLI latency (Refs #698) · [`f90451d2c34c`](https://github.com/gmanldn/smoothcast/commit/f90451d2c34cd3064a4574eb510a6fc4bb8937f3)

- ⬜ **19:17:41 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`39723f41b4d1`](https://github.com/gmanldn/smoothcast/commit/39723f41b4d1ec901024e9911696df6bc5070805)

- ⬜ **19:15:05 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`e759cdf4f1c5`](https://github.com/gmanldn/smoothcast/commit/e759cdf4f1c5101e66fb4ec3b297139a2f3be790)

- ⬜ **19:15:05 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`00d33f189408`](https://github.com/gmanldn/smoothcast/commit/00d33f189408eb0b4e2583ae9a8a19e381e1a0d7)

- 🟪 **19:14:59 · Tests** — test: cover upload symlink escape rejection (Refs #325) · [`fab3f44a31a6`](https://github.com/gmanldn/smoothcast/commit/fab3f44a31a63decde9177ff90e2a9b90e37284b)

- ⬜ **19:11:06 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`e91814dc3ae8`](https://github.com/gmanldn/smoothcast/commit/e91814dc3ae84225165da47904305a8623f1ce24)

- ⬜ **19:11:06 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`40e9108ff19d`](https://github.com/gmanldn/smoothcast/commit/40e9108ff19d98ac04026fc25e52be01351cd696)

- 🟥 **19:10:47 · Fix** — fix: contain guest uploads within the upload root (Refs #325) · [`fa85e55d8986`](https://github.com/gmanldn/smoothcast/commit/fa85e55d89861a77aafaa7c1dc9009cb313b2978)

- ⬜ **19:06:15 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`29e8a55217fa`](https://github.com/gmanldn/smoothcast/commit/29e8a55217fa177caf0ea69cc387282b708ab928)

- 🟥 **19:06:15 · Fix** — fix: honor deferred bootstrap interrupt before success (Refs #580) · [`6aa2138844b0`](https://github.com/gmanldn/smoothcast/commit/6aa2138844b0b32b5558dd6236a0c1d4b8c8f206)

- ⬜ **19:06:15 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`4886a238aba1`](https://github.com/gmanldn/smoothcast/commit/4886a238aba1dac3326ebacfce59d983be10b0a4)

- ⬜ **19:03:58 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`15e385f85a87`](https://github.com/gmanldn/smoothcast/commit/15e385f85a87cea4177b7e77023ac608c450033c)

- ⬜ **19:03:57 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`d8c8b51eb17a`](https://github.com/gmanldn/smoothcast/commit/d8c8b51eb17a243b268ec39eed5f7fea91245bfe)

- 🟪 **19:03:57 · CI** — ci: publish nightly develop health verdict (Refs #700) · [`07e2a292bb7c`](https://github.com/gmanldn/smoothcast/commit/07e2a292bb7ce847eba0b48fcf1b519b879d863a)

- ⬜ **18:59:03 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`17679752624c`](https://github.com/gmanldn/smoothcast/commit/17679752624cfd36d8cbce07f08630afee5dd70e)

- ⬜ **18:59:03 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`6dc79432597a`](https://github.com/gmanldn/smoothcast/commit/6dc79432597ad05b22be7c44aead1dbcefbe3e0d)

- 🟥 **18:58:58 · Fix** — fix: roll back upload offsets after checkpoint failure (Refs #568) · [`dd08800bb76a`](https://github.com/gmanldn/smoothcast/commit/dd08800bb76ade8fb9264d7f3004291b8617438e)

- ⬜ **18:56:41 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`23164a23cdbc`](https://github.com/gmanldn/smoothcast/commit/23164a23cdbc71e5f984f4eb212c7259b31d37cb)

- 🟥 **18:56:41 · Fix** — fix: defer bootstrap interrupts until rollback-safe points (Refs #580) · [`3ed049c33e0b`](https://github.com/gmanldn/smoothcast/commit/3ed049c33e0b8eb118f19ec7fd82d9d6ecef94f3)

- ⬜ **18:56:41 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`009ae0a95ddb`](https://github.com/gmanldn/smoothcast/commit/009ae0a95ddb07bf05c0bec542cb01b324d70920)

- ⬜ **18:53:48 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`2e1080c9e393`](https://github.com/gmanldn/smoothcast/commit/2e1080c9e393daaf8faa3effc4c11f98f3cc4d65)

- ⬜ **18:53:47 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`399b729ae092`](https://github.com/gmanldn/smoothcast/commit/399b729ae092cc59d8bd12b7a30baddfc212a717)

- 🟩 **18:53:47 · Feature** — feat: show complete mesh node details in web panel (Refs #710) · [`8ca8d693c851`](https://github.com/gmanldn/smoothcast/commit/8ca8d693c851b28e0dcc5e75dd47eb941b01b2f8)

- ⬜ **18:52:23 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`f3220e3822ac`](https://github.com/gmanldn/smoothcast/commit/f3220e3822ac46351e73dac6922eb6778a1f3a34)

- 🟪 **18:52:23 · Tests** — test: assert shared queue order in browser sync (Refs #324) · [`0664c5244c8e`](https://github.com/gmanldn/smoothcast/commit/0664c5244c8e90c3119d3c67933aba422a65d2b7)

- ⬜ **18:52:23 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`faac3947d537`](https://github.com/gmanldn/smoothcast/commit/faac3947d537e3fe2050a4bcf2fcb83317fe869b)

- ⬜ **18:48:01 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`3132d2016be0`](https://github.com/gmanldn/smoothcast/commit/3132d2016be0cbbeeb3e7b61ca66995277981f8c)

- 🟩 **18:48:01 · Feature** — feat: include platform in mesh node profiles (Refs #710) · [`5d06db71f813`](https://github.com/gmanldn/smoothcast/commit/5d06db71f8135eb402551b9cd3a4759d81e86249)

- 🟩 **18:48:01 · Feature** — feat: include platform in mesh node profiles (Refs #710) · [`ea9a0ceb0293`](https://github.com/gmanldn/smoothcast/commit/ea9a0ceb0293ee6ad1df0878ae5b87ee5e7a89aa)

- ⬜ **18:48:01 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`207c576a1fdd`](https://github.com/gmanldn/smoothcast/commit/207c576a1fdd9d59c48add3f8c7d5852598cad65)

- ⬜ **18:47:43 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`4fa6f60f40bb`](https://github.com/gmanldn/smoothcast/commit/4fa6f60f40bbea766d739137c14f5188746e0b39)

- 🟪 **18:47:43 · Tests** — test: align browser upload assertion with waiting playback state (Refs #570) · [`61e04e388cde`](https://github.com/gmanldn/smoothcast/commit/61e04e388cde2f5430c8cc70c5a9b7d00441c090)

- ⬜ **18:47:43 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`714edc6d17ee`](https://github.com/gmanldn/smoothcast/commit/714edc6d17ee774e7b96f24b41a17ce51f5a7a87)

- ⬜ **18:47:07 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`872a150c673e`](https://github.com/gmanldn/smoothcast/commit/872a150c673e78ed5b8a99f537e3c360eb2668ac)

- ⬜ **18:47:06 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`2a6f2ea268e2`](https://github.com/gmanldn/smoothcast/commit/2a6f2ea268e27174bdcc53875dff9650bb3a71fe)

- 🟦 **18:43:13 · Refactor** — refactor: use typed settings in cast restart paths (Refs #693) · [`eb959cac72a1`](https://github.com/gmanldn/smoothcast/commit/eb959cac72a1fd19b00c7386d4db4a9001a29e73)

- 🟦 **18:42:48 · Refactor** — refactor: use typed settings in cast restart paths (Refs #693) · [`92cc27cf8abb`](https://github.com/gmanldn/smoothcast/commit/92cc27cf8abb87b4291b487421a5613ddda3ff44)

- ⬜ **18:42:15 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`201031415e47`](https://github.com/gmanldn/smoothcast/commit/201031415e4773a5f4e7bdfc49f3551438b53888)

- ⬜ **18:42:15 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`b033372cde54`](https://github.com/gmanldn/smoothcast/commit/b033372cde5472a14a291e8452d280a956132e72)

- 🟪 **18:42:00 · CI** — ci: archive scheduled mesh transfer benchmark reports (Refs #573) · [`665c6ad8b06b`](https://github.com/gmanldn/smoothcast/commit/665c6ad8b06b4c0f38fa9ac47045e39d54497147)

- ⬜ **18:40:38 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`4c20fe536570`](https://github.com/gmanldn/smoothcast/commit/4c20fe5365705eb648823dbaf28dfa8910962f53)

- ⬜ **18:40:38 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`bb0aee60f37a`](https://github.com/gmanldn/smoothcast/commit/bb0aee60f37a5971c2c00a964ee2ed15da063d8d)

- 🟪 **18:40:33 · Tests** — test: inject transfer disconnect and verify retry recovery (Refs #573) · [`7cfc6261d0f1`](https://github.com/gmanldn/smoothcast/commit/7cfc6261d0f13e361ba24236c2f3f43644dfa293)

- ⬜ **18:38:52 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`cab53e513dcb`](https://github.com/gmanldn/smoothcast/commit/cab53e513dcb0304ff14a35d387b0ba65d2a2780)

- ⬜ **18:38:52 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`e6b98c99a21b`](https://github.com/gmanldn/smoothcast/commit/e6b98c99a21b4b11542aa6bcb426a9dbc0241faf)

- 🟩 **18:38:47 · Feature** — feat: add shaped transfer benchmarks and baseline comparison (Refs #573) · [`e4ff2c93fdd4`](https://github.com/gmanldn/smoothcast/commit/e4ff2c93fdd4ff3158ff7c1a0bee553765206704)

- ⬜ **18:37:21 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`1323f00931c2`](https://github.com/gmanldn/smoothcast/commit/1323f00931c2ce197e916939646511cdbc547955)

- ⬜ **18:37:21 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`d33cb3359ccd`](https://github.com/gmanldn/smoothcast/commit/d33cb3359ccd4f09524fd9c45e8c9fd8ffacdf7b)

- 🟩 **18:37:16 · Feature** — feat: add deterministic mesh transfer benchmark scenarios (Refs #573) · [`2f4577df3fb5`](https://github.com/gmanldn/smoothcast/commit/2f4577df3fb539b4a968c42a6a8863458abadd4b)

- ⬜ **18:33:30 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`1b1bb66257a3`](https://github.com/gmanldn/smoothcast/commit/1b1bb66257a3203fa02e30dfaa1026987428becf)

- ⬜ **18:33:30 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`d183b42e58a7`](https://github.com/gmanldn/smoothcast/commit/d183b42e58a70352e041e0c3c2e841cc9a750eb0)

- 🟪 **18:33:25 · Tests** — test: remove converted shortcut tests from text baseline (Refs #695) · [`2c5e9fa79ed4`](https://github.com/gmanldn/smoothcast/commit/2c5e9fa79ed429179efe2e50d6ee25e337a2fafa)

- ⬜ **18:31:28 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`2277764c04e1`](https://github.com/gmanldn/smoothcast/commit/2277764c04e11bd29007524f7e70e8961465885c)

- ⬜ **18:31:28 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`38b5b75b76fe`](https://github.com/gmanldn/smoothcast/commit/38b5b75b76fed8fe3879b8952d0bae887de34a0d)

- 🟥 **18:31:15 · Fix** — fix: show exact running build identity in updates (Refs #582) · [`35a9c1ad2a2a`](https://github.com/gmanldn/smoothcast/commit/35a9c1ad2a2af0c1b10c5d004325d3c5f05c5a37)

- ⬜ **18:31:08 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`710b64549cc8`](https://github.com/gmanldn/smoothcast/commit/710b64549cc8342c4bd2b4eb8b806f172ea097ae)

- ⬜ **18:31:08 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`69e6782698c8`](https://github.com/gmanldn/smoothcast/commit/69e6782698c8ffad4a65eaeda3f494e8110068c0)

- 🟥 **18:30:53 · Fix** — fix(errors): preserve cast startup failure during cleanup (Refs #694) · [`75a03407e462`](https://github.com/gmanldn/smoothcast/commit/75a03407e462d5e5c797dfcc043dfc406188065b)

- ⬜ **18:26:01 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`d247e56053f7`](https://github.com/gmanldn/smoothcast/commit/d247e56053f7e75c0b87affc01f3e40fec99f9bd)

- ⬜ **18:26:01 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`87d06f7cf6b1`](https://github.com/gmanldn/smoothcast/commit/87d06f7cf6b14f52abcc616f99ef149931f137d7)

- 🟨 **18:25:57 · Documentation** — docs(security): link portal threat model from handbook (Refs #702) · [`abd18926cd5d`](https://github.com/gmanldn/smoothcast/commit/abd18926cd5d60089a0cdc45976fcb7c4508a127)

- ⬜ **18:22:26 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`9eb28b06e0b5`](https://github.com/gmanldn/smoothcast/commit/9eb28b06e0b5c54ba73150ee88904cb0f288a993)

- ⬜ **18:22:26 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`fa0b90e6105e`](https://github.com/gmanldn/smoothcast/commit/fa0b90e6105e6fb9eac2ed977f7bef91a13d8962)

- 🟪 **18:22:13 · Tests** — test: exercise installed shortcuts behaviorally (Refs #699) · [`9bf3fcc4dbd4`](https://github.com/gmanldn/smoothcast/commit/9bf3fcc4dbd47f44022c608671f12a072f9ab60d)

- ⬜ **18:14:40 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`3a31538a4a49`](https://github.com/gmanldn/smoothcast/commit/3a31538a4a494b10a318c29bec09a14b12ce8a88)

- 🟥 **18:14:40 · Fix** — fix: check official develop when restarting installed SmoothCast (Refs #579) · [`4e88d9063820`](https://github.com/gmanldn/smoothcast/commit/4e88d90638201b0000e08f446a3cf7f1764a9d3c)

- ⬜ **18:14:40 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`7f93af38790a`](https://github.com/gmanldn/smoothcast/commit/7f93af38790a7b59c4adefe2578c8044d3a73316)

- ⬜ **18:13:18 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`3d21204b8e28`](https://github.com/gmanldn/smoothcast/commit/3d21204b8e28bac06f24af287c4d9d5b1bdf7413)

- ⬜ **18:13:18 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`e0621343c48c`](https://github.com/gmanldn/smoothcast/commit/e0621343c48ceaa489ab29aee6140939c03895ba)

- 🟥 **18:13:14 · Fix** — fix: keep Network profiles usable when uptime is unavailable (Refs #710) · [`0da01f9349ae`](https://github.com/gmanldn/smoothcast/commit/0da01f9349aeb30c9513348c645323272012d88d)

- ⬜ **18:10:55 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`fea1b3442501`](https://github.com/gmanldn/smoothcast/commit/fea1b3442501d277cd7a02a339b6e6212a3dcccb)

- ⬜ **18:10:55 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`a74b6f88725c`](https://github.com/gmanldn/smoothcast/commit/a74b6f88725c3b20de94873bdea00c6966376f45)

- ⬜ **18:10:50 · Maintenance** — style: polish the web Home player and quick actions (Refs #709) · [`064ecfe85539`](https://github.com/gmanldn/smoothcast/commit/064ecfe8553991ab7c82b5557f230363941b6660)

- ⬜ **18:06:41 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`13fc306185b3`](https://github.com/gmanldn/smoothcast/commit/13fc306185b3c2b2268ff7525ca59e0faf0f4354)

- 🟪 **18:06:41 · Tests** — test: recover browser upload checkpoint coverage (Refs #568) · [`31723d987d76`](https://github.com/gmanldn/smoothcast/commit/31723d987d76cba7dd7f4231896b9bee7db9c5de)

- ⬜ **18:06:41 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`e0670a3c9e36`](https://github.com/gmanldn/smoothcast/commit/e0670a3c9e366a784c2eaf7566c912b6def2cf7e)

- ⬜ **18:05:14 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`8899446c7667`](https://github.com/gmanldn/smoothcast/commit/8899446c76672a869ef5be32088472755a1b1ef8)

- 🟪 **18:05:14 · Tests** — test(agents): align hygiene gate with current develop-only policy (Refs #700) · [`20199530b869`](https://github.com/gmanldn/smoothcast/commit/20199530b869f3013fff0af9dc1dea94742c7f40)

- ⬜ **18:05:14 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`bcec07b92944`](https://github.com/gmanldn/smoothcast/commit/bcec07b929441b5969e304801b8197f01da8c227)

- ⬜ **18:03:43 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`a18ebbff3625`](https://github.com/gmanldn/smoothcast/commit/a18ebbff36259773a4db58c59da21b10fa896a1c)

- ⬜ **18:03:42 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`a1eb001dc594`](https://github.com/gmanldn/smoothcast/commit/a1eb001dc594ed6a77fbee8d0cd9c307aa70c0ab)

- 🟨 **18:03:42 · Documentation** — docs: measure upload checkpoints and clarify restart recovery (Refs #568) · [`ff46ce5ba397`](https://github.com/gmanldn/smoothcast/commit/ff46ce5ba397dca361266f65d3bf3e12ccf66250)

- ⬜ **18:03:07 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`5e89c097913c`](https://github.com/gmanldn/smoothcast/commit/5e89c097913cff34f319b5acf6218f9eec92e83f)

- ⬜ **18:03:07 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`e107c71a3caf`](https://github.com/gmanldn/smoothcast/commit/e107c71a3cafb3ece00d9f98ec52074fab3cf89d)

- 🟥 **18:03:06 · Fix** — fix(ci): restore agent control-plane checks (Refs #700) · [`a648b36632cc`](https://github.com/gmanldn/smoothcast/commit/a648b36632cc88eacaa057c5dab4c9f88e9581f8)

- ⬜ **18:02:13 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`a6a60f0781cb`](https://github.com/gmanldn/smoothcast/commit/a6a60f0781cbd4db8502e2aa82bdefb1b58f4918)

- 🟥 **18:02:13 · Fix** — fix: close SmoothCast cleanly on terminal Ctrl+C (Refs #717) · [`dd256b09bc66`](https://github.com/gmanldn/smoothcast/commit/dd256b09bc663c865e27431d3b27067b0c66372c)

- ⬜ **18:02:13 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`89afbdbd774d`](https://github.com/gmanldn/smoothcast/commit/89afbdbd774d68a61de54bc11cba5519ddca5339)

- ⬜ **18:01:42 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`08f1567163d0`](https://github.com/gmanldn/smoothcast/commit/08f1567163d04a1ffd7c7b7149208901cf8fae79)

- ⬜ **18:01:42 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`3175bba88354`](https://github.com/gmanldn/smoothcast/commit/3175bba883540d3eedf7690f68795e14767fbfed)

- 🟪 **18:01:34 · Tests** — test: restore sparse preview coverage after typed video settings (Refs #40) · [`064cf508c856`](https://github.com/gmanldn/smoothcast/commit/064cf508c856f10ab5ec054fec6a7464d9c69482)

- ⬜ **17:59:19 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`2c848fe00e9b`](https://github.com/gmanldn/smoothcast/commit/2c848fe00e9bd7670db176bc46a5c75db6354543)

- ⬜ **17:59:19 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`98afff3d68c8`](https://github.com/gmanldn/smoothcast/commit/98afff3d68c813fd7f2765dde45440c025d6f071)

- 🟪 **17:59:16 · Tests** — test: measure portal quit with overlapping mDNS goodbyes (Refs #705) · [`9dcdf679427a`](https://github.com/gmanldn/smoothcast/commit/9dcdf679427a49dc616583fd39c56b94abcff529)

- ⬜ **17:55:42 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`55762ff9e79d`](https://github.com/gmanldn/smoothcast/commit/55762ff9e79d0045330ecfb0120d71a18982b533)

- ⬜ **17:55:42 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`800b12e32422`](https://github.com/gmanldn/smoothcast/commit/800b12e324227bee908194743c8643bd7d79d9ca)

- 🟪 **17:55:38 · Tests** — test(agents): verify scope narrowing and changelog shipment recovery (Refs #715) · [`f44aafb27e8a`](https://github.com/gmanldn/smoothcast/commit/f44aafb27e8a1403505592ff37952c3eccb183b5)

- ⬜ **17:47:13 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`81ef38363e98`](https://github.com/gmanldn/smoothcast/commit/81ef38363e98d7411f65c7d3348bfb6a0cb34e57)

- ⬜ **17:47:13 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`2b9b67563a1d`](https://github.com/gmanldn/smoothcast/commit/2b9b67563a1d559975a9b371ffb28496ffa008d2)

- 🟥 **17:47:05 · Fix** — fix(stream): the live cast encoder runs at normal priority so a busy host no longer starves it below real time (0.52x observed at nice 10); background conversions stay low (Refs #686) (Refs #247) · [`00c82e3c414e`](https://github.com/gmanldn/smoothcast/commit/00c82e3c414e90d378ba1db970419d29cc8f1b84)

- 🟩 **17:45:09 · Feature** — feat(arch): supervisor.bounded() for deadline-limited closes, reused by Supervisor.stop (Refs #692) · [`9ca270116fc8`](https://github.com/gmanldn/smoothcast/commit/9ca270116fc83ce275ed35d8d38615dd8f72799f)

- 🟦 **17:43:48 · Refactor** — refactor(settings): typed VideoSettings group for quality, rotation, aspect and cover art; cast\_av reads it (Refs #693) · [`3c01805dae92`](https://github.com/gmanldn/smoothcast/commit/3c01805dae926970d94df3d7fb0565555f7c7684)

- 🟩 **17:42:16 · Feature** — feat(network): node profiles show uptime from the announced boot epoch, in the headline, GTK popover and web panel (Refs #710) · [`04965f6e2ae0`](https://github.com/gmanldn/smoothcast/commit/04965f6e2ae0277de0151a958b29c24df3c985d0)

- ⬜ **17:41:24 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`4c9361b1e77f`](https://github.com/gmanldn/smoothcast/commit/4c9361b1e77f19e53d8b68a66962cc3e0aa8b557)

- ⬜ **17:41:24 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`0651d1fb673d`](https://github.com/gmanldn/smoothcast/commit/0651d1fb673dc57831dd85562c879673f5e628c9)

- 🟦 **17:41:20 · Refactor** — refactor(errors): justify castctl boundary catches (Refs #694) · [`221c8aef1d00`](https://github.com/gmanldn/smoothcast/commit/221c8aef1d0058f3a141f8e01e52487d4f102881)

- ⬜ **17:39:23 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`dfae87c9bc00`](https://github.com/gmanldn/smoothcast/commit/dfae87c9bc0057079a975426b483683c703f4551)

- 🟦 **17:39:23 · Refactor** — refactor(errors): justify cli\_control boundary catch (Refs #694) · [`524dc74b2f87`](https://github.com/gmanldn/smoothcast/commit/524dc74b2f8779e1332270d79e9bbf004e355582)

- ⬜ **17:39:23 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`8423dc30e54a`](https://github.com/gmanldn/smoothcast/commit/8423dc30e54a66b91cdab09c06d91c8ebb62a9b2)

- 🟪 **17:38:58 · Tests** — test(update): settings test checks UpdateSettings behaviour instead of source text that moved; baseline shrinks (Refs #711) · [`27d8766e9cb1`](https://github.com/gmanldn/smoothcast/commit/27d8766e9cb1e497feea39d1f340ddfb2623ca9f)

- ⬜ **17:37:29 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`849548861772`](https://github.com/gmanldn/smoothcast/commit/8495488617729b1a8ac2e35d67ba5bc06487844a)

- 🟦 **17:37:29 · Refactor** — refactor(errors): justify boundary catches across eighteen more modules (Refs #694) · [`4a8a9c32de39`](https://github.com/gmanldn/smoothcast/commit/4a8a9c32de39b6daf2fde65617fbc4a66593ac89)

- ⬜ **17:37:29 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`def14edfa392`](https://github.com/gmanldn/smoothcast/commit/def14edfa3924ff2496e1944ba091490753c7296)

- 🟪 **17:35:54 · Tests** — test(gui): frame-step test drives the real mixin methods and installed shortcuts via a new gui\_shortcuts helper; baseline shrinks (Refs #699) · [`ba8b6d36a67d`](https://github.com/gmanldn/smoothcast/commit/ba8b6d36a67debdc88f57f56ab0c438f4deda463)

- ⬜ **17:34:28 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`2edf2a4667ef`](https://github.com/gmanldn/smoothcast/commit/2edf2a4667efcfd9939e994a6c1608cef6b540b5)

- ⬜ **17:34:27 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`4b96ee7e3208`](https://github.com/gmanldn/smoothcast/commit/4b96ee7e320808b709477ea9681c556150a57336)

- 🟦 **17:34:27 · Refactor** — refactor(errors): justify boundary catches across fifteen more modules (Refs #694) · [`ef6cbef75ad1`](https://github.com/gmanldn/smoothcast/commit/ef6cbef75ad1ab8f760a746c8b5fa4fe964354ee)

- 🟪 **17:34:03 · Tests** — test(cast): warmup test calls the window timer start with fakes instead of reading source text; unblocks the source-text ratchet (Refs #699) · [`e9084c5e65d8`](https://github.com/gmanldn/smoothcast/commit/e9084c5e65d855ac10bde7948bb708f299463daa)

- 🟩 **17:31:59 · Feature** — feat(room): RoomService JSON facade over queue and playback with payload validation and one lock, shared by portal, GTK and mesh adapters (Refs #695) · [`c26872fa944c`](https://github.com/gmanldn/smoothcast/commit/c26872fa944c7531758e414f0d39d3a8a02baea3)

- 🟦 **17:30:02 · Refactor** — refactor(arch): drop duplicate power\_backends module; power\_port is the single sleep-inhibit port (Refs #703) · [`ba7f0ed6eef8`](https://github.com/gmanldn/smoothcast/commit/ba7f0ed6eef898d484308789d8a385323024e329)

- ⬜ **17:29:56 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`f202a8c07bc5`](https://github.com/gmanldn/smoothcast/commit/f202a8c07bc585d75efc0b88f7b69dc6e21c257e)

- ⬜ **17:29:55 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`e9a7f8b73d18`](https://github.com/gmanldn/smoothcast/commit/e9a7f8b73d181d77101aef17449e68bb3fd4c258)

- 🟦 **17:29:55 · Refactor** — refactor(errors): justify boundary catches across eleven more modules (Refs #694) · [`ef476a643720`](https://github.com/gmanldn/smoothcast/commit/ef476a643720e6f9e2e75c3154eb065fe560e078)

- 🟥 **17:29:17 · Fix** — fix(agents): run ship checks at nice 19/ionice idle so pytest -n auto never starves a live cast's encoder on the owner's desktop (Refs #686) · [`84b813c02047`](https://github.com/gmanldn/smoothcast/commit/84b813c02047a3a88416b8136ab475744eb4cb68)

- 🟩 **17:28:15 · Feature** — feat(diagnostics): shared latency Stats with atomic save/load; the CLI diagnostics command bundles saved latency (Refs #698) · [`f63150530922`](https://github.com/gmanldn/smoothcast/commit/f6315053092277f399939e137a0647fcf84a69ec)

- ⬜ **17:27:04 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`97a4169032d7`](https://github.com/gmanldn/smoothcast/commit/97a4169032d751c30af0d0fa5e1edbfe595ba628)

- ⬜ **17:27:03 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`2e1e1d1ae6fd`](https://github.com/gmanldn/smoothcast/commit/2e1e1d1ae6fdc96b56a88b6cdf0785d42eacf66b)

- 🟦 **17:27:03 · Refactor** — refactor(errors): justify 21 boundary catches across nine modules (Refs #694) · [`d95f0b281989`](https://github.com/gmanldn/smoothcast/commit/d95f0b281989862282543002601107b01d28dc4a)

- 🟩 **17:25:46 · Feature** — feat(diagnostics): bundle carries latency percentiles and buckets when a Stats is supplied (Refs #698) · [`dd0c4cefd543`](https://github.com/gmanldn/smoothcast/commit/dd0c4cefd54382c808f4e20cc5241663c9d4c4fb)

- 🟦 **17:24:14 · Refactor** — refactor(runtime): sc\_core loop runs under spawn\_daemon keeping its thread name; allowance removed (Refs #696) · [`4dea2bedca9d`](https://github.com/gmanldn/smoothcast/commit/4dea2bedca9d0c8e4b1d8846b70fa4518e42236e)

- ⬜ **17:23:30 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`7670fadf573b`](https://github.com/gmanldn/smoothcast/commit/7670fadf573b406a4975ac08265cec9ce2be811d)

- ⬜ **17:23:29 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`8dfe02001d53`](https://github.com/gmanldn/smoothcast/commit/8dfe02001d536ad2f479b8967e4da8c210e5579a)

- 🟦 **17:23:28 · Refactor** — refactor(errors): justify 13 boundary catches in portal\_screens\_http, config\_control, mesh\_ui (Refs #694) · [`e3544c342b58`](https://github.com/gmanldn/smoothcast/commit/e3544c342b5842e4dc3da5c19d1846b2965b4724)

- 🟦 **17:22:02 · Refactor** — refactor(runtime): library indexer runs under spawn\_daemon, observes scope cancel within 1s; allowance removed (Refs #696) · [`4f4cad12d3d7`](https://github.com/gmanldn/smoothcast/commit/4f4cad12d3d703b280134b1c995d4b0beaf22f86)

- ⬜ **17:19:31 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`573414ba54bb`](https://github.com/gmanldn/smoothcast/commit/573414ba54bbe9bbfda9576bb8b1b6d6d9ad8b95)

- 🟥 **17:19:31 · Fix** — fix(preferences): split shared-room group into preferences\_room\_ui to restore size budget (Refs #706) · [`2e6ceb1f2ee8`](https://github.com/gmanldn/smoothcast/commit/2e6ceb1f2ee8fc23d1b539313be264ebd0668b40)

- ⬜ **17:19:31 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`97137c817b12`](https://github.com/gmanldn/smoothcast/commit/97137c817b12dcc0dbd0744cb121243228dabae7)

- 🟦 **17:18:41 · Refactor** — refactor(runtime): mesh heartbeat runs under spawn\_daemon keeping its thread name; allowance removed (Refs #696) · [`162792480f21`](https://github.com/gmanldn/smoothcast/commit/162792480f214e6553de940f99459feda2341021)

- 🟦 **17:16:06 · Refactor** — refactor(runtime): mesh loop thread runs under spawn\_daemon keeping its smoothcast-mesh name; spawn\_daemon takes thread\_name; allowance removed (Refs #696) · [`bed11997289d`](https://github.com/gmanldn/smoothcast/commit/bed11997289d10de103203c8fcf11b2a72742442)

- ⬜ **17:15:27 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`b7ddc57afc19`](https://github.com/gmanldn/smoothcast/commit/b7ddc57afc19ec1238a1babd9aae429ad2446341)

- ⬜ **17:15:26 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`c0ce904d6497`](https://github.com/gmanldn/smoothcast/commit/c0ce904d649703eb77d1a3862f0e196fa03b2556)

- 🟦 **17:15:26 · Performance** — perf(cast): warm the FFmpeg version check off-thread at window start so the first cast skips a ~4.6 s stall · [`322bffa0ae7b`](https://github.com/gmanldn/smoothcast/commit/322bffa0ae7b1caf3153708d054944adacea4c83)

- ⬜ **17:14:58 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`aee6c1cdc19a`](https://github.com/gmanldn/smoothcast/commit/aee6c1cdc19ad8f1bc3cb96b95f62069830fa25a)

- ⬜ **17:14:58 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`c2b391a9adf5`](https://github.com/gmanldn/smoothcast/commit/c2b391a9adf5872788e94b877e42ded6ef897d1f)

- 🟦 **17:14:50 · Refactor** — refactor(errors): justify 16 boundary catches across five small modules (Refs #694) · [`f4ef2a6e2b28`](https://github.com/gmanldn/smoothcast/commit/f4ef2a6e2b289ea6ff1bbb15b1a8ac78e06aef3c)

- ⬜ **17:11:40 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`15887829be0d`](https://github.com/gmanldn/smoothcast/commit/15887829be0d5d45e02947d137497556e8bd9a99)

- ⬜ **17:11:40 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`de83a1486d92`](https://github.com/gmanldn/smoothcast/commit/de83a1486d9254ca7dda989748929448f1bfc627)

- 🟦 **17:11:38 · Refactor** — refactor(errors): justify the 12 boundary catches in pychromecast\_backend (Refs #694) · [`0322ab5aaf0e`](https://github.com/gmanldn/smoothcast/commit/0322ab5aaf0ebcdb7370eaf94bd6e574b3ef06c3)

- 🟦 **17:11:13 · Refactor** — refactor(runtime): egress proxy accept loop and per-connection tunnels run under task\_runtime.spawn\_daemon; close cancels the scope; raw-thread allowance removed (Refs #696) · [`6dca7bb93473`](https://github.com/gmanldn/smoothcast/commit/6dca7bb9347315aa4c4277a33748fecea7fa2a9b)

- ⬜ **17:09:45 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`d466985106c2`](https://github.com/gmanldn/smoothcast/commit/d466985106c2f20757847cd759819b7889712287)

- ⬜ **17:09:45 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`7119d92eeffd`](https://github.com/gmanldn/smoothcast/commit/7119d92eeffdb9c3990a834cd5346759cf21daa2)

- 🟦 **17:09:39 · Refactor** — refactor(errors): justify boundary catches in sc\_core and cast\_mesh (Refs #694) · [`bfe21937f4ee`](https://github.com/gmanldn/smoothcast/commit/bfe21937f4ee24287c7ac1414cccb831a7918388)

- 🟦 **17:07:38 · Refactor** — refactor(runtime): replica\_manager loop runs under task\_runtime.spawn\_daemon; Scope.wait wakes on cancel; raw-thread allowance lowered (Refs #696) · [`1070bda004fe`](https://github.com/gmanldn/smoothcast/commit/1070bda004fe69caeea826e8e47408a1f5540a1e)

- ⬜ **17:06:10 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`45e9c8f0178d`](https://github.com/gmanldn/smoothcast/commit/45e9c8f0178d75b952ecc355b4108076017f21fb)

- ⬜ **17:06:10 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`04cd4cc9cda8`](https://github.com/gmanldn/smoothcast/commit/04cd4cc9cda82512300e58f182d067e34830e57b)

- 🟦 **17:06:09 · Refactor** — refactor(errors): justify boundary catches in desktop\_failure\_notice and peer\_discovery (Refs #694) · [`aef743601af5`](https://github.com/gmanldn/smoothcast/commit/aef743601af586be02ae29cb8aea137743f75e65)

- 🟩 **17:05:45 · Feature** — feat(runtime): spawn\_daemon owns long-lived loops (named, counted, cancelled and joined at shutdown, errors recorded), unblocking migration of accept loops and heartbeats (Refs #696) · [`bdd45e8d4338`](https://github.com/gmanldn/smoothcast/commit/bdd45e8d4338aef07b92910c86efb731cf6b444a)

- ⬜ **17:03:56 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`99e349a4ee76`](https://github.com/gmanldn/smoothcast/commit/99e349a4ee760f3d2b85bb8bb567ed694c15188b)

- ⬜ **17:03:55 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`a97e6feb27ff`](https://github.com/gmanldn/smoothcast/commit/a97e6feb27ff2f6027cb3884a7d1d99034130a7a)

- 🟦 **17:03:55 · Refactor** — refactor(errors): justify the five zeroconf boundary catches in entry\_name; ratchet drops (Refs #694) · [`4790db4c2860`](https://github.com/gmanldn/smoothcast/commit/4790db4c286085b48e445182e8766db6aa875bb6)

- 🟥 **17:03:01 · Fix** — fix(room): a rejected playback command key stays rejected on retry, same rule as room\_store (Refs #695) · [`3be92d035431`](https://github.com/gmanldn/smoothcast/commit/3be92d035431123c14cc5ffc0c0c3f3fe267e06e)

- ⬜ **17:01:55 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`c6b3227d6b14`](https://github.com/gmanldn/smoothcast/commit/c6b3227d6b14c7512caf33a5a1f5aa5d63d94873)

- ⬜ **17:01:55 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`df934baf8584`](https://github.com/gmanldn/smoothcast/commit/df934baf8584b6e7fd8fe57d1e18973c36ffa51e)

- 🟨 **17:01:49 · Documentation** — docs(uploads): document received/committed offsets and coalesced checkpoint contract (Refs #568) · [`4b0f53310ff3`](https://github.com/gmanldn/smoothcast/commit/4b0f53310ff3c0da6adc797feccad9845d803ca4)

- 🟥 **17:01:34 · Fix** — fix(room): a rejected command key stays rejected on retry (found by property test); add events\_since and Replica for rejoin (Refs #695) · [`542303d8244e`](https://github.com/gmanldn/smoothcast/commit/542303d8244e711ed8350d205fc5e4f2462ab60a)

- ⬜ **16:58:34 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`33faac9b7327`](https://github.com/gmanldn/smoothcast/commit/33faac9b73270af1359eaf6dc28b04be4f9dacf1)

- ⬜ **16:58:34 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`82409d5e5e34`](https://github.com/gmanldn/smoothcast/commit/82409d5e5e342b5b84dc2492c627cbdbe183c73d)

- 🟥 **16:58:33 · Fix** — fix(portal): repair syntax error in route table from previous patch (Refs #689) · [`0791e010c417`](https://github.com/gmanldn/smoothcast/commit/0791e010c417d76a7103bcb2083317772cd4ade9)

- 🟩 **16:57:55 · Feature** — feat(arch): power-inhibit backends (logind, caffeinate, Windows) and fake behind one contract test, injected OS calls, unwired (Refs #703) · [`ffc427c93124`](https://github.com/gmanldn/smoothcast/commit/ffc427c93124aacda52e3d6350a61b3820e99bfc)

- ⬜ **16:57:29 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`805574cdd94a`](https://github.com/gmanldn/smoothcast/commit/805574cdd94a70d8abe4185ec203be7870a23e37)

- ⬜ **16:57:29 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`886305779283`](https://github.com/gmanldn/smoothcast/commit/886305779283cbf4f771fbd939957b9e25bfd257)

- 🟩 **16:57:28 · Feature** — feat(doctor): warn when the receiver route runs through a VPN; doctor.py baseline 187-&gt;188 for the one-line hook into doctor\_vpn (Refs #211, #210) (Refs #325) · [`41c5a1f878d1`](https://github.com/gmanldn/smoothcast/commit/41c5a1f878d10988b454c7ebe4cd5545ecc8f405)

- ⬜ **16:55:08 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`d369e2dc030f`](https://github.com/gmanldn/smoothcast/commit/d369e2dc030f7bfb43616ec838e6eb09cc243431)

- ⬜ **16:55:07 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`a0a11de7f67e`](https://github.com/gmanldn/smoothcast/commit/a0a11de7f67e12aef5cb05e002a912847de5865a)

- 🟪 **16:54:44 · Tests** — test(portal): route table must match api\_spec auth/csrf; fix /api/session policy (Refs #689) · [`eaba79dd45cd`](https://github.com/gmanldn/smoothcast/commit/eaba79dd45cd97e8cf14a98e5871303bafdd2022)

- 🟩 **16:52:44 · Feature** — feat(ci): pure time-to-red measure with the 15-minute budget (Refs #700) · [`e8084a33647a`](https://github.com/gmanldn/smoothcast/commit/e8084a33647a66ee5b951a876aa188d6d4eefc42)

- ⬜ **16:52:20 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`8ae1b7f5931a`](https://github.com/gmanldn/smoothcast/commit/8ae1b7f5931ac86a826d66ac1a2087fae00f29a0)

- ⬜ **16:52:20 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`b8a56d56579b`](https://github.com/gmanldn/smoothcast/commit/b8a56d56579b493fcfe92a118cc92a5e6a5a8f89)

- 🟪 **16:52:11 · Tests** — test(arch): ratchet against new two-way imports; one known cycle frozen (Refs #690) · [`ac557b5e4e98`](https://github.com/gmanldn/smoothcast/commit/ac557b5e4e9869a8b244d6e17cfb46254351b62d)

- 🟪 **16:50:41 · CI** — ci(security): portal-security job also runs the parser fuzz, egress policy and capability gate tests (Refs #702) · [`83c9705bda1e`](https://github.com/gmanldn/smoothcast/commit/83c9705bda1e2bcb2d0b4addc697634238992eb8)

- ⬜ **16:49:51 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`78ff032502ba`](https://github.com/gmanldn/smoothcast/commit/78ff032502ba04929b943ebe111c835bb9704c9e)

- ⬜ **16:49:51 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`120a3d50564a`](https://github.com/gmanldn/smoothcast/commit/120a3d50564ac99daddecdd6f12b4df2f70ddefa)

- 🟥 **16:49:42 · Fix** — fix(audio): local preview meter uses the shared 6 dB default gain (Refs #693) · [`2c84cc0a4bd7`](https://github.com/gmanldn/smoothcast/commit/2c84cc0a4bd7183b839f12dabc3fe58dfd090faa)

- ⬜ **16:48:12 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`3431044e53c1`](https://github.com/gmanldn/smoothcast/commit/3431044e53c1b58a08e6805e8f8340f9649b74a1)

- ⬜ **16:48:12 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`da6d9d4454b7`](https://github.com/gmanldn/smoothcast/commit/da6d9d4454b75f08e729f91605e3883209b09883)

- 🟪 **16:48:04 · Tests** — test(state): behavioural state-label tests replace source reads; baseline shrinks (Refs #699) · [`d2ed3d37595e`](https://github.com/gmanldn/smoothcast/commit/d2ed3d37595e17b24915b0f4867a73a667683178)

- ⬜ **16:47:03 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`02216e998ab2`](https://github.com/gmanldn/smoothcast/commit/02216e998ab290ac45a29ed6898934b2562a6879)

- ⬜ **16:47:02 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`abdc1689985d`](https://github.com/gmanldn/smoothcast/commit/abdc1689985d1dcbf57e11959ea3d0ee000bcbd3)

- 🟩 **16:47:02 · Feature** — feat(network): route diagnostic reports a plain VPN warning from address\_policy (Refs #210) (Refs #325) · [`06856f793b24`](https://github.com/gmanldn/smoothcast/commit/06856f793b24a1e6cbeb999e3510bf6afc9380fc)

- ⬜ **16:46:17 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`a6bbd0f719e2`](https://github.com/gmanldn/smoothcast/commit/a6bbd0f719e28aa7ac6a774f0b4a592c4db0a3cc)

- ⬜ **16:46:16 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`7558cb664bd4`](https://github.com/gmanldn/smoothcast/commit/7558cb664bd474a28130728eecb9fb6409e6d5ce)

- 🟩 **16:46:16 · Feature** — feat(portal): declarative route table with policy in data (Refs #689) · [`0765c06e43a7`](https://github.com/gmanldn/smoothcast/commit/0765c06e43a791d7aaa23d27584c67c98b9663f5)

- 🟨 **16:45:51 · Documentation** — docs(perf): record first isolated-Xvfb interaction run; every scenario breaches its SLO, no baseline committed (Refs #627) · [`b0bf6d886610`](https://github.com/gmanldn/smoothcast/commit/b0bf6d886610258e01ded41733cb2098c044abf3)

- ⬜ **16:43:45 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`d16fd0b3467a`](https://github.com/gmanldn/smoothcast/commit/d16fd0b3467a21d1edbd68002368755922937ce3)

- ⬜ **16:43:44 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`d3374183c9d7`](https://github.com/gmanldn/smoothcast/commit/d3374183c9d7b846966916ba218b204be31080bf)

- 🟩 **16:43:36 · Feature** — feat(sandbox): Sandbox port with bubblewrap and sandbox-exec backends, visible degradation (Refs #703) · [`ffc34fe99fa8`](https://github.com/gmanldn/smoothcast/commit/ffc34fe99fa81310717cb4bcd921efaea77faf57)

- ⬜ **16:41:45 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`e56bbef2aaed`](https://github.com/gmanldn/smoothcast/commit/e56bbef2aaedb95ba8d4ed17a7a191404531ec1b)

- ⬜ **16:41:45 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`96d37cd3f91d`](https://github.com/gmanldn/smoothcast/commit/96d37cd3f91d9ce10ec460ff72d85d28312cba70)

- 🟩 **16:41:44 · Feature** — feat(power): PowerManager port with systemd, caffeinate and Windows backends plus fake (Refs #703) · [`04ff9993d480`](https://github.com/gmanldn/smoothcast/commit/04ff9993d480e02b414c7d6ad204178f32405870)

- ⬜ **16:41:05 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`f9ac6c5e7676`](https://github.com/gmanldn/smoothcast/commit/f9ac6c5e7676b5c3a86d0e5161e8c62bd4b952a1)

- 🟥 **16:40:03 · Fix** — fix(gui): external streams with no reported length show a moving playhead marker, elapsed time and 'Live'/'length not reported' on native and web (Refs #635) · [`b27c748f80fa`](https://github.com/gmanldn/smoothcast/commit/b27c748f80fa1795ec71b49118c72b54e546873a)

- ⬜ **16:39:32 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`0751572a68d6`](https://github.com/gmanldn/smoothcast/commit/0751572a68d62f6397b87169b9f6e9dc8d617d5b)

- ⬜ **16:39:31 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`9e30dfe83aef`](https://github.com/gmanldn/smoothcast/commit/9e30dfe83aef3cb14faa58e1abb6fc2aaca42887)

- 🟩 **16:39:26 · Feature** — feat(hw): QSV and VideoToolbox backends behind the HardwareEncoder port (Refs #703) · [`1c7ebc316378`](https://github.com/gmanldn/smoothcast/commit/1c7ebc316378578d4ff1d3f77aaee9386bdf32c5)

- ⬜ **16:36:37 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`3227c9b2a3a6`](https://github.com/gmanldn/smoothcast/commit/3227c9b2a3a6a558f23f50eff57f242fa0c6c761)

- 🟩 **16:36:37 · Feature** — feat(attempts): attempt folders default to the active command-trace id; ids sanitised (Refs #698) · [`8b7b70d8fa31`](https://github.com/gmanldn/smoothcast/commit/8b7b70d8fa31b7c5b9ffb9eca8fa03582a0cd70d)

- ⬜ **16:36:37 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`8389ea277a36`](https://github.com/gmanldn/smoothcast/commit/8389ea277a36bcea24e87fbdf9dd68843cb6d3d8)

- ⬜ **16:36:25 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`58614346f12e`](https://github.com/gmanldn/smoothcast/commit/58614346f12e36921b40b17b477fbeea8aee7e58)

- 🟩 **16:36:25 · Feature** — feat(errors): app.save\_failed code, recorded when a store write fails (Refs #207, #701) (Refs #325) · [`82b6356dfcc6`](https://github.com/gmanldn/smoothcast/commit/82b6356dfcc6ff2cf13ffc14ddfae08242d53f25)

- ⬜ **16:36:25 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`0beec0947d94`](https://github.com/gmanldn/smoothcast/commit/0beec0947d94e726e948813ed342bde0a4324ea5)

- 🟪 **16:34:18 · Tests** — test(arch): test\_managed\_source reads a staged temp file, not production source; baseline 104 -&gt; 103 (Refs #699) · [`f223f0509ce5`](https://github.com/gmanldn/smoothcast/commit/f223f0509ce5bc90b8f7b7602de26104f6a83891)

- ⬜ **16:34:10 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`ba42de094a4b`](https://github.com/gmanldn/smoothcast/commit/ba42de094a4b781fc4ae023f8eb4da5bf1565743)

- ⬜ **16:34:10 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`3b5368476438`](https://github.com/gmanldn/smoothcast/commit/3b53684764380374128d24fa6540ba5643e3eed1)

- 🟩 **16:33:59 · Feature** — feat(cli): smoothcast diagnose writes a redacted support bundle, nothing sent (Refs #698) · [`f62681e7a1a4`](https://github.com/gmanldn/smoothcast/commit/f62681e7a1a44e43cc5a2dfc6ac642bcdd840f23)

- 🟪 **16:30:13 · Tests** — test(arch): convert two source-text tests (accent default behaviour, action-state wiring greps removed); baseline 106 -&gt; 104 (Refs #699) · [`db4d71c0494a`](https://github.com/gmanldn/smoothcast/commit/db4d71c0494a5b98f89f40621bfa17129b1ea961)

- ⬜ **16:28:29 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`a914823490f9`](https://github.com/gmanldn/smoothcast/commit/a914823490f986567886fcaf680f07fa2ca5e919)

- ⬜ **16:28:28 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`18b63b01bd24`](https://github.com/gmanldn/smoothcast/commit/18b63b01bd242426d7e256983a30e58dbdd91808)

- 🟪 **16:28:23 · Tests** — test(quarantine): 7 known-red agent lifecycle tests dated and owned until 2026-12-11 (Refs #700) · [`3adcb7a73d6b`](https://github.com/gmanldn/smoothcast/commit/3adcb7a73d6bffb9b94570e24e5f45ca1407813c)

- ⬜ **16:23:58 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`b10ff6160cca`](https://github.com/gmanldn/smoothcast/commit/b10ff6160ccafe6c0bc5f61dd911b8875af25fcd)

- ⬜ **16:23:57 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`6221a584f7b6`](https://github.com/gmanldn/smoothcast/commit/6221a584f7b6bf26745ccd1e319e8599b1968eda)

- 🟩 **16:23:57 · Feature** — feat(room): receiver ownership and playback as replayable commands/events (Refs #695) · [`8da3eaa4a927`](https://github.com/gmanldn/smoothcast/commit/8da3eaa4a927aaea323ae1a393fe755c8d908dce)

- 🟩 **16:23:22 · Feature** — feat(observability): bounded local latency histograms and correlation ids, pure and unwired (Refs #698) · [`43380ccd2ec2`](https://github.com/gmanldn/smoothcast/commit/43380ccd2ec2b42c6a788a52bcfeb5d83b613ad1)

- ⬜ **16:21:37 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`95cf434105bf`](https://github.com/gmanldn/smoothcast/commit/95cf434105bfdaa92c559fde66b59e87e879d1d6)

- ⬜ **16:21:36 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`ba193b666472`](https://github.com/gmanldn/smoothcast/commit/ba193b66647225bcec66e231dd97d42e54aa2df3)

- 🟪 **16:21:31 · Tests** — test(errors): broad-except ratchet, 233 untagged frozen across 89 files (Refs #694) · [`9c61b1972227`](https://github.com/gmanldn/smoothcast/commit/9c61b19722275193fad967d50c51399c31a94055)

- 🟩 **16:18:57 · Feature** — feat(release): GPLv3 source-offer gate: licence/notice text, tag+SHA pin, About link, FFmpeg disclosure with negative fixtures (Refs #538) · [`36fb164eae52`](https://github.com/gmanldn/smoothcast/commit/36fb164eae5290850fbab0c5b1eb0e3ae36f9a1b)

- ⬜ **16:17:54 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`503726f17510`](https://github.com/gmanldn/smoothcast/commit/503726f1751053da532a2a8c974e78c083342eae)

- ⬜ **16:17:53 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`da24af847baa`](https://github.com/gmanldn/smoothcast/commit/da24af847baa55028c659748a05fc2dc32f2bb7b)

- 🟦 **16:17:53 · Refactor** — refactor(settings): speed and gain controls read AudioSettings/PlaybackSettings (Refs #693) · [`d79d2cc65c3d`](https://github.com/gmanldn/smoothcast/commit/d79d2cc65c3dbe7751b6618293e0bc5038cbde20)

- ⬜ **16:17:35 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`8c734835d60b`](https://github.com/gmanldn/smoothcast/commit/8c734835d60bb3b0c2f05b04fc910ecb13d56100)

- ⬜ **16:17:35 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`7d466e0ea9c3`](https://github.com/gmanldn/smoothcast/commit/7d466e0ea9c3eebff5fcdafc19f8920f3e11ef0b)

- ⬜ **16:17:34 · Maintenance** — chore: rebaseline update\_managed.py complexity 26-&gt;41; #690 moved setup-module loading into it to drop sys.path mutation (Refs #706) · [`b94e6b37cb1c`](https://github.com/gmanldn/smoothcast/commit/b94e6b37cb1c94aa0bd10279f849570e9eaee7f2)

- ⬜ **16:17:17 · Maintenance** — Merge pull request #716 from gmanldn/develop · [`1122bbb01731`](https://github.com/gmanldn/smoothcast/commit/1122bbb01731536a47bccb76dc05f1c5a70cc676)

- ⬜ **16:14:23 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`1c408ddef26a`](https://github.com/gmanldn/smoothcast/commit/1c408ddef26a3285c6662a000bf5fc0423634d2a)

- ⬜ **16:14:23 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`cf9f9a1fc237`](https://github.com/gmanldn/smoothcast/commit/cf9f9a1fc2375ddd3bd40187515afa6f4dba6991)

- 🟪 **16:14:14 · Tests** — test(tiers): report-only per-tier time summary (Refs #699) · [`fabb01b05e4e`](https://github.com/gmanldn/smoothcast/commit/fabb01b05e4e41207d2cce0ba308b8b0f9176f8a)

- ⬜ **16:13:14 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`2b4aed75c83c`](https://github.com/gmanldn/smoothcast/commit/2b4aed75c83c405bbf44b803edc2ddc3b081d191)

- ⬜ **16:13:14 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`7b10fc947e9b`](https://github.com/gmanldn/smoothcast/commit/7b10fc947e9b2f4706537d0deb1a4a069ddd05aa)

- 🟥 **16:12:56 · Fix** — fix(web): CSS comment no longer reads as a hard-coded colour; clears the last quarantine entry (Refs #700) (Refs #325) · [`2a60c75eae50`](https://github.com/gmanldn/smoothcast/commit/2a60c75eae50a803b172fc1faa077f225faeaaae)

- ⬜ **16:10:27 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`f7d41c487730`](https://github.com/gmanldn/smoothcast/commit/f7d41c487730a6e7f578d826c112495a8f793d4f)

- ⬜ **16:10:26 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`70218ff4a468`](https://github.com/gmanldn/smoothcast/commit/70218ff4a4686bac5d288b1d2d71c8ad45e9468c)

- 🟥 **16:10:25 · Fix** — fix(a11y): label the room-name entry and drop its quarantine entry (Refs #700) (Refs #325) · [`b95718ccf5a4`](https://github.com/gmanldn/smoothcast/commit/b95718ccf5a4ea3016489f4db9a76d0cc381ac74)

- 🟪 **16:09:59 · Tests** — test(upload): over HTTP a 503 early-cast rejection is retried and accepted on the next chunk (Refs #686) · [`21987441f49e`](https://github.com/gmanldn/smoothcast/commit/21987441f49e316b43832224c1b3342340b833ea)

- 🟦 **16:08:30 · Refactor** — refactor(runtime): update button check/apply run on the bounded network pool; raw-thread ratchet shrinks by 3 (Refs #696) · [`df6295eaaf78`](https://github.com/gmanldn/smoothcast/commit/df6295eaaf78d614b26fb25d618f51ae9d987ebb)

- ⬜ **16:07:50 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`b3b86580c7b2`](https://github.com/gmanldn/smoothcast/commit/b3b86580c7b222612950464a82fad0e4c43ace78)

- ⬜ **16:07:49 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`6a89078cf06f`](https://github.com/gmanldn/smoothcast/commit/6a89078cf06f0807a7a420596b507aeea99b6cc0)

- 🟪 **16:07:41 · Tests** — test(store): record presence.py as explicit raw-writer debt (Refs #701) · [`a25d9c44a0aa`](https://github.com/gmanldn/smoothcast/commit/a25d9c44a0aa781e67bff0dd068ead789f4e2e73)

- ⬜ **16:06:13 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`bda5e86d4630`](https://github.com/gmanldn/smoothcast/commit/bda5e86d4630eb80042c4dccbc889096e9b4254f)

- 🟦 **16:06:13 · Refactor** — refactor(store): house\_history and known\_nodes persist via Store (Refs #701) · [`a438a89da58a`](https://github.com/gmanldn/smoothcast/commit/a438a89da58aad5fd80d62e6ce93631a8fe16c36)

- ⬜ **16:06:13 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`0afe32a4b965`](https://github.com/gmanldn/smoothcast/commit/0afe32a4b9657800e0c57b734a3e161553ea227e)

- ⬜ **16:04:28 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`b95d0a279bc6`](https://github.com/gmanldn/smoothcast/commit/b95d0a279bc6905ecaa218e1558ba59d383ada8e)

- ⬜ **16:04:27 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`eba496590660`](https://github.com/gmanldn/smoothcast/commit/eba4965906605e09f86312fa8fee4a2ad57edb0a)

- 🟦 **16:04:08 · Refactor** — refactor(paths): control\_api and portal\_uploads use paths.APP\_DIR; allowlist shrinks to 4 (Refs #701) (Refs #325) · [`1910a690b139`](https://github.com/gmanldn/smoothcast/commit/1910a690b139e73fb4559f252d8c661cb0e8be01)

- ⬜ **16:03:18 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`e2a38bcf34e3`](https://github.com/gmanldn/smoothcast/commit/e2a38bcf34e301646cf01f5400c4a9e46dde69f2)

- 🟦 **16:03:18 · Refactor** — refactor(store): error\_tail publish state uses Store (Refs #701) · [`b96e603d02d8`](https://github.com/gmanldn/smoothcast/commit/b96e603d02d83a0158a5bd724c7e2fcedced67e3)

- ⬜ **16:03:18 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`b37423710fe2`](https://github.com/gmanldn/smoothcast/commit/b37423710fe2481017b567d0f89e481ce0a4d5bb)

- ⬜ **16:02:51 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`08bff2e33299`](https://github.com/gmanldn/smoothcast/commit/08bff2e33299181dc64cfbb0fc8bc7f584a1cbe1)

- ⬜ **16:02:51 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`c7c138da85d1`](https://github.com/gmanldn/smoothcast/commit/c7c138da85d1d70583b0850ab40506617ea7c355)

- 🟦 **16:02:50 · Refactor** — refactor(paths): CONFIG\_DIR uses paths.APP\_DIR (Refs #701) (Refs #325) · [`7117382857fa`](https://github.com/gmanldn/smoothcast/commit/7117382857fa1b9749d5b89854ac6671c7ddbb9b)

- 🟩 **16:02:29 · Feature** — feat(portal): pure cross-node target picker rows, stable selection and validation (Refs #575) · [`804b5624979e`](https://github.com/gmanldn/smoothcast/commit/804b5624979e5fcd3aa46aa78730e758e6c9d877)

- ⬜ **16:00:41 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`bfe40c70605d`](https://github.com/gmanldn/smoothcast/commit/bfe40c70605dd285a45119adde4093d45246ace0)

- 🟥 **16:00:41 · Fix** — fix: clear develop mypy errors in queue\_crdt, server, cli\_control (Refs #698) · [`c66c73a05baa`](https://github.com/gmanldn/smoothcast/commit/c66c73a05baadd7c6f1d77a551d2ddcf39f6e979)

- ⬜ **16:00:41 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`a0baa2e4f8cc`](https://github.com/gmanldn/smoothcast/commit/a0baa2e4f8cc782366e83ae887e81a8d85c16a37)

- 🟥 **16:00:16 · Fix** — fix(upload): early-cast wording says 'not started yet' since a busy host now retries (Refs #686) · [`9ca5264348be`](https://github.com/gmanldn/smoothcast/commit/9ca5264348be16a63c091ba5c39f48f187a421bd)

- ⬜ **16:00:02 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`d6fc80b9b19d`](https://github.com/gmanldn/smoothcast/commit/d6fc80b9b19dc2d8513f9ed6889a2a0c3566c8df)

- ⬜ **16:00:01 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`f45f9e97f12a`](https://github.com/gmanldn/smoothcast/commit/f45f9e97f12af77daeac37a15dc925e31889cffe)

- 🟦 **16:00:00 · Refactor** — refactor(paths): demo, reliability and diagnostics use paths.APP\_DIR; allowlist shrinks to 6 (Refs #701) (Refs #325) · [`6f6712c727d5`](https://github.com/gmanldn/smoothcast/commit/6f6712c727d5662482b33769729f712f1c99941f)

- ⬜ **15:59:13 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`f0a92cd4c98a`](https://github.com/gmanldn/smoothcast/commit/f0a92cd4c98a5de8bc1d8e4217a1cb9727de1281)

- ⬜ **15:59:13 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`4aca0c67b597`](https://github.com/gmanldn/smoothcast/commit/4aca0c67b5971cb228e43020e07274274b708ece)

- 🟦 **15:59:12 · Refactor** — refactor(arch): hw\_encoder\_state no longer imports media\_tools at import time; layering debt now empty (Refs #690) · [`a9c0afe1d708`](https://github.com/gmanldn/smoothcast/commit/a9c0afe1d70805be4c2cc70d181b5ce329252302)

- 🟩 **15:58:56 · Feature** — feat(bench): pure transfer metrics: percentiles, fairness, invariant and baseline gates, bottleneck hint, redaction (Refs #573) · [`ec8a399aca85`](https://github.com/gmanldn/smoothcast/commit/ec8a399aca85af1322d145f26272a74a82cfcf7d)

- ⬜ **15:56:45 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`60eb91f36e26`](https://github.com/gmanldn/smoothcast/commit/60eb91f36e26836dc3a05dfb100208f60a08e0a0)

- ⬜ **15:56:44 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`4cd260f04ce6`](https://github.com/gmanldn/smoothcast/commit/4cd260f04ce6eefb0bd89a954bd2db0ac9d73256)

- 🟩 **15:56:36 · Feature** — feat(store): lossless idempotent legacy-directory migration helper (Refs #701) (Refs #325) · [`2c92c828e611`](https://github.com/gmanldn/smoothcast/commit/2c92c828e61169f23c3f2d931edea8b3d6f0b5c0)

- ⬜ **15:56:10 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`33ea1029fe43`](https://github.com/gmanldn/smoothcast/commit/33ea1029fe439e5518358477fa75562017b7faf8)

- ⬜ **15:56:09 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`3ecb41e8a575`](https://github.com/gmanldn/smoothcast/commit/3ecb41e8a57516c6273d02ae879ea6b828e333a3)

- 🟪 **15:56:09 · Tests** — test(arch): core-only-imports-core layering contract with 1 known violation (Refs #690) · [`f92f5165d0a8`](https://github.com/gmanldn/smoothcast/commit/f92f5165d0a893e317a94375f3d014730a66dbaa)

- 🟩 **15:55:30 · Feature** — feat(upload): growing-file reader with watermark, stall/cancel/stale handling and MP4 faststart gate (Refs #572) · [`5dbf67bceac5`](https://github.com/gmanldn/smoothcast/commit/5dbf67bceac57dedf6236e95aa5ec56257faff18)

- ⬜ **15:54:12 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`38fa14a53498`](https://github.com/gmanldn/smoothcast/commit/38fa14a5349808a7a5e46a156d0e2f8f5afe5e0e)

- ⬜ **15:54:12 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`cf97bd28531a`](https://github.com/gmanldn/smoothcast/commit/cf97bd28531a173f7e6d677711e358d18f448bdd)

- 🟪 **15:54:11 · Tests** — test(cast): every castctl control helper is accepted by the pychromecast backend; unknown verbs fail without raising (Refs #202) · [`b6ab068c737e`](https://github.com/gmanldn/smoothcast/commit/b6ab068c737e7072f5cba4dd120fca2ecbe85b98)

- ⬜ **15:53:54 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`0648af44c42c`](https://github.com/gmanldn/smoothcast/commit/0648af44c42c632f46aa06584510517401f2f557)

- ⬜ **15:53:53 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`f61d57db1718`](https://github.com/gmanldn/smoothcast/commit/f61d57db171842a903977eccefca76bd55179df1)

- 🟦 **15:53:49 · Refactor** — refactor(settings): library\_indexer flag in PortalSettings (Refs #693) (Refs #325) · [`39d27a1fa0b0`](https://github.com/gmanldn/smoothcast/commit/39d27a1fa0b07713d6eb5c7aaf42ad899fc68172)

- ⬜ **15:53:34 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`0e5323864942`](https://github.com/gmanldn/smoothcast/commit/0e532386494255dfdd602c5a3fbd36818a19c54a)

- ⬜ **15:53:33 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`a33b470dbf4c`](https://github.com/gmanldn/smoothcast/commit/a33b470dbf4cda0394b3af59f63177b19d1e4167)

- ⬜ **15:53:33 · Maintenance** — chore(agent): ship syncs pyproject py-modules when src modules are added or removed (Refs #690) · [`3c83207fabb1`](https://github.com/gmanldn/smoothcast/commit/3c83207fabb1019972262628215b17c084601f5a)

- ⬜ **15:52:58 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`d05eee752e78`](https://github.com/gmanldn/smoothcast/commit/d05eee752e78175cefa85afd2c284a19d5b512ff)

- ⬜ **15:52:58 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`eef2dc8ce907`](https://github.com/gmanldn/smoothcast/commit/eef2dc8ce907ddda7353a172448307753a2b6064)

- 🟦 **15:52:57 · Refactor** — refactor(settings): in-app updater channel comes from UpdateSettings (Refs #693) (Refs #325) · [`13ea63cb2a69`](https://github.com/gmanldn/smoothcast/commit/13ea63cb2a694a5ef26b701c5948a93ac42473f3)

- 🟩 **15:52:50 · Feature** — feat(portal): pure upload-panel view model: EMA speed, ETA range, honest stages, resume invitation, cast confirm (Refs #570) · [`5a3d702459de`](https://github.com/gmanldn/smoothcast/commit/5a3d702459de18346e3446ef3bbb6be95a763bea)

- 🟥 **15:52:15 · Fix** — fix(gui): make guest profile editing responsive and session safe (Refs #709) · [`91b5b180e7f9`](https://github.com/gmanldn/smoothcast/commit/91b5b180e7f982ebbb9078a16313284ddb1896c1)

- ⬜ **15:51:29 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`e576230df224`](https://github.com/gmanldn/smoothcast/commit/e576230df224752937b3c4042dd912929535fbb7)

- 🟦 **15:51:29 · Refactor** — refactor(settings): release-update checks read UpdateSettings, not raw cfg keys (Refs #693) (Refs #325) · [`f1cada395b84`](https://github.com/gmanldn/smoothcast/commit/f1cada395b84834b8dc057f0444d4fef823fc67f)

- ⬜ **15:51:29 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`b5c25e2ac56c`](https://github.com/gmanldn/smoothcast/commit/b5c25e2ac56ca6893cad766c0907fa876da4a92d)

- 🟥 **15:50:47 · Fix** — fix(web): fence mesh feed callbacks and stop hidden heartbeat polling (Refs #710) · [`c715d07c26fa`](https://github.com/gmanldn/smoothcast/commit/c715d07c26fa8cd45d1ac1163f965d10cfbaffb4)

- ⬜ **15:49:18 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`46abce9827cb`](https://github.com/gmanldn/smoothcast/commit/46abce9827cb6e6c6e12f051e83a335422404393)

- ⬜ **15:49:18 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`4d9bf74717c5`](https://github.com/gmanldn/smoothcast/commit/4d9bf74717c5b3bd9fd8d8508ce5b2e3ffd25d74)

- ⬜ **15:49:16 · Maintenance** — chore(packaging): sync pyproject py-modules with src (diagnose\_bundle, media\_source) (Refs #690) · [`92b3ce16ae52`](https://github.com/gmanldn/smoothcast/commit/92b3ce16ae52e8be01b0a92c69f7fc8308204b72)

- ⬜ **15:48:14 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`a354b3a2258d`](https://github.com/gmanldn/smoothcast/commit/a354b3a2258dbdefc73b5de810ea74e1679df8a2)

- ⬜ **15:48:14 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`1b11c5d85649`](https://github.com/gmanldn/smoothcast/commit/1b11c5d85649066d894c05ccb2bb8cf6581b7403)

- 🟩 **15:48:12 · Feature** — feat(security): MediaSource resolves uploads/library files by real path containment, rejecting .., symlinks and non-files (Refs #702) · [`c8f093262f00`](https://github.com/gmanldn/smoothcast/commit/c8f093262f00816ea3aabd8f54d155c9596cd830)

- ⬜ **15:47:22 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`4bf9e78213c0`](https://github.com/gmanldn/smoothcast/commit/4bf9e78213c08c0a8c237a0d324e18132115f0fb)

- 🟪 **15:47:22 · Tests** — test(arch): ratchet blocks new source-text tests; 106 existing frozen (Refs #699) · [`c0e9b819cc53`](https://github.com/gmanldn/smoothcast/commit/c0e9b819cc530da66668cf36486961710822e8a8)

- ⬜ **15:47:22 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`42470539674c`](https://github.com/gmanldn/smoothcast/commit/42470539674cedd3e7e300f01775b482452feb53)

- 🟩 **15:47:19 · Feature** — feat(transfer): pure browser-to-mesh transfer session contract, API doc and tests (Refs #569) · [`437b440a4d3a`](https://github.com/gmanldn/smoothcast/commit/437b440a4d3a15452e0969bc204b57537cde39ff)

- ⬜ **15:46:44 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`95637c71f289`](https://github.com/gmanldn/smoothcast/commit/95637c71f28917598a2037a611c936de91d57759)

- ⬜ **15:46:44 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`aba79c15204a`](https://github.com/gmanldn/smoothcast/commit/aba79c15204aa1ebd968ce4ea3d5a9383803248d)

- 🟦 **15:46:42 · Refactor** — refactor(settings): PortalSettings.house\_pin; portal PIN and guest-screens reads go through the typed settings (Refs #693) (Refs #325) · [`91741cf9104a`](https://github.com/gmanldn/smoothcast/commit/91741cf9104aa880ca8092ec2e2c6878cefbb1ec)

- ⬜ **15:46:21 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`84f31d591441`](https://github.com/gmanldn/smoothcast/commit/84f31d5914416bfd44c6893cb10e410125244dd9)

- 🟩 **15:46:21 · Feature** — feat(diagnose): redacted local diagnostics bundle writer (Refs #698) · [`46df44f5fe95`](https://github.com/gmanldn/smoothcast/commit/46df44f5fe9565495f52ab82959af3556431f664)

- ⬜ **15:46:21 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`b7684a460916`](https://github.com/gmanldn/smoothcast/commit/b7684a4609165510521eaf7562d38616573bc314)

- 🟥 **15:44:13 · Fix** — fix(upload): a busy host (409/503) re-arms early cast on the next chunk, up to 6 times, instead of permanently declining it, so large browser uploads start playing before they finish (Refs #686) · [`bc9dc93d8927`](https://github.com/gmanldn/smoothcast/commit/bc9dc93d89277b7b965bc325810273f788e64d1d)

- ⬜ **15:43:55 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`564905802c8c`](https://github.com/gmanldn/smoothcast/commit/564905802c8c9a61aecd2c2a0f3f1d8cfc3a5af7)

- ⬜ **15:43:55 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`8bd12ad7a690`](https://github.com/gmanldn/smoothcast/commit/8bd12ad7a690f2006f7168ad7611f7faa37c4846)

- 🟩 **15:43:43 · Feature** — feat(portal): web room chapter jump through the fenced seek envelope; parity row added (Refs #635) · [`ab1e5ec1ed43`](https://github.com/gmanldn/smoothcast/commit/ab1e5ec1ed43591d472de97747e86d86ea342a84)

- ⬜ **15:43:18 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`11ea3152ad34`](https://github.com/gmanldn/smoothcast/commit/11ea3152ad345d9ec3046c4952a90515fe296775)

- ⬜ **15:43:18 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`9d4c3e9c57a2`](https://github.com/gmanldn/smoothcast/commit/9d4c3e9c57a2b90200d5680af64b8c80dd046302)

- 🟨 **15:42:42 · Documentation** — docs: record Cast backend dependency pins and licences (Refs #202) · [`a9516374a3f1`](https://github.com/gmanldn/smoothcast/commit/a9516374a3f1fd1dbcd0a7010f2caaccf725af94)

- ⬜ **15:41:26 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`76f4878e1d9d`](https://github.com/gmanldn/smoothcast/commit/76f4878e1d9db68c666d7927efc37b885b464313)

- ⬜ **15:41:26 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`f0ba271f0a5a`](https://github.com/gmanldn/smoothcast/commit/f0ba271f0a5a42896d82ddfc2df01388fcd9d8a5)

- 🟪 **15:41:24 · Tests** — test(portal): upload recovery harness supplies the confirmed receiver required by the #572 retry fence, so the reconcile and fallback tests exercise the retry again (Refs #686) · [`86b2fe60c2fe`](https://github.com/gmanldn/smoothcast/commit/86b2fe60c2fec91793e1dbea8465f290effef442)

- ⬜ **15:40:22 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`5791e2f4f6b5`](https://github.com/gmanldn/smoothcast/commit/5791e2f4f6b53fb9124e8188f1c14fc84912b189)

- ⬜ **15:40:22 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`799cf39d3d8d`](https://github.com/gmanldn/smoothcast/commit/799cf39d3d8d06cf7b02b9a53a031bcf22b07327)

- 🟥 **15:40:20 · Fix** — fix(portal): a guest whose session or CSRF token is rejected on an action again gets 403 'Your session has ended. Reload the page and join the room again.' instead of 401 'Session expired'; reads keep 401. Restores the reply central authorization changed in 8a058ee0 (Refs #702) (Refs #686) · [`13e40ab359b2`](https://github.com/gmanldn/smoothcast/commit/13e40ab359b202304f9c9ce43985bf3294d97798)

- 🟪 **15:34:05 · Tests** — test(msi): verify installed licence and icon and repair licence (Refs #535) · [`cf4f12c40aaf`](https://github.com/gmanldn/smoothcast/commit/cf4f12c40aaf01b04aaaafa5532279b4f3847007)

- 🟪 **15:31:35 · CI** — ci(msi): build isolated fixtures and run native upgrade matrix (Refs #535) · [`0d262ead6fa9`](https://github.com/gmanldn/smoothcast/commit/0d262ead6fa96f981129e13833d0a8a566b64c76)

- 🟥 **15:19:19 · Fix** — fix(web): recover network diagrams after failed image loads (Refs #710) · [`d0dde6ba175d`](https://github.com/gmanldn/smoothcast/commit/d0dde6ba175d9329edcae882f98e344521ba9424)

- 🟥 **15:18:07 · Fix** — fix(gui): show the named room before joining and clarify profile controls (Refs #709) · [`f633ac2a7e18`](https://github.com/gmanldn/smoothcast/commit/f633ac2a7e1832e96eff0a21aa3611b2e765b84d)

- 🟩 **14:34:41 · Feature** — feat(win): fail-closed FFmpeg archive verifier/stager with PE x64 and capability checks (Refs #529) · [`e836471a988e`](https://github.com/gmanldn/smoothcast/commit/e836471a988eb8a2f901e9ffc9584edfa2c16be7)

- ⬜ **07:56:11 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`5b8e24020016`](https://github.com/gmanldn/smoothcast/commit/5b8e2402001652abac67f2192cc9df1059a296bf)

- ⬜ **07:56:11 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`0429fc5601bb`](https://github.com/gmanldn/smoothcast/commit/0429fc5601bbd7c0dc03ee91b2d43ef70986659f)

- 🟩 **07:56:06 · Feature** — feat(settings): AudioSettings and PlaybackSettings with safe coercion and clamping (Refs #693) · [`fdad33070ed4`](https://github.com/gmanldn/smoothcast/commit/fdad33070ed47d0bafdd0f4eec3e434904a9107d)

- 🟩 **07:55:18 · Feature** — feat(visual): pure tolerant screenshot diff, red diff image and fixed scenario matrix (Refs #455) · [`4fa5f27bdd3f`](https://github.com/gmanldn/smoothcast/commit/4fa5f27bdd3f703620e07174d6d7e6d569e5be59)

- ⬜ **07:54:53 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`a7d83051a336`](https://github.com/gmanldn/smoothcast/commit/a7d83051a33638e0c517968f905e35f848ae28af)

- ⬜ **07:54:53 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`63be9ca26245`](https://github.com/gmanldn/smoothcast/commit/63be9ca26245c5a2745ff1e84f839af6a0df42ab)

- 🟦 **07:54:48 · Refactor** — refactor(arch): update\_managed loads setup modules by path, no sys.path mutation; ratchet 3-&gt;2 (Refs #690) · [`e0669995d6f6`](https://github.com/gmanldn/smoothcast/commit/e0669995d6f68829b7fb1d349106061d6168c1be)

- 🟩 **07:54:18 · Feature** — feat(a11y): pure AT-SPI tree auditor, queue-row announcement and text-scale clip check (Refs #449) · [`1663cde80bf5`](https://github.com/gmanldn/smoothcast/commit/1663cde80bf5cc33eaefa54dfa3ab055507b92da)

- ⬜ **07:53:51 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`9c8cf43ba048`](https://github.com/gmanldn/smoothcast/commit/9c8cf43ba048cfdc19b3bcba335dcc62be975887)

- ⬜ **07:53:51 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`b04565e4c059`](https://github.com/gmanldn/smoothcast/commit/b04565e4c0599305570f6b4d7691c486efd490cb)

- 🟩 **07:53:46 · Feature** — feat(health): honest plain-text rows for the stream-health console (Refs #49) · [`d1a6bc137f62`](https://github.com/gmanldn/smoothcast/commit/d1a6bc137f62f97e4c80a90ebbd09134f8dcc14c)

- 🟩 **07:53:13 · Feature** — feat(queue): pure old/new to Gio-style splice diff for incremental queue model updates (Refs #462) · [`5980e4cc8a67`](https://github.com/gmanldn/smoothcast/commit/5980e4cc8a679b2e51874c97c25ebfce15a03644)

- ⬜ **07:52:44 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`3a2cdec87d0a`](https://github.com/gmanldn/smoothcast/commit/3a2cdec87d0a0674b1f948fbd59bc916046bfee8)

- ⬜ **07:52:44 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`d5461e19a780`](https://github.com/gmanldn/smoothcast/commit/d5461e19a780a838452d02e3099f2c11519ddf16)

- 🟩 **07:52:39 · Feature** — feat(doctor): read-only firewall check (ufw/firewalld) with honest WARN when unverifiable (Refs #211) · [`db2f79a1cd04`](https://github.com/gmanldn/smoothcast/commit/db2f79a1cd0411d8cadcb894ab7faecfcc3f3fc7)

- ⬜ **07:51:14 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`5aa73ce73f54`](https://github.com/gmanldn/smoothcast/commit/5aa73ce73f5460c604c459118c2fd6898437d1ca)

- ⬜ **07:51:14 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`1ac9a3237d3b`](https://github.com/gmanldn/smoothcast/commit/1ac9a3237d3bb378b0d0bdef7df3549e25b9d7f0)

- 🟩 **07:51:09 · Feature** — feat(arch): PortalService adapter so the portal runs under the Supervisor (Refs #692) · [`352138071991`](https://github.com/gmanldn/smoothcast/commit/3521380719914dfb8869e1e8df7d055f76985799)

- 🟩 **07:50:45 · Feature** — feat(history): shared house history store with retention, private-room and guest filters (Refs #433) · [`62ec96b58cb0`](https://github.com/gmanldn/smoothcast/commit/62ec96b58cb06b506cb6b04f3861deaf3eb2565b)

- ⬜ **07:50:06 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`ee36b0d96b76`](https://github.com/gmanldn/smoothcast/commit/ee36b0d96b76dccf04e12830dde3304c4229f510)

- ⬜ **07:50:06 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`78e0236ce729`](https://github.com/gmanldn/smoothcast/commit/78e0236ce729bda59461295ac6d1421a6b995efe)

- 🟪 **07:50:00 · Tests** — test(arch): ratchet freezes sys.path mutation in src and setup at 3 (Refs #690) · [`aba08883f4ca`](https://github.com/gmanldn/smoothcast/commit/aba08883f4caeec6661560799f023c7632fddecd)

- 🟩 **07:49:34 · Feature** — feat(presence): opt-in who's-home store with expiry and no history beyond last\_seen (Refs #432) · [`985c071d047a`](https://github.com/gmanldn/smoothcast/commit/985c071d047a3989912c6772d30506e60e2d73e5)

- ⬜ **07:48:51 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`2432503087e9`](https://github.com/gmanldn/smoothcast/commit/2432503087e981569e062e111b48f419ce6119ad)

- ⬜ **07:48:50 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`517a9af33f16`](https://github.com/gmanldn/smoothcast/commit/517a9af33f16d7ba0b0fc1929102fb6590f9fdc6)

- 🟦 **07:48:50 · Refactor** — refactor(runtime): portal update check runs on the bounded network pool (Refs #696) · [`506b7a049028`](https://github.com/gmanldn/smoothcast/commit/506b7a049028a71be0ce36572d439150928bd353)

- 🟩 **07:48:32 · Feature** — feat(rooms): pure house/solo namespaced queues with isolated revisions and deduped rejoin (Refs #429) · [`945e79b8741f`](https://github.com/gmanldn/smoothcast/commit/945e79b8741f66c5f6ea2109287bfc52ca2fd9b9)

- ⬜ **07:48:20 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`28f6f57cff33`](https://github.com/gmanldn/smoothcast/commit/28f6f57cff330499674edf18f4024d5105e35045)

- 🟥 **07:48:20 · Fix** — fix(cast): a receiver that keeps timing out is logged once per kind of failure, not once per timeout value, so a status poll can no longer write 68 near-identical lines an hour to errors.log (Refs #686) · [`908d0ab63a47`](https://github.com/gmanldn/smoothcast/commit/908d0ab63a4705342248cae760efe8b3f6a8b745)

- ⬜ **07:48:20 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`ab9d7c33a543`](https://github.com/gmanldn/smoothcast/commit/ab9d7c33a543a21eb00c9ea86b5352fd49f903db)

- ⬜ **07:47:47 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`00bd571e4596`](https://github.com/gmanldn/smoothcast/commit/00bd571e459631487b7c91df4fb50f9eef8e7873)

- ⬜ **07:47:47 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`db804506182e`](https://github.com/gmanldn/smoothcast/commit/db804506182e80f3118ca4a028f8ef56a5b6e2d7)

- 🟦 **07:47:42 · Refactor** — refactor(runtime): link setup runs on the bounded disk pool; raw-thread ratchet shrinks (Refs #696) · [`22dbe8f37892`](https://github.com/gmanldn/smoothcast/commit/22dbe8f37892fbdc4a54a332110a4ca5860e66a4)

- 🟩 **07:47:11 · Feature** — feat(energy): pure energy-aware node scoring and keep-active-stream rule (Refs #428) · [`85e452b3df7f`](https://github.com/gmanldn/smoothcast/commit/85e452b3df7f774ed8716b3f0398699cde0203e0)

- ⬜ **07:46:38 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`b705ba192b70`](https://github.com/gmanldn/smoothcast/commit/b705ba192b7079eabb3e350dec79564e83237a75)

- ⬜ **07:46:38 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`f52dd0b7fe25`](https://github.com/gmanldn/smoothcast/commit/f52dd0b7fe2541579e978505be908cef66b0b003)

- 🟦 **07:46:37 · Refactor** — refactor(runtime): update check runs on the bounded network pool with a 60s deadline; raw-thread ratchet shrinks (Refs #696) · [`5072309a7cd7`](https://github.com/gmanldn/smoothcast/commit/5072309a7cd7a004b3b0b2e34b229b8600acfd56)

- 🟩 **07:46:12 · Feature** — feat(wol): magic packet, opt-in node record, deduped wake flow with 60 s timeout (Refs #427) · [`eda399e185a9`](https://github.com/gmanldn/smoothcast/commit/eda399e185a90f93a446efb641771bd60a498d0b)

- ⬜ **07:45:15 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`9ce4286e5969`](https://github.com/gmanldn/smoothcast/commit/9ce4286e5969453cba3518adc5560a59ffa242d3)

- ⬜ **07:45:15 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`5d952fd66c77`](https://github.com/gmanldn/smoothcast/commit/5d952fd66c77534afccaaf697d88272bcc8350f3)

- 🟦 **07:45:09 · Refactor** — refactor(settings): portal preferred port reads through PortalSettings so a corrupt value cannot crash start-up (Refs #693) · [`42b48c1b7e8b`](https://github.com/gmanldn/smoothcast/commit/42b48c1b7e8b25c8edea39e36cc70c9a6eee6733)

- 🟩 **07:44:55 · Feature** — feat(drain): pure drain state machine and bounded sleep inhibitor (Refs #426) · [`468c01d8e159`](https://github.com/gmanldn/smoothcast/commit/468c01d8e1593fc9f02c0fab46de397f5596112b)

- ⬜ **07:44:22 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`91662b9102fd`](https://github.com/gmanldn/smoothcast/commit/91662b9102fd487f5915dc7f8352cc1111272fac)

- ⬜ **07:44:22 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`c442863d8e73`](https://github.com/gmanldn/smoothcast/commit/c442863d8e73a166463e2a7e93cd30622b3e5b06)

- 🟩 **07:44:17 · Feature** — feat(arch): HardwareEncoder port with VAAPI, NVENC and fake backends, ranked selection with visible reasons (Refs #703) · [`9ee923f2ace5`](https://github.com/gmanldn/smoothcast/commit/9ee923f2ace5fae6738dc9da5dc6b94db0b4ed9b)

- 🟩 **07:43:40 · Feature** — feat(prewarm): pure single-job warm registry with instant cancel, budget and take-over (Refs #423) · [`90a5a24f619e`](https://github.com/gmanldn/smoothcast/commit/90a5a24f619e5edd40be52533b97a2d414c60ac9)

- ⬜ **07:42:53 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`be431811e567`](https://github.com/gmanldn/smoothcast/commit/be431811e5678bb48deed83e9fbf5560081af7a0)

- 🟩 **07:42:53 · Feature** — feat(arch): per-attempt artifact folders, bounded retention and redacted bundle (Refs #698) · [`be459e78f831`](https://github.com/gmanldn/smoothcast/commit/be459e78f831fde2dfaa8e4aadfddfdac0bcc503)

- ⬜ **07:42:53 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`2e9062f56aba`](https://github.com/gmanldn/smoothcast/commit/2e9062f56aba06e1fc727f992087931b60fbb2b1)

- 🟩 **07:42:34 · Feature** — feat(queue): pure fractional-key sequence CRDT for a partition-tolerant Up Next (Refs #421) · [`d9bbdb14c1d5`](https://github.com/gmanldn/smoothcast/commit/d9bbdb14c1d578bd497b9ff318086b54445ab414)

- ⬜ **07:41:41 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`cad5aa251e6e`](https://github.com/gmanldn/smoothcast/commit/cad5aa251e6ef68b0237b75fe45c5d941ff58ef3)

- ⬜ **07:41:41 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`22f3ead50092`](https://github.com/gmanldn/smoothcast/commit/22f3ead50092381e24ed305bb366ad5cb1ad3cd9)

- 🟩 **07:41:36 · Feature** — feat(arch): pure plan\_encode with reasons, golden argv tests and lighter-plan degradation (Refs #697) · [`1671d0da4594`](https://github.com/gmanldn/smoothcast/commit/1671d0da459413c959f93780926d3a8e988a62f2)

- ⬜ **07:41:07 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`f270b476f9b2`](https://github.com/gmanldn/smoothcast/commit/f270b476f9b22bec31084ad6ac95d0b08976f37c)

- ⬜ **07:41:07 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`cbb6e7578e54`](https://github.com/gmanldn/smoothcast/commit/cbb6e7578e54c6a59b983c71fe079fc357118371)

- 🟥 **07:40:56 · Fix** — fix(persist): night mode, lyrics sync nudges and the room requests board save through store.Store, so a full or read-only disk no longer raises out of a GTK or portal handler and saves are fsynced and owner-only (Refs #686) · [`db46ca635fc2`](https://github.com/gmanldn/smoothcast/commit/db46ca635fc279dba4bb47e9c01045deb052fb51)

- 🟩 **07:40:34 · Feature** — feat(mesh): known\_nodes TOFU pinning, quarantine ids and MESH\_DESIGN trust tiers for auto-membership (Refs #418) · [`615a1946faf0`](https://github.com/gmanldn/smoothcast/commit/615a1946faf0ec597a814a5ed778b4c34249afd6)

- ⬜ **07:40:28 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`1547376a0baa`](https://github.com/gmanldn/smoothcast/commit/1547376a0baa97ade53449083c2cee00fd6fbf7b)

- ⬜ **07:40:28 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`113db534bc58`](https://github.com/gmanldn/smoothcast/commit/113db534bc5808ba67c656a6362ab5809103426d)

- 🟩 **07:40:23 · Feature** — feat(arch): bounded task runtime (scopes, deadlines, bounded shutdown) and raw-thread ratchet (Refs #696) · [`328dab94d036`](https://github.com/gmanldn/smoothcast/commit/328dab94d0367872f6d51bdc1b142fd75327659a)

- ⬜ **07:39:14 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`f64bba5dce73`](https://github.com/gmanldn/smoothcast/commit/f64bba5dce73f731842e33c0cbbe605b28c467b5)

- 🟩 **07:39:14 · Feature** — feat(arch): pure event-sourced room queue store with idempotency, revision fences and replay (Refs #695) · [`3049aa2bdd90`](https://github.com/gmanldn/smoothcast/commit/3049aa2bdd909bcf2d8f0ee5cc696fa96e757fa9)

- ⬜ **07:39:14 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`d7ffb71449cb`](https://github.com/gmanldn/smoothcast/commit/d7ffb71449cbebc40efd8090b9e6d86818086300)

- 🟩 **07:39:04 · Feature** — feat(search): pure play-by-key resolver with origin failover, idempotent revision-checked enqueue (Refs #414) · [`b906f65df160`](https://github.com/gmanldn/smoothcast/commit/b906f65df160596575b85ff37227acb923d2dd80)

- ⬜ **07:38:09 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`6cd76f36739c`](https://github.com/gmanldn/smoothcast/commit/6cd76f36739ceeca4ea5531e6e554edf79e612dc)

- ⬜ **07:38:09 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`e69d4d24158a`](https://github.com/gmanldn/smoothcast/commit/e69d4d24158a64e622aead907350dfad9d6abc1a)

- 🟩 **07:38:04 · Feature** — feat(arch): pure service supervisor with bounded stop, health and restart backoff (Refs #692) · [`f4f6efed9d0e`](https://github.com/gmanldn/smoothcast/commit/f4f6efed9d0e028824a084b1c54bc2d25f7757ca)

- 🟩 **07:37:51 · Feature** — feat(rooms): pure movie-night poll with instant-runoff, seeded ties and kids-aware suggestions (Refs #392) · [`089b787b3b45`](https://github.com/gmanldn/smoothcast/commit/089b787b3b45cebd85cff388d8231513621b8e69)

- ⬜ **07:37:04 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`66fdc4695a9a`](https://github.com/gmanldn/smoothcast/commit/66fdc4695a9a452fdede290ca8b73ada722f9ab3)

- ⬜ **07:37:04 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`f3b9b529c531`](https://github.com/gmanldn/smoothcast/commit/f3b9b529c531b3b186bf77cfb7ea8a7154feba0d)

- 🟪 **07:36:58 · Tests** — test(arch): MainWindow base-class ratchet at 17 (Refs #691) · [`18cd3bf830be`](https://github.com/gmanldn/smoothcast/commit/18cd3bf830bec2b9b6def34c76e2ba4c6a3cbc2c)

- 🟩 **07:36:10 · Feature** — feat(requests): pure request board with duplicate +1, guest expiry, fulfil notifications (Refs #391) · [`74bfc6d575da`](https://github.com/gmanldn/smoothcast/commit/74bfc6d575dae41ae77d0a5a1647a1f89e06d2cd)

- ⬜ **07:36:06 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`bd730391397d`](https://github.com/gmanldn/smoothcast/commit/bd730391397d0d4e4561e034c0b5595d9051490d)

- ⬜ **07:36:06 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`3f9742f9f598`](https://github.com/gmanldn/smoothcast/commit/3f9742f9f598435c12b33678a206a6c144b9e022)

- 🟥 **07:36:00 · Fix** — fix(ship): refuse to commit while new src/tests/scripts files are untracked and unnamed (Refs #700) · [`ca22093a3375`](https://github.com/gmanldn/smoothcast/commit/ca22093a3375e1530e009606680344a260c9d050)

- ⬜ **07:35:05 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`3160ac3dc39a`](https://github.com/gmanldn/smoothcast/commit/3160ac3dc39a4f0a0937a6b3e65e0b8316a70785)

- ⬜ **07:35:05 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`fc704d3ac5a4`](https://github.com/gmanldn/smoothcast/commit/fc704d3ac5a4915a3cfbea7fa114e177f32b5258)

- 🟪 **07:34:59 · Tests** — test(arch): core purity ratchet for 15 pure modules (Refs #690) · [`b5b503fedf15`](https://github.com/gmanldn/smoothcast/commit/b5b503fedf1566c70f0e227c324284e7be16ff8e)

- 🟩 **07:34:51 · Feature** — feat(audio): pure night-mode filter chain, ordering, restart plan and per-room levels (Refs #390) · [`d614f6ebab77`](https://github.com/gmanldn/smoothcast/commit/d614f6ebab7710cef7ff60fb93c6784627eaa954)

- ⬜ **07:34:17 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`b8f1432c083f`](https://github.com/gmanldn/smoothcast/commit/b8f1432c083f1ef6cc28cb6a41010078e8cd41e7)

- ⬜ **07:34:17 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`05289cb3be04`](https://github.com/gmanldn/smoothcast/commit/05289cb3be04ce50f4f27e4c0111d0891a7ec1d1)

- 🟥 **07:34:11 · Fix** — fix(arch): add src/settings.py that update\_facts imports; it was left untracked by the previous ship (Refs #693) · [`93f6b2d30611`](https://github.com/gmanldn/smoothcast/commit/93f6b2d30611fa0c9afab4551e47dac3058576c9)

- 🟩 **07:33:36 · Feature** — feat(a11y): pure per-resident accessibility prefs, track selection, add-my-captions and static HTML audit (Refs #389) · [`826ee2cf7b6f`](https://github.com/gmanldn/smoothcast/commit/826ee2cf7b6f443dc2a01077a5d51d3f6d3171d5)

- ⬜ **07:32:45 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`f923251f9eef`](https://github.com/gmanldn/smoothcast/commit/f923251f9eef6a022732ef889db619a6723ac086)

- 🟪 **07:32:45 · Tests** — test(arch): import-cycle ratchet ignores TYPE\_CHECKING imports; zero module-level cycles remain (Refs #690) · [`3e9ed8499a4a`](https://github.com/gmanldn/smoothcast/commit/3e9ed8499a4ad3a3b71a05a103a034e64f4dc597)

- ⬜ **07:32:45 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`a712d45f9978`](https://github.com/gmanldn/smoothcast/commit/a712d45f99783802e26c3975ee488c06a63ce333)

- ⬜ **07:32:21 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`60c595b7eaf9`](https://github.com/gmanldn/smoothcast/commit/60c595b7eaf9c19534be158f2db2042fde78822a)

- ⬜ **07:32:21 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`0898c21f6bb1`](https://github.com/gmanldn/smoothcast/commit/0898c21f6bb1ae839161914094dc8e7da528307c)

- 🟩 **07:32:20 · Feature** — feat(web): publish source chapters in the room status so the web room can show and jump to them (Refs #39) (Refs #325) · [`8275cbd73763`](https://github.com/gmanldn/smoothcast/commit/8275cbd737633bc1638a3688c38dba7f3259497f)

- 🟩 **07:31:06 · Feature** — feat(health): pure house health view-model and strict node.heartbeat validation (Refs #386) · [`510d918a31bd`](https://github.com/gmanldn/smoothcast/commit/510d918a31bd0fc0ee98def8a40f02bfe7c6e380)

- ⬜ **07:30:59 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`339a0abdcf43`](https://github.com/gmanldn/smoothcast/commit/339a0abdcf43bb9ea730d0e0fb93d7df2834304c)

- ⬜ **07:30:58 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`02f9929e5c95`](https://github.com/gmanldn/smoothcast/commit/02f9929e5c95743d92be6879695d0e8b22eaa525)

- 🟪 **07:30:52 · Tests** — test(arch): import-cycle ratchet; one known module-level cycle allowlisted (Refs #690) · [`468872c9785e`](https://github.com/gmanldn/smoothcast/commit/468872c9785e09813a8bcfb2db230ab5d10b527e)

- ⬜ **07:29:54 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`450acc00976f`](https://github.com/gmanldn/smoothcast/commit/450acc00976fb77f7caa4cc141f87f83ca78bfc3)

- ⬜ **07:29:53 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`7f3aeb9d1f92`](https://github.com/gmanldn/smoothcast/commit/7f3aeb9d1f92b0757201748e927e7f9b2a77567e)

- 🟩 **07:29:53 · Feature** — feat(persist): tell the user once at start-up when a damaged settings file was set aside (Refs #701) (Refs #325) · [`67bd4999dc3f`](https://github.com/gmanldn/smoothcast/commit/67bd4999dc3fc4743c6bf7564f21343318546b0b)

- ⬜ **07:29:28 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`edc9c5926e88`](https://github.com/gmanldn/smoothcast/commit/edc9c5926e88f31f59442428a91ee3d6e1776606)

- ⬜ **07:29:27 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`bd17d1909c60`](https://github.com/gmanldn/smoothcast/commit/bd17d1909c60241a1cae549ade66bd9dbd2eea3f)

- 🟪 **07:29:21 · Tests** — test: drop source-size assertion from audio-delay wiring test; behaviour is covered above (Refs #699) · [`0b32fe093bac`](https://github.com/gmanldn/smoothcast/commit/0b32fe093bac96b734e67e2e4040045a278076b0)

- 🟩 **07:28:34 · Feature** — feat(rooms): CEC wake wrapper with allow-list, 3 s timeout and once-only ignore logging (Refs #384) · [`fd999c6ee00b`](https://github.com/gmanldn/smoothcast/commit/fd999c6ee00be8ba6662fb34e5484bdc3f03b253)

- ⬜ **07:28:20 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`a079fc05688f`](https://github.com/gmanldn/smoothcast/commit/a079fc05688fd70c2d5d028861e4ddd88ea49477)

- 🟪 **07:28:20 · Tests** — test(arch): quarantine a11y inventory red with owner; name owner for design-token red (Refs #700) · [`54bb90508b68`](https://github.com/gmanldn/smoothcast/commit/54bb90508b6829f9dd36297c51bf67bea2c959e1)

- ⬜ **07:28:20 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`f4e6dc28c9f0`](https://github.com/gmanldn/smoothcast/commit/f4e6dc28c9f018b12cfff0fc46c749660f1ce1a2)

- ⬜ **07:27:54 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`8205924d5d0e`](https://github.com/gmanldn/smoothcast/commit/8205924d5d0e2cdedfc6a8f8591f9a5452ec4d2a)

- ⬜ **07:27:54 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`8a6e81f13ab4`](https://github.com/gmanldn/smoothcast/commit/8a6e81f13ab4a37823b9ccb0b9f340f2fa7d9d72)

- 🟦 **07:27:41 · Refactor** — refactor(paths): receiver memory locates its state through paths (Refs #701) (Refs #325) · [`809e2e41aded`](https://github.com/gmanldn/smoothcast/commit/809e2e41aded889beb1b5e609be35fe642a0352f)

- 🟩 **07:27:20 · Feature** — feat(integrations): pure Home Assistant MQTT discovery, state, command gate and backoff (Refs #383) · [`21fd12471472`](https://github.com/gmanldn/smoothcast/commit/21fd1247147242ba84f66a3972b99026ce3b46cc)

- ⬜ **07:26:36 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`3f711f42417b`](https://github.com/gmanldn/smoothcast/commit/3f711f42417b7578fa7097cdba33d4c85a632bce)

- ⬜ **07:26:36 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`7c212cfffb17`](https://github.com/gmanldn/smoothcast/commit/7c212cfffb17c4b3760e31e27f367a8b82df88fc)

- ⬜ **07:26:35 · Maintenance** — chore(arch): reviewed complexity baseline (doctor CLI #211, stream-health I/O #49, Store #701); off quarantine (Refs #700) · [`247cf071d9c5`](https://github.com/gmanldn/smoothcast/commit/247cf071d9c5935072b2f30c1d86d87f087d8677)

- ⬜ **07:26:26 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`2426f9e6b2fd`](https://github.com/gmanldn/smoothcast/commit/2426f9e6b2fd3f04698c941e516c2fd978689921)

- ⬜ **07:26:26 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`db1029327834`](https://github.com/gmanldn/smoothcast/commit/db10293278348d507b9da995826c907a01123ac3)

- 🟩 **07:26:13 · Feature** — feat(arch): probed DRM render-node helper for hardware encode, not yet used by the streamer (Refs #703) (Refs #325) · [`a1037dbb37a2`](https://github.com/gmanldn/smoothcast/commit/a1037dbb37a2506a900ee2fb81d5979700d3f02b)

- 🟩 **07:25:56 · Feature** — feat(portal): pure share-target manifest entry, /share guard, classifier and pending-share store (Refs #382) · [`1efdaa73b776`](https://github.com/gmanldn/smoothcast/commit/1efdaa73b776386b72201fe906e41a0aa35ed572)

- ⬜ **07:25:08 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`ea77b00a8d77`](https://github.com/gmanldn/smoothcast/commit/ea77b00a8d774693b1305ece77fbfbe2d1d26712)

- 🟩 **07:25:08 · Feature** — feat(persist): Store write failures carry a typed reason (disk full, permission denied, I/O) (Refs #701) (Refs #325) · [`e1d475c203b4`](https://github.com/gmanldn/smoothcast/commit/e1d475c203b48c3f3be47484c85e32c19c907ff5)

- ⬜ **07:25:08 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`382e3a05b452`](https://github.com/gmanldn/smoothcast/commit/382e3a05b45200743c7b91dea4eee55e69592952)

- 🟩 **07:24:52 · Feature** — feat(photos): pure EXIF orientation/GPS strip, slideshow plan and ephemeral store (Refs #381) · [`ddbb5a528ab2`](https://github.com/gmanldn/smoothcast/commit/ddbb5a528ab23ad8a7d816825b33df0965459e93)

- ⬜ **07:23:59 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`1607c6e6fbd5`](https://github.com/gmanldn/smoothcast/commit/1607c6e6fbd5b6e7c32600ab139f033270a54ff0)

- ⬜ **07:23:59 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`af46c18ff507`](https://github.com/gmanldn/smoothcast/commit/af46c18ff5070e19b089fb7f33cb240e68734c4a)

- 🟩 **07:23:48 · Feature** — feat(persist): Store quarantines a corrupt record and starts from defaults (Refs #701) (Refs #325) · [`b99f55d05c87`](https://github.com/gmanldn/smoothcast/commit/b99f55d05c8735cd71a0a22a9634771304f4613c)

- 🟩 **07:23:31 · Feature** — feat(music): pure podcast feed parser with XML hardening, subscriptions and conditional refresh (Refs #380) · [`678c835302c6`](https://github.com/gmanldn/smoothcast/commit/678c835302c652e3cc31495a535674c324644c90)

- ⬜ **07:22:43 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`53c4bceece6c`](https://github.com/gmanldn/smoothcast/commit/53c4bceece6c1c6dfbffd0de29a4567b08899126)

- ⬜ **07:22:43 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`0f1dfb2a5e15`](https://github.com/gmanldn/smoothcast/commit/0f1dfb2a5e1596d9abb15fbbf2cccc882cbb097e)

- 🟩 **07:22:36 · Feature** — feat(ship): warn on pre-existing red that is not in the quarantine list (Refs #700) · [`aa08a81bfdb6`](https://github.com/gmanldn/smoothcast/commit/aa08a81bfdb6289622e435311b3fc8669782e746)

- ⬜ **07:22:13 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`09c666cb7770`](https://github.com/gmanldn/smoothcast/commit/09c666cb7770b4baa34860d64d91ef13057cd529)

- ⬜ **07:22:12 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`1c38bc888d40`](https://github.com/gmanldn/smoothcast/commit/1c38bc888d403f5347d24f1a7d663752d3823f93)

- 🟦 **07:21:57 · Refactor** — refactor(paths): diagnostics, doctor, low-end probe, link qualification and portal room locate state through paths (Refs #701) (Refs #325) · [`d1320ef1a9e2`](https://github.com/gmanldn/smoothcast/commit/d1320ef1a9e282a31ad1913a10c652d619d95adb)

- 🟩 **07:21:43 · Feature** — feat(music): pure seeded house-radio scorer with repeat rules, kids filter and feedback (Refs #379) · [`b27ee88fd1f1`](https://github.com/gmanldn/smoothcast/commit/b27ee88fd1f16d42a7401947fd488f05caafd867)

- ⬜ **07:21:32 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`07cc958f1942`](https://github.com/gmanldn/smoothcast/commit/07cc958f19428211a38f75fd926d15b5a90377d4)

- ⬜ **07:21:31 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`1aafd5b4b798`](https://github.com/gmanldn/smoothcast/commit/1aafd5b4b79822300c3a586aa1bd066fa9999e99)

- 🟥 **07:21:24 · Fix** — fix(test): restore quarantine list dropped by a stale ship; openapi test removed as green (Refs #700) · [`eaed2fbc74f5`](https://github.com/gmanldn/smoothcast/commit/eaed2fbc74f5d3832669c7615a02133c9198da8e)

- 🟩 **07:20:18 · Feature** — feat(music): pure LRC and enhanced-LRC parser, line/word lookup and per-track offsets (Refs #378) · [`cd2650954224`](https://github.com/gmanldn/smoothcast/commit/cd265095422492d390844b841cb7675c9ab1e7a1)

- ⬜ **07:18:53 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`ce183aaea146`](https://github.com/gmanldn/smoothcast/commit/ce183aaea1468eacdbc7adc90b0b98cfef4d9ba2)

- 🟦 **07:18:53 · Refactor** — refactor(paths): error log, link sandbox and loudness cache use paths; ratchet shrinks (Refs #701) (Refs #325) · [`a068ca992fbc`](https://github.com/gmanldn/smoothcast/commit/a068ca992fbcbfdbd327c19a286494ee09885d9e)

- ⬜ **07:18:53 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`9d156ed9699f`](https://github.com/gmanldn/smoothcast/commit/9d156ed9699f18b421bb98f45fb0895ae1a450ce)

- 🟩 **07:18:36 · Feature** — feat(playback): pure skip intro/recap/credits markers from chapters and audio-hash matching (Refs #377) · [`94b9e560868a`](https://github.com/gmanldn/smoothcast/commit/94b9e560868add3d573fa0052ab30dc9a36bf749)

- ⬜ **07:18:05 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`98a9b7000897`](https://github.com/gmanldn/smoothcast/commit/98a9b700089769aba708d17c51817dec790007f1)

- 🟪 **07:18:05 · Tests** — test(arch): unit/contract/integration/e2e tiers auto-tagged, hermetic public-TCP guard; allow two new writers in ratchet (Refs #699) · [`6be0d1c4cf57`](https://github.com/gmanldn/smoothcast/commit/6be0d1c4cf577bc7aeaa2fe5e84caa78138a50f4)

- ⬜ **07:18:05 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`2606e0a7af83`](https://github.com/gmanldn/smoothcast/commit/2606e0a7af83f3541ccabaab6b007d8c8ef64917)

- 🟩 **07:17:14 · Feature** — feat(rooms): pure private-room visibility, 404 policy, temporary share and host stop log (Refs #376) · [`a8ee581ef73b`](https://github.com/gmanldn/smoothcast/commit/a8ee581ef73baa1734439610c9b76d476a927cb3)

- ⬜ **07:16:26 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`900c97e06992`](https://github.com/gmanldn/smoothcast/commit/900c97e069920a71b269d0cac6b875910b0a078e)

- ⬜ **07:16:25 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`cff00a6d6e22`](https://github.com/gmanldn/smoothcast/commit/cff00a6d6e229e6cb27b21b6b7947048b768275f)

- 🟪 **07:16:12 · Tests** — test(paths): ratchet so no new file hard-codes the legacy app directory (Refs #701) (Refs #325) · [`118aa416681d`](https://github.com/gmanldn/smoothcast/commit/118aa416681d28c95211293310f190f585c2c0b8)

- ⬜ **07:15:58 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`eaf470edc523`](https://github.com/gmanldn/smoothcast/commit/eaf470edc523e45a099dcf6c7902c21c3c292727)

- 🟥 **07:15:58 · Fix** — fix(cast,api): kept status connection is created under the mirror lock so concurrent reads no longer leak a second Chromecast socket; OpenAPI documents /api/mesh/profiles, /api/mesh/diagram.svg and GET/POST /api/update with capabilities (Refs #686) · [`731b2e8279c6`](https://github.com/gmanldn/smoothcast/commit/731b2e8279c61f73691665fef6325834ed126807)

- ⬜ **07:15:58 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`06594cc48374`](https://github.com/gmanldn/smoothcast/commit/06594cc483742dc100d4165b1b60a46ef6c20d19)

- 🟩 **07:15:46 · Feature** — feat(rooms): pure quiet-hours rules with midnight windows, strictest-wins cap, fade and 1h override (Refs #375) · [`0d20c8cdf539`](https://github.com/gmanldn/smoothcast/commit/0d20c8cdf539e0e87083e9884265ed90db00bb85)

- ⬜ **07:15:14 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`fccd3cdd72b9`](https://github.com/gmanldn/smoothcast/commit/fccd3cdd72b9d674d0a86590d955893ff1f18de0)

- ⬜ **07:15:14 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`08941575a769`](https://github.com/gmanldn/smoothcast/commit/08941575a7697a57617f8e93864bce1a1e2ab962)

- 🟦 **07:15:01 · Refactor** — refactor(paths): five duplicated config.json locators use paths.config\_dir (Refs #701) (Refs #325) · [`4bbd0824b7f3`](https://github.com/gmanldn/smoothcast/commit/4bbd0824b7f383a23419def1a09d659140e53ec3)

- 🟩 **07:14:06 · Feature** — feat(guests): pure scoped, expiring guest passes with hashed tokens and permission table (Refs #374) · [`6bc7efc3ef5d`](https://github.com/gmanldn/smoothcast/commit/6bc7efc3ef5de13d66bdee72cc01bbea36b223e6)

- 🟥 **07:13:40 · Fix** — fix(test): quarantine hook no longer shadows the platform-gap hook (Refs #700) · [`473ad5e018c8`](https://github.com/gmanldn/smoothcast/commit/473ad5e018c811126102bfb22eb2cd43cf44f2bf)

- ⬜ **07:13:40 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`3597ce590828`](https://github.com/gmanldn/smoothcast/commit/3597ce5908284327141aa4b869ffdd537bddab8f)

- ⬜ **07:13:18 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`ff9b0b8262cc`](https://github.com/gmanldn/smoothcast/commit/ff9b0b8262cc518233514635bbe3aa01cd433cfe)

- 🟦 **07:13:18 · Refactor** — refactor(persist): room policy saved through the atomic owner-only Store (Refs #701) (Refs #325) · [`702c05d4e9fb`](https://github.com/gmanldn/smoothcast/commit/702c05d4e9fbbb10aa8fd6e37a947ddb4797800f)

- ⬜ **07:13:18 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`1c1bb16fcafb`](https://github.com/gmanldn/smoothcast/commit/1c1bb16fcafb9fa5760e206ba9d8cb925ddd6af2)

- 🟪 **07:13:08 · Tests** — test(arch): dated quarantine list for known-red tests; expired entries stop being excused (Refs #700) · [`46b17c730937`](https://github.com/gmanldn/smoothcast/commit/46b17c730937fd4f761b436845cf8eb53333186c)

- ⬜ **07:13:08 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`ce6cba966368`](https://github.com/gmanldn/smoothcast/commit/ce6cba96636869efe346124357ec7ab4b38cfc73)

- 🟩 **07:12:47 · Feature** — feat(sync): pure watch-together session clock, command fencing, RTT clock and drift correction (Refs #373) · [`7d1fbf0778b0`](https://github.com/gmanldn/smoothcast/commit/7d1fbf0778b0086e580fd9dbeb763873da6240d2)

- ⬜ **07:11:47 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`74082d951b4f`](https://github.com/gmanldn/smoothcast/commit/74082d951b4fda329e3da9b18d64bdfbf02ace90)

- ⬜ **07:11:47 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`163c1618c6fd`](https://github.com/gmanldn/smoothcast/commit/163c1618c6fdfd585f4298cf8d5436470c969fcb)

- 🟦 **07:11:35 · Refactor** — refactor(persist): node trust and resident profiles saved through the atomic owner-only Store (Refs #701) (Refs #325) · [`d97c72744e87`](https://github.com/gmanldn/smoothcast/commit/d97c72744e877733f0d33dd0712988735bdcd43d)

- 🟩 **07:10:20 · Feature** — feat(rooms): pure follow-me handoff state machine, stop source only after target confirmed (Refs #372) · [`adc7dcb319b0`](https://github.com/gmanldn/smoothcast/commit/adc7dcb319b00e385822a8bea5d7394fce2c2da9)

- 🟩 **07:09:27 · Feature** — feat(arch): typed Settings groups (update, portal); update\_facts reads through them (Refs #693) · [`eb35cff3297c`](https://github.com/gmanldn/smoothcast/commit/eb35cff3297c46be59625a51e266c53dea510179)

- ⬜ **07:09:27 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`0f7f106d982a`](https://github.com/gmanldn/smoothcast/commit/0f7f106d982a0dc7781c5fa1fca4625b8ab5eeb1)

- 🟩 **07:09:04 · Feature** — feat(rooms): pure speaker preset save/prune/recall planning with ceilings and guest gate (Refs #371) · [`01041af8d15c`](https://github.com/gmanldn/smoothcast/commit/01041af8d15c94dc752c69c08f08418a78ac4eff)

- ⬜ **07:08:35 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`c085e95f033d`](https://github.com/gmanldn/smoothcast/commit/c085e95f033d1b8d53cd1ea5c885007c0508e46f)

- 🟥 **07:08:35 · Fix** — fix(stream): HLS server serves legacy segment-NNNNN.ts again; the stream-health suffix regex shadowed the module allow-list \_SEGMENT, so every tokenless segment request returned 404 since 7c712970 (Refs #686) · [`b251fe76e8a1`](https://github.com/gmanldn/smoothcast/commit/b251fe76e8a1e9e309fe6869dd4d15b1e4da9f88)

- ⬜ **07:08:35 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`f9baef748ee2`](https://github.com/gmanldn/smoothcast/commit/f9baef748ee2957368819b0e1b59faaabd20e6fc)

- 🟩 **07:08:01 · Feature** — feat(rooms): pure named-room store with newest-wins merge, tombstones and picker view (Refs #370) · [`b274e7743f01`](https://github.com/gmanldn/smoothcast/commit/b274e7743f016f83b26a6bb2a584d14ab2a7ddf3)

- ⬜ **07:07:40 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`f927cdcc8f14`](https://github.com/gmanldn/smoothcast/commit/f927cdcc8f14f9bea466376d37c8a854b41eb48f)

- ⬜ **07:07:40 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`bc7ba5ef793c`](https://github.com/gmanldn/smoothcast/commit/bc7ba5ef793c26277d4bb570f06bc6ed6b1706bf)

- 🟩 **07:07:25 · Feature** — feat(diagnostics): Receiver (measured) row from the stream-health aggregate: decoder state and encoder recoveries, unknown when unobserved (Refs #49) (Refs #325) · [`6c44f3bf52e7`](https://github.com/gmanldn/smoothcast/commit/6c44f3bf52e785be3acea0e28b58b17ce469ffe7)

- 🟩 **07:06:58 · Feature** — feat(offline): pure download admission, tidy rules, eviction reconcile and signed tokens (Refs #369) · [`9e1a204765d3`](https://github.com/gmanldn/smoothcast/commit/9e1a204765d3845a44708c15f85788370758d0ff)

- ⬜ **07:06:43 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`f67989852675`](https://github.com/gmanldn/smoothcast/commit/f6798985267528ff21bbcfe2c1742f01d7c27f75)

- ⬜ **07:06:43 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`76e0c6684643`](https://github.com/gmanldn/smoothcast/commit/76e0c6684643c752aef571308b41132e189f52a6)

- 🟥 **07:06:33 · Fix** — fix(errors): castctl logs status-refresh and disconnect failures instead of swallowing (Refs #694) · [`2907d0bba615`](https://github.com/gmanldn/smoothcast/commit/2907d0bba6158641b92d297ac193f0ee2262d952)

- 🟩 **07:06:02 · Feature** — feat(library): pure series parser, show grouping, next-episode and autoplay rules (Refs #368) · [`df7ba1df9aa7`](https://github.com/gmanldn/smoothcast/commit/df7ba1df9aa7a2861e14bbfb96b2cab65539d6bc)

- 🟩 **07:04:57 · Feature** — feat(library): pure merged house catalogue with best-copy routing and offline reasons (Refs #367) · [`67e16cdbb725`](https://github.com/gmanldn/smoothcast/commit/67e16cdbb72514d0fcab3d2a6bf6c669f6b0e648)

- 🟩 **07:03:03 · Feature** — feat(residents): per-person resume store with order-independent cross-node merge (Refs #365) · [`a4d9f77e08bd`](https://github.com/gmanldn/smoothcast/commit/a4d9f77e08bdcc47599cc6410a483acc700ff542)

- ⬜ **07:02:23 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`74b9ca1f110d`](https://github.com/gmanldn/smoothcast/commit/74b9ca1f110d6e8269ce9cdc37edec4c1e22adb4)

- 🟪 **07:02:23 · Tests** — test(arch): ratchet against new raw os.replace writers; allowlist only shrinks (Refs #701) · [`dcd0d324a691`](https://github.com/gmanldn/smoothcast/commit/dcd0d324a691904c94f0e7f0b907863a8ce5c84a)

- ⬜ **07:02:23 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`37e724e1522c`](https://github.com/gmanldn/smoothcast/commit/37e724e1522c5ba5c94ca1eee7a70d63d89b5b86)

- 🟩 **07:02:10 · Feature** — feat(kids): pure rating, bedtime (midnight-safe) and budget limits (Refs #364) · [`541a1787a8e5`](https://github.com/gmanldn/smoothcast/commit/541a1787a8e596090a032e7f4c8d9fabe857c09a)

- ⬜ **07:01:16 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`6b15ed0a46cc`](https://github.com/gmanldn/smoothcast/commit/6b15ed0a46cc2d30fc87923f4beee5d66e84c4b6)

- 🟦 **07:01:16 · Refactor** — refactor(arch): link qualification cache persists through the atomic Store (Refs #701) · [`6dbfbb68db77`](https://github.com/gmanldn/smoothcast/commit/6dbfbb68db778f4fe3526cd875641c09c2357fd9)

- ⬜ **07:01:16 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`83f4780b3107`](https://github.com/gmanldn/smoothcast/commit/83f4780b3107441b4d7a7c25c7dbf16c5e5715ac)

- 🟩 **07:01:09 · Feature** — feat(residents): atomic versioned resident store with scrypt PINs and lockout (Refs #363) · [`aa9c97899908`](https://github.com/gmanldn/smoothcast/commit/aa9c978999085266256b6df000eb7f8b87e0fa86)

- 🟩 **07:00:05 · Feature** — feat(mesh): pure receiver-side copy state with consent, quota, resume and digest verification (Refs #357) · [`fe6e0fc208a4`](https://github.com/gmanldn/smoothcast/commit/fe6e0fc208a42ea5cfd2c8f2cd411bd83297d26c)

- 🟩 **06:58:54 · Feature** — feat(mesh): pure node playback-target readiness and session fencing (Refs #356) · [`939d04e3d239`](https://github.com/gmanldn/smoothcast/commit/939d04e3d239729f877dfe3c5b76aa3509c41775)

- ⬜ **06:58:19 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`21a1755c2d36`](https://github.com/gmanldn/smoothcast/commit/21a1755c2d36e40b741a69da8c5cae6232a7a5ec)

- ⬜ **06:58:19 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`7808f217dab1`](https://github.com/gmanldn/smoothcast/commit/7808f217dab1f9f9177b0ed8ed5dc6f2e0fe479b)

- 🟦 **06:58:18 · Refactor** — refactor(arch): shutdown ledger persists through the atomic Store (Refs #701) · [`cc5923b41949`](https://github.com/gmanldn/smoothcast/commit/cc5923b4194953313912773b8f5998838117460b)

- 🟩 **06:57:25 · Feature** — feat(mesh): pure per-peer expiring media ids for explicitly shared items (Refs #355) · [`8a5129fc6811`](https://github.com/gmanldn/smoothcast/commit/8a5129fc68112d4c952ed7a9ee6a327cc53713d8)

- ⬜ **06:56:47 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`636b51bd0da2`](https://github.com/gmanldn/smoothcast/commit/636b51bd0da2f194c34894480d2ba1c74377f79b)

- ⬜ **06:56:47 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`65188eac0ec1`](https://github.com/gmanldn/smoothcast/commit/65188eac0ec1a342af62708710a2257963ab377a)

- 🟥 **06:55:37 · Fix** — fix(errors): add portal.missing\_capability to catalogue + portal category (Refs #207) · [`91e6ba68680a`](https://github.com/gmanldn/smoothcast/commit/91e6ba68680a822af5d477ea0f44a19941ddb52a)

- 🟩 **06:55:27 · Feature** — feat(mesh): pure node pairing with SAS confirmation, scoped revocable trust and replay protection (Refs #358) · [`de6b2f97d28a`](https://github.com/gmanldn/smoothcast/commit/de6b2f97d28ab67547ec1874ff493a7fdd63b12e)

- ⬜ **06:54:37 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`dbc0511b82e9`](https://github.com/gmanldn/smoothcast/commit/dbc0511b82e970613bf2c8382e71c0ea7e2c4010)

- ⬜ **06:54:37 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`2cdc341e0c79`](https://github.com/gmanldn/smoothcast/commit/2cdc341e0c79082a1a444180ec65c82dd31bc1d8)

- 🟦 **06:54:26 · Refactor** — refactor(arch): hw encoder failure record persists through the atomic Store (Refs #701) · [`edda32045082`](https://github.com/gmanldn/smoothcast/commit/edda320450829eacb1efd58c008124c3f1df5111)

- 🟩 **06:53:20 · Feature** — feat(setup): pure read-only bootstrap preflight planner for virgin machines (Refs #350) · [`7bd6bade120c`](https://github.com/gmanldn/smoothcast/commit/7bd6bade120c736bbf66c5329e56b7b30758d1fa)

- ⬜ **06:51:49 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`ba748bb2ddbc`](https://github.com/gmanldn/smoothcast/commit/ba748bb2ddbc37a8d669f24d9090686bf53934bf)

- ⬜ **06:51:48 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`448889e3e6ed`](https://github.com/gmanldn/smoothcast/commit/448889e3e6ed2d10d198950d76aa1400a4464dae)

- 🟩 **06:51:42 · Feature** — feat(arch): paths.py and atomic schema-versioned Store, first slice of one persistence layer (Refs #701) · [`2bd8f693529f`](https://github.com/gmanldn/smoothcast/commit/2bd8f693529f70d22381e1992496c1e9f68da7af)

- 🟩 **06:51:10 · Feature** — feat(portal): pure fail-closed policy checks for opt-in LAN HTTPS (Refs #340) · [`5726c6881011`](https://github.com/gmanldn/smoothcast/commit/5726c68810119cf67dd644e3f4a13869834f4a78)

- ⬜ **06:49:50 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`860aa256201f`](https://github.com/gmanldn/smoothcast/commit/860aa256201fee65c506f61450e6523832da72e6)

- ⬜ **06:49:49 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`85476a7bc5b1`](https://github.com/gmanldn/smoothcast/commit/85476a7bc5b192e83fc7bb344987a287d4557b62)

- 🟩 **06:49:49 · Feature** — feat(doctor): network route and discovery-multicast checks (Refs #211) · [`4b3b55095952`](https://github.com/gmanldn/smoothcast/commit/4b3b5509595286b3f0323d7fb898a16650d969f7)

- 🟩 **06:49:35 · Feature** — feat(web): pure PWA manifest, allow-list service worker and install-offer policy (Refs #341) · [`e5b25eade99f`](https://github.com/gmanldn/smoothcast/commit/e5b25eade99f702e5e948bf94e20a53f34bd1425)

- 🟩 **06:48:14 · Feature** — feat(library): pure shared music catalogue with opaque ids, share/revoke and capped search (Refs #349) · [`3a5dc66a8b59`](https://github.com/gmanldn/smoothcast/commit/3a5dc66a8b5977c1cc6ad63de94f4934d0825a3e)

- 🟩 **06:46:44 · Feature** — feat(audio): pure crossfade transition planner with equal-power gains and fallback reasons (Refs #348) · [`c874d55869ba`](https://github.com/gmanldn/smoothcast/commit/c874d55869ba065c0a10552390b41a11d383693c)

- ⬜ **06:46:21 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`c79c05e84030`](https://github.com/gmanldn/smoothcast/commit/c79c05e84030e1914a424de62bb4ab560cae5d0b)

- ⬜ **06:46:21 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`78d061b1d6a3`](https://github.com/gmanldn/smoothcast/commit/78d061b1d6a33b767ff984ae0715485433058991)

- 🟩 **06:46:05 · Feature** — feat(doctor): smoothcast doctor \[--json\] \[--receiver HOST\] CLI over the check engine (Refs #211) · [`cd17d48e48f0`](https://github.com/gmanldn/smoothcast/commit/cd17d48e48f0fe8bada98d297d2fc22a8716224a)

- ⬜ **06:45:37 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`5b05e4c8ec05`](https://github.com/gmanldn/smoothcast/commit/5b05e4c8ec05b422e75784e67e093f1bc162dc7f)

- ⬜ **06:45:37 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`1606f3c70bd8`](https://github.com/gmanldn/smoothcast/commit/1606f3c70bd80c334c5f59dcbe88dd30729ca31e)

- 🟥 **06:45:36 · Fix** — fix(portal): dispatcher-side capability enforcement for ROUTE\_CAPABILITIES (Refs #702) · [`8a058ee07293`](https://github.com/gmanldn/smoothcast/commit/8a058ee0729391102ffa5cdb919f91f50b123ab5)

- 🟩 **06:44:46 · Feature** — feat(audio): pure Bass/Mid/Treble tone knobs with headroom limiter and revisioned room state (Refs #346) · [`49f1995c619f`](https://github.com/gmanldn/smoothcast/commit/49f1995c619fe65743b7e83637321173b8bc4607)

- ⬜ **06:43:45 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`e3cb8c1d6d9e`](https://github.com/gmanldn/smoothcast/commit/e3cb8c1d6d9e7e2f30e2344e6f73fa2274fe356e)

- ⬜ **06:43:45 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`ba5478e77d86`](https://github.com/gmanldn/smoothcast/commit/ba5478e77d86a8c93548a5023f14b7bb766868d9)

- 🟩 **06:43:39 · Feature** — feat(stream): publish measured stream-health from the HLS server and attach it to the room status as stream\_health (Refs #49) · [`3bdacaf4592b`](https://github.com/gmanldn/smoothcast/commit/3bdacaf4592b6c3a320593c3abb4d65d4b605d92)

- 🟩 **06:41:45 · Feature** — feat(remote): pure playback phase projection and bounded recovery notifier (Refs #338) · [`a8ca1da8162f`](https://github.com/gmanldn/smoothcast/commit/a8ca1da8162f5d791f261b7ec6e219cca5ca4e4e)

- ⬜ **06:40:42 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`2efacec86a33`](https://github.com/gmanldn/smoothcast/commit/2efacec86a3317f68220f8b8c81885141418cf82)

- ⬜ **06:40:42 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`ef9352eabdfe`](https://github.com/gmanldn/smoothcast/commit/ef9352eabdfe670cece2be7469f002c468e65d3e)

- 🟩 **06:40:26 · Feature** — feat(stream): server counts served and failed HLS segments into the measured stream-health aggregate (Refs #49) · [`7c712970d1bf`](https://github.com/gmanldn/smoothcast/commit/7c712970d1bfed23360419b6635fb4bb49075681)

- 🟩 **06:39:15 · Feature** — feat(remote): single capability view driving every control, shared with server-side gate (Refs #337) · [`42321da6bbb9`](https://github.com/gmanldn/smoothcast/commit/42321da6bbb9a1f85455e7da5eb023ee105ccd7b)

- ⬜ **06:37:46 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`e25df5de42eb`](https://github.com/gmanldn/smoothcast/commit/e25df5de42eb99b41f700528a737afd6946c4d05)

- ⬜ **06:37:46 · Maintenance** — chore(ci): rebaseline complexity after reviewed feature growth (api\_spec OpenAPI routes, mesh\_ui row reconciliation #707, portal mesh panel, lifecycle mixin split #706, ffmpeg\_compat timeout) so the ratchet flags new growth again instead of every ship reporting a pre-existing failure (Refs #706) · [`a3a74cc1d4c0`](https://github.com/gmanldn/smoothcast/commit/a3a74cc1d4c0284dd363c2c4584ca47e993921b0)

- ⬜ **06:37:46 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`15bb5b5ad4d5`](https://github.com/gmanldn/smoothcast/commit/15bb5b5ad4d5eb793132e3fe782b36d77625c70f)

- 🟩 **06:37:24 · Feature** — feat(remote): pure role-scoped track descriptors and generation-bound selection (Refs #335) · [`82aae3358b67`](https://github.com/gmanldn/smoothcast/commit/82aae3358b67cfaf42fb49c3dd40e330ae85ba52)

- 🟩 **06:35:49 · Feature** — feat(queue): pure guest URL validator with SSRF/rebinding revalidation (Refs #334) · [`c54193c49f70`](https://github.com/gmanldn/smoothcast/commit/c54193c49f70d06f59500381c65d6c7fd41aad98)

- ⬜ **06:33:52 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`ef3fc30e5805`](https://github.com/gmanldn/smoothcast/commit/ef3fc30e58050b9b5172a34b1bfde4a6ccf48dff)

- 🟥 **06:33:52 · Fix** — fix(errors): ffmpeg\_compat no longer silently swallows an unreadable binary stat (Refs #694) · [`e29b56a56ca0`](https://github.com/gmanldn/smoothcast/commit/e29b56a56ca01456e4abfddc327d65f4dced8588)

- ⬜ **06:33:52 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`8c06b1dfc152`](https://github.com/gmanldn/smoothcast/commit/8c06b1dfc152db4b67304372b1685d884b75b9cc)

- 🟩 **06:33:23 · Feature** — feat(portal): pure seek/skip control lease with scope binding and host takeover (Refs #331) · [`e305b400754a`](https://github.com/gmanldn/smoothcast/commit/e305b400754aab96f7def6b85967c909bc7f3c82)

- 🟩 **06:30:11 · Feature** — feat(volume): pure per-receiver guest ceiling, step clamp and rate limiter (Refs #330) · [`05157474dcf7`](https://github.com/gmanldn/smoothcast/commit/05157474dcf78aec2c47601e0cb73f5b64e28972)

- ⬜ **06:29:42 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`412d9ae974a9`](https://github.com/gmanldn/smoothcast/commit/412d9ae974a99c025d1e45acfcf91502fe500277)

- ⬜ **06:29:42 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`4a9618133b3f`](https://github.com/gmanldn/smoothcast/commit/4a9618133b3f8a7b568aa846434e03988d97d3c3)

- 🟨 **06:29:21 · Documentation** — docs(setup): document sc.py --fresh and stale-instance reclaim (Refs #325) · [`4ac39ee0321d`](https://github.com/gmanldn/smoothcast/commit/4ac39ee0321d83f50554eeb617a98ffadb5953aa)

- 🟩 **06:27:59 · Feature** — feat(privacy): pure role-aware snapshot redaction with canary leak check (Refs #329) · [`7a87a1651588`](https://github.com/gmanldn/smoothcast/commit/7a87a16515881e407ace8961e26785128eea43b1)

- ⬜ **06:27:32 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`8098bbfc7177`](https://github.com/gmanldn/smoothcast/commit/8098bbfc7177c04aacf01871a0ecea7935c3e21b)

- ⬜ **06:27:31 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`51b36131b562`](https://github.com/gmanldn/smoothcast/commit/51b36131b562e1fed5968fe9e941cea215cf33e5)

- 🟩 **06:27:10 · Feature** — feat(ui): one front-page section model (now playing, devices, up next, people; details disclosed) with a web/GTK parity test (Refs #709) (Refs #325) · [`b947706f31a7`](https://github.com/gmanldn/smoothcast/commit/b947706f31a75e65d1ca3f8d5dd75b1e18ce5049)

- ⬜ **06:26:17 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`3b9112a16872`](https://github.com/gmanldn/smoothcast/commit/3b9112a168728fe30693863e00ba02c8c83cb369)

- ⬜ **06:26:16 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`c4b45095ac1f`](https://github.com/gmanldn/smoothcast/commit/c4b45095ac1f09184cd86469a5f447dfce30348b)

- 🟩 **06:26:15 · Feature** — feat(ui): shared corner-radius token scale; GTK stylesheet snapped to it and a parity test against the web page (Refs #708) (Refs #325) · [`ccbfab324b41`](https://github.com/gmanldn/smoothcast/commit/ccbfab324b4135044d4793a38c070bb86a3e9fd8)

- 🟩 **06:25:30 · Feature** — feat(queue): pure bounded undo log for add/remove/move with revision check (Refs #328) · [`7a54815fd83c`](https://github.com/gmanldn/smoothcast/commit/7a54815fd83c13dc4ae05d5f3023469a2b9d795b)

- 🟩 **06:23:16 · Feature** — feat(brand): apply SmoothCast Glacier and Ink web palette (Refs #708) · [`ac510aa701d2`](https://github.com/gmanldn/smoothcast/commit/ac510aa701d269d21296a0ddeae42be6550971fb)

- ⬜ **06:22:43 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`0f6e51d9e9cd`](https://github.com/gmanldn/smoothcast/commit/0f6e51d9e9cd47dfabf74fa7b34cfd25c093ce3c)

- ⬜ **06:22:43 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] · [`03e4e93751c2`](https://github.com/gmanldn/smoothcast/commit/03e4e93751c24b3c579b33a184ddfc40737e1506)

- 🟥 **06:22:42 · Fix** — fix(portal): finished portal uploads unused for two weeks are reclaimed at start-up; the private upload folder no longer grows without bound (13 GB seen) (Refs #686) · [`d81dc8c74635`](https://github.com/gmanldn/smoothcast/commit/d81dc8c74635545038d46e38d4f3bc9e9aeeff06)

- 🟩 **06:22:24 · Feature** — feat(room): pure participant panel rows and atomic room policy store (Refs #322) · [`017336378188`](https://github.com/gmanldn/smoothcast/commit/017336378188bae509c7338cad81d1d97d8319ed)

- 🟩 **06:19:32 · Feature** — feat(portal): pure command receipt tracker (accepted/confirmed/failed/uncertain) scoped to generation (Refs #320) · [`63079f2b68c5`](https://github.com/gmanldn/smoothcast/commit/63079f2b68c5b4ce973ac7004fe42a5326617477)

- 🟩 **06:17:02 · Feature** — feat(remote): pure phone-remote link state model with discard-not-replay and capped jittered backoff (Refs #317) · [`08e665a51a56`](https://github.com/gmanldn/smoothcast/commit/08e665a51a56eef13227dcac9e25833d5a3c24ef)

- 🟩 **06:15:22 · Feature** — feat(queue): pure one-vote-per-person ordering that never moves the playing or pinned items (Refs #326) · [`f71443eb92a2`](https://github.com/gmanldn/smoothcast/commit/f71443eb92a2af58f207dff095b92acd7924e087)

- 🟩 **06:12:58 · Feature** — feat(i18n): placeholder-safe pseudo-locale and RTL wrappers for layout smoke tests (Refs #219) · [`abbdccca860f`](https://github.com/gmanldn/smoothcast/commit/abbdccca860fac71af27570bac44f0f569ad645b)

- 🟥 **06:10:23 · Fix** — fix(msi): fail closed on incomplete upgrade qualification (Refs #535) · [`dcad2faa3cb8`](https://github.com/gmanldn/smoothcast/commit/dcad2faa3cb8e9152f88d39cea582b9b6615fa7f)

- 🟦 **06:08:26 · Refactor** — refactor(gui): move runtime version notices into lifecycle mixin (Refs #706) · [`275531ac80f2`](https://github.com/gmanldn/smoothcast/commit/275531ac80f2fa3de803e0f9d7a99955adb6f37d)

- 🟥 **06:04:29 · Fix** — fix(packaging): bundle and verify GPLv3 project legal notices (Refs #218) · [`e88a2d672692`](https://github.com/gmanldn/smoothcast/commit/e88a2d672692db17ac109e4e4325c5d9562854f1)

- 🟥 **05:54:50 · Fix** — fix(agents): restore root instruction budget without relaxing policies (Refs #706) · [`c8137ab7cc52`](https://github.com/gmanldn/smoothcast/commit/c8137ab7cc520cac286f247bdaa50b669af4956a)

- 🟦 **05:47:31 · Performance** — perf(web): defer network profiles and fence stale diagram updates (Refs #710) · [`31ca4719ce39`](https://github.com/gmanldn/smoothcast/commit/31ca4719ce39132abd0c818e460ce0467c97e48e)

- 🟥 **05:41:58 · Fix** — fix(gui): keep renamed room and guest labels in sync (Refs #709) · [`82c41421ffe1`](https://github.com/gmanldn/smoothcast/commit/82c41421ffe11a61965d39fa155dbd7806c9caab)

- 🟨 **05:32:46 · Documentation** — docs(manual): publish expanded SmoothCast product manual and technical reference · [`6512e96c0729`](https://github.com/gmanldn/smoothcast/commit/6512e96c0729bf4793c1e2214d78fc265ebaaba2)

- 🟦 **05:24:48 · Performance** — perf(gui): defer network diagram rendering and keep labels readable (Refs #710) · [`38270735f209`](https://github.com/gmanldn/smoothcast/commit/38270735f2092089f58a34e1100d45923ac07410)

- 🟥 **05:23:03 · Fix** — fix(agents): preserve Markdown punctuation in changelog entries (Refs #715) · [`7516b89286ab`](https://github.com/gmanldn/smoothcast/commit/7516b89286ab5cc13805bd4a4108c807f4a7a5ba)

- 🟩 **05:14:31 · Feature** — feat(room): add direct desktop rename control (Refs #709) · [`3fd7ff997c35`](https://github.com/gmanldn/smoothcast/commit/3fd7ff997c35fd0abe2073333f3f7f2cec6f2e15)

- 🟩 **05:05:41 · Feature** — feat(agents): establish readable changelog and reduce file lease contention (Refs #715) · [`4c028b9b81ef`](https://github.com/gmanldn/smoothcast/commit/4c028b9b81ef445117856c2a2a06cee017019519)

- 🟥 **05:04:50 · Fix** — fix(version): validate registered checkout provenance and cover malformed source markers · [`61bc7d5ee1b3`](https://github.com/gmanldn/smoothcast/commit/61bc7d5ee1b317deaad814b0353f97922ee70abd)

- 🟥 **04:58:59 · Fix** — fix(version): report exact shipped version and reconcile nonblocking PATCH policy · [`4531358000cb`](https://github.com/gmanldn/smoothcast/commit/4531358000cba49a19d8cd6dc581854edfd1871f)

- 🟥 **04:56:59 · Fix** — fix(version): detect pulled source updates and make PATCH allocation best effort · [`3aa29834937e`](https://github.com/gmanldn/smoothcast/commit/3aa29834937e2655c931b9c2aec5b16891e7b390)

- 🟥 **04:53:41 · Fix** — fix(version): allocate PATCH atomically in guarded connector shipments · [`e011c0099a75`](https://github.com/gmanldn/smoothcast/commit/e011c0099a75b50ca6125605493030652ce2655d)

- 🟥 **04:53:18 · Fix** — fix(version): restore retry-safe automatic PATCH allocation on native shipment · [`db0a48d26344`](https://github.com/gmanldn/smoothcast/commit/db0a48d263444b96d203695c21b23040453c46e4)

- 🟥 **04:50:45 · Fix** — fix(flatpak): verify installed portal modules and icon outside checkout (Refs #263) · [`4bba898907b7`](https://github.com/gmanldn/smoothcast/commit/4bba898907b7f2f9bdb456f31675e5771bcf1306)

- 🟥 **04:49:22 · Fix** — fix(uploads): coalesced durable checkpoints with committed/received offsets (Refs #568) · [`a5c5d367337b`](https://github.com/gmanldn/smoothcast/commit/a5c5d367337bcaecc056d9e62da5a8418600fd26)

- ⬜ **04:47:00 · Maintenance** — chore(version): release 2.3.2 · [`6f544b515552`](https://github.com/gmanldn/smoothcast/commit/6f544b515552b0a45a19998f440812aaab8be305)

- 🟨 **04:46:54 · Documentation** — docs(version): reconcile autonomous PATCH policy in scripts/connector\_ship.mjs · [`6ed3f11bd155`](https://github.com/gmanldn/smoothcast/commit/6ed3f11bd15549a0ccc5bbc55675e1142d95b92d)

- 🟨 **04:46:51 · Documentation** — docs(version): reconcile autonomous PATCH policy in docs/agents/sandbox-network.md · [`5c8de96643b8`](https://github.com/gmanldn/smoothcast/commit/5c8de96643b886f265c73588c37b1bb743411f97)

- 🟨 **04:46:48 · Documentation** — docs(version): reconcile autonomous PATCH policy in docs/agents/workflow.md · [`4d5c6427935e`](https://github.com/gmanldn/smoothcast/commit/4d5c6427935e2cf2b35f470184a4c81228427b22)

- 🟨 **04:46:00 · Documentation** — docs(policy): authorise autonomous PATCH increments on develop · [`d97966c1daea`](https://github.com/gmanldn/smoothcast/commit/d97966c1daea29207202d9251308568aed249546)

- 🟥 **04:43:46 · Fix** — fix(portal): central capability lookup and public-route invariant (#702) · [`d9ce60591e73`](https://github.com/gmanldn/smoothcast/commit/d9ce60591e73c5ead822dc4833dae055df461f17)

- 🟥 **04:39:57 · Fix** — fix(portal): declare per-route capabilities and add portal threat model (#702) · [`86ba4f92d4f3`](https://github.com/gmanldn/smoothcast/commit/86ba4f92d4f353f30ed328261506960602aa0152)

- 🟩 **04:37:31 · Feature** — feat(room): persistent host-editable room names and live headings (Refs #709) · [`771dc47f6886`](https://github.com/gmanldn/smoothcast/commit/771dc47f6886a1d74cb4b32a7321843a55e95925)

- 🟥 **04:26:05 · Fix** — fix(mesh): retain asymmetric network reachability in diagram (Refs #710) · [`fd5e4da417e3`](https://github.com/gmanldn/smoothcast/commit/fd5e4da417e3baadaff4abbcfac6e0ab956c97db)

- 🟥 **04:24:59 · Fix** — fix(portal): reject oversized seek positions before float conversion (Refs #702) · [`b30d70644632`](https://github.com/gmanldn/smoothcast/commit/b30d70644632cc93dd6a155e15ce642b57819432)

- 🟥 **04:23:19 · Fix** — fix(cast): preserve status fallback budget after failed direct probe (Refs #712) · [`87b1e21a01a5`](https://github.com/gmanldn/smoothcast/commit/87b1e21a01a5a9ec32559fa5081026a3ce1ee7a3)

- 🟥 **04:16:35 · Fix** — fix(portal): fence deferred upload retry to confirmed receiver (Refs #572) · [`9c8fe59513ed`](https://github.com/gmanldn/smoothcast/commit/9c8fe59513ed8f234caf542799b814f96b7495f0)

- ⬜ **04:05:18 · Maintenance** — Merge remote-tracking branch 'origin/develop' into develop · [`5b439b7ab6b6`](https://github.com/gmanldn/smoothcast/commit/5b439b7ab6b618101527e4723c241276fd7826bf)

- 🟨 **04:01:11 · Documentation** — docs: make hardware qualification non-blocking for develop (Refs #714) · [`2aa97d0bfa1f`](https://github.com/gmanldn/smoothcast/commit/2aa97d0bfa1f0e728ebef0ba943d8117f3006129)

- 🟥 **03:56:59 · Fix** — fix: trim cast\_portal.py comments to stay within size budget · [`ed522d724ede`](https://github.com/gmanldn/smoothcast/commit/ed522d724ede94c9a2a58b7b85274829761dc7f7)

- ⬜ **03:41:14 · Maintenance** — Merge pull request #713 from gmanldn/develop · [`22ab63b67bf4`](https://github.com/gmanldn/smoothcast/commit/22ab63b67bf4691401b4ec60649b05f13a921681)

- ⬜ **03:41:05 · Maintenance** — Merge branch 'main' into develop · [`cf3472700dca`](https://github.com/gmanldn/smoothcast/commit/cf3472700dca33031f91c1860cf22565a231cf77)

- 🟩 **03:36:47 · Feature** — feat(slo): median-of-N regression gate for reliability SLIs that fails closed on missing data (Refs #206) · [`6cf9825d271d`](https://github.com/gmanldn/smoothcast/commit/6cf9825d271ddcdf57e550772ae86f1b5fe508d2)

- 🟩 **03:35:40 · Feature** — feat(network): classify multi-NIC, VPN, VLAN, isolation and blocked-discovery failures into catalogued codes (Refs #210, #207) · [`a784b9db8c76`](https://github.com/gmanldn/smoothcast/commit/a784b9db8c767676d05906477a456c99ac277a8a)

- 🟥 **03:35:18 · Fix** — fix(cast): remember a good FFmpeg version check per binary and give a loaded host 15 s; a slow check no longer aborts the cast as 'install FFmpeg' (Refs #686) · [`6beefa8a9277`](https://github.com/gmanldn/smoothcast/commit/6beefa8a9277c97bc4075d00597b9f813fd3263a)

- 🟥 **03:32:52 · Fix** — fix(launch): fail closed without psutil, confirm a hung primary with a second probe and only replace this install's own instance, abort --fresh when a process survives, keep unknown/error out of 'playing on TV' and keep the local-playing chip (review findings, Refs #582) · [`aa112b4a91f5`](https://github.com/gmanldn/smoothcast/commit/aa112b4a91f57b03590bf2dab976ef52fcdef3d4)

- 🟩 **03:32:34 · Feature** — feat(doctor): read-only check engine with pass/warn/fail, remediation text and JSON output (Refs #211) · [`84737ee15e2e`](https://github.com/gmanldn/smoothcast/commit/84737ee15e2e3f4e2d6eed817fc2dd0c343f42a6)

- 🟩 **03:27:18 · Feature** — feat(stream): measured stream-health aggregate that reports unknown instead of inferred success (Refs #49) · [`9e326f08d541`](https://github.com/gmanldn/smoothcast/commit/9e326f08d54150eb464b37d106831d6d590f1317)

- 🟩 **03:25:47 · Feature** — feat(chapters): picker rows with clock times and exact source-to-stream mapping (Refs #39) · [`c458437bf158`](https://github.com/gmanldn/smoothcast/commit/c458437bf1589528e76be51394d6ae0b50f8a82c)

- ⬜ **03:25:38 · Maintenance** — Merge branch 'develop' of https://github.com/gmanldn/smoothcast into develop · [`a28f1aebc796`](https://github.com/gmanldn/smoothcast/commit/a28f1aebc79651600d5731ed2f57e984bfa14652)

- 🟥 **03:24:57 · Fix** — fix(launch): add the missing setup/fresh\_start.py that sc.py imports (Refs #582) · [`8cfa91507f5a`](https://github.com/gmanldn/smoothcast/commit/8cfa91507f5a8d23146c623f329d5e1575f6311c)

- 🟩 **03:24:47 · Feature** — feat(group): pure multi-room latency alignment and ceiling-safe shared volume (Refs #46) · [`cf5a0a7eff3e`](https://github.com/gmanldn/smoothcast/commit/cf5a0a7eff3eafd8a44ba5aff181e79e7eb7ee9c)

- 🟩 **03:23:16 · Feature** — feat(cast): video files sent to an audio-only speaker plan soundtrack-only output instead of a video transcode (Refs #45) · [`af8d5d7c4c6e`](https://github.com/gmanldn/smoothcast/commit/af8d5d7c4c6e5cb4473c4a2dd59ea4939f5e3d27)

- ⬜ **03:22:56 · Maintenance** — Merge origin/develop into local develop · [`a854cf804566`](https://github.com/gmanldn/smoothcast/commit/a854cf8045660058e831dfa15370458ee4c8c6b0)

- 🟩 **03:22:05 · Feature** — feat(launch): sc.py replaces a hung primary and reaps its helpers; sc.py --fresh forces a full reset before the install refresh (Refs #582) · [`c2e3724b5af2`](https://github.com/gmanldn/smoothcast/commit/c2e3724b5af20a6fe51dcb3a416b8144f50da77e)

- ⬜ **03:21:04 · Maintenance** — 1 · [`e7846f3627d0`](https://github.com/gmanldn/smoothcast/commit/e7846f3627d0083d8e4e8aae1afa5c544232ac7b)

- 🟩 **03:20:40 · Feature** — feat(stream): pure adaptive-bitrate controller with hysteresis and cool-down (Refs #31) · [`db579f28b3dd`](https://github.com/gmanldn/smoothcast/commit/db579f28b3dd7d72e3aec80eee2af5df7af0a27d)

- 🟥 **03:18:15 · Fix** — fix(cast): read a verified receiver over the kept direct connection before spawning catt, so a slow catt (7s+) no longer marks a live Chromecast OFFLINE (Refs #712) · [`8bb3d14deb52`](https://github.com/gmanldn/smoothcast/commit/8bb3d14deb529d8e48537887d18abfd4cd3877e9)

- 🟦 **03:14:58 · Performance** — perf: overlap portal mDNS goodbyes during application quit (Refs #705) · [`e1f1e69897c2`](https://github.com/gmanldn/smoothcast/commit/e1f1e69897c21bca30f4bfbeff90eb51a39e210b)

- 🟩 **03:14:27 · Feature** — feat(update): require room for two generations before staging a managed candidate (Refs #580) · [`118af79fbe98`](https://github.com/gmanldn/smoothcast/commit/118af79fbe98d5b88c4c5154e611da8b5979bde2)

- ⬜ **03:12:51 · Maintenance** — chore(version): release 2.3.1 (Refs #686) · [`1791c5caa52b`](https://github.com/gmanldn/smoothcast/commit/1791c5caa52b01a2eda71b57943b3f7e2ca320b2)

- 🟪 **03:12:18 · Tests** — test(links): YouTube Find harness fakes document.getElementById so the portal's update-button script in the same block no longer crashes it (Refs #686) · [`5fb4548ce666`](https://github.com/gmanldn/smoothcast/commit/5fb4548ce6663bb5af4f2e71466b7f34ebdb5581)

- 🟩 **03:11:49 · Feature** — feat(update): desktop front-page Update and restart button next to Network (Refs #711) · [`ff379b68edfe`](https://github.com/gmanldn/smoothcast/commit/ff379b68edfee7e79c074b768dc6c348c09ed3e3)

- 🟥 **03:10:44 · Fix** — fix(links): a failed link download is journalled as failed before anyone can see it fail; no reader or crash can observe 'failed' while the journal still says 'resolving' (Refs #686) · [`cec893343f26`](https://github.com/gmanldn/smoothcast/commit/cec893343f26f7696efbc9d31251e7f1d87e23e3)

- 🟩 **03:10:11 · Feature** — feat(web): front page at-a-glance tiles for playing, target and people (Refs #709) · [`a58d72322ccb`](https://github.com/gmanldn/smoothcast/commit/a58d72322ccb53be1b9bde6cddf8ca1aec14f4ca)

- 🟦 **03:10:00 · Refactor** — refactor(gui): split receiver discovery/polling into cast\_discovery and remote-URL casting into cast\_remote\_url; cast\_queue 37.9k-&gt;18.9k, cast\_session under its 56k read budget (Refs #706) · [`50632d6dc995`](https://github.com/gmanldn/smoothcast/commit/50632d6dc9957f3cf1a44d11f4b34f258d4500e9)

- 🟩 **03:09:23 · Feature** — feat(import): smoothcast import jellyfin|plex|kodi brings watched/resume state from export files; dry run by default, matches by path, file name, title+year or show+SxxEyy, reports ambiguity, --apply merges only watch keys (Refs #435) · [`18b021585be7`](https://github.com/gmanldn/smoothcast/commit/18b021585be7c3d49b1f6879116cf8ebd53adb41)

- 🟩 **03:07:25 · Feature** — feat(mesh): desktop Network popover shows the connection diagram and full device detail (Refs #710) · [`e6237a451694`](https://github.com/gmanldn/smoothcast/commit/e6237a45169495f6bd5043a159a1a4be7a669a24)

- 🟩 **03:06:04 · Feature** — feat(web): Now Playing card matches the desktop hero card (Refs #708) · [`7665b182df03`](https://github.com/gmanldn/smoothcast/commit/7665b182df03a8d63dcc047f2f5c87bebf908421)

- 🟩 **03:02:29 · Feature** — feat(export): smoothcast export --to DIR writes queue.m3u8/.xspf, history, rooms and preferences as plain files with no secrets; order-preserving round trip (Refs #435) · [`cdde0499ffb6`](https://github.com/gmanldn/smoothcast/commit/cdde0499ffb620bb7629d2da561ccd4600b046b5)

- 🟩 **03:02:24 · Feature** — feat(update): attach the shared UpdateRunner to the portal so the web Update button works (Refs #711) · [`b3be99e18059`](https://github.com/gmanldn/smoothcast/commit/b3be99e18059710862cad1d1d7388475dce18af6)

- 🟩 **02:59:20 · Feature** — feat(update): one-click Update and restart in the web room, host-only, via UpdateRunner (Refs #711) · [`f70defda0504`](https://github.com/gmanldn/smoothcast/commit/f70defda0504f1ff2a77cb983a7d7162626e8f33)

- 🟥 **02:55:32 · Fix** — fix(cast): direct-cast acceptance, foreign-playback guard, CLI status and network activity read catt's nested media\_metadata title (they always saw no title before) (Refs #686) · [`bb9dfc58eef2`](https://github.com/gmanldn/smoothcast/commit/bb9dfc58eef23131e47c8104ca7bd54b1bd88e43)

- 🟥 **02:54:47 · Fix** — fix(flatpak): lock compiled wheels for the GNOME 51 SDK's CPython 3.14 (CI-probed), not 3.13 (Refs #263) · [`2ba6838cf6e7`](https://github.com/gmanldn/smoothcast/commit/2ba6838cf6e79293e849bbf1f15353682e698558)

- 🟩 **02:48:55 · Feature** — feat(flatpak): buildable offline manifest with hash-pinned Python wheels, pinned x264 + FFmpeg 8.1.3 (libx264, VAAPI, ffplay) and an experimental CI build (Refs #263) · [`a710cde34990`](https://github.com/gmanldn/smoothcast/commit/a710cde349909d4f933196bc8dbefc881be1965f)

- 🟥 **02:48:22 · Fix** — fix(cast): confirm direct/HLS playback against catt's nested media\_metadata title; another app's playing media no longer falsely confirms our cast (Refs #686) · [`65982dad26e5`](https://github.com/gmanldn/smoothcast/commit/65982dad26e594b9f028ba66b0fcf57be571a58e)

- 🟥 **02:46:08 · Fix** — fix(mesh): add node\_profile, mesh\_diagram and tests missing from the previous push (Refs #710) · [`9f59d4af2ea0`](https://github.com/gmanldn/smoothcast/commit/9f59d4af2ea0325d9d99938ed2cff4155ae94439)

- 🟩 **02:41:49 · Feature** — feat(mesh): node profiles and SVG connection diagram in the web Network pane (Refs #710) · [`1069a4697335`](https://github.com/gmanldn/smoothcast/commit/1069a469733517fed7ab75a7dc914c77df2916e0)

- 🟥 **02:40:54 · Fix** — fix(stream): a slow but advancing encoder gets up to 120 s to produce its first segments instead of a fixed 15/30 s kill; stalled encoders still time out (Refs #686) · [`b1a6aaf2aaeb`](https://github.com/gmanldn/smoothcast/commit/b1a6aaf2aaeb78f8b23a2fbfcb02abf0580a568f)

- 🟥 **02:37:29 · Fix** — fix(repo): add the 13 GTK-free modules whose tests landed without their source · [`7e564b92f835`](https://github.com/gmanldn/smoothcast/commit/7e564b92f8354ea20900f9397ddd4008d4090f17)

- 🟥 **02:36:06 · Fix** — fix(repo): commit the 14 GTK-free modules whose tests landed without their source · [`cad2b9a3a67a`](https://github.com/gmanldn/smoothcast/commit/cad2b9a3a67a51d9229db778218155a0e4383db0)

- 🟩 **02:28:38 · Feature** — feat(api): versioned local API envelope with strict command validation (Refs #213) · [`c719c5979621`](https://github.com/gmanldn/smoothcast/commit/c719c59796212d847cccfd15062f204323380180)

- 🟩 **02:27:10 · Feature** — feat(encoder): pure ffmpeg capability parsing, required-filter messages and verified encoder ladder (Refs #217) · [`d1fea9d3eaf3`](https://github.com/gmanldn/smoothcast/commit/d1fea9d3eaf38f331ed3a5627325782da1da2dd1)

- 🟩 **02:23:57 · Feature** — feat(network): pure IPv6-safe URL, source ranking and interface scoring policy (Refs #210) · [`5e3992b0928e`](https://github.com/gmanldn/smoothcast/commit/5e3992b0928ec0684e31ed9d1be5552fde93389a)

- 🟩 **02:22:06 · Feature** — feat(sessions): isolated per-receiver session registry with token-scoped control (Refs #132) · [`4f92740e9eec`](https://github.com/gmanldn/smoothcast/commit/4f92740e9eecbc8d73b61ded545bb3fa07fe82e6)

- 🟩 **02:21:38 · Feature** — feat(sessions): isolated per-receiver session registry with token-scoped control (Refs #132) · [`7915e7d8db32`](https://github.com/gmanldn/smoothcast/commit/7915e7d8db3225b8bfae7c5a5908bfc1b0de51ed)

- 🟩 **02:21:24 · Feature** — feat(sessions): isolated per-receiver session registry with token-scoped control (Refs #132) · [`b238bc7ee31c`](https://github.com/gmanldn/smoothcast/commit/b238bc7ee31cb2be481193454dc941e39458c78b)

- 🟩 **02:20:03 · Feature** — feat(art): now-playing art source policy separating attached pictures from motion video (Refs #130) · [`fe973e22d30d`](https://github.com/gmanldn/smoothcast/commit/fe973e22d30d27112ba626f8ced36a14d5bcd510)

- 🟦 **02:19:28 · Refactor** — refactor(ui): one status-chip decision table and header state wording from state\_labels; header reads 'ready' instead of 'idle' (Refs #582) · [`ca542d36900c`](https://github.com/gmanldn/smoothcast/commit/ca542d36900c1a317445addc1baae4d991d6f0d4)

- 🟩 **02:18:36 · Feature** — feat(ui): honest floating-preview capability policy for Wayland/X11 (Refs #124) · [`15c5ca120ca9`](https://github.com/gmanldn/smoothcast/commit/15c5ca120ca927d050b799b18851846c6bf53201)

- 🟩 **02:17:14 · Feature** — feat(ui): mini-player layout policy keeping essential controls at any width (Refs #118) · [`290f64cc11ac`](https://github.com/gmanldn/smoothcast/commit/290f64cc11ac9ead1a3c8b239fd3e8406d22f164)

- 🟩 **02:16:01 · Feature** — feat(crop): pure zoom/pan and manual-crop geometry with even in-bounds rectangles (Refs #115) · [`4326bd87900f`](https://github.com/gmanldn/smoothcast/commit/4326bd87900fcac3270048111cc8aa213ba8ff3e)

- 🟩 **02:14:40 · Feature** — feat(queue): cancellable token-checked prewarm planner for next-item handoff (Refs #48) · [`7a5ad1679dc4`](https://github.com/gmanldn/smoothcast/commit/7a5ad1679dc43c82ef745e7c8932809edf2ab945)

- 🟩 **02:12:58 · Feature** — feat(presets): validated per-receiver quality and subtitle presets with reset (Refs #47) · [`5eee47279142`](https://github.com/gmanldn/smoothcast/commit/5eee4727914265f6bded3bb7a89790bfa5a5a059)

- ⬜ **02:12:18 · Maintenance** — chore(version): release 2.3.0 — shared batch-upload queue visibility, richer Now Playing for external streams, chapter navigation and equaliser/scrub-preview foundations (Refs #324) · [`1b40f8100f52`](https://github.com/gmanldn/smoothcast/commit/1b40f8100f524162f661d2f4dc7bcdac6f471a1e)

- 🟩 **02:10:47 · Feature** — feat(handoff): per-receiver start-error history and bounded latency compensation (Refs #41) · [`af252cc93e53`](https://github.com/gmanldn/smoothcast/commit/af252cc93e534064092ade527dbd9cc9140261fb)

- 🟥 **02:10:31 · Fix** — fix(launcher): sc.py starts even when local checkout is behind or dirty · [`7c8f110c6dfa`](https://github.com/gmanldn/smoothcast/commit/7c8f110c6dfa48c84af9c996b5b8acf021ac6928)

- 🟩 **02:07:55 · Feature** — feat(chapters): pure chapter parsing, current-chapter lookup and next/previous jump (Refs #39) · [`4ab712a11314`](https://github.com/gmanldn/smoothcast/commit/4ab712a11314183bd5ea31c4fbeb76867a6be9fc)

- 🟩 **02:04:53 · Feature** — feat(audio): pure 10-band equaliser model and filter builder; sync pyproject module list (Refs #111, #40) · [`d07055ac7779`](https://github.com/gmanldn/smoothcast/commit/d07055ac7779c49436510f053e79643d8be07678)

- 🟪 **02:03:25 · CI** — ci(complexity): rebaseline after cast-reliability work (castctl status mirror/route retry, server kept-stream watchdog, IPv6 receiver URLs, receiver-authoritative playback state) so develop's budget test is green again (Refs #698) · [`2d7c1e6bfa6b`](https://github.com/gmanldn/smoothcast/commit/2d7c1e6bfa6bb9846786ebf47d8b7608f6a51f28)

- 🟪 **02:02:08 · Tests** — test(packaging): ratchet against stdlib-shadowing and new generic top-level module names (Refs #107) · [`de25a5977003`](https://github.com/gmanldn/smoothcast/commit/de25a59770039ec6ed38996425fec981c905767c)

- 🟩 **01:59:54 · Feature** — feat(preview): GTK-free thumbnail strip cache and frame-step maths for instant scrub previews (Refs #40) · [`022d1743d1ed`](https://github.com/gmanldn/smoothcast/commit/022d1743d1ed2912e5c24ff9fbcbe694cbba0c58)

- 🟥 **01:59:33 · Fix** — fix(agents): agent.py ship refuses to run from the owner's primary checkout; only agent.py start worktrees can push (Refs #688) · [`e3be2d74810b`](https://github.com/gmanldn/smoothcast/commit/e3be2d74810bef04ec84c54bedce540368bda58e)

- 🟪 **01:58:50 · Tests** — test: no test can open a real Chromecast status connection through the catt fallback mirror (Refs #686) (Refs #698) · [`f91d9af73db5`](https://github.com/gmanldn/smoothcast/commit/f91d9af73db5979689e337af29b60d2faea41653)

- 🟥 **01:58:08 · Fix** — fix(mesh): reconcile GTK rows without removing unattached widgets (Refs #707) · [`4b95fa0860dd`](https://github.com/gmanldn/smoothcast/commit/4b95fa0860ddab9d0771240164ea2865e3f9c499)

- 🟥 **01:56:03 · Fix** — fix(stream): HLS server stops an orphaned kept encoder after 10 min with no receiver fetches, then exits; a kept stream no longer transcodes a whole film to nobody (Refs #698) · [`4107d2858c38`](https://github.com/gmanldn/smoothcast/commit/4107d2858c389548750fd4e8e6698b40b1b9ccc9)

- 🟥 **01:52:02 · Fix** — fix(subtitles): an unsupported sidecar no longer re-runs and logs a traceback on every seek-bar hover; cache no-cues once (Refs #698) · [`c0c7c42e58cb`](https://github.com/gmanldn/smoothcast/commit/c0c7c42e58cb65a012cbd990c8b18cd1b05deff5)

- 🟥 **01:43:48 · Fix** — fix(errors): keep the silent-exception ratchet green on develop; the catt code-recorder drops a redundant try around a defensive call, and the two kept-connection best-effort cleanups are documented in the allow-list (Refs #207, #686) · [`70ae8181ba1e`](https://github.com/gmanldn/smoothcast/commit/70ae8181ba1e396ba8593dc33612791135e54445)

- 🟥 **01:38:31 · Fix** — fix(cast): once a direct status connection is proven, poll it first instead of spawning catt; a dropped socket falls back to catt and is forgotten (Refs #686) · [`b1f543a8b3c9`](https://github.com/gmanldn/smoothcast/commit/b1f543a8b3c9e144dd7999cd833d90a49410b69f)

- 🟥 **01:37:53 · Fix** — fix(cast): direct status reads return the same media keys as catt info (content/stream type, metadata, subtitle tracks, commands) (Refs #686) · [`b83707a8898a`](https://github.com/gmanldn/smoothcast/commit/b83707a8898a82e80b6ad87a1d6f7df0426e4a01)

- 🟥 **01:36:58 · Fix** — fix(a11y): keyboard Tab no longer traps on Open media when the other action buttons are disabled; a disabled button now disables its FlowBoxChild, and the Tab walk tolerates layout shifts and disabled controls; drops an unused local that failed ruff on develop (Refs #449) · [`f3b3804eaf3b`](https://github.com/gmanldn/smoothcast/commit/f3b3804eaf3b856a3ba99e069ec226a003a46c23)

- 🟥 **01:36:45 · Fix** — fix(a11y): keyboard Tab no longer traps on Open media when the other action buttons are disabled; a disabled button now disables its FlowBoxChild, and the Tab walk tolerates layout shifts and disabled controls (Refs #449) · [`b8b862edc73c`](https://github.com/gmanldn/smoothcast/commit/b8b862edc73c47b339292c74efd36e30acfa025d)

- 🟥 **01:30:19 · Fix** — fix(preferences): drop the test-only sync guard and keep preferences\_ui within its read budget (Refs #579) · [`ca9aec44031a`](https://github.com/gmanldn/smoothcast/commit/ca9aec44031a95cb389dd1964c7822954ea81d86)

- 🟨 **01:28:47 · Documentation** — docs(agents): edit only in private worktrees, never the owner's main checkout (Refs #688) · [`edc7b96135a8`](https://github.com/gmanldn/smoothcast/commit/edc7b96135a83744fbb00fe6d75587f93b429ff0)

- 🟨 **01:28:47 · Documentation** — docs(agents): edit only in private worktrees, never the owner's main checkout (Refs #688) · [`0905687e2a7c`](https://github.com/gmanldn/smoothcast/commit/0905687e2a7c9e4d57b6e94f7dda430e64133604)

- 🟥 **01:27:18 · Fix** — fix(errors): catt command failures record catalogue codes (receiver\_offline on timeout, command\_failed on exit/start) and log the helper's stderr tail (Refs #207) · [`e84d0ea9092a`](https://github.com/gmanldn/smoothcast/commit/e84d0ea9092a672c67d5c65c5c37912ef3d420af)

- 🟦 **01:26:43 · Refactor** — refactor(update): move managed-install facts to update\_managed to stay in the size budget (Refs #579) · [`0ee235e10b9b`](https://github.com/gmanldn/smoothcast/commit/0ee235e10b9baf230bae76741e883894de8e510f)

- 🟩 **01:24:07 · Feature** — feat(network): IPv6-safe receiver URL builder that brackets IPv6 and refuses link-local, zone-scoped and loopback hosts (Refs #210) · [`9a739cd5b940`](https://github.com/gmanldn/smoothcast/commit/9a739cd5b94011bcc08dfa611f6267405dcd4472)

- 🟩 **01:23:02 · Feature** — feat(network): IPv6-safe receiver URL builder that brackets IPv6 and refuses link-local, zone-scoped and loopback hosts (Refs #210) · [`6bb6e67ef495`](https://github.com/gmanldn/smoothcast/commit/6bb6e67ef49518214d0693a001c375f27cd18e5c)

- 🟩 **01:21:02 · Feature** — feat(update): Check now reports the candidate through the update status model; unsigned never shows as available (Refs #579) · [`d72ed8415493`](https://github.com/gmanldn/smoothcast/commit/d72ed8415493719ac3a429949051efc6820ded23)

- 🟥 **01:20:44 · Fix** — fix(cast): when a catt status read fails, answer from a kept read-only PyChromecast connection to the verified receiver address (instant after first connect) (Refs #686) · [`94cafa31c367`](https://github.com/gmanldn/smoothcast/commit/94cafa31c367719ff51d1b7a19d81fb91055b98d)

- 🟩 **01:19:39 · Feature** — feat(portal): announce a whole upload batch so every guest sees waiting files in the incoming panel (Refs #324) · [`9e0a72084249`](https://github.com/gmanldn/smoothcast/commit/9e0a720842491d67f3987894dda7270e167135f1)

- 🟥 **01:16:22 · Fix** — fix(perf): drive the interaction benchmark's volume scene and give the run a full budget (Refs #683) · [`52d823993e48`](https://github.com/gmanldn/smoothcast/commit/52d823993e487ddf70ffbb76b1aba6f48d5f9017)

- 🟥 **01:12:53 · Fix** — fix(msi): accept Windows 10/11 whose installer reports VersionNT 603 (Refs #535) · [`fb4d64c251ce`](https://github.com/gmanldn/smoothcast/commit/fb4d64c251cefbfcdb1d2b5cfdfa5276a04e1ae8)

- 🟥 **01:09:20 · Fix** — fix(cast): decode and encode 10-bit 4:2:0 on VAAPI so weak CPUs start casting (Refs #325) · [`5115dd9f8cdd`](https://github.com/gmanldn/smoothcast/commit/5115dd9f8cdde48ce617ba87a04495b0f501430e)

- 🟥 **01:09:05 · Fix** — fix(cast): keep a receiver status read, rediscovery and retry within the caller's timeout; learn the route in the background when out of budget (Refs #686) (Refs #320) · [`32c78aee6bba`](https://github.com/gmanldn/smoothcast/commit/32c78aee6bba5d2b9812e71fc03b42b897f8e234)

- 🟩 **01:08:34 · Feature** — feat(portal): show 'File i of n' for batch uploads in the room's incoming panel (Refs #324) · [`3aba27ca1a4c`](https://github.com/gmanldn/smoothcast/commit/3aba27ca1a4c5a96713f0b7e0be3a31855c49979)

- 🟪 **01:06:47 · CI** — ci(msi): keep and print msiexec logs when the lifecycle smoke fails (Refs #535) · [`6f236abf4c94`](https://github.com/gmanldn/smoothcast/commit/6f236abf4c94d859df4be2997197f4e11f1a2675)

- 🟪 **01:01:12 · Tests** — test: align stale GUI, capability and selftest assertions with landed changes (Refs #579, #11, #449) · [`c5db38aae970`](https://github.com/gmanldn/smoothcast/commit/c5db38aae970edf35f4ecd51073c8879460ceeff)

- 🟥 **01:00:01 · Fix** — fix(cast): skip receiver activity polling while a cast is starting (Refs #686) · [`94d2acf63547`](https://github.com/gmanldn/smoothcast/commit/94d2acf63547985dc40a8f5b611eb8ba7628c968)

- 🟥 **00:55:34 · Fix** — fix(cast): 3x encoder start-up window for subtitle burn-in; name silent-ffmpeg timeouts (Refs #686) · [`5a691f7b9e8a`](https://github.com/gmanldn/smoothcast/commit/5a691f7b9e8a0c8699d101d2d5d5c3c8fcaf8342)

- 🟩 **00:48:20 · Feature** — feat(now-playing): describe external streams (format, length, source) on web and native; tolerate missed receiver status reads; release 2.2.8 (Refs #324) · [`72ba6a22354b`](https://github.com/gmanldn/smoothcast/commit/72ba6a22354becdf0a0988a1e296cab787a7094f)

- 🟩 **00:48:20 · Feature** — feat(portal): Up Next pages past 100 items with Show more (Refs #324) · [`50c34091ee21`](https://github.com/gmanldn/smoothcast/commit/50c34091ee2119c38a5677c5138b41da3d5d3bff)

- 🟥 **00:42:20 · Fix** — fix(cast): retry a failed name-based receiver status read once via a verified address (Refs #686) · [`f51c5fe19414`](https://github.com/gmanldn/smoothcast/commit/f51c5fe194144d844d8445b34cc002dec67e7c53)

- 🟪 **00:41:09 · Tests** — test(portal): three-guest retry, race and rejoin queue adds land exactly once (Refs #325) · [`0809c514899d`](https://github.com/gmanldn/smoothcast/commit/0809c514899d5aca7b6399fa6282201a9f742fdd)

- ⬜ **00:37:15 · Maintenance** — chore(version): release 2.2.7 (Refs #635) · [`807577a0a977`](https://github.com/gmanldn/smoothcast/commit/807577a0a977c608b1ccdbb89d88f08de55d45e0)

- 🟥 **00:34:38 · Fix** — fix(playback): share receiver-authoritative external media display clock (Refs #635) · [`71cbe88649f9`](https://github.com/gmanldn/smoothcast/commit/71cbe88649f93b697926fa333c97355deddefae7)

- 🟪 **00:33:21 · Tests** — test(cast): cover every receiver-confirmation failure branch with a fake backend (Refs #320) · [`78934a1bbeb5`](https://github.com/gmanldn/smoothcast/commit/78934a1bbeb5aaf4cb62003a46ed6c85c2d3817c)

- ⬜ **00:32:05 · Maintenance** — chore(version): release 2.2.6 (Refs #588) · [`e97bea908609`](https://github.com/gmanldn/smoothcast/commit/e97bea908609d1106e74a1b1a16798f58d10cef0)

- 🟩 **00:29:44 · Feature** — feat(link): Preferences 'Set up' button installs and attack-tests the isolation launcher off-thread (Refs #588) · [`4cc35f33bd30`](https://github.com/gmanldn/smoothcast/commit/4cc35f33bd30f2579bf8c0501e6bac739b4eb5be)

- 🟩 **00:28:34 · Feature** — feat(link): Preferences 'Set up' button installs and attack-tests the isolation launcher off-thread (Refs #588) · [`723bb6c4f064`](https://github.com/gmanldn/smoothcast/commit/723bb6c4f0649fedad789616b119c95af4b4115c)

- 🟩 **00:27:57 · Feature** — feat(link): Preferences 'Set up' button installs and attack-tests the isolation launcher off-thread (Refs #588) · [`8ee61d2d7fcd`](https://github.com/gmanldn/smoothcast/commit/8ee61d2d7fcdd343a4a0f5926d6c044347751b79)

- ⬜ **00:12:30 · Maintenance** — chore(version): release 2.2.5 (Refs #324) · [`edcde44dc92d`](https://github.com/gmanldn/smoothcast/commit/edcde44dc92dba588805f74ee2d7055a945403f2)

- 🟥 **00:10:16 · Fix** — fix(cast): include receiver status failure reason in 'did not return status' error (Refs #686) · [`4196a1a547e8`](https://github.com/gmanldn/smoothcast/commit/4196a1a547e864eb00aa9ab43b58311e0a038327)

- 🟥 **00:04:00 · Fix** — fix(cast): record and log why receiver status reads fail (Refs #686) · [`83e88a88c387`](https://github.com/gmanldn/smoothcast/commit/83e88a88c387af3bc58ec5e5498aac149a958c25)

- 🟩 **00:00:40 · Feature** — feat(errors): tag discovery, DLNA fault and port-in-use failures with catalogue codes at the raise site (Refs #207) · [`d758c288dddd`](https://github.com/gmanldn/smoothcast/commit/d758c288dddd8cd92bd61805878b7a18d3577d0a)

---

## 2026-11-26 · UTC

- 🟩 **23:48:20 · Feature** — feat(updates): explicit Check now button runs the read-only check off the GTK thread (Refs #579) · [`b1c116a93a4f`](https://github.com/gmanldn/smoothcast/commit/b1c116a93a4f43d42a7d6740925c92c3904c7007)

- 🟩 **23:47:44 · Feature** — feat(updates): explicit Check now button runs the read-only check off the GTK thread (Refs #579) · [`a67b4c7165b8`](https://github.com/gmanldn/smoothcast/commit/a67b4c7165b8564a3f60c4ab5b19fab420703b4c)

- 🟩 **23:36:12 · Feature** — feat(updates): show managed install reference and journal state in Preferences (Refs #579, #582) · [`6160050247c9`](https://github.com/gmanldn/smoothcast/commit/6160050247c9cfd2513db2aa950189893886107d)

- 🟩 **23:35:33 · Feature** — feat(updates): show managed install reference and journal state in Preferences (Refs #579, #582) · [`4e80f6e89fa9`](https://github.com/gmanldn/smoothcast/commit/4e80f6e89fa99f99178adec97a5f29d796c129a4)

- ⬜ **23:21:17 · Maintenance** — chore(version): release 2.2.4 (Refs #324) · [`6eeed62bff55`](https://github.com/gmanldn/smoothcast/commit/6eeed62bff55fef16071e1bdb16e124664bcdce0)

- 🟥 **23:20:24 · Fix** — fix(web): Home action tiles reflow to one column at 200% text so 320px never scrolls sideways (Refs #324) · [`1b926bce8324`](https://github.com/gmanldn/smoothcast/commit/1b926bce8324966249956cced900d512e41ffb09)

- 🟪 **23:19:15 · Tests** — test(web): stale queue move is rejected with an explanation and the browser list catches up (Refs #324) · [`85e39ad1c9a6`](https://github.com/gmanldn/smoothcast/commit/85e39ad1c9a626ff62fbd9a0d981cf573dd15a2a)

- 🟩 **23:18:38 · Feature** — feat(updates): show running build and channel in Preferences from offline facts (Refs #579, #582) · [`2ac5d4db7c04`](https://github.com/gmanldn/smoothcast/commit/2ac5d4db7c04bf7d3ebcb53599b0036c03624ad4)

- 🟥 **23:15:50 · Fix** — fix(link): point Linux repair step at --link-check --setup and state the BitTorrent limit (Refs #588) · [`09b4ab4979c3`](https://github.com/gmanldn/smoothcast/commit/09b4ab4979c3a62ad3466dad4bf18d944dbb8547)

- 🟥 **23:15:29 · Fix** — fix(link): point Linux repair step at --link-check --setup and state the BitTorrent limit (Refs #588) · [`6efcf4216e19`](https://github.com/gmanldn/smoothcast/commit/6efcf4216e19e4d7852809e1be7a2dcaf659c312)

- ⬜ **23:08:38 · Maintenance** — chore: refresh complexity baseline for catalogue growth in errors.py (+26 lines: 3 codes, categories) and link\_sandbox\_probe (Refs #207) · [`2115329e22b1`](https://github.com/gmanldn/smoothcast/commit/2115329e22b1adc497314e01cd7da5bc072352f1)

- 🟩 **23:08:12 · Feature** — feat: root bounce.py safe explicit update to latest develop, never stopping a running primary (Refs #626) · [`9b33ca521af6`](https://github.com/gmanldn/smoothcast/commit/9b33ca521af6b2873785a6f50a4bcf657e4e65b6)

- 🟩 **23:07:36 · Feature** — feat(errors): catalogue discovery, DLNA fault and port-in-use failures and classify them (Refs #207) · [`d9665dbb243b`](https://github.com/gmanldn/smoothcast/commit/d9665dbb243b2473aba98b1cc720437714f64465)

- 🟥 **23:06:34 · Fix** — fix: sync pyproject module list for link\_provision (Refs #588) · [`a4b843a95d95`](https://github.com/gmanldn/smoothcast/commit/a4b843a95d959b66a978226541a27966dd8edfbc)

- 🟩 **23:05:34 · Feature** — feat(link): --setup provisions and qualifies the reference launcher; auto-discover it (Refs #588) · [`bdfad0751932`](https://github.com/gmanldn/smoothcast/commit/bdfad0751932c050925589bd8331a12677c832f1)

- 🟥 **23:04:10 · Fix** — fix: clean up partial sandbox qualification setup (Refs #588) · [`df8546304156`](https://github.com/gmanldn/smoothcast/commit/df85463041568618249da53819262dc38eadc7e9)

- 🟥 **22:19:50 · Fix** — fix: retain upload cast ownership while progressive or pending (Refs #570) · [`be985934e329`](https://github.com/gmanldn/smoothcast/commit/be985934e32985ebecbe30e441b969bb9574a15e)

- 🟥 **21:57:10 · Fix** — fix(web): Up Next over 100 items says '100 of N shown' instead of silently reporting 100 waiting (Refs #324) · [`13ce49e35296`](https://github.com/gmanldn/smoothcast/commit/13ce49e35296eb7ca0189319f6d2acf9a4677249)

- ⬜ **21:55:29 · Maintenance** — chore(version): release 2.2.3 (Refs #324) · [`61b0cdc718a7`](https://github.com/gmanldn/smoothcast/commit/61b0cdc718a737aa14dc05a759dbf2c08b07d406)

- 🟥 **21:55:29 · Fix** — fix(web): Up Next over 100 items says '100 of N shown' instead of silently reporting 100 waiting (Refs #324) · [`412844c92857`](https://github.com/gmanldn/smoothcast/commit/412844c9285744df6db1bfcaf88c2e20152f7f7e)

- 🟥 **21:55:29 · Fix** — fix(web): Up Next over 100 items says '100 of N shown' instead of silently reporting 100 waiting (Refs #324) · [`e55e52e6a671`](https://github.com/gmanldn/smoothcast/commit/e55e52e6a67186ffe44f65a84756f6c61dcd9600)

- 🟥 **21:55:04 · Fix** — fix: require complete sandbox qualification evidence (Refs #588) · [`575abc1c08d3`](https://github.com/gmanldn/smoothcast/commit/575abc1c08d3af9921a37e3ad55aeb9388464925)

- 🟥 **21:51:59 · Fix** — fix: keep error reporting safe with malformed exception metadata (Refs #207) · [`07b158f69189`](https://github.com/gmanldn/smoothcast/commit/07b158f691894f84c0da24be2d2520279dbc0fd8)

- 🟪 **21:50:51 · Tests** — test(web): two-browser real-Chrome Up Next sync over the production queue mixin; ~0.22s cross-client move (Refs #324) · [`1af0d30c3284`](https://github.com/gmanldn/smoothcast/commit/1af0d30c32847c3ee1a60752b3f36885e9e2192c)

- ⬜ **21:47:05 · Maintenance** — chore(version): release 2.2.2 (Refs #324) · [`5564113db733`](https://github.com/gmanldn/smoothcast/commit/5564113db733f744cf07cb59dcc194290ec8f996)

- 🟥 **21:46:09 · Fix** — fix(web): phone header no longer overflows 320px when the version string is long; real-browser Up Next test (Refs #324) · [`eb05bd158d82`](https://github.com/gmanldn/smoothcast/commit/eb05bd158d82dcaa88e72f75c2aab0c33cd5ed00)

- 🟩 **21:26:05 · Feature** — feat(a11y): opt-in keyboard Tab-order walk in isolated AT-SPI smoke; finds Tab stuck on 'Open media' (Refs #449) · [`e529dd363bce`](https://github.com/gmanldn/smoothcast/commit/e529dd363bce727d04114ebbc1d49b999eb5ef21)

- 🟥 **21:11:38 · Fix** — fix: exact-match receiver model profiles; ambiguous models stay baseline (Refs #11) (Refs #207) · [`f38da4e6b491`](https://github.com/gmanldn/smoothcast/commit/f38da4e6b4918169361cf6b999314bb1a6d24c24)

- 🟩 **21:09:20 · Feature** — feat(a11y): AT-SPI walk asserts every showing control is named in the isolated smoke (Refs #449). Complexity baseline refreshed: +7 lines in gui\_test\_safety (private a11y bus guard), new selftest\_hold module; also catches up other agents' modules. · [`b591b67bb7d0`](https://github.com/gmanldn/smoothcast/commit/b591b67bb7d0574be00a9d45529bdecdb5fa76ce)

- ⬜ **21:08:26 · Maintenance** — chore(version): release 2.2.1 (Refs #588) · [`b8e1d8690b76`](https://github.com/gmanldn/smoothcast/commit/b8e1d8690b76c77985e4e79222a8d39e751fb39f)

- 🟩 **20:13:32 · Feature** — feat: record catalogue codes for cast failures and add no-traceback chaos checks (Refs #207) · [`acce19075536`](https://github.com/gmanldn/smoothcast/commit/acce19075536d78da138c75193aea7968968c91d)

- 🟩 **12:45:47 · Feature** — feat(perf): measure the 1,000-item queue edit cost (Refs #462) (Refs #685) · [`bec75e81e25d`](https://github.com/gmanldn/smoothcast/commit/bec75e81e25d761fb90e6ca8de1d342f5622d1d3)

- 🟥 **12:42:04 · Fix** — fix(perf): acknowledge the interaction instead of timing out on a paint (Refs #627) (Refs #684) · [`6f24ecbfd302`](https://github.com/gmanldn/smoothcast/commit/6f24ecbfd30200d6f27a6e8ce3e5387ae5f8e413)

- 🟩 **12:38:58 · Feature** — feat(perf): isolated-Xvfb interaction driver and runner mode (Refs #627) (Refs #683) · [`21a1323ab000`](https://github.com/gmanldn/smoothcast/commit/21a1323ab000f05ee7fc944d9e016ef1f68004bb)

- 🟦 **12:33:47 · Refactor** — refactor(perf): single-source the 1,000-item / 32-phone load definition (Refs #627) (Refs #682) · [`9ce921b05964`](https://github.com/gmanldn/smoothcast/commit/9ce921b05964648ff3a932006423cb0f44eb23cb)

- 🟩 **12:30:57 · Feature** — feat(perf): fail-closed isolation guard for interaction samples (Refs #627) (Refs #681) · [`6f82ab20e61c`](https://github.com/gmanldn/smoothcast/commit/6f82ab20e61cc367d33c53926ee56764d5c2a957)

- 🟩 **12:28:28 · Feature** — feat(perf): interaction probe core for the native budget (Refs #627) (Refs #680) · [`c142b367c5db`](https://github.com/gmanldn/smoothcast/commit/c142b367c5db052a15d9d947a2849b094757557f)

- 🟨 **12:26:21 · Documentation** — docs(reliability): record the native interaction-latency budget (#627) (Refs #679) · [`7eeccf89363a`](https://github.com/gmanldn/smoothcast/commit/7eeccf89363aec9fd3284d379a85aca03c59da00)

- 🟩 **12:13:48 · Feature** — feat(perf): native interaction-latency budget script and tests (Refs #627) (Refs #678) · [`8083b42c29e2`](https://github.com/gmanldn/smoothcast/commit/8083b42c29e2d1606b9f498c3bd1522ccaf046dc)

- 🟩 **12:10:55 · Feature** — feat(perf): schedule the jank watchdog from the app and gate the isolated smoke at 250 ms (Refs #442) (Refs #677) · [`1349a11ec9a3`](https://github.com/gmanldn/smoothcast/commit/1349a11ec9a3181ab8dbdb844ab4db179021925e)

- 🟩 **12:05:15 · Feature** — feat(perf): tested on/off policy for the jank watchdog (Refs #442) (Refs #676) · [`e63bf31c4b89`](https://github.com/gmanldn/smoothcast/commit/e63bf31c4b89e53bd962111348fd5f0e84e70948)

- 🟩 **11:52:29 · Feature** — feat(diagnostics): report jank stalls and p99 in the bundle (Refs #442) (Refs #675) · [`16bf31933a68`](https://github.com/gmanldn/smoothcast/commit/16bf31933a689c66763d4bd243a6dc43f9fe30a1)

- 🟩 **11:49:14 · Feature** — feat(perf): GTK-free main-loop jank detector core with fake-clock tests (Refs #442) (Refs #674) · [`1c6e605982ed`](https://github.com/gmanldn/smoothcast/commit/1c6e605982eda8c8ac6193a9e0c5f9b068e777fe)

- 🟪 **11:35:36 · Tests** — test(perf): prove the planner is GUI-free in a clean interpreter, not via suite-order sys.modules (Refs #673) · [`baf5c8efec17`](https://github.com/gmanldn/smoothcast/commit/baf5c8efec17e80e6718b7edf09e1ece4970fe42)

- 🟪 **11:12:15 · Tests** — test(perf): skip the planner wall-clock budget when the host is loaded (Refs #673) · [`9a7b51f4c6cd`](https://github.com/gmanldn/smoothcast/commit/9a7b51f4c6cd2e67d742d983168ddb7c5b51dfd0)

- 🟪 **11:00:39 · Tests** — test(perf): take the best of five planner samples so host contention cannot fail the 2 ms contract (Refs #673) · [`73c6ca897be0`](https://github.com/gmanldn/smoothcast/commit/73c6ca897be0153c1aa99c80078a15802fc71aff)

- 🟪 **10:49:15 · Tests** — test(ci): force the catt fallback in test\_core, isolate the link-tools probe, and take the best of two for the planner budget (Refs #673) · [`e2b3cbddef9f`](https://github.com/gmanldn/smoothcast/commit/e2b3cbddef9f9fd354e083f6ca1c2a78626c2636)

- 🟪 **10:35:17 · Tests** — test(env): skip or isolate the LAN- and dependency-sensitive tests (#658) (Refs #672) · [`a6a34fa4b07e`](https://github.com/gmanldn/smoothcast/commit/a6a34fa4b07efbbcd137781aea05858c6f89aff1)

- 🟥 **10:31:51 · Fix** — fix(mesh): plain guest wording for mesh acquisition failures (Refs #671) · [`91173fd8a107`](https://github.com/gmanldn/smoothcast/commit/91173fd8a10799cc575ac7bcc78ee56ae9fe83c5)

- 🟥 **10:29:08 · Fix** — fix(portal): plain guest wording for link-acquisition failures; refresh the baseline for the DOWNLOAD\_CANCELLED catalogue entry (Refs #670) · [`3bb8e74cdc83`](https://github.com/gmanldn/smoothcast/commit/3bb8e74cdc8317edcd4e2ddc1b9cc96854767427)

- 🟥 **10:25:58 · Fix** — fix(mesh): plain shared wording for search and download failures; refresh the complexity baseline for the grown guest\_messages catalogue (one justified 5-line growth) (Refs #668) · [`25a9a6c09829`](https://github.com/gmanldn/smoothcast/commit/25a9a6c09829c72f6e56ccd81488058676608d75)

- 🟥 **10:24:56 · Fix** — fix(mesh): plain shared wording for search and download failures (Refs #668) · [`72b79ef4b787`](https://github.com/gmanldn/smoothcast/commit/72b79ef4b78708ffe0d6cf3c0a332682c8de2824)

- 🟥 **10:21:58 · Fix** — fix(portal): plain shared wording for guest search failures (Refs #667) · [`d25758aa6ee9`](https://github.com/gmanldn/smoothcast/commit/d25758aa6ee977bd01ea2730a26a487ff72a9d06)

- 🟦 **10:19:05 · Refactor** — refactor(control): move app lifecycle helpers into a mixin; all INV-011 budgets green (Refs #634) · [`cd2a1484908f`](https://github.com/gmanldn/smoothcast/commit/cd2a1484908f062b0f0af5cd58c9e0ce180a386f)

- 🟪 **10:15:03 · Tests** — test(transport): give the preview fixture its time labels (Refs #666) · [`39ad94468a70`](https://github.com/gmanldn/smoothcast/commit/39ad94468a70f39c0dde931614976d5ea3c86173)

- 🟪 **10:12:31 · Tests** — test(setup): make the Windows check tests independent of the developer venv (Refs #665) · [`7c35c7c12756`](https://github.com/gmanldn/smoothcast/commit/7c35c7c1275671f89d1ae87973c4223a7d272c71)

- 🟪 **10:10:41 · Tests** — test(cast): assert the split confirmation messages and device-only info call (Refs #664) · [`65a71b1e7368`](https://github.com/gmanldn/smoothcast/commit/65a71b1e7368d22759b2f0e9e0028158b4e1248d)

- 🟪 **10:08:52 · Tests** — test(shortcuts): point at the actions mixin and stop the node slice at the wiring (Refs #663) · [`10971ce66f9b`](https://github.com/gmanldn/smoothcast/commit/10971ce66f9b579a631e27c2345a7ee0c836c33c)

- 🟪 **10:04:40 · Tests** — test(portal): assert the seek paint guard without pinning its brace form (Refs #662) · [`203ace3c60ca`](https://github.com/gmanldn/smoothcast/commit/203ace3c60cafed503f6d160d780662923397211)

- 🟪 **10:01:46 · Tests** — test(mesh): assert the current acquisition defaults and legacy retirement (Refs #661) · [`80fcc316d5f6`](https://github.com/gmanldn/smoothcast/commit/80fcc316d5f6d18a6f2518b19dd0127122714040)

- 🟪 **09:58:48 · Tests** — test(cast): force the catt fallback in the malformed-port scan test (Refs #660) · [`bd605ac6137f`](https://github.com/gmanldn/smoothcast/commit/bd605ac6137f0da96e16df1a18f2e03e02276994)

- 🟨 **09:56:10 · Documentation** — docs(api): document POST /api/search/magnets and regenerate the spec (Refs #659) · [`5c4e53f30a7a`](https://github.com/gmanldn/smoothcast/commit/5c4e53f30a7a4df89a2e43bb0242b6643f2ad601)

- 🟪 **09:43:18 · Tests** — test(ci): accept dotted version comments on immutable action pins (Refs #657) · [`df1e7cde9ff2`](https://github.com/gmanldn/smoothcast/commit/df1e7cde9ff2e176808fb69db551c8da5d7cacc5)

- 🟥 **09:42:06 · Fix** — fix(portal): plain wording for the YouTube-off guest message (Refs #656) · [`58e3994ea908`](https://github.com/gmanldn/smoothcast/commit/58e3994ea908f87be9a627baf9df57e9142507e7)

- 🟪 **09:37:51 · Tests** — test(discovery): give the identity test double \_device/device\_state and the #210 retention rule (Refs #655) · [`10183ddf6dbe`](https://github.com/gmanldn/smoothcast/commit/10183ddf6dbe7e88cf7d78080c2606dd0d6d9f6b)

- 🟪 **09:33:42 · Tests** — test(errors): ratchet raised codes against the taxonomy catalogue (Refs #654) · [`b69077d4e94f`](https://github.com/gmanldn/smoothcast/commit/b69077d4e94f82e24bf68d5f5ea7b2e184f45a9e)

- 🟨 **09:31:55 · Documentation** — docs(parity): web/desktop matrix with a drift ratchet (Refs #635) (Refs #653) · [`ef023996d000`](https://github.com/gmanldn/smoothcast/commit/ef023996d00041f632d84a16957353f1154bc07a)

- 🟪 **09:27:22 · Tests** — test(portal): encode the six-panel blade navigation semantics (Refs #652) · [`0d915afc8e11`](https://github.com/gmanldn/smoothcast/commit/0d915afc8e111db21f12b0a12822d58426c3b1fc)

- 🟪 **09:24:45 · Tests** — test(portal): target the current quick-cast and live-room elements (Refs #651) · [`a8d23fbda40d`](https://github.com/gmanldn/smoothcast/commit/a8d23fbda40d611f111f005b60cdd577a65e6125)

- 🟪 **09:22:11 · Tests** — test(portal): record the intentional now-playing display-name retention (Refs #650) · [`3f20c240106f`](https://github.com/gmanldn/smoothcast/commit/3f20c240106f664cbfb46200cfac98c17927ce84)

- ⬜ **09:19:34 · Maintenance** — chore(ci): refresh complexity baseline — 16 modules drifted past the 10% module tolerance during recent room/portal, diagnostics and GUI-split work; total src lines stay within tolerance (Refs #649) · [`6c6c6133d3b7`](https://github.com/gmanldn/smoothcast/commit/6c6c6133d3b7e9adb83959d1be66050456448867)

- 🟪 **09:17:53 · Tests** — test(release): cover prefix-colliding ticket PATCH ids in the guard (Refs #613) · [`a556208a60bd`](https://github.com/gmanldn/smoothcast/commit/a556208a60bda4670f9c63b864fd3c5ce34d641a)

- 🟪 **09:15:59 · Tests** — test(subtitle): assert the current search-folder expression (Refs #648) · [`2a205c0099c1`](https://github.com/gmanldn/smoothcast/commit/2a205c0099c1b2189b2afc4c35d5e214d530ada0)

- 🟪 **09:09:06 · Tests** — test(portal): make the find\_portal queue stub enqueue and drop the stale busy 409 (Refs #647) · [`b72081882ebf`](https://github.com/gmanldn/smoothcast/commit/b72081882ebf9dd9e4fde68ca80038f9ea863db7)

- 🟪 **09:07:04 · Tests** — test(portal): declare the library-search empty-state bindings (Refs #646) · [`eeb8855d8a56`](https://github.com/gmanldn/smoothcast/commit/eeb8855d8a56b1373df04dff28d2c093014618e1)

- 🟪 **09:05:19 · Tests** — test(portal): assert the Home-pane-first layout order (Refs #645) · [`297990f2ec0e`](https://github.com/gmanldn/smoothcast/commit/297990f2ec0e815da6f9cf58ea03c3e589c46838)

- 🟪 **09:03:43 · Tests** — test(portal): give the link-acquisition browser harness its page-scope globals (Refs #644) · [`c0ecfc942c59`](https://github.com/gmanldn/smoothcast/commit/c0ecfc942c59848e463c6bde96f9e3282505a397)

- 🟪 **09:01:19 · Tests** — test(portal): fix transfer-journey literal and link-clarity csrf binding (Refs #643) · [`ca105edadc0b`](https://github.com/gmanldn/smoothcast/commit/ca105edadc0be25abc7fdd2e8cf3af2a58fb01ab)

- 🟪 **08:59:17 · Tests** — test(portal): track the current Home-queue render key and row fields (Refs #642) · [`513d688527a3`](https://github.com/gmanldn/smoothcast/commit/513d688527a38b300a2c68b7dad4330cfca8c5f7)

- 🟪 **08:57:55 · Tests** — test(portal): give the activity test double its queue attribute (Refs #641) · [`bee93393a726`](https://github.com/gmanldn/smoothcast/commit/bee93393a726888672dbd52bf30f301a12166c89)

- 🟪 **08:55:53 · Tests** — test(portal): update stale assertions after the room restructure (Refs #640) · [`8a57971b6f9c`](https://github.com/gmanldn/smoothcast/commit/8a57971b6f9c46a4486f14f2a1721b6e2fa49058)

- 🟥 **08:47:44 · Fix** — fix(portal): use plain words in guest seek/volume/cast help (Refs #639) · [`dbf98b6760d4`](https://github.com/gmanldn/smoothcast/commit/dbf98b6760d489cf640c5acf53eae617282296f7)

- 🟪 **08:45:42 · Tests** — test(portal): assert the Home-pane cast entry structure (Refs #638) · [`6a8d577d98c8`](https://github.com/gmanldn/smoothcast/commit/6a8d577d98c83b8f3224218fb43a69683ae6dc5d)

- 🟪 **08:44:05 · Tests** — test(portal): check subresources in markup, not runtime script links (Refs #637) · [`2f0f5cf28130`](https://github.com/gmanldn/smoothcast/commit/2f0f5cf28130fd1c18754f90e5ccf0176d176d01)

- ⬜ **08:39:54 · Maintenance** — chore(release): initialise 2.2.0 qualification evidence entry (Refs #264) · [`032a6a9a89c4`](https://github.com/gmanldn/smoothcast/commit/032a6a9a89c451514a6bc40ecc5965a901b9ecdd)

- ⬜ **08:39:19 · Maintenance** — chore(version): release 2.2.0 · [`6ff731835773`](https://github.com/gmanldn/smoothcast/commit/6ff7318357734302f82db0885c7999bf67e1ab2a)

- 🟪 **08:38:43 · Tests** — test(visual): assert the current cast-sensitivity expression (Refs #636) · [`d605d3a7775a`](https://github.com/gmanldn/smoothcast/commit/d605d3a7775adbc53e3426f2b42be19ebba28592)

- ⬜ **08:34:08 · Maintenance** — chore(license): relicense SmoothCast under GPL-3.0-or-later · [`df816c5cc10b`](https://github.com/gmanldn/smoothcast/commit/df816c5cc10b61e9a25744f18ff3bfa03155b63d)

- 🟩 **08:32:57 · Feature** — feat(diagnostics): rate limit and serialise error-tail publishers (Refs #620) · [`d78eda1368a1`](https://github.com/gmanldn/smoothcast/commit/d78eda1368a13b5162e5ff66613e73c867712831)

- 🟥 **08:29:21 · Fix** — fix(web): default uploads to Up Next and drop the not-allowed cursor · [`336b41df1dac`](https://github.com/gmanldn/smoothcast/commit/336b41df1dac6d9b4016a4412ec3bc9a5949e210)

- 🟦 **08:27:29 · Refactor** — refactor(gui): drop stale imports after the mixin split (Refs #634) · [`799a71342fab`](https://github.com/gmanldn/smoothcast/commit/799a71342fab43ac783e3f09aca98187314672a8)

- 🟦 **08:26:34 · Refactor** — refactor(gui): split portal, lifecycle, session and favourites mixins under read budgets (Refs #634) · [`6595e2200f28`](https://github.com/gmanldn/smoothcast/commit/6595e2200f28a70fde43fa8e279d5bd3a1681e5b)

- ⬜ **08:23:14 · Maintenance** — chore: bump version to 2.1.8 · [`6f5c74531c9a`](https://github.com/gmanldn/smoothcast/commit/6f5c74531c9a784ab2056c21841875411e77e34e)

- ⬜ **08:23:14 · Maintenance** — chore(repo): consolidate pytest config into pyproject · [`8cc994e00af5`](https://github.com/gmanldn/smoothcast/commit/8cc994e00af5f10509caec2e9b7588c1511c45ce)

- 🟥 **08:15:37 · Fix** — fix(web): isolate command replay receipts by participant (Refs #635) · [`c433ea50d836`](https://github.com/gmanldn/smoothcast/commit/c433ea50d836bb484f18a1a8da1316c738ae2b51)

- 🟥 **08:14:30 · Fix** — fix: unify Home and shared queue web panes (Refs #324) · [`97c43b472356`](https://github.com/gmanldn/smoothcast/commit/97c43b4723567a746c44188150750c07a5ad7851)

- 🟥 **08:13:05 · Fix** — fix: deduplicate diagnostic snapshots and validate publish destinations (Refs #620) · [`ddaaacd86b2c`](https://github.com/gmanldn/smoothcast/commit/ddaaacd86b2c539b78a75139cc31c1b0b76e3b6d)

- 🟩 **08:11:53 · Feature** — feat(web): expose fenced fine seek and mute controls (Refs #635) · [`4199c43882c9`](https://github.com/gmanldn/smoothcast/commit/4199c43882c97215b4ec49e4eafaf57e65321105)

- 🟥 **08:11:01 · Fix** — fix: isolate upload shutdown cleanup failures (Refs #570) · [`7a4c32fcd27f`](https://github.com/gmanldn/smoothcast/commit/7a4c32fcd27fec61de211377115d3ee23d738cea)

- 🟥 **08:08:27 · Fix** — fix: preserve progressive cast ownership during upload finalisation (Refs #570) · [`bb64a101c79b`](https://github.com/gmanldn/smoothcast/commit/bb64a101c79be408c5be78f1c05b0d6c60a08cf9)

- 🟥 **07:59:27 · Fix** — fix(find): distinguish provider failures and check fallback torrents (Refs #633) · [`c6bd92252bc2`](https://github.com/gmanldn/smoothcast/commit/c6bd92252bc2d39ab88eddb32a4d72a753578cbc)

- 🟨 **07:57:31 · Documentation** — docs: trim connector-first guidance under the agent-context char caps (Refs #631) · [`5d6c91da94a0`](https://github.com/gmanldn/smoothcast/commit/5d6c91da94a05aa72b89ba19ca3d35f5c532010d)

- 🟨 **07:56:38 · Documentation** — docs: trim connector-first guidance back under the agent-context char caps (Refs #631) · [`3d3a22c1fbb8`](https://github.com/gmanldn/smoothcast/commit/3d3a22c1fbb8623096e129d84819d8d7ae15aecf)

- 🟪 **07:49:06 · Tests** — test: add cross-surface freshness gate with a 500 ms bound (Refs #629) · [`62827ce592e1`](https://github.com/gmanldn/smoothcast/commit/62827ce592e1af42b9ac1b0ccea83b8906353f0a)

- 🟩 **07:45:24 · Feature** — feat(find): discover openly licensed archive torrents with live opt-in search (Refs #633) · [`177375fed52d`](https://github.com/gmanldn/smoothcast/commit/177375fed52d7ec6d6a0663884ff698831d1576e)

- ⬜ **07:40:44 · Maintenance** — chore(version): release 2.1.7 (Refs #631) · [`c842b101605f`](https://github.com/gmanldn/smoothcast/commit/c842b101605f551a24a909e7b729dbe25c4d9cc0)

- 🟩 **07:39:54 · Feature** — feat: give Find a responsive search workspace and clearer discovery flows (Refs #414) · [`08a38ab1b7cd`](https://github.com/gmanldn/smoothcast/commit/08a38ab1b7cdc75d3913d6f95a9957c62c917794)

- 🟩 **07:38:16 · Feature** — feat: qualify guarded owner-directed connector PATCH releases (Refs #631) · [`0340aef3a5e0`](https://github.com/gmanldn/smoothcast/commit/0340aef3a5e04da80f3dcbd190d0789a260166f7)

- 🟩 **07:37:08 · Feature** — feat: unify file uploads and shared queue in one web pane (Refs #570) · [`6ca4d47a8d22`](https://github.com/gmanldn/smoothcast/commit/6ca4d47a8d22b8d76e8de9dc98defe82a9d98dc3)

- 🟥 **07:35:16 · Fix** — fix: reject malformed room addresses in printable join QR (Refs #621) · [`c2c947cb23f9`](https://github.com/gmanldn/smoothcast/commit/c2c947cb23f9242a36a2edbbf2de6a825b2cbaf8)

- 🟥 **07:34:02 · Fix** — fix: verify the actual MSI product upgrade identity (Refs #531) · [`338e61ac19c6`](https://github.com/gmanldn/smoothcast/commit/338e61ac19c6092e2e203a4c10a218630ec0d0d0)

- 🟥 **07:32:47 · Fix** — fix: require exact installed CLI version in MSI lifecycle smoke (Refs #535) · [`613f82896397`](https://github.com/gmanldn/smoothcast/commit/613f828963973bbe7e3e6a3d1613ae1bd2d186fe)

- 🟥 **07:31:39 · Fix** — fix: refuse redirected Windows media sidecar directories (Refs #530) · [`abb10d28417b`](https://github.com/gmanldn/smoothcast/commit/abb10d28417be01ba8c6d7e0fc335f71809e2ecc)

- 🟩 **07:28:16 · Feature** — feat(ui): show commit time in canonical build identity (Refs #632) · [`3baaf712304e`](https://github.com/gmanldn/smoothcast/commit/3baaf712304ebdc11715df14b3fde1dd27abbd36)

- 🟥 **07:23:36 · Fix** — fix: resolve canonical package metadata without importing runtime modules (Refs #535) · [`7d5fd22cdf65`](https://github.com/gmanldn/smoothcast/commit/7d5fd22cdf653a3d1b730c51a60de9d1b417f1b6)

- 🟥 **07:20:56 · Fix** — fix(upload): protect progressive sources during expiry and shutdown (Refs #570) · [`d594a5bf3fee`](https://github.com/gmanldn/smoothcast/commit/d594a5bf3feec726d40fa83bdb29088da4f25c01)

- ⬜ **07:16:34 · Maintenance** — chore(release): bump version to 2.1.6 · [`bdde27ee924c`](https://github.com/gmanldn/smoothcast/commit/bdde27ee924ca0c0ed77f51713a3e8ac3f7562ef)

- 🟥 **07:14:04 · Fix** — fix: delegate YouTube search to qualified mesh workers (Refs #587) · [`b3340d3d37e4`](https://github.com/gmanldn/smoothcast/commit/b3340d3d37e4088c10f817be38f07a1c8aabb44d)

- 🟩 **07:11:40 · Feature** — feat: unite Live and Mesh in an always-accessible network pane (Refs #386) · [`78a6f8b9e58d`](https://github.com/gmanldn/smoothcast/commit/78a6f8b9e58d855a67b2b50f85abbe50f9460a3b)

- 🟥 **07:04:46 · Fix** — fix: enable standard media capabilities on existing and new profiles (Refs #587) · [`a9934a4e6fa1`](https://github.com/gmanldn/smoothcast/commit/a9934a4e6fa1d2b4c608e920c2e0d00ece5a7f2e)

- 🟥 **07:03:38 · Fix** — fix(queue): search visible media titles and preserve accessible names (Refs #324) · [`eb6809c24307`](https://github.com/gmanldn/smoothcast/commit/eb6809c24307f0b4a9ea39b39f35e3c2fe9e494c)

- 🟥 **07:02:21 · Fix** — fix(upload): prevent zero-filled resume corruption (Refs #568) · [`0f90e6cab355`](https://github.com/gmanldn/smoothcast/commit/0f90e6cab355f44e707deea7658e099e87a916b4)

- 🟥 **06:56:29 · Fix** — fix(ui): declutter Home and bound queue preview updates (Refs #324) · [`9a5f1b85e6f9`](https://github.com/gmanldn/smoothcast/commit/9a5f1b85e6f941e43c321787959882622814f905)

- ⬜ **06:46:54 · Maintenance** — chore(release): SmoothCast 2.1.5; recover Windows package and CodeQL repair · [`17108678fce3`](https://github.com/gmanldn/smoothcast/commit/17108678fce3f2f6d1de24f8716727e2550f4e24)

- ⬜ **06:41:07 · Maintenance** — Merge remote-tracking branch 'origin/develop' · [`1896aea64fd6`](https://github.com/gmanldn/smoothcast/commit/1896aea64fd6c4fef7cc693952d68720d5c4b1db)

- 🟥 **06:37:38 · Fix** — fix(ui): preserve confirmed media titles through playback and queue edits (Refs #324) · [`9946d9665cd3`](https://github.com/gmanldn/smoothcast/commit/9946d9665cd345675e89b106c96ee8abd44c8e88)

- 🟨 **06:29:03 · Documentation** — docs: make offline hosted agents connector-first (Refs #631) · [`5c84ac3630c3`](https://github.com/gmanldn/smoothcast/commit/5c84ac3630c32fc5f9c24e1cfe159395c3cb2108)

- 🟥 **06:25:58 · Fix** — fix: prevent late preview callbacks overriding cast preparation (Refs #324) · [`e9c9e70300bd`](https://github.com/gmanldn/smoothcast/commit/e9c9e70300bd55b4af7e35327e4ffe158dd5ad6e)

- 🟥 **06:24:20 · Fix** — fix: keep live mesh contributions visible during playback commands (Refs #324) · [`ff853beeb4d5`](https://github.com/gmanldn/smoothcast/commit/ff853beeb4d5ff871cfa7b6ac9e05d5ef12dbd42)

- 🟥 **06:18:13 · Fix** — fix: preserve progressive cast source during pending or active playback (Refs #570) · [`f75a638c4bb3`](https://github.com/gmanldn/smoothcast/commit/f75a638c4bb318c96975101675253a35c9a3b908)

- 🟥 **06:13:41 · Fix** — fix: bound public diagnostic projection and omit untrusted frame fields (Refs #620) · [`997526980666`](https://github.com/gmanldn/smoothcast/commit/99752698066697501b1846ee3863830e61037555)

- 🟥 **05:57:16 · Fix** — fix(ui): restore combined Home and verified preview titles (Refs #324) · [`169096486a10`](https://github.com/gmanldn/smoothcast/commit/169096486a1079070ca790e8d0b53a3e74687461)

- 🟥 **05:53:19 · Fix** — fix: serialise concurrent failure notification rate limiting (Refs #207) · [`5a4737b49e44`](https://github.com/gmanldn/smoothcast/commit/5a4737b49e4428926bdf25d4449cfd092f50c4f8)

- 🟥 **05:52:05 · Fix** — fix(metrics): reject malformed and non-finite reliability records (Refs #206) · [`6c8069e033ef`](https://github.com/gmanldn/smoothcast/commit/6c8069e033efcc4f8c5cddb329efc212f023e9cb)

- 🟥 **05:50:53 · Fix** — fix(queue): avoid filesystem reads on metadata cache misses (Refs #324) · [`15690cbae0c3`](https://github.com/gmanldn/smoothcast/commit/15690cbae0c308d67b2d3feddff6efd5c6fb65eb)

- 🟥 **05:46:00 · Fix** — fix: fence unavailable and stale YouTube result actions (Refs #587) · [`d0db86f8d9c0`](https://github.com/gmanldn/smoothcast/commit/d0db86f8d9c0d5c89ffae436d532ddf26efd9c9f)

- 🟥 **05:44:52 · Fix** — fix: fence Cast status and commands after receiver disconnect (Refs #202) · [`553755335737`](https://github.com/gmanldn/smoothcast/commit/553755335737c03387bbe074a5c5af99286d6b84)

- 🟥 **05:41:19 · Fix** — fix(queue): accept local library contributions during cast preparation (Refs #325) · [`df1c95a4ddfb`](https://github.com/gmanldn/smoothcast/commit/df1c95a4ddfb0e0368f9d5d9bfcfd4d6f2ccaf71)

- 🟥 **05:36:14 · Fix** — fix: respect closed download disclosure during progress updates (Refs #587) · [`3ef635ec2a0a`](https://github.com/gmanldn/smoothcast/commit/3ef635ec2a0a386481960efe2699e933dfe8d396)

- 🟥 **05:31:03 · Fix** — fix: preserve catalogued errors without reviewed display copy (Refs #207) · [`3468ecda7764`](https://github.com/gmanldn/smoothcast/commit/3468ecda776485c80a50aed243f10cf9cafe695a)

- 🟥 **05:14:12 · Fix** — fix: make custom web accent links and controls meet AA contrast (Refs #447) · [`aa0b367199bf`](https://github.com/gmanldn/smoothcast/commit/aa0b367199bf1fe3550e0839c91864b9eef68082)

- 🟥 **05:10:01 · Fix** — fix: make cnode queue shortcut preserve explicit queue-only intent (Refs #570) · [`861354803969`](https://github.com/gmanldn/smoothcast/commit/861354803969af03831e525f52a53f6064cf28c4)

- 🟥 **05:05:43 · Fix** — fix(cast): reject ambiguous playback toggles without current receiver state (Refs #202) · [`76ab9452624f`](https://github.com/gmanldn/smoothcast/commit/76ab9452624fd3c86c5ae647f4da46434641f2d9)

- 🟥 **05:01:06 · Fix** — fix: allow fresh cnode cast confirmation after receiver changes (Refs #570) · [`f8d84f5b549a`](https://github.com/gmanldn/smoothcast/commit/f8d84f5b549a30eea7ce605ca7f6181b15e72946)

- 🟥 **04:54:04 · Fix** — fix: keep cnode queue and transfer updates live during controls (Refs #324) · [`ad33dd6ca6fc`](https://github.com/gmanldn/smoothcast/commit/ad33dd6ca6fcce1ec082bab4bf0a473f053f5556)

- 🟥 **04:46:08 · Fix** — fix(diagnostics): name the platform-appropriate link sandbox launcher and its Linux-only reference (Refs #588) · [`387c55a38d2e`](https://github.com/gmanldn/smoothcast/commit/387c55a38d2e8ad4529146b25a55ed9b5e032fda)

- ⬜ **04:43:59 · Maintenance** — chore(release): bump to 2.1.4 for link qualification slices (Refs #588) · [`886e6473d75b`](https://github.com/gmanldn/smoothcast/commit/886e6473d75bcd5a7dc62d98c116ba44d55f3dd4)

- 🟩 **04:43:30 · Feature** — feat(diagnostics): opt-in allowlisted error-tail preview and publish (Refs #620) · [`40d0dfa85a72`](https://github.com/gmanldn/smoothcast/commit/40d0dfa85a724dc14d328ed24a673c6f77f1d787)

- 🟩 **04:42:10 · Feature** — feat(link): verify engines run through the isolation launcher (Refs #588) · [`17c8d7cba047`](https://github.com/gmanldn/smoothcast/commit/17c8d7cba0473b31f2d0e524bc169e4bd9e23f54)

- 🟩 **04:40:01 · Feature** — feat(link): qualify isolation against IPv6 loopback and cloud metadata (Refs #588) · [`5d1d2da5c23d`](https://github.com/gmanldn/smoothcast/commit/5d1d2da5c23d40879730392535a7fd7d35f22504)

- ⬜ **04:38:33 · Maintenance** — build: register state\_parity in the wheel module list (Refs #628) · [`a271394e670d`](https://github.com/gmanldn/smoothcast/commit/a271394e670d1efbcf66c6274564506b0453bda4)

- 🟪 **04:37:22 · Tests** — test: ratchet desktop to web state parity with a declared field table (Refs #628) · [`6c8af8f62fcf`](https://github.com/gmanldn/smoothcast/commit/6c8af8f62fcf71eed0cb273336f58e5518a43881)

- ⬜ **04:17:39 · Maintenance** — chore(release): bump to 2.1.3 and make new versions in develop · [`78ab510dbea0`](https://github.com/gmanldn/smoothcast/commit/78ab510dbea046940a4746dd490ba543d8248f42)

- 🟥 **04:10:15 · Fix** — fix(web): retry transient guest upload completion instead of stalling (Refs #570) · [`66707ce18a5b`](https://github.com/gmanldn/smoothcast/commit/66707ce18a5b28be89f72dc0e020346c2de4e672)

- ⬜ **03:01:01 · Maintenance** — Merge branch 'develop' of https://github.com/gmanldn/smoothcast into develop · [`bbfa51023ed4`](https://github.com/gmanldn/smoothcast/commit/bbfa51023ed4c8acf16de96b31536bf86857ac2c)

- ⬜ **03:00:01 · Maintenance** — cmt · [`9c046c8e5ff6`](https://github.com/gmanldn/smoothcast/commit/9c046c8e5ff6380a09e40c5bd7f2e3cd2bf03fb2)

- 🟥 **02:57:32 · Fix** — fix(web): preserve guest download controls across progress snapshots (Refs #587) · [`05d5df5eb954`](https://github.com/gmanldn/smoothcast/commit/05d5df5eb954dc03a6ed0863a34f00ca9e9c6572)

- 🟥 **02:53:05 · Fix** — fix(web): keep scrubber preview timestamp stable during status updates (Refs #319) · [`70ddc7ae79c8`](https://github.com/gmanldn/smoothcast/commit/70ddc7ae79c8e02f067ff9a300f9b610ae84fdbf)

- 🟦 **02:36:51 · Performance** — perf(web): preserve incoming transfer rows and throttle sender progress paints (Refs #570) · [`6bcfb77a3ad4`](https://github.com/gmanldn/smoothcast/commit/6bcfb77a3ad4d191dbe5c7704a6f930894244652)

- 🟥 **02:24:55 · Fix** — fix(stream): restrict HLS worker identity to the private cache (Refs #625) · [`622e2b4eb5d2`](https://github.com/gmanldn/smoothcast/commit/622e2b4eb5d22d52f444f307f6e7e15aba32f682)

- 🟥 **02:19:57 · Fix** — fix(room): accept background queue additions while casting prepares (Refs #570) · [`c2450821686f`](https://github.com/gmanldn/smoothcast/commit/c2450821686f43c730c6f076af85524d006f0198)

- 🟥 **02:14:52 · Fix** — fix(room): reserve first overlapping cast upload and queue competing transfers (Refs #570) · [`9e2e1009d271`](https://github.com/gmanldn/smoothcast/commit/9e2e1009d27107f13155f06887d33ee4bd917dcd)

- 🟥 **00:56:20 · Fix** — fix(update): reject nonportable and colliding generation paths (Refs #580) · [`c4eca8c3f0cc`](https://github.com/gmanldn/smoothcast/commit/c4eca8c3f0cc9484c9653d1b24eeb1ad2a54b5c2)

- 🟩 **00:55:14 · Feature** — feat(room): publish concurrent incoming media and durable progress (Refs #570) · [`e1a4d42b88fd`](https://github.com/gmanldn/smoothcast/commit/e1a4d42b88fd2a67ae31845a3cc788f877216c3c)

- 🟥 **00:40:19 · Fix** — fix(setup): verify Windows native packages and preserve runtime prefix (Refs #350) · [`748260ad3099`](https://github.com/gmanldn/smoothcast/commit/748260ad3099f057f3dd84113ce206a6082810ef)

- 🟥 **00:27:13 · Fix** — fix(windows): provision native dependencies and verify installed Start menu entry (Refs #350) · [`c516f54736bd`](https://github.com/gmanldn/smoothcast/commit/c516f54736bd5800ad59fac191a36f2ae591d34a)

- 🟥 **00:22:41 · Fix** — fix(update): fence rollback and reject malformed activation journals (Refs #581) · [`78d6644d6948`](https://github.com/gmanldn/smoothcast/commit/78d6644d6948e0a46a01cdbee326c6902b4702fa)

- 🟩 **00:15:50 · Feature** — feat(mesh): always-on sc-core coordinator auto-joins the house on a private LAN (Refs #418) · [`ff4f54d06fc7`](https://github.com/gmanldn/smoothcast/commit/ff4f54d06fc7c46bcc426a6e98e2b2a690892972)

- 🟥 **00:08:27 · Fix** — fix(startup): repair missing registered venv and recover from spawn failures (Refs #350) · [`18411239ee60`](https://github.com/gmanldn/smoothcast/commit/18411239ee60fcc6b0ea229be6cc80cefb3ff66b)

- 🟥 **00:05:42 · Fix** — fix(room): retain original media names across queue recovery (Refs #324) · [`097a79f38b75`](https://github.com/gmanldn/smoothcast/commit/097a79f38b7558eaf588413db3ad79ce76b7cfa1)

---

## 2026-11-25 · UTC

- ⬜ **23:50:08 · Maintenance** — chore(version): PATCH for issue #626 · [`26b2bcfd344d`](https://github.com/gmanldn/smoothcast/commit/26b2bcfd344d6c45d13f8e8456ae822794ea3a6a)

- 🟥 **23:45:42 · Fix** — fix(setup): support ZIP relaunch and retire legacy installed wrapper (Refs #350) · [`46b589050d9a`](https://github.com/gmanldn/smoothcast/commit/46b589050d9abe36c54d44d47555779f55cc0d48)

- 🟥 **23:44:08 · Fix** — fix(startup): retain local recovery web on desktop crash and announce room URL (Refs #350) · [`f47e063f9c9e`](https://github.com/gmanldn/smoothcast/commit/f47e063f9c9ead379325cb059a4eca6fa389a5f0)

- 🟥 **23:32:37 · Fix** — fix(startup): preserve content keys and room PIN on a bounce (Refs #626) · [`2e2df1b4fcbc`](https://github.com/gmanldn/smoothcast/commit/2e2df1b4fcbc55c3ecdee8ddfc875b644be9d4ac)
