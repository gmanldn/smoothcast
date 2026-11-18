---
name: ponytail
description: >-
  Minimal complete Python coding changes: reuse-first, YAGNI, no speculative
  abstractions; retain correctness, safety, compatibility and focused tests.
---

# Ponytail — smallest complete change (project adapter)

Adapted from [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail).
This is a **repository-scoped instruction adapter**, not the upstream
Ponytail plugin, hooks or live token-accounting dashboard.

1. **Understand:** inspect the affected code, every caller and any data/TV
   ownership edge cases before changing it. Define the required outcome.
2. **Choose the smallest complete solution:** first reuse project behaviour,
   then Python standard library, then existing dependencies. Add a helper or
   dependency only when it clearly simplifies the *whole* patch.
3. **Remove needless work:** no unrequested toggles, factory classes, fallback
   layers, config knobs, speculative abstractions or duplicated functionality.
   Keep existing conventions and public interfaces.
4. **Finish the contract:** update all affected callers, configuration,
   docs and tests. Preserve error handling, trust-boundary validation,
   privacy, accessibility, multimedia correctness and TV ownership.
5. **Verify intelligently:** for a new condition, parser, side effect,
   concurrency or security-sensitive path, add a focused regression test.
   Run the relevant headless suite; do not spawn the GUI to test.
6. **Report:** state the change, actual tests and unverified behaviour.
   Don't claim a measured token reduction based solely on lines removed.

Default to Ponytail **full** principles. `lite` prioritises explicit user
scope; `ultra` challenges unnecessary features, but never silently drops
explicit requirements. The upstream plugin provides interactive modes if
installed separately. This local skill does not implement slash commands.

Never trade away reliability, checks or user work for shorter code.
