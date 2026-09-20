import { useState, useEffect, useCallback, FormEvent } from "react";

import { API_BASE } from "../../lib/constants";

export interface ScannerV2Props {
  onPickSymbol?: (symbol: string) => void;
  selectedSymbol?: string;
}

interface CatalogueInstrument {
  symbol: string;
  name?: string;
  exchange?: string;
  instrument_type?: string;
  description?: string;
  provenance?: {
    source?: string;
    provider_version?: string;
    data_time?: string;
  };
}

interface CatalogueSearchPayload {
  query?: string;
  matches?: string[];
  instruments?: CatalogueInstrument[];
}

interface FilterPreset {
  id: string;
  label: string;
  description: string;
  query: string;
}

interface SavedScreen {
  id: string;
  name: string;
  filters: Record<string, unknown>;
  query: string;
  createdAt: string;
}

const FILTER_PRESETS: FilterPreset[] = [
  { id: "gainers", label: "Top Gainers", description: "Stocks with highest daily gain", query: "gainers" },
  { id: "losers", label: "Top Losers", description: "Stocks with highest daily loss", query: "losers" },
  { id: "volume", label: "High Volume", description: "Unusual volume spikes", query: "volume" },
  { id: "rsi-overbought", label: "RSI Overbought", description: "RSI > 70", query: "rsi>70" },
  { id: "rsi-oversold", label: "RSI Oversold", description: "RSI < 30", query: "rsi<30" },
  { id: "breakout", label: "Breakout Candidates", description: "Near 52-week highs", query: "breakout" },
  { id: "tech", label: "Tech Stocks", description: "Technology sector", query: "sector:tech" },
  { id: "etfs", label: "Major ETFs", description: "SPY, QQQ, IWM, VTI", query: "etf" },
];

const STORAGE_KEY = "gateway_scanner_screens";

