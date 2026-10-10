# Trading Chart and UI Interactions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the paper-trading chart fill its resizable panel, keep side columns anchored, and make the account menu, idle privacy overlay, and context popup behave as approved.

**Architecture:** Preserve the existing React/CSS desk grid and resize controls. Add opt-in fill-parent sizing to the desk's `MainChart`; use explicit React state/effects for the account menu and idle screen; keep the wheel and popup inside one pointer region with a transparent CSS bridge.

**Tech Stack:** React 18, TypeScript, CSS, Vite.

**Spec:** [docs/superpowers/specs/2026-10-09-trading-chart-and-ui-interactions-design.md](../specs/2026-10-09-trading-chart-and-ui-interactions-design.md)

## Global Constraints

- No new runtime dependency or backend change.
- Non-desk `MainChart` instances keep their existing default dimensions.
- Use the existing persisted desk width and height controls; add no separate chart-width preference.
- Only **I'm Back** dismisses the settings idle overlay after it appears.
- Profile avatar click opens the account menu; only Account settings navigates to settings.

## Review Focus

- Desk card heights include toolbar and timeframe controls; the canvas must receive only remaining height and not overflow.
- The flexible center grid track can shrink at responsive widths without displacing the first/last columns.
- The account menu must close on outside click and Escape without making hover reveal it.
- Events over the lock overlay must not reset the inactivity clock; only the button does.
- Popup open state must survive pointer movement over the invisible gap, including the diagonal bridge area.

---

### Task 1: Make the paper-trading chart fill its panel

**Files:**
- Modify: `quant-app-v1/frontend/src/components/charts/MainChart.tsx`
- Modify: `quant-app-v1/frontend/src/components/features/PaperTrading.tsx`
- Modify: `quant-app-v1/frontend/src/styles/extensions.css`

**Interfaces:**
- `MainChartProps` gains optional `fillContainer?: boolean` defaulting to `false`.
- Paper Trading passes `fillContainer` to the chart instance.

- [ ] **Step 1: Add fill sizing mode and layout constraints**

Use the opt-in prop to set chart container height to `100%` instead of `min(460px, 56vh)`. Style desk chart card as a constrained flex column; give `.desk-chart-body` `flex: 1 1 0`, `min-height: 0`, and width 100%; in fill mode make the `.main-chart` container height 100%. Preserve other chart callers' defaults. Verify existing `ResizeObserver` continues to redraw.

- [ ] **Step 2: Enable fill mode for desk chart**

Pass `fillContainer` only to `MainChart` in `PaperTrading`. Ensure the chart card's content box allocates remaining height after toolbar/timeframe controls without overflow.

- [ ] **Step 3: Verify chart sizing**

Run: `cd quant-app-v1/frontend && npx tsc --noEmit`
Expected: exit 0. In browser, resize card vertically and desk columns horizontally, compare card/canvas `getBoundingClientRect()` dimensions and canvas backing dimensions, and confirm the rail/ticket remain at first/last grid tracks at wide and narrow viewport sizes.

### Task 2: Make account menu explicitly click-controlled

**Files:**
- Modify: `quant-app-v1/frontend/src/components/layout/TopBar.tsx`
- Modify: `quant-app-v1/frontend/src/styles/app.css`

**Interfaces:**
- TopBar owns a boolean open state for the account menu; avatar reports `aria-expanded` and `aria-controls`.

- [ ] **Step 1: Implement explicit menu open/close behavior**

Avatar click toggles menu without navigation. Add outside-pointer and Escape listeners while open. Account settings closes the menu then navigates; logout closes and performs existing logout. Use stable menu id and accurate menu ARIA attributes.

- [ ] **Step 2: Remove CSS hover opening**

Make `.user-dropdown` visibility depend on an `.open` class controlled by state. Remove hover and `:focus-within` visibility selectors while retaining transitions and keyboard reachability.

- [ ] **Step 3: Verify menu behavior**

Run: `cd quant-app-v1/frontend && npx tsc --noEmit`
Expected: exit 0. Browser-check hover does not open; avatar opens; selecting Account settings navigates; outside click and Escape close.

### Task 3: Lock the idle privacy overlay until explicit return

**Files:**
- Modify: `quant-app-v1/frontend/src/components/layout/IdleScreen.tsx`

- [ ] **Step 1: Separate background idle tracking from locked overlay**

While not idle, activity events update `lastActivityRef`. Once idle is true, ignore all activity events and stop recalculating dismissal from activity. Keep the timer updating displayed clock/duration. The **I'm Back** handler alone sets the timestamp and clears idle.

- [ ] **Step 2: Verify idle behavior**

Run: `cd quant-app-v1/frontend && npx tsc --noEmit`
Expected: exit 0. Browser-check overlay appears after its configured timeout; movement, click outside button, scrolling, and non-button key do not hide it; **I'm Back** does.

### Task 4: Keep the context usage popup reachable

**Files:**
- Modify: `quant-app-v1/frontend/src/components/layout/AiHarness.tsx`
- Modify: `quant-app-v1/frontend/src/styles/extensions.css`

- [ ] **Step 1: Use a shared pointer region and transparent bridge**

Move wheel hover enter/leave handling to `.ctx-pop-anchor` so its child popup belongs to the same hover region. Add a transparent pseudo-element triangle between wheel and popup with pointer events enabled and no visual fill/border. Keep click toggle and compact action close behavior.

- [ ] **Step 2: Verify popup interaction**

Run: `cd quant-app-v1/frontend && npx tsc --noEmit`
Expected: exit 0. Browser-check hover opens popup, pointer path across the gap/triangle to Compact chat keeps it visible and clickable, leaving the anchor closes it, and clicking the wheel still toggles it.

### Task 5: Full integration verification

**Files:**
- Recheck all modified frontend files.

- [ ] **Step 1: Run production build**

Run: `cd quant-app-v1/frontend && npm run build`
Expected: TypeScript and Vite production build exit 0.

- [ ] **Step 2: Exercise all acceptance criteria through browser**

Start/reuse the frontend dev server following package scripts and existing lockfile. Verify paper-trading chart rendered dimensions at desktop and responsive viewport sizes; test fixed desk columns, account menu, settings privacy lock, and context-popup Compact chat path. Inspect browser console and network failures; report environment/setup limitations rather than assuming a check passed.

- [ ] **Step 3: Read back final changes**

Inspect final diffs for all modified files and confirm exact paths/interfaces/acceptance criteria from the spec are represented. Rerun affected typecheck/build after any repair.
