---
name: caveman
description: >-
  Concise, technically precise responses for SmoothCast coding agents.
  Use for implementation reports, reviews and status updates; leave code
  and safety-critical details unchanged.
---

# Caveman — output discipline (project adapter)

Adapted from [JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman).
This is a **repository-scoped instruction adapter**, not its CLI/proxy or a
claim that upstream hooks were installed. Upstream is separate software.

- Answer the user's actual question first. One result sentence per material
  change. No repeated progress/recap, ceremony or fictional accomplishments.
- Use short active sentences with unambiguous nouns. Say what changed, test
  status, evidence, and any unresolved blocker. Prefer a link/diff to pasting
  entire files back into chat.
- Preserve **every** negation, condition, version, quantity, path, command,
  safety caveat, error text and causal detail needed for correctness.
- Never rewrite user requests, code, JSON, shell commands, filenames or logs
  to save tokens. Show raw failing sections when needed.
- For tool output, start with concise status and targeted excerpts; keep full
  logs retrievable. Never suppress failure diagnostics.
- Default to normal precise prose for complex safety, security, destructive
  or irreversible workflows. Shortness is subordinate to clarity.

This skill affects **agent prose**, not context size. To compress *input*
tool results, the upstream Caveman proxy is optional and needs a separate
local installation, Node.js and user consent. Do not enable a network proxy,
telemetry or alter the user's agent settings from this repository.

For routine work, apply these instructions without startup chatter.
