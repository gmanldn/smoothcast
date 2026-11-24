# Agent sandbox networking preflight

On a network-related fetch, push or dependency failure, diagnose the agent
environment once before retrying. Some hosted ChatGPT execution sandboxes
have returned temporary DNS resolution failures for GitHub and PyPI
(for example with resolver `168.63.129.16`); this is not evidence of a
SmoothCast runtime defect. The GitHub connector may use independent
networking and remain available.

From the repository root, run the bounded, read-only diagnostic (no GUI,
package installation or interactive credential prompts):

```sh
python3 scripts/agent_network.py
```

Exit 0 means native Git can read develop; exit 1 means it cannot be verified.
Direct DNS probes may fail even when proxy-backed Git succeeds. Offline tests:
`python3 -m unittest discover -s tests -p test_agent_network.py`.

- Interpret DNS, transport/TLS, authentication/authorisation and missing-ref
  failures separately. DNS success alone does not prove Git access;
  a connector read does not prove native Git works. Proxy-backed Git may work
  despite direct DNS failures. Inspect actual stderr; do not print credentials.
- If native Git is unavailable, use the connected GitHub API for read-only
  triage, current develop source and issue/handover inspection. Do not keep
  repeating network-dependent commands or treat every task as blocked.
  Connector access does not waive claim, version-history, ship or closure
  safeguards; do not bypass them with unguarded writes. If the normal
  shipment cannot be verified, preserve the work and hand over to a
  network-enabled agent or the owner.
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
