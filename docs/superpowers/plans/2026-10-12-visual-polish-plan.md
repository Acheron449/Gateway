# Model, Calendar, and Backtester Visual Polish Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the touched model-selection, calendar, and strategy-run controls coherent, readable, and responsive without a broad application redesign.

**Architecture:** Reuse the existing Gateway dark terminal palette and shared ModelPicker. Improve only the panels introduced or edited by the associated approved plans, with consistent spacing, labels, focus states, empty/error messages, and small-screen stacking.

**Tech Stack:** React, TypeScript, existing `extensions.css`, existing browser preview.

**Spec:** [../specs/2026-10-12-model-chat-backtest-calendar-design.md](../specs/2026-10-12-model-chat-backtest-calendar-design.md)

## Global Constraints

- No new design/dependency system and no broad restyling of unrelated app views.
- Preserve semantic labels, keyboard focus, and accessible state text.
- Keep historical-only disclaimer and explicit confirmation affordance prominent.

## Review Focus

- At 360px viewport, model dropdown/toggle or launch fields do not overflow horizontally.
- Loading, empty, and error states remain distinguishable and do not shift/remove labels.
- Focus rings and checked/disabled contrast remain visible in dark mode.
- The Backtester review summary differentiates a proposal from a running/completed job.
- Calendar source selection remains compact and its Yahoo best-effort status is legible.

### Task 1: Visual consistency pass

**Files:**
- Modify: `quant-app-v1/frontend/src/styles/extensions.css`
- Modify: affected JSX only where semantic markup/labels need correction in `ModelPicker.tsx`, `AiHarness.tsx`, `AgenticLab.tsx`, `Backtester.tsx`, `CalendarView.tsx`.

- [ ] Step 1: Capture existing affected screens at desktop and 360px widths; expected baseline screenshots identify existing overflow before changes.
- [ ] Step 2: Add narrowly scoped CSS for consistent model-control spacing, status text, proposal cards, launcher grouping and mobile stacking; expected no unrelated view styling changes.
- [ ] Step 3: Rebuild frontend; browser-verify desktop/mobile layout, keyboard focus, select/toggle states, status/error flows; expected controls remain operable with no horizontal overflow at 360px.
- [ ] Step 4: Run `git diff --check`; inspect the visual changes and avoid unrelated CSS selectors; expected no whitespace errors.

### Task 2: Final visual acceptance

- [ ] Step 1: Verify AI Chat, Agentic Lab, Provider Settings, Calendar, and Backtester using the actual browser preview; expected each touched screen matches acceptance criteria.
- [ ] Step 2: Ensure the app is usable when unauthenticated (read-only controls/status) and clearly requests sign-in before paid actions.
- [ ] Step 3: Rerun `cd quant-app-v1/frontend && npm run build` after the final edited files and record browser limitations.

---

This polish plan consumes the picker from [the shared picker/calendar plan](2026-10-12-model-picker-and-calendar-plan.md) and the proposal/launcher controls from [the Chat and Backtester plan](2026-10-12-chat-tools-backtester-plan.md). Execute after both implementation plans.
