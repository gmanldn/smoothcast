# Optional historical exact-head CI diagnostic

**Current policy (develop-only):** Verify SmoothCast is a **manual**
`workflow_dispatch` workflow. It does not run on each push and never
promotes to `main`. Agents may push code without tests, but MUST report
the result as **unverified** until independent evidence exists. The only
active development branch is `develop`, and only the owner may merge to
`main`.

`scripts/ci/head_verdict.py` was originally designed for a push-triggered
Verify run and automatic main promotion. **Do not use its exit status as a
routine shipping or ticket-closing prerequisite** under the current policy;
it can return unknown when no exact-head Verify run was requested. Its
historical release fields are not a statement that promotion is enabled.

For manual verification, visit
[Verify SmoothCast](https://github.com/gmanldn/smoothcast/actions/workflows/verify.yml),
run the workflow explicitly on the desired `develop` commit, inspect the
job results, and record the actual tested SHA in the GitHub issue. Earlier
successful checks do not certify a newer concurrent agent commit. Security,
runtime, packaging and receiver qualification remain separate evidence
requirements where relevant.

A missing CI run is **not a passing check**. A manually run check is not
permission to publish or merge `main`.
