# SmoothCast changelog

A chronological record of changes shipped to `develop`, newest first. Dates and times are UTC. Entries describe the actual commit subject; they do not imply release qualification or ticket closure.

🟩 Feature · 🟥 Fix · 🟦 Performance/refactor · 🟪 Tests/CI · 🟨 Documentation · ⬜ Maintenance/integration

Initial history: 300 recent commits plus intervening changes before this file was introduced (25–27 November 2026). Older history remains in [GitHub commits](https://github.com/gmanldn/smoothcast/commits/develop/). New entries accumulate; this is not a rolling window.

A provisional entry describes the current publication before its own SHA exists; the next refresh replaces it with the actual committed timestamp and link.

<!-- sc-changelog-through: 95637c71f28917598a2037a611c936de91d57759 -->

## 2026-11-27 · UTC

- ⬜ **15:46:44 · Maintenance** — chore(changelog): record shipment \[sc-auto-changelog\] <!-- sc-changelog-pending -->

- ⬜ **15:46:44 · Maintenance** — chore(version): advance shipment PATCH \[sc-auto-patch\] · [`95637c71f289`](https://github.com/gmanldn/smoothcast/commit/95637c71f28917598a2037a611c936de91d57759)

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
