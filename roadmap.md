# Roadmap

## Current Status

- 2026-03-11 02:32 UTC: Current best verified result is `1149` cycles on `python tests/submission_tests.py`, down from the starter `147734`.
- 2026-03-11 02:48 UTC: the branch now keeps the `1149` submission-harness result while falling back to a safe scalar kernel for unsupported batch shapes (for example non-`8`-multiple tails or larger divisible batches that would overflow scratch).
- 2026-03-11 02:48 UTC: benchmarked nearby public/local branches; none beat `1149` (`pr29` was the closest at `1158`).
- Current milestone: the target is beaten, hardened for general repo usage, and still locally frontier-best. Remaining loop time can go to deeper simplification or an even lower cycle search.

## Milestone 1 — Baseline And Constraints

Success criteria:
- Project repo is registered and has upstream/origin configured.
- Starter benchmark is reproduced locally.
- Core machine constraints and kernel bottlenecks are documented.

Gate status:
- `done` — fork registered locally and remotes configured.
- `done` — starter benchmark reproduced at `147734` cycles.
- `done` — durable design notes capture both the failed `2425`-cycle path and the winning `1149`-cycle design.

## Milestone 2 — Viable Kernel Redesign

Success criteria:
- Chosen design has a defensible cycle budget under the simulator's slot limits.
- Kernel implementation passes correctness on `tests/submission_tests.py`.
- Cycle count improves materially over the starter baseline.

Gate status:
- `done` — selected and documented a vectorized scratch-resident baseline and then the stronger shallow-specialized design.
- `done` — implemented the redesign and validated correctness.
- `done` — the benchmark is improved materially, from `147734` cycles to `1149`.
- `done` — the remaining node-access bottleneck is resolved well enough to clear the target.

## Milestone 3 — Competitive Result

Success criteria:
- Kernel beats `1487` cycles without changing `tests/`.
- Result is checkpointed in git and summarized in the task report.

Gate status:
- `done` — the kernel beats `1487` at `1149` cycles without touching `tests/`.
- `done` — the result is checkpointed in git and summarized in the task report.
- `done` — the delivered branch preserves correctness for unsupported batch shapes via a fallback path without perturbing the target benchmark.
