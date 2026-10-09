# Trading Chart and UI Interactions Design

## Goal

Make the paper-trading chart visibly follow its resizable panel in both dimensions, without shifting the desk's left rail or right ticket; make account settings, idle privacy, and context-popup interactions intentional and reliable.

## User-approved interaction decisions

- Clicking the profile avatar opens a small account menu. It does not navigate to settings. Selecting **Account settings** navigates to settings.
- The settings privacy overlay disappears only after the user activates **I'm Back**. Pointer movement or other activity must not dismiss it.
- The context usage popup remains open as the pointer moves from the context wheel to **Compact chat**, including across the gap between them.
- Keep the existing desk resize model; do not add a separate free-floating chart width setting. The chart uses the available center track between the existing side columns.

## Design

### Trading chart sizing and anchored desk columns

The chart card already has persisted height state and vertical resize controls. Its embedded `MainChart` currently sets a fixed `min(460px, 56vh)` height, so that child does not fill the height allotted by the card. Give the chart an explicit opt-in fill-parent mode (or an equivalent narrow interface) used by the paper-trading chart only. In that mode the chart container occupies the available width and height of `.desk-chart-body`; make the toolbar/body/timeframe layout allocate remaining card height to the body without overflow. Keep ordinary `MainChart` uses on their current default sizing.

The center grid track remains flexible (`minmax(0, 1fr)`) between the left desk rail/watchlist and right ticket. Existing side-panel width controls change the space available to the center track, and `MainChart`'s resize observer redraws its canvas at the resulting dimensions. Preserve the grid's first and last side-column placement so resizing the chart does not move the left rail or right ticket. Do not make chart resizing alter the workspace-level app sidebar or inspector.

### Account menu

Replace hover/focus-driven dropdown visibility and avatar-to-settings navigation with explicit open state. The avatar toggles the menu; it has accurate expanded/menu ARIA state. Close the menu on outside pointer interaction, Escape, Account settings selection, or logout. The menu remains usable by keyboard, and hovering over the avatar alone does not open it.

### Idle privacy overlay

Continue tracking inactivity until the 15-second threshold. Once visible, the overlay is locked: activity events must not update the idle timestamp or hide the overlay. Only the **I'm Back** button resets the inactivity clock and dismisses the overlay. Keep the time/duration display ticking while it is shown.

### Context popup hover bridge

Treat the wheel and popup as one hover region and add a transparent triangular pointer hit area spanning the visual gap from the popup toward the wheel. Moving the pointer across that bridge must not close the popup before the user can activate **Compact chat**. Preserve click toggling and close behavior when the pointer leaves the combined region; after compacting, close the popup as before.

## Acceptance criteria

1. On paper trading, drag the existing vertical chart resize handle. The chart card and rendered canvas both gain/lose height; the canvas drawing fills the chart area and redraws at its new pixel dimensions.
2. Resize adjacent desk columns so the center track becomes wider and narrower. The rendered chart width tracks the center track, while the first-column rail and last-column ticket remain at their desk edges and do not jump with chart size changes.
3. Other views embedding `MainChart` retain their existing default dimensions.
4. Merely hovering over or clicking the avatar does not navigate to settings. Clicking it opens the menu; selecting Account settings navigates there. Outside click and Escape close the menu.
5. After inactivity covers Settings, moving the pointer, clicking elsewhere, scrolling, or pressing a non-button key does not reveal Settings. Activating **I'm Back** does.
6. Hovering the context wheel opens the popup. Moving the pointer through the gap into **Compact chat** keeps it open, and the action remains clickable. Leaving the combined hover region closes it.
7. Frontend TypeScript check and production build pass. Verify chart dimensions and interactions in a running browser at a wide desktop viewport and a narrower responsive viewport; inspect console/network errors.

## Scope and files expected to change

- `quant-app-v1/frontend/src/components/charts/MainChart.tsx` — opt-in fill-parent sizing for the desk chart.
- `quant-app-v1/frontend/src/components/features/PaperTrading.tsx` — enable fill-parent sizing on the desk instance, only if required by the chosen prop interface.
- `quant-app-v1/frontend/src/styles/extensions.css` — chart body sizing, desk alignment invariants, and context popup bridge hit area.
- `quant-app-v1/frontend/src/components/layout/TopBar.tsx` and `quant-app-v1/frontend/src/styles/app.css` — click-controlled account menu.
- `quant-app-v1/frontend/src/components/layout/IdleScreen.tsx` — explicit-only unlock behavior.
- `quant-app-v1/frontend/src/components/layout/AiHarness.tsx` — combined wheel/popup hover handling.

No new runtime dependency or backend change is expected. The frontend package currently defines no test script; verification will use the project's TypeScript/build commands and browser interaction checks unless a suitable existing focused test harness is discovered during planning.

## Out of scope

- Independent persisted width for the chart separate from the desk grid tracks.
- Changes to chart data, indicators, trading behavior, or non-desk chart defaults.
- Changing inactivity threshold or adding authentication/lock semantics beyond the current privacy overlay.
- Backend, deployment, or credential changes.
