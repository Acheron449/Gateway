import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, ReactElement } from "react";

import { useChartPrefs } from "../../lib/chartPrefs";
import { API_BASE } from "../../lib/constants";

interface ProviderOption {
  id: string;
  name: string;
  detail: string;
  available: boolean;
  is_default: boolean;
}

interface ProvidersResponse {
  providers: ProviderOption[];
  default: string;
}

/** Module-level cache so both chart toolbars fetch the list once. */
let providerCache: ProviderOption[] | null = null;

function ChevronIcon(): ReactElement {
  return (
    <svg className="ps-caret" viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
      <path d="M2 4l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function SearchIcon(): ReactElement {
  return (
    <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
      <circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

/**
 * Dropdown for choosing the chart's data provider, with a search field so
 * the user can type a few letters and jump straight to a provider.
 */
export function ProviderSelect() {
  const [{ provider }, { setProvider }] = useChartPrefs();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState<ProviderOption[]>(() => providerCache ?? []);
  const [highlight, setHighlight] = useState(0);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (providerCache) return undefined;
    const ac = new AbortController();
    fetch(`${API_BASE}/history/providers`, { signal: ac.signal })
      .then(async (res) => (res.ok ? ((await res.json()) as ProvidersResponse) : null))
      .then((payload) => {
        if (!payload || !Array.isArray(payload.providers)) return;
        providerCache = payload.providers;
        setOptions(payload.providers);
      })
      .catch(() => undefined);
    return () => ac.abort();
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: MouseEvent): void => {
      const root = rootRef.current;
      if (root && !root.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setHighlight(0);
    const id = window.setTimeout(() => inputRef.current?.focus(), 0);
    return () => window.clearTimeout(id);
  }, [open]);

  const filtered = query.trim()
    ? options.filter((option) =>
        `${option.name} ${option.detail}`.toLowerCase().includes(query.trim().toLowerCase()),
      )
    : options;
  const current =
    options.find((option) => option.id === provider) ??
    ({ id: provider, name: "Yahoo Finance", detail: "", available: true, is_default: true } as ProviderOption);

  const select = (option: ProviderOption): void => {
    if (!option.available) return;
    setProvider(option.id);
    setOpen(false);
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>): void => {
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (filtered.length === 0) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlight((prev) => Math.min(prev + 1, filtered.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlight((prev) => Math.max(prev - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const option = filtered[highlight] ?? filtered[0];
      if (option) select(option);
    }
  };

  return (
    <div className="provider-select" ref={rootRef}>
      <button
        type="button"
        className={`provider-select-btn ${open ? "open" : ""}`}
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="listbox"
        aria-expanded={open}
        title="Chart data provider"
      >
        <span className="ps-dot" aria-hidden="true" />
        <span className="ps-label">{current.name}</span>
        <ChevronIcon />
      </button>

      {open && (
        <div className="provider-menu" role="dialog" aria-label="Select data provider">
          <div className="provider-search">
            <SearchIcon />
            <input
              ref={inputRef}
              type="text"
              value={query}
              placeholder="Search providers"
              aria-label="Search providers"
              onChange={(event) => {
                setQuery(event.target.value);
                setHighlight(0);
              }}
              onKeyDown={onKeyDown}
            />
          </div>
          <ul className="provider-list" role="listbox">
            {filtered.map((option, index) => (
              <li key={option.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={option.id === provider}
                  disabled={!option.available}
                  className={[
                    "provider-option",
                    option.id === provider ? "is-current" : "",
                    index === highlight ? "is-highlighted" : "",
                    option.available ? "" : "is-disabled",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  onMouseEnter={() => setHighlight(index)}
                  onClick={() => select(option)}
                >
                  <span className="po-name">{option.name}</span>
                  <span className="po-detail">{option.available ? option.detail : "Not configured"}</span>
                  {option.id === provider && <span className="po-check" aria-hidden="true">✓</span>}
                </button>
              </li>
            ))}
            {filtered.length === 0 && (
              <li className="provider-empty">No providers match “{query.trim()}”</li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
