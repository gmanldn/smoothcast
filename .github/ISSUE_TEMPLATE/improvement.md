---
name: "Bug or improvement"
about: "Propose or claim one concrete SmoothCast fix, feature or receiver verification"
title: ""
labels: []
assignees: []
---

## Outcome

What must change, for which user/source/receiver/platform? For a bug, state
observed vs expected behaviour and a deterministic reproducer.

## Existing implementation and evidence

Relevant functions, callers, saved state, logs, upstream PRs and dependencies.
If this extends an implemented feature, describe the **remaining** work, not a
rewrite.

## Affected area

Likely files/modules, callers and tests; related issues or PRs.

## Acceptance criteria

- [ ] Working behaviour with a measurable success criterion
- [ ] Failure, cancellation and ownership safety tested
- [ ] Portable automated regression tests pass
- [ ] Platform/real-receiver verification where required (otherwise state why not)
- [ ] Documentation updated; commit(s) on `develop` reference this issue

## Work unit

- Normalized units: 1
- Why this is one coherent, independently reviewable slice:
- Split trigger (new issue instead of expanding this one):

## Verification class

- [ ] Fast lane (patch) or full portable CI (MINOR/MAJOR)
- [ ] Isolated GTK/Xvfb smoke (explicit authorisation only)
- [ ] Physical receiver or OS validation (state device/version)
- [ ] Not applicable; reason:

## Priority and effort

P0 (correctness/critical), P1 (high value) or P2 (refinement); S/M/L effort.

## Provenance and links

Original request, research source, legacy `SC-nnn` if applicable, linked
issues and PRs. Check [the issue workflow](https://github.com/gmanldn/smoothcast/blob/main/docs/ISSUES.md)
and do not create a parallel Markdown backlog.

## Agent notes

Start with `python3 scripts/ticket_digest.py --next` or `--show <number>`; read
one issue body at a time. Claim by assigning yourself and posting one short
comment. Routine tests must not launch or focus the real GTK app. Hardware
checks require a controlled receiver. A merged implementation still needs an
open issue if qualification is unfinished.
