import { useCallback, useEffect, useRef } from "react";

export type HandleSide = "left" | "right" | "top" | "bottom";

/** Separator orientation: "vertical" = side-by-side panels, "horizontal" = stacked panels. */
export type HandleOrientation = "vertical" | "horizontal";

/**
 * "anchor" measures from the window edge (workspace sidebars).
 * "delta" measures from the host element's width at drag start (sections
 * inside a grid, whose absolute position on screen is not meaningful).
 */
export type HandleMode = "anchor" | "delta";

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
  /** Defaults to "anchor" — existing workspace sidebar behaviour. */
  mode?: HandleMode;
  /** Width restored on double-click (defaults to 240/320 by side). */
  defaultWidth?: number;
  /** Extra class(es) for positioning variants (e.g. desk grid handles). */
  className?: string;
  /**
   * Element whose width to adjust in "delta" mode. Needed when the handle is
   * rendered outside its target section (e.g. in a grid gap). Falls back to
   * the handle's parent element.
   */
  measureRef?: React.RefObject<HTMLElement | null>;
  /** Defaults to "vertical" (side-by-side panels resized by dragging left/right). */
  orientation?: HandleOrientation;
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
  mode = "anchor",
  defaultWidth,
  className,
  measureRef,
  orientation = "vertical",
}: ResizeHandleProps) {
  const draggingRef = useRef(false);
  const lastExpandedRef = useRef<number>(Math.max(width, collapseBelow + 8));
  const startXRef = useRef(0);
  const startYRef = useRef(0);
  const startWidthRef = useRef(width);

  const isCollapsed = width <= collapsedWidth;

  const handlePointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      draggingRef.current = true;
      try {
        e.currentTarget.setPointerCapture(e.pointerId);
      } catch {
        /* synthetic/unavailable pointer — move events still arrive */
      }
      document.body.classList.add("panel-resizing");
      if (mode === "delta") {
        // Measure the target section's rendered size so the drag starts from
        // what the user actually sees (media-query defaults included).
        const host = measureRef?.current ?? e.currentTarget.parentElement;
        startXRef.current = e.clientX;
        startYRef.current = e.clientY;
        startWidthRef.current = host
          ? host.getBoundingClientRect()[orientation === "horizontal" ? "height" : "width"]
          : width;
      } else if (!isCollapsed) {
        lastExpandedRef.current = width;
      }
    },
    [isCollapsed, measureRef, mode, orientation, width],
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!draggingRef.current) return;
      if (mode === "delta") {
        const axisDelta =
          orientation === "horizontal" ? e.clientY - startYRef.current : e.clientX - startXRef.current;
        const direction =
          orientation === "horizontal"
            ? side === "top"
              ? 1
              : -1
            : side === "left"
              ? 1
              : -1;
        const raw = startWidthRef.current + direction * axisDelta;
        onChange(Math.min(maxWidth, Math.max(minWidth, raw)));
        return;
      }
      const delta = side === "left" ? e.clientX : window.innerWidth - e.clientX;
      const next = Math.min(maxWidth, Math.max(collapsedWidth, delta));
      if (next <= collapseBelow) {
        onChange(collapsedWidth); // snap into the icon rail
      } else {
        onChange(next);
      }
    },
    [mode, orientation, side, minWidth, maxWidth, collapseBelow, collapsedWidth, onChange],
  );

  const handlePointerUp = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!draggingRef.current) return;
      draggingRef.current = false;
      try {
        e.currentTarget.releasePointerCapture(e.pointerId);
      } catch {
        /* not captured — nothing to release */
      }
      document.body.classList.remove("panel-resizing");
      if (mode === "delta") return; // consumer persists the final clamped width via onChange
      try {
        localStorage.setItem(storageKey, String(width));
      } catch {
        /* private mode — ignore */
      }
    },
    [mode, storageKey, width],
  );

  useEffect(() => {
    return () => document.body.classList.remove("panel-resizing");
  }, []);

  // Double-click restores a sensible default expanded width.
  const handleDoubleClick = useCallback(() => {
    const fallback = defaultWidth ?? (side === "left" ? 240 : 320);
    const restored = Math.max(minWidth, Math.min(maxWidth, fallback));
    onChange(restored);
    if (mode === "delta") return; // consumer persists via onChange
    try {
      localStorage.setItem(storageKey, String(restored));
    } catch {
      /* private mode — ignore */
    }
  }, [defaultWidth, minWidth, maxWidth, mode, onChange, side, storageKey]);

  return (
    <div
      className={`resize-handle resize-handle-${side} resize-handle-${orientation} ${isCollapsed ? "handle-collapsed" : ""} ${className ?? ""}`}
      role="separator"
      aria-orientation={orientation === "horizontal" ? "horizontal" : "vertical"}
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
