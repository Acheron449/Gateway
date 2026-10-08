import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Idle privacy screen for the settings page (where credentials live).
 *
 * After 15 seconds without pointer or keyboard input the viewport is covered
 * by a blackout showing the current time, how long the screen has been idle,
 * a prompt and an "I'm Back" button. Any interaction dismisses it.
 */

const IDLE_AFTER_MS = 15_000;
const TICK_MS = 1_000;

const ACTIVITY_EVENTS = ["mousemove", "pointerdown", "keydown", "wheel", "touchstart"] as const;

function fmtClock(ms: number): string {
  return new Date(ms).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function fmtDuration(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  if (minutes === 0) return `${seconds}s`;
  return `${minutes}m ${seconds}s`;
}

export function IdleScreen() {
  const lastActivityRef = useRef<number>(Date.now());
  const [now, setNow] = useState<number>(() => Date.now());
  const [idle, setIdle] = useState(false);

  const markActive = useCallback(() => {
    lastActivityRef.current = Date.now();
    setIdle(false);
  }, []);

  // Poll the clock and evaluate the idle threshold.
  useEffect(() => {
    const id = window.setInterval(() => {
      const current = Date.now();
      setNow(current);
      setIdle(current - lastActivityRef.current >= IDLE_AFTER_MS);
    }, TICK_MS);
    return () => window.clearInterval(id);
  }, []);

  // Any real interaction counts as presence.
  useEffect(() => {
    const onActivity = () => markActive();
    for (const event of ACTIVITY_EVENTS) {
      window.addEventListener(event, onActivity, { passive: true });
    }
    return () => {
      for (const event of ACTIVITY_EVENTS) {
        window.removeEventListener(event, onActivity);
      }
    };
  }, [markActive]);

  if (!idle) return null;

  const idleFor = now - lastActivityRef.current;

  return (
    <div
      className="idle-screen"
      role="dialog"
      aria-modal="true"
      aria-label="Screen locked due to inactivity"
      // Stop activity listeners on this layer from instantly unlocking it —
      // only an explicit click/keypress outside the button should.
      onPointerDown={(event) => event.stopPropagation()}
      onKeyDown={(event) => event.stopPropagation()}
    >
      <div className="idle-screen-card">
        <div className="idle-screen-clock" aria-live="off">
          {fmtClock(now)}
        </div>
        <p className="idle-screen-idle">No input for {fmtDuration(idleFor)}</p>
        <p className="idle-screen-prompt">Are you still there?</p>
        <button
          type="button"
          className="btn-primary idle-screen-back"
          onClick={markActive}
          autoFocus
        >
          I&apos;m Back
        </button>
        <p className="idle-screen-hint">Settings are hidden to keep your keys private.</p>
      </div>
    </div>
  );
}
