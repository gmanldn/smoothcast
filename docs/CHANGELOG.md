# Changelog — publication contract

The root [CHANGELOG.md](../CHANGELOG.md) is the readable commit journal, not a substitute for Git history, issue handovers or release qualification.

- One entry per actual commit, newest UTC date first, with blank lines and daily separators.
- Use clear conventional commit subjects (feature, fix, performance, refactor, tests, CI, documentation or maintenance). Include issue references; avoid secrets and raw logs.
- Historical entries use exact Git committer UTC time and immutable SHA links. The current commit's SHA cannot appear inside its own hashed tree; a single provisional row uses the planned UTC time and subject. The next shipment resolves it to actual Git history.
- The initial backfill is 300 commits. Later entries accumulate, including merge and release commits. Older history is accessible in Git.
- Never manually edit or lease the generated changelog during implementation. Native ship generates a dedicated metadata commit after rebase and patch allocation; connector ship includes the generated file in the atomic candidate. On races, regenerate from the latest base, not a union merge.
- The anchor is the latest actual history SHA recorded, not a release number. Both transports check its ancestry and read all missing commits. A missing/incomplete history or malformed log is an explicit error, never permission to discard entries.
- Native recovery removes only an exact, unpublished generated changelog commit whose parent, metadata and contents can be reconstructed. Published commits and user edits are never reset.
- Connector manifests must pin `changelogDate` as UTC `YYYY-MM-DDTHH:MM:SSZ` and keep it identical across candidate, receipt and publication stages. The file is generated, not an explicit manifest change (except this one-time bootstrap).
- Changelog refresh commits are themselves recorded provisionally and resolved in the next refresh. No self-referential commit hash or fabricated verification.

Direct/manual commits outside the standard agent transports must be followed by a normal guarded shipment to catch up the actual history. Do not rewrite shared history to fix old commit messages.
