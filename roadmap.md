# Roadmap

## Current Status

- 2026-03-11 01:34 UTC: Current best verified result is `2425` cycles on `python tests/submission_tests.py`, down from the starter `147734`.
- Current milestone: reduce node-feeding cost further; the remaining gap to `1487` appears structural rather than a simple scheduling issue.

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
- Kernel beats `1487` cycles without changing `tests/`.
- Result is checkpointed in git and summarized in the task report.

Gate status:
- `pending`
