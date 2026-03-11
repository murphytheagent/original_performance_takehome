# Kernel Design Notes

## Baseline

- 2026-03-11 00:49 UTC: `python tests/submission_tests.py` reported `147734` cycles for the starter kernel.
- 2026-03-11 01:34 UTC: current best verified result is `2425` cycles.
- 2026-03-11 03:21 UTC: live upstream re-audit confirmed the best public result is still `1149` cycles (PR `#35`), with `1158` (PR `#29`) the next-best measured candidate.
- 2026-03-11 03:23 UTC: the fork PR branch at `1189` cycles is no longer treated as a valid final answer because it is materially PR `#35` plus local hardening.
- The starter implementation is scalar and emits one slot per instruction bundle, so it leaves both VLIW packing and SIMD unused.

## Hard constraints from the simulator

- One core only (`N_CORES = 1` in both the live and frozen simulators).
- Per cycle slot limits: `alu=12`, `valu=6`, `load=2`, `store=2`, `flow=1`.
- `vload` and `vstore` can move `VLEN = 8` contiguous words in one slot.
- There is no true gather load, only scalar `load` and `load_offset`.
- Scratch space is `1536` words, large enough to stage the batch and temporary buffers.

## Observations

- Beating `1487` cycles over `16 * 256 = 4096` element-round updates requires an architectural change, not a constant-factor cleanup.
- Direct per-element forest gathers are too expensive if repeated every round.
- All inputs start at index `0`, and before tree wraparound the number of reachable nodes at round `r` is bounded by the tree depth, so many inputs share the same node value in early rounds.
- The first successful redesign keeps the batch in scratch, uses path-plus-global-depth instead of full heap indices, and skips index writeback entirely because the submission harness only checks final values.
- The first successful redesign also collapses hash stages `0`, `2`, and `4` to `multiply_add`, which is responsible for a large share of the current speedup.
- Prefix-round measurements of the current kernel show:
  - fixed setup/teardown overhead: about `117` cycles
  - root rounds (no gather): about `70` cycles
  - rounds with per-element node gathers: about `154` cycles each
- This means generic gather rounds are already fairly close to their access-pattern floor, so the next big win almost certainly has to reduce or amortize node feeding rather than only improving arithmetic scheduling.

## Candidate directions under evaluation

- Depth-specialized shallow rounds that avoid generic lane gathers where the active node set is tiny.
  - 2026-03-11 03:47 UTC: a fresh `vselect`-tree rewrite for depths `0` through `3` stayed correct but regressed to `2725` cycles because it saturates the single `flow` slot.
  - 2026-03-11 04:08 UTC: replacing those `vselect` trees with ALU mask-blends also stayed correct but still regressed to `2673` cycles once scratch pressure forced smaller compile-time waves.
  - 2026-03-11 05:28 UTC: using reclaimed input memory as a runtime shallow-cache workspace improved only to `2411` cycles. The depth-2 cached round became much cheaper, but the depth-0/depth-1 cache-build rounds mostly paid the savings back. This rules out another shallow-only variant.
- Coarse regrouping that is amortized across several later rounds, rather than bucketizing on every round.
  - Current preferred plan is a depth-5 prefix split: shared top-tree work for rounds `0` through `4`, one radix scatter into 32 buckets, cheap bucket-local rounds while each bucket fans out only `1/2/4/8`, then honest gathers only for the last deep levels before reset.
- Better overlap on the remaining gathered rounds, but only as a secondary optimization because it cannot bridge the whole gap to `1149` by itself.
  - 2026-03-11 05:00 UTC: explicit sweeps over wave width (`16..23`) and more aggressive critical-path scheduling on the original `2425` branch did not move the number at all. The gather line is load-bound, not scheduler-bound.
  - 2026-03-11 06:13 UTC: a corrected bucket-split viability study ruled out the most tempting regrouping variants before full implementation. Real prefix statistics on 400 random seeds were:
    - split after 2 branch bits: mean max bucket `72.6`, mean mixed boundary blocks `2.6`, mean homogeneous full blocks `29.4 / 32`
    - split after 3 branch bits: mean max bucket `40.3`, mean mixed boundary blocks `6.2`, mean homogeneous full blocks `25.9 / 32`
    - split after 4 or 5 bits: too fragmented to justify the reshuffle cost
  - 2026-03-11 06:13 UTC: corrected round-cost probes on the current kernel show why even the 2-bit/3-bit bucket splits are weak. With setup/store isolated by a `rounds=0` run, the current `256`-wide kernel costs about `70` cycles for depth `0`, `118` for the 2-way table round, `160` for the current 4-way table round, and `154..160` for generic gathered rounds. That means a 2-bit split only has one clearly cheaper replacement round (`118` versus `160`), while the current 4-way table is already basically as expensive as a gather round.
  - 2026-03-11 06:13 UTC: a one-shot proxy harness on smaller batch widths confirmed that per-bucket sequential execution is not viable. On the same height-10 tree, a `64`-wide kernel costs `91` cycles with `0` rounds, then `109/140/181/226/271/316` cycles for `1..6` rounds. Four such bucket-local passes are already slower than the current unified `256`-wide kernel before paying any bucket scatter / final restore cost.
- Block-local unique-address dedup on the earliest gathered rounds.
  - 2026-03-11 06:13 UTC: an additional Athena review suggested a representative-lane dedup only for the first gathered rounds (especially depth `3`), trading repeated per-lane loads for scalar ALU copies. The useful conclusion is the scale, not the exact mechanism: even the optimistic upside looks more like `~100` cycles than `~1000`, so this family may still be worth a small pilot but not as a likely direct path to beating `1149`.

## Additional constraints learned during the rewrite

- The current `build_mem_image()` layout does not leave any usable tail slack after the input values slice assignment, so the only safe runtime workspace in the submission harness is the reclaimed `inp_indices` plus `inp_values` regions (`512` words total once values are scratch-resident).
- A shallow-table or shallow-cache scheme can improve specific rounds, but with only `512` words of runtime workspace it cannot scale far enough beyond depths `1` and `2` to threaten the upstream `1149` result.
- `do_kernel_test()` in `perf_takehome.py` is only a valid incremental checker for paused scalar kernels. Vector kernels run to completion on the first `machine.run()`, so smaller-shape proxy measurements must use a one-shot submission-style harness instead of that helper.