export function ScannerV2({ onPickSymbol, selectedSymbol }: ScannerV2Props) {
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<CatalogueInstrument[]>([]);
  const [provenance, setProvenance] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activePreset, setActivePreset] = useState<string | null>(null);
  const [showPresets, setShowPresets] = useState(false);
  const [savedScreens, setSavedScreens] = useState<SavedScreen[]>([]);
  const [showSavedScreens, setShowSavedScreens] = useState(false);
  const [newScreenName, setNewScreenName] = useState("");

  // Load saved screens from localStorage
  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        setSavedScreens(JSON.parse(stored));
      }
    } catch {
      // Ignore parse errors
    }
  }, []);

  const saveScreens = useCallback((screens: SavedScreen[]) => {
    setSavedScreens(screens);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(screens));
  }, []);

  const runSearch = async (evt?: FormEvent) => {
    evt?.preventDefault();
    const q = query.trim().toUpperCase();
    if (q.length < 1) {
      setMatches([]);
      setProvenance(null);
      return;
    }
    setBusy(true);
    setError(null);

    try {
      const url = `${API_BASE}/catalogue/search?query=${encodeURIComponent(q)}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(await res.text());
      const body = (await res.json()) as CatalogueSearchPayload;
      const instruments = Array.isArray(body.instruments) ? body.instruments : [];
      setMatches(instruments);
      const first = instruments[0];
      setProvenance(
        first?.provenance?.source && first?.provenance?.provider_version
          ? `${first.provenance.source} · ${first.provenance.provider_version}`
          : null,
      );
    } catch {
      setError("Catalogue search failed");
      setMatches([]);
      setProvenance(null);
    } finally {
      setBusy(false);
    }
  };

  const applyPreset = useCallback((preset: FilterPreset) => {
    setQuery(preset.query);
    setActivePreset(preset.id);
    setShowPresets(false);
    runSearch();
  }, []);

  const saveCurrentScreen = useCallback(() => {
    if (!newScreenName.trim()) return;
    const screen: SavedScreen = {
      id: `screen-${Date.now()}`,
      name: newScreenName.trim(),
      filters: { query, activePreset },
      query,
      createdAt: new Date().toISOString(),
    };
    saveScreens([...savedScreens, screen]);
    setNewScreenName("");
    setShowSavedScreens(true);
  }, [newScreenName, query, activePreset, savedScreens, saveScreens]);

  const loadScreen = useCallback((screen: SavedScreen) => {
    setQuery(screen.query);
    setActivePreset(screen.filters.activePreset as string || null);
    setShowSavedScreens(false);
    runSearch();
  }, [runSearch]);

  const deleteScreen = useCallback((id: string) => {
    saveScreens(savedScreens.filter((s) => s.id !== id));
  }, [savedScreens, saveScreens]);

  return (
    <section className="scanner-v2">
      <div className="scanner-header">
        <h2 className="scanner-title">Scanner</h2>
        <div className="scanner-actions">
          <button
            className={`icon-button ${showPresets ? "active" : ""}`}
            onClick={() => setShowPresets(!showPresets)}
            aria-expanded={showPresets}
            aria-label="Filter presets"
            title="Filter Presets"
          >
            ⚙
          </button>
          <button
            className={`icon-button ${showSavedScreens ? "active" : ""}`}
            onClick={() => setShowSavedScreens(!showSavedScreens)}
            aria-expanded={showSavedScreens}
            aria-label="Saved screens"
            title="Saved Screens"
          >
            ⭐
          </button>
        </div>
      </div>

      {/* Filter Presets Dropdown */}
      {showPresets && (
        <div className="scanner-dropdown presets-dropdown">
          <div className="dropdown-header">Filter Presets</div>
          <ul className="presets-list" role="listbox">
            {FILTER_PRESETS.map((preset) => (
              <li key={preset.id} role="option" aria-selected={activePreset === preset.id}>
                <button
                  className={`preset-item ${activePreset === preset.id ? "active" : ""}`}
                  onClick={() => applyPreset(preset)}
                >
                  <span className="preset-label">{preset.label}</span>
                  <span className="preset-description">{preset.description}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Saved Screens Dropdown */}
      {showSavedScreens && (
        <div className="scanner-dropdown screens-dropdown">
          <div className="dropdown-header">
            <span>Saved Screens</span>
            <button className="icon-button" onClick={() => setShowSavedScreens(false)} aria-label="Close">×</button>
          </div>
          {savedScreens.length === 0 ? (
            <div className="empty-state">No saved screens yet. Create one below.</div>
          ) : (
            <ul className="screens-list" role="listbox">
              {savedScreens.map((screen) => (
                <li key={screen.id} role="option">
                  <div className="screen-item">
                    <button className="screen-name" onClick={() => loadScreen(screen)}>
                      {screen.name}
                    </button>
                    <button
                      className="icon-button danger"
                      onClick={(e) => { e.stopPropagation(); deleteScreen(screen.id); }}
                      aria-label={`Delete ${screen.name}`}
                    >
                      🗑
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
          <div className="save-screen-form">
            <input
              type="text"
              value={newScreenName}
              onChange={(e) => setNewScreenName(e.target.value)}
              placeholder="New screen name..."
              className="save-screen-input"
              onKeyDown={(e) => e.key === "Enter" && saveCurrentScreen()}
            />
            <button className="save-screen-btn" onClick={saveCurrentScreen} disabled={!newScreenName.trim()}>
              Save
            </button>
          </div>
        </div>
      )}

      {/* Search Form */}
      <form onSubmit={(e) => void runSearch(e)} className="scanner-form">
        <div className="search-input-wrapper">
          <input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value.toUpperCase());
              setActivePreset(null);
            }}
            placeholder="Search catalogue…"
            className="scanner-input"
            aria-label="Catalogue query"
          />
          <button
            type="submit"
            disabled={busy}
            className={`scanner-submit ${busy ? "loading" : ""}`}
          >
            {busy ? "Searching…" : "Scan"}
          </button>
        </div>
      </form>

      {error && <p className="scanner-error">{error}</p>}
      {provenance && <p className="scanner-provenance">Source: {provenance}</p>}

      {/* Results */}
      {matches.length > 0 && (
        <ul className="scanner-results" role="listbox" aria-label="Search results">
          {matches.map((inst) => (
            <li key={inst.symbol} role="option" aria-selected={selectedSymbol === inst.symbol}>
              <button
                type="button"
                className={`symbol-result ${selectedSymbol === inst.symbol ? "active" : ""}`}
                onClick={() => onPickSymbol?.(inst.symbol ?? "")}
                title={inst.name ?? inst.symbol}
              >
                <span className="result-symbol">{inst.symbol}</span>
                {inst.name && <span className="result-name">{inst.name}</span>}
                {inst.exchange && <span className="result-exchange">{inst.exchange}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}

      {matches.length === 0 && !busy && query && !error && (
        <p className="scanner-empty">No instruments found for "{query}"</p>
      )}
    </section>
  );
}