# Project: Original Performance Takehome

Fork of Anthropic's `original_performance_takehome`. Current focus: redesign the kernel in `perf_takehome.py` to beat `1487` cycles without modifying anything under `tests/`.

## Key Docs
- `roadmap.md` — milestones, current status, validation gates
- `docs/README.md` — durable notes and design references
- `Readme.md` — upstream task statement and benchmark thresholds

## Sub-Session Instructions
- Read `roadmap.md` then the relevant doc in `docs/` before editing.
- Primary implementation target: `perf_takehome.py`
- Validation: `python tests/submission_tests.py`
- Keep `tests/` unchanged; use `git diff upstream/main tests/` to verify if needed.
- Commit style: short imperative subject lines
- Do NOT communicate on Slack; the parent worker handles Slack I/O

## Context Loading
- New to the repo: `Readme.md`, then `roadmap.md`, then `docs/README.md`
- Working on the kernel: `docs/kernel-design.md`
