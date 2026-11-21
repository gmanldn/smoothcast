# Shared-room model-based conformance (#452)

Fast CI runs `tests/test_room_state_machine.py` as part of the portable suite
(45 examples of 22 random steps). Production `PortalQueueMixin`, `PortalRoom`,
`CommandFence` and `CommandDispatcher` are exercised with fake GTK
adapters, not a mock of the queue algorithm. Rules include join/leave,
vote/unvote, add/remove/move/play, generation rollover, stale writes and
replayed/mutated request IDs. The independent reference queue and vote model
are asserted after every step.

For a deep run, use `SMOOTHCAST_MODEL_DEEP=1 python -m pytest -q
tests/test_room_state_machine.py`. The scheduled **Shared room model nightly**
workflow runs 750 examples × 80 steps on the repository's default branch
once promoted there, and supports manual `workflow_dispatch`. Hypothesis
prints a minimized action trace and a reproduction blob when a failure is
found. Rerun with its `--hypothesis-seed=<seed>` switch or its suggested
`@reproduce_failure` decorator. This is a fast in-memory conformance gate;
it does not replace real receiver or network-chaos testing.
