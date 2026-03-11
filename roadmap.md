# Roadmap

## Current Status

- 2026-03-11 03:07 UTC: Fork PR branch `perf-kernel-optimization` is still parked at a guarded `1189` cycles on `python tests/submission_tests.py`, down from the starter `147734`.
- 2026-03-11 03:23 UTC: That `1189` branch is no longer considered a valid final answer because it is materially derived from upstream PR `#35` and no longer beats the live upstream best of `1149`.
- 2026-03-11 07:48 UTC: The current best independent rewrite branch is now `1815` cycles on the unmodified submission harness. The improvement came from a full 16-round wave scheduler rewrite: emit the entire round sequence as one dependency DAG, then schedule by group so a block can keep advancing while later blocks are still filling the machine. This is the first independent line here that materially reduced deep-round cost instead of only trimming shallow setup.
- 2026-03-11 08:08 UTC: A second independent gain came from using the idle `flow` engine more selectively rather than treating all `vselect`-based logic as dead. Rewriting only the depth-1 and depth-2 cached-node selection onto `flow.vselect`, while retuning the active wave width from `16` to `18`, lowered the independent branch from `1815` to `1689` cycles on the unmodified submission harness.
- 2026-03-11 08:58 UTC: A broader scheduler search found one more real overlap win on the independent branch. On the `valu` engine only, frontloading ops with `stage < 7` while draining higher-numbered groups first lowered the unmodified submission harness from `1689` to `1678` without changing scratch usage or touching the tests.
- 2026-03-11 08:58 UTC: The next obvious dependency-shortening family is now closed out as a negative result. Carried-address software-pipeline variants for later gathered rounds stayed correct but regressed to `1775`, `1723`, `1754`, and `1731`, so simple next-round address handoff is not the path below `1149`.
- 2026-03-11 19:45 UTC: The current best independent rewrite branch is now `1668` cycles on the unmodified submission harness. Two small but real gains landed in sequence: a leaner depth-3 cache that materializes the next depth-3 node vector from preloaded nodes `7..14` with one extra wave temp lowered the branch from `1678` to `1671`, and then removing the now-dead generic base vectors for cached depths `1..3` shaved another `3` cycles of setup/scratch overhead without touching the round logic.
- 2026-03-11 19:45 UTC: The follow-up probes around that `1668` branch were negative, which is still useful. A broader scheduler sweep on the new valu-bound shape found no sort order better than the existing one, widening the active wave back to `17` groups regressed to `1705`, and a shallow pre-update-bit routing rewrite regressed to `1698`. The remaining gap is therefore still structural rather than another obvious overlap tweak.
- 2026-03-11 20:15 UTC: The current best independent rewrite branch is now `1622` cycles on the unmodified submission harness. The first step was another small vector-ALU cleanup inside the existing design: write the root parity bit straight into `path` instead of copying it one cycle later, and keep the depth-3 cache builder's existing middle-bit mask alive through the select tree instead of recomputing it. Those two edits lowered the branch from `1668` to `1648` and reduced vector-ALU ops from `8229` to `8101`.
- 2026-03-11 20:15 UTC: A fresh local scheduler sweep on top of that `1648` kernel found that the older `stage < 7` valu-priority rule had become counterproductive after the new cleanup. Removing the cutoff and simply draining ready `valu` ops by stage while still preferring higher-numbered groups lowered the branch again from `1648` to `1622`. A re-run of the same 24-case value sweep still matched `reference_kernel2`.
- 2026-03-11 20:15 UTC: Two follow-up probes closed out more cheap ideas around the `1622` branch. A split-phase prototype that kept the shallow cached rounds separate from a wider deep gathered phase, reusing the same scratch window for a `20`-group deep wave, regressed badly to `2119` cycles and was reverted immediately. A broader engine-specific scheduler sweep also found no configuration below `1622`, so the next credible gain is back to a true deep-round node-feeding change rather than more overlap tuning.
- 2026-03-11 21:54 UTC: The current best independent rewrite branch is now `1558` cycles on the unmodified submission harness. This pass did not change the round body. It rewrote the vector-kernel setup path so vector constants and shallow-node preloads are emitted through packed initialization pipelines instead of near-serial one-slot bundles, and then folded two more standalone init bundles into the final broadcast-only setup cycles. The `rounds=0` kernel dropped from `120` to `56` cycles, scratch usage fell from `1485` to `1462`, and the full `16`-round harness improved from `1622` to `1558` while the same 24-case value sweep stayed clean.
- 2026-03-11 21:54 UTC: The lower scratch footprint was useful diagnostically but did not change the next strategic step. A `17`-group variant now fits within scratch at about `1502 / 1536`, but it still regressed to `1594`, so the remaining gap is still in deep node feeding rather than another wave-width retune.
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
- `done` — current redesign improves the benchmark materially to `1668` cycles.
- `in_progress` — next redesign step still needed for the remaining node-access bottleneck.
- `done` — 2026-03-11 07:48 UTC full-wave scheduling rewrite proved that global scheduling was still a real lever once the kernel was emitted as a single 16-round DAG; this cut the independent branch from `2285` to `1815` while staying correct.
- `done` — 2026-03-11 08:08 UTC a narrower `flow` offload proved worthwhile even though the earlier full shallow `vselect` tree lost badly. Moving only the existing depth-1/depth-2 cached-node selection onto `flow.vselect` cut the independent branch from `1815` to `1689` while leaving the deeper gathered rounds unchanged.
- `done` — 2026-03-11 08:58 UTC a wider scheduler search found a smaller but real follow-up overlap gain: frontloading earlier `valu` stages while draining higher-numbered groups first cut the independent branch from `1689` to `1678`.
- `done` — 2026-03-11 19:45 UTC a narrower depth-3 cache with one extra wave temp turned one deep gather round into a flow-side select tree and improved the independent branch from `1678` to `1671` while staying correct on the frozen harness and the earlier boundary/value sweep.
- `done` — 2026-03-11 19:45 UTC removing the dead generic base vectors for cached depths `1..3` shaved another `3` cycles (`1671 -> 1668`) and dropped scratch usage to `1485 / 1536`.
- `done` — 2026-03-11 20:15 UTC two more low-risk cleanups lowered the independent branch from `1668` to `1648`: root parity now writes directly into `path`, and the depth-3 cache builder reuses its existing middle-bit mask instead of recomputing it.
- `done` — 2026-03-11 20:15 UTC a fresh scheduler sweep on the `1648` kernel showed the previous `stage < 7` valu cutoff had flipped sign; removing it lowered the independent branch again from `1648` to `1622` while keeping the same 24-case value sweep clean.
- `in_progress` — the remaining work is still structural. After the packed-setup rewrite the best independent branch is `1558`, but the fused round body is still the same `1502`-cycle core and the newly legal `17`-group wave still regressed. The next material gain still has to attack deep node feeding itself rather than only changing ready-op order, wave width, or fixed setup cost.

## Milestone 3 — Competitive Result

Success criteria:
- Kernel beats the live upstream best (`1149` as of 2026-03-11 03:21 UTC) without changing `tests/`.
- Result is independently developed rather than materially copied from an upstream PR.
- Result is checkpointed in git and summarized in the task report.

Gate status:
- `in_progress` — current fork PR branch beats `1487` but fails the originality / best-upstream bar.
- `in_progress` — independent rewrite branch started from original commit `ca5bfd5`.
- `in_progress` — latest independent checkpoint is `1558` cycles on the submission harness, still correct on the generated zero-index submission shape and the earlier tail / overflow spot checks, but still above the `1149` target.
- `in_progress` — corrected 2026-03-11 06:13 UTC cycle accounting rules out the naïve 2-bit / 3-bit prefix-bucket path as a likely winner; even before permutation cost, the current 4-way table round is already near generic-round cost.
- `in_progress` — corrected 2026-03-11 08:58 UTC measurements also rule out the next simple software-pipeline variant: carrying precomputed next-round gathered addresses across the DAG regressed even in narrow depth-limited forms.
