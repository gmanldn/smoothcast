---
name: "Improvement / regression"
about: "Propose or claim a concrete SmoothCast improvement, regression fix or receiver verification"
title: ""
labels: []
assignees: []
---

## Problem or outcome
What specifically needs to change? State observed and expected behaviour for a bug.

## Existing implementation and evidence
Relevant functions, saved state, logs, upstream PRs and dependencies. If this
extends an implemented feature, describe the **remaining** work, not a rewrite.

## Acceptance criteria
- [ ] Working behaviour with a measurable success criterion
- [ ] Failure, cancellation and ownership safety tested
- [ ] Portable automated regression tests pass
- [ ] Platform/real receiver verification where required (otherwise state why not)
- [ ] Documentation updated and PR linked

## Priority / effort
P0 (correctness/critical), P1 (high value), or P2 (refinement); S/M/L effort.

## Provenance / related work
Original request, research source, legacy SC-nnn ID if applicable, linked
issues and PRs. Check [the issue workflow](../../docs/ISSUES.md) and avoid
creating a parallel Markdown backlog.

## Notes
Testing must not repeatedly launch/focus the real GTK app. Use the isolated
Xvfb smoke runner only when explicitly authorised; hardware checks require a
controlled receiver. A merged implementation still needs an open issue if
qualification is unfinished.
