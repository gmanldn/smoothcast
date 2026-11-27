# Agent sandbox networking and connector-first workflow

**Owner policy (26 Nov 2026): hosted ChatGPT execution containers are offline
for native repository and dependency access.** Treat this as an environment
constraint, not a transient SmoothCast defect. The GitHub connector uses a
separate transport and can read and publish without container internet access.
Do not attempt repeated native Git/gh/curl commands, DNS checks, pip downloads,
proxy changes or network workarounds. Begin with the connector: resolve the
current develop SHA, read the relevant rules and issue, check complete lease
feeds, claim the scope, edit pinned text, run available offline checks and ship
using the guarded procedure below. If the connector is unavailable, report
that blocker; never invent a push or a test result.

## Native network-enabled environments only

On a new network-related failure on a machine expected to have internet access,
diagnose once before retrying. Skip this diagnostic entirely in known offline
ChatGPT containers.

From the repository root, run the bounded, read-only diagnostic (no GUI,
package installation or interactive credential prompts):

```sh
python3 scripts/agent_network.py
```

The agent's remote fetch/push operations now use a bounded noninteractive
transport call and emit a sanitised failure category, never raw remote stderr.
No additional network probe runs on the healthy path. A timeout during push
leaves the exact pending receipt for ancestry reconciliation; if a later
fetch also fails, exit 5 remains uncertain (exit 7 retains confirmed-push
handover recovery). Run the doctor once, then retry ship in the same worktree.

Exit 0 means native Git can read develop; exit 1 means it cannot be verified.
Direct DNS probes may fail even when proxy-backed Git succeeds. Offline tests:
`python3 -m unittest discover -s tests -p test_agent_network.py`.

- Interpret DNS, transport/TLS, authentication/authorisation and missing-ref
  failures separately. DNS success alone does not prove Git access;
  a connector read does not prove native Git works. Proxy-backed Git may work
  despite direct DNS failures. Inspect actual stderr; do not print credentials.
- If native Git is unavailable, connector-hosted agents may use the guarded
  guarded transport in `scripts/connector_ship.mjs` (#598). Progress is the
  default; agents may independently use the separate PATCH release lane
  below. No separate Contents API writes, force updates, main or issue closure.
- If connectivity failed during shipment, follow the
  [pending-push recovery rules](../COORDINATION.md#recovery-and-exit-statuses)
  in the original worktree. Never create duplicate commits or assume an
  unacknowledged push failed.
- Record the failed operation, actual error, whether connector access worked,
  affected SHA/worktree and remaining verification. Run offline checks if
  possible; label skipped network-dependent checks UNVERIFIED.
- Do not rewrite host DNS, disable TLS, hard-code GitHub IP addresses,
  change SmoothCast networking, or alter the user's virtual environment
  merely to work around an agent sandbox outage.


## Guarded connector shipment (default for hosted ChatGPT agents)

This is the normal hosted-container workflow, not a local gh CLI or DNS change.
Read `scripts/connector_ship.mjs` at the current develop SHA and load its
functions in a connector-capable runner (paste definitions without the ES
module export when imports are unavailable). Confirm a structured claim
covering all production paths. Build a manifest from immutable base files:

```js
const api = connectorAdapter(tools);
const p = {issue: 123, agent: "agent-unique", base: "<full develop SHA>",
  versionBlob: "<offline AST-validated version.py Git blob SHA>",
  changes: [{path: "src/example.py", old: "<base blob SHA or null for new>",
             content: "<complete reviewed new text>"}],
  message: "fix: bounded result", verification: "actual tests or not run",
  next: "remaining acceptance and native finish"};
const candidate = await prepare(api, p);
await ship(api, p, candidate);
// Prefer separate bounded runner calls when connector call budgets are tight.
// Preserve the same exact manifest and SHA across calls:
// const candidate = await createCandidate(api, p); // immutable objects only
// await verifyCandidate(api, p, candidate);       // read-only validation
// await recordPending(api, p, candidate);
// await publishPending(api, p, candidate);
// await recordHandover(api, p, candidate);
```

Before preparing, fetch the exact version.py and canonical AST guard
(`scripts/ci/check_version_history.py`) at the base. Verify Git blob hashes
offline and run its parse_version on the pinned version source. The candidate
must contain the exact next PATCH version blob (or the unchanged valid blob
when allocation is exhausted), and have one parent and precisely the reviewed
changed paths plus any generated version edit. A normal shipment allocates the next PATCH in the same candidate; the transition is
checked without executing application code. No per-ticket PATCH allocation,
deletion, mode change, binary edit or closure is supported here.

### Guarded PATCH release

No per-bump owner approval is required. Use `kind: "release"`, a live issue lease
covering `src/version.py`, and exactly one change to that file. Pin `versionBlob`
to the old blob and `releaseBlob` to the new blob; run the canonical Python AST
parser on both exact byte sequences offline. The message must be
`chore(version): release X.Y.Z` (without ticket PATCH attribution); `next` must
record outstanding qualification, not closure. The guard validates exactly one
PATCH increment and unchanged non-PATCH bytes before object creation and again
before publication. Use the identical staged receipt/CAS/ancestry workflow.
No mandatory per-ticket release, issue closure, main changes, tags or publishing.

The coordinator reads complete global and issue lease feeds, creates an
immutable Git tree/commit, verifies candidate contents and parent, records a
pending issue receipt, then moves only develop non-force and verifies
ancestry. Re-run ship with the same manifest/candidate after uncertain
acknowledgement or handover; never recreate a pending candidate. If another
agent advanced the base and the candidate is provably not reachable, record
an explicit abandoned receipt with SHA after verifying ancestry and obtain
fresh base blobs/version proof before preparing another. Release only your
own lease after confirmed handover. Run `node --test tests/test_connector_ship.mjs`
for guard regressions. Per-ticket PATCH allocation is retired (25 Nov 2026);
native finish closes verified tickets without a version bump.
