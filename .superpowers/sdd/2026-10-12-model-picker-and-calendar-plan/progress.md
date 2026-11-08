# SDD ledger — plan: docs/superpowers/plans/2026-10-12-model-picker-and-calendar-plan.md

Pre-flight: Native execution approved; implementation in current branch `0.04` per user choice. Not an isolated worktree. Superpowers helper scripts and TDD sub-skill were not present at the advertised sibling paths or synced skill set; following the plan's explicit test-first steps with existing pytest/build tooling. No frontend test runner is installed/configured; browser verification will be used rather than adding dependencies. No commits will be made because the user did not request commits.

Pre-flight interface: ModelPicker task produces `ModelPicker({providerId, configured, value, onChange, className?})`; Chat/Backtester plan consumes the same exact prop contract. Calendar uses the existing provider interface and normalized `EconomicEvent`.
