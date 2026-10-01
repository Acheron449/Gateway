import { useCallback, useEffect, useRef } from "react";

export type HandleSide = "left" | "right";

interface ResizeHandleProps {
  side: HandleSide;
  width: number;
  minWidth: number;
  /** Width at or below which a drag snaps the panel to its collapsed rail. */
  collapseBelow: number;
  collapsedWidth: number;
  maxWidth: number;
  onChange: (width: number) => void;
  storageKey: string;
  ariaLabel: string;
}

/**
 * Invisible drag strip on a panel's screen edge. Dragging resizes the panel
 * smoothly; dragging past `collapseBelow` snaps it into the compact icon rail
 * (width = collapsedWidth), and dragging the rail outward restores the last
 * expanded width. Persisted per-panel in localStorage.
 */
export function ResizeHandle({
  side,
  width,
  minWidth,
  collapseBelow,
  collapsedWidth,
  maxWidth,
  onChange,
  storageKey,
  ariaLabel,
}: ResizeHandleProps) {
  const draggingRef = useRef(false);
  const lastExpandedRef = useRef<number>(Math.max(width, collapseBelow + 8));

  const isCollapsed = width <= collapsedWidth;

  const handlePointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      draggingRef.current = true;
      e.currentTarget.setPointerCapture(e.pointerId);
      document.body.classList.add("panel-resizing");
      if (!isCollapsed) {
        lastExpandedRef.current = width;
      }
    },
    [isCollapsed, width],
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!draggingRef.current) return;
      const delta = side === "left" ? e.clientX : window.innerWidth - e.clientX;
      const next = Math.min(maxWidth, Math.max(collapsedWidth, delta));
      if (next <= collapseBelow) {
        onChange(collapsedWidth); // snap into the icon rail
      } else {
        onChange(next);
      }
    },
    [side, maxWidth, collapseBelow, collapsedWidth, onChange],
  );

  const handlePointerUp = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!draggingRef.current) return;
      draggingRef.current = false;
      e.currentTarget.releasePointerCapture(e.pointerId);
      document.body.classList.remove("panel-resizing");
      try {
        localStorage.setItem(storageKey, String(width));
      } catch {
        /* private mode — ignore */
      }
    },
    [storageKey, width],
  );

  useEffect(() => {
    return () => document.body.classList.remove("panel-resizing");
  }, []);

  // Double-click restores a sensible default expanded width.
  const handleDoubleClick = useCallback(() => {
    const restored = Math.max(minWidth, Math.min(maxWidth, side === "left" ? 240 : 320));
    onChange(restored);
  }, [minWidth, maxWidth, onChange, side]);

  return (
    <div
      className={`resize-handle resize-handle-${side} ${isCollapsed ? "handle-collapsed" : ""}`}
      role="separator"
      aria-orientation="vertical"
      aria-label={ariaLabel}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onDoubleClick={handleDoubleClick}
    >
      <span className="resize-handle-grip" aria-hidden="true" />
    </div>
  );
}
