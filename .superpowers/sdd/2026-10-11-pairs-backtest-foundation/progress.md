# SDD ledger — plan: docs/superpowers/plans/2026-10-11-pairs-backtest-foundation.md

Pre-flight: Task 1 produces `run_pairs_backtest` / config / statsmodels coint service; Tasks 2 consumes that module for fills/folds; Task 3 consumes it for dispatch and stored run schema; Task 4 consumes stored result fields. Interface labels have not yet been implemented; align after Task 1.
Ruling: work in current checkout rather than create a separate linked worktree — explicitly selected by user; protects approved, untracked spec and plan in place.
Ruling: unavailable `superpowers:test-driven-development`, `superpowers:verification-before-completion`, and SDD scripts — paths absent from synced skill set. Follow tests-first and explicit verification in plan using available CLI, but cannot meet those skill-specific script requirements.
