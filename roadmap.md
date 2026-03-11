# Roadmap

## Current Status

- 2026-03-11 03:07 UTC: Fork PR branch `perf-kernel-optimization` is still parked at a guarded `1189` cycles on `python tests/submission_tests.py`, down from the starter `147734`.
- 2026-03-11 03:23 UTC: That `1189` branch is no longer considered a valid final answer because it is materially derived from upstream PR `#35` and no longer beats the live upstream best of `1149`.
- 2026-03-11 07:48 UTC: The current best independent rewrite branch is now `1815` cycles on the unmodified submission harness. The improvement came from a full 16-round wave scheduler rewrite: emit the entire round sequence as one dependency DAG, then schedule by group so a block can keep advancing while later blocks are still filling the machine. This is the first independent line here that materially reduced deep-round cost instead of only trimming shallow setup.
- 2026-03-11 08:08 UTC: A second independent gain came from using the idle `flow` engine more selectively rather than treating all `vselect`-based logic as dead. Rewriting only the depth-1 and depth-2 cached-node selection onto `flow.vselect`, while retuning the active wave width from `16` to `18`, lowered the independent branch from `1815` to `1689` cycles on the unmodified submission harness.
- 2026-03-11 08:58 UTC: A broader scheduler search found one more real overlap win on the independent branch. On the `valu` engine only, frontloading ops with `stage < 7` while draining higher-numbered groups first lowered the unmodified submission harness from `1689` to `1678` without changing scratch usage or touching the tests.
- 2026-03-11 08:58 UTC: The next obvious dependency-shortening family is now closed out as a negative result. Carried-address software-pipeline variants for later gathered rounds stayed correct but regressed to `1775`, `1723`, `1754`, and `1731`, so simple next-round address handoff is not the path below `1149`.
- Current milestone: replace the disqualified PR35-derived branch with an original kernel that beats `1149`; the remaining gap is now smaller, but the latest probes still say cheap branch-bit shortcuts, within-block dedup, and simple carried-address overlap are not enough, so the next attempt still has to reduce true deep-round node feeding rather than only polish scheduling further.

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
- `done` — current redesign improves the benchmark materially to `1678` cycles.
- `in_progress` — next redesign step still needed for the remaining node-access bottleneck.
- `done` — 2026-03-11 07:48 UTC full-wave scheduling rewrite proved that global scheduling was still a real lever once the kernel was emitted as a single 16-round DAG; this cut the independent branch from `2285` to `1815` while staying correct.
- `done` — 2026-03-11 08:08 UTC a narrower `flow` offload proved worthwhile even though the earlier full shallow `vselect` tree lost badly. Moving only the existing depth-1/depth-2 cached-node selection onto `flow.vselect` cut the independent branch from `1815` to `1689` while leaving the deeper gathered rounds unchanged.
- `done` — 2026-03-11 08:58 UTC a wider scheduler search found a smaller but real follow-up overlap gain: frontloading earlier `valu` stages while draining higher-numbered groups first cut the independent branch from `1689` to `1678`.
- `in_progress` — the remaining work is still structural. The latest pass squeezed another `11` cycles out of overlap, but the next material gain still has to attack deep node feeding itself rather than only changing ready-op order.

## Milestone 3 — Competitive Result

Success criteria:
- Kernel beats the live upstream best (`1149` as of 2026-03-11 03:21 UTC) without changing `tests/`.
- Result is independently developed rather than materially copied from an upstream PR.
- Result is checkpointed in git and summarized in the task report.

Gate status:
- `in_progress` — current fork PR branch beats `1487` but fails the originality / best-upstream bar.
- `in_progress` — independent rewrite branch started from original commit `ca5bfd5`.
- `in_progress` — latest independent checkpoint is `1678` cycles on the submission harness, still correct on the generated zero-index submission shape and the earlier tail / overflow spot checks, but still above the `1149` target.
- `in_progress` — corrected 2026-03-11 06:13 UTC cycle accounting rules out the naïve 2-bit / 3-bit prefix-bucket path as a likely winner; even before permutation cost, the current 4-way table round is already near generic-round cost.
- `in_progress` — corrected 2026-03-11 08:58 UTC measurements also rule out the next simple software-pipeline variant: carrying precomputed next-round gathered addresses across the DAG regressed even in narrow depth-limited forms.
