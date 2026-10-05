import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactElement } from "react";

import { useChartPrefs } from "../../lib/chartPrefs";
import {
  INDICATOR_CATEGORIES,
  INDICATORS,
  type IndicatorCategory,
  type IndicatorDef,
} from "../../lib/indicators";

type PanelSection = "library" | "active" | "favorites" | "common" | IndicatorCategory;

export interface IndicatorPanelProps {
  active: readonly string[];
  favorites: readonly string[];
  onToggle: (id: string) => void;
  onToggleFavorite: (id: string) => void;
  onClose: () => void;
}

function MagnifierIcon(): ReactElement {
  return (
    <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">
      <circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function isCategory(section: PanelSection): section is IndicatorCategory {
  return (INDICATOR_CATEGORIES as readonly string[]).includes(section);
}

/**
 * Popup for picking chart indicators — left nav (active/favourites/common/library
 * plus categories) and a searchable list on the right.
 */
export function IndicatorPanel({
  active,
  favorites,
  onToggle,
  onToggleFavorite,
  onClose,
}: IndicatorPanelProps) {
  const [section, setSection] = useState<PanelSection>("library");
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const activeSet = useMemo(() => new Set(active), [active]);
  const favSet = useMemo(() => new Set(favorites), [favorites]);

  const list: IndicatorDef[] = useMemo(() => {
    const q = query.trim().toLowerCase();
    let items: IndicatorDef[];
    if (q) {
      items = INDICATORS.filter(
        (def) =>
          def.name.toLowerCase().includes(q) ||
          def.desc.toLowerCase().includes(q) ||
          def.id.includes(q),
      );
    } else if (section === "active") {
      items = INDICATORS.filter((def) => activeSet.has(def.id));
    } else if (section === "favorites") {
      items = INDICATORS.filter((def) => favSet.has(def.id));
    } else if (section === "common") {
      items = INDICATORS.filter((def) => def.common);
    } else if (isCategory(section)) {
      items = INDICATORS.filter((def) => def.category === section);
    } else {
      items = [...INDICATORS];
    }
    return [...items].sort((a, b) => a.name.localeCompare(b.name));
  }, [query, section, activeSet, favSet]);

  const navItem = (
    id: PanelSection,
    glyph: string,
    label: string,
    badge?: number,
  ): ReactElement => (
    <button
      key={id}
      type="button"
      className={`ip-nav-item ${section === id && !query ? "is-active" : ""}`}
      onClick={() => {
        setQuery("");
        setSection(id);
      }}
    >
      <span className="ip-nav-glyph" aria-hidden="true">{glyph}</span>
      <span className="ip-nav-label">{label}</span>
      {badge !== undefined && (badge > 0 || id === "active") && (
        <span className="ip-badge">{badge}</span>
      )}
    </button>
  );

  return (
    <div
      className="indicator-panel"
      role="dialog"
      aria-label="Indicators"
      onPointerDown={(event) => event.stopPropagation()}
    >
      <aside className="indicator-panel-nav">
        <div className="ip-nav-title">INDICATORS</div>
        {navItem("active", "∿", "Active Indicators", active.length)}
        {navItem("favorites", "★", "Favourites", favorites.length)}
        {navItem("common", "◎", "Common Indicators")}
        {navItem("library", "▦", "Indicator Library")}
        <hr className="ip-nav-rule" />
        <div className="ip-nav-title">CATEGORIES</div>
        {INDICATOR_CATEGORIES.map((category) => navItem(category, "▸", category))}
      </aside>

      <div className="indicator-panel-main">
        <div className="ip-search">
          <MagnifierIcon />
          <input
            ref={inputRef}
            type="text"
            value={query}
            placeholder="Search Indicators"
            aria-label="Search indicators"
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <div className="ip-list">
          {list.map((def) => {
            const isActive = activeSet.has(def.id);
            const isFav = favSet.has(def.id);
            return (
              <div key={def.id} className={`ip-row ${isActive ? "is-active" : ""}`}>
                <button
                  type="button"
                  className={`ip-star ${isFav ? "is-fav" : ""}`}
                  aria-label={isFav ? `Remove ${def.name} from favourites` : `Add ${def.name} to favourites`}
                  aria-pressed={isFav}
                  onClick={() => onToggleFavorite(def.id)}
                >
                  {isFav ? "★" : "☆"}
                </button>
                <button
                  type="button"
                  className="ip-name"
                  aria-pressed={isActive}
                  onClick={() => onToggle(def.id)}
                >
                  {def.name}
                </button>
                <span className="ip-info" title={def.desc} aria-label={def.desc}>
                  ⓘ
                </span>
                {isActive && <span className="ip-active-dot" aria-hidden="true" />}
              </div>
            );
          })}
          {list.length === 0 && (
            <div className="ip-empty">
              {query.trim()
                ? `No indicators match “${query.trim()}”`
                : "Nothing here yet — star indicators you use often."}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Toolbar button that opens the indicator popup. Handles click-outside
 * (the popup disappears when the user clicks anywhere outside it).
 */
export function IndicatorsButton() {
  const [{ indicators, favorites }, { toggleIndicator, toggleFavorite }] = useChartPrefs();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: PointerEvent): void => {
      const root = rootRef.current;
      if (root && !root.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  return (
    <div className="indicator-menu-anchor" ref={rootRef}>
      <button
        type="button"
        className={`chart-tool-btn ${open ? "open" : ""}`}
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        <span className="ctb-glyph" aria-hidden="true">∿</span>
        <span>Indicators</span>
        {indicators.length > 0 && <span className="ctb-count">{indicators.length}</span>}
      </button>
      {open && (
        <IndicatorPanel
          active={indicators}
          favorites={favorites}
          onToggle={toggleIndicator}
          onToggleFavorite={toggleFavorite}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  );
}
