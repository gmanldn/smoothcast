# Caveman + Ponytail: token-efficient SmoothCast agents

This repository now includes lightweight, **local instruction adapters**:
- [Caveman](../.kilo/skills/caveman/SKILL.md): concise, exact answers and
  targeted evidence rather than repeated transcripts.
- [Ponytail](../.kilo/skills/ponytail/SKILL.md): the smallest *complete* code
  change, using existing helpers with focused regressions.

The root [AGENTS.md](../AGENTS.md) applies both principles to agents that
read repository instructions. Kilo can additionally discover the named
`.kilo/skills/` entries. These adapters are **not** the official upstream
Caveman proxy or Ponytail hook plugin, and they do not alter your local
global agent configurations.

## Measured repository instruction size

At integration, the original `AGENTS.md` was **30,316 characters
(195 lines)**. It was copied **without removing a line** to
[AGENT_REFERENCE.md](AGENT_REFERENCE.md), then replaced with a **3,625
character (71-line)** front door: **88.0% fewer characters read if an
agent loads only the root file**. This is a byte/character comparison,
**not a measured model-token count** and not an end-to-end API cost saving.

Retrieve only the task-relevant reference sections; reading the archive
every session forfeits the benefit. New architecture and process rules belong
in compact root instructions or focused docs, not a growing global prompt.

## Measured GUI module sizes

The GTK window was one **200,282-byte (4,566-line)** `cast_control.py`, so a
task that touched one concern still had to grep and read a whole-file region.
It is now split by concern, with `MainWindow` inheriting the mixins:

| Module | Lines | Bytes |
| --- | --- | --- |
| `cast_control.py` (`MainWindow.__init__`, `CastControlApp`, `main`) | 414 | 17,294 |
| `cast_widgets.py` (shared constants, config, `SeekBar`, `LevelMeter`, `PreviewScreen`) | 698 | 25,798 |
| `cast_ui.py` (`UiMixin`) | 1,161 | 54,438 |
| `cast_queue.py` (`QueueMixin`) | 729 | 29,972 |
| `cast_session.py` (`SessionMixin`) | 1,002 | 41,623 |
| `cast_av.py` (`AvMixin`) | 562 | 22,256 |
| `cast_lifecycle.py` (`LifecycleMixin`) | 302 | 11,285 |

The largest file an agent can now be forced to read is **54 KB instead of
200 KB**, and most tickets read one 20-30 KB module. This is a
byte/character comparison, **not** a measured model-token count.
`tests/test_agent_token_efficiency.py` fails if any GUI module regrows past
its budget, and `tests/gui_source.py` lets source-asserting tests keep working
without hard-coding the module layout.

## Workflow for coding agents

1. Identify the task and affected module. Search relevant symbols/callers;
   avoid entire repo/tree dumps unless the task requires them.
2. Choose Ponytail's smallest complete solution. Preserve every behaviour,
   security check, compatibility contract and required regression test.
3. Run `python3 -m pytest -q tests/test_affected.py`; expand to the full
   headless suite before calling a change verified. Never start the GUI,
   activate GTK, probe a real TV or steal desktop focus.
4. Use Caveman for status and review prose: result, evidence, risk, next
   needed action. Show exact errors, commands and changed code intact.
5. For noisy logs, keep an unabridged file on disk and summarise failures
   plus a pointer. Avoid lossily compressing stack traces, tests, patch
   contexts, nonces or code the agent must edit.
6. Count **provider-billed input/output/cached tokens per completed task**,
   and compare task success and retries in an A/B trial before claiming
   financial savings. Smaller text alone may increase turns or total cost.

## Optional upstream integrations (not enabled by this repo)

The full official tools provide more than these instruction adapters:

- **Caveman** (JuliusBrussee): response skill and optional input-context
  proxy. Kilo's *optional* skill installer:
  `npx skills add JuliusBrussee/caveman -a kilo`.
  The optional proxy requires Node.js 22.13+ and can route supported
  agents via `caveman kilo`; inspect its privacy/telemetry and credential
  routing first. Never install it as a SmoothCast runtime dependency.
- **Ponytail** (DietrichGebert): interactive modes, review and audit
  hooks where the host supports them. See official installation directions
  for the chosen coding agent. The repository adapter offers the code
  discipline without hooks or Node.js.

Official sources:
- https://github.com/JuliusBrussee/caveman
- https://docs.caveman.so/caveman/installation
- https://github.com/DietrichGebert/ponytail

Installing/activating user-level plugins, proxying API calls or turning on
telemetry changes the user's development environment. None is done by this
commit. Python remains SmoothCast's initial setup dependency.

## Safety

Project instructions never override explicit task requirements. Never
drop source fidelity, errors, tests, diagnostics, security, accessibility,
state reconciliation, casting ownership or setup reliability just to reduce
token usage. Keep full original history available in the reference file.
