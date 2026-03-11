# Roadmap

## Current Status

- 2026-03-11 03:07 UTC: Fork PR branch `perf-kernel-optimization` is still parked at a guarded `1189` cycles on `python tests/submission_tests.py`, down from the starter `147734`.
- 2026-03-11 03:23 UTC: That `1189` branch is no longer considered a valid final answer because it is materially derived from upstream PR `#35` and no longer beats the live upstream best of `1149`.
- Current milestone: replace the disqualified PR35-derived branch with an original kernel that beats `1149`; the current leading direction is a depth-5 prefix bucket split rather than more shallow preload experiments.

## Milestone 1 — Baseline And Constraints

Success criteria:
- Project repo is registered and has upstream/origin configured.
- Starter benchmark is reproduced locally.
- Core machine constraints and kernel bottlenecks are documented.

Gate status:
- `done` — fork registered locally and remotes configured.
- `done` — starter benchmark reproduced at `147734` cycles.
- `in_progress` — durable design notes still being written.

## Milestone 2 — Viable Kernel Redesign

Success criteria:
- Chosen design has a defensible cycle budget under the simulator's slot limits.
- Kernel implementation passes correctness on `tests/submission_tests.py`.
- Cycle count improves materially over the starter baseline.

Gate status:
- `done` — selected and documented a vectorized scratch-resident path-state design.
- `done` — implemented the first redesign and validated correctness.
- `done` — current redesign improves the benchmark materially to `2425` cycles.
- `in_progress` — next redesign step still needed for the remaining node-access bottleneck.

## Milestone 3 — Competitive Result

Success criteria:
- Kernel beats the live upstream best (`1149` as of 2026-03-11 03:21 UTC) without changing `tests/`.
- Result is independently developed rather than materially copied from an upstream PR.
- Result is checkpointed in git and summarized in the task report.

Gate status:
- `in_progress` — current fork PR branch beats `1487` but fails the originality / best-upstream bar.
- `in_progress` — independent rewrite branch started from original commit `ca5bfd5`.
