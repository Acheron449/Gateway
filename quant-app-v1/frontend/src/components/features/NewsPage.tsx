import { useEffect, useState, useCallback, useMemo } from "react";

import { API_BASE } from "../../lib/constants";

/**
 * Full-screen, scrollable news reader.
 *
 * Opened from the Overview NEWS card and the inspector's "View all news"
 * button — both only preview what fits in their small panels, and this page
 * shows the whole feed (up to 50 stories) with category filters and an
 * explicit source picker (auto chain = Finnhub → Yahoo Finance).
 */

interface NewsStory {
  id: string;
  headline: string;
  url?: string;
  source: string;
  thumbnail?: string | null;
  published_at: string;
  categories: string[];
  related_symbols: string[];
}

interface NewsPayload {
  items: NewsStory[];
  provenance?: { source?: string; provider_version?: string; entitlement?: string };
  status?: string;
  message?: string | null;
}

interface NewsSource {
  id: string;
  name: string;
  detail: string;
  available: boolean;
}

interface NewsPageProps {
  open: boolean;
  onClose: () => void;
  /** Optional ticker scope — mirrors the inspector's per-symbol feed. */
  symbol?: string;
}

/** Client-side category tabs (keyword match over headline/source/categories). */
const TOPIC_TABS: { id: string; label: string; keywords: string[] | null }[] = [
  { id: "top", label: "Top", keywords: null },
  {
    id: "markets",
    label: "Markets",
    keywords: ["market", "stock", "rally", "selloff", "investor", "nasdaq", "dow", "s&p", "wall street", "ipo"],
  },
  {
    id: "economy",
    label: "Economy",
    keywords: ["fed ", "federal reserve", "inflation", "cpi", "rate", "economy", "recession", "jobs", "gdp", "treasury"],
  },
  {
    id: "tech",
    label: "Tech",
    keywords: [" ai", "ai ", "chip", "semiconductor", "tech", "apple", "nvidia", "google", "microsoft", "software"],
  },
  { id: "energy", label: "Energy", keywords: ["oil", "crude", "energy", "gas", "opec", "solar", "wti"] },
  { id: "policy", label: "Policy", keywords: ["sec ", "regulat", "congress", "court", "tariff", "policy", "white house"] },
  { id: "deals", label: "Deals", keywords: ["acqui", "merger", "deal", "buyout", "stake", "takeover"] },
];

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(ms / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function matchesTopic(story: NewsStory, keywords: string[] | null): boolean {
  if (!keywords) return true;
  const haystack = `${story.headline} ${story.source} ${(story.categories || []).join(" ")}`.toLowerCase();
  return keywords.some((word) => haystack.includes(word));
}

export function NewsPage({ open, onClose, symbol }: NewsPageProps) {
  const [stories, setStories] = useState<NewsStory[]>([]);
  const [sources, setSources] = useState<NewsSource[]>([]);
  const [provider, setProvider] = useState("auto");
  const [topic, setTopic] = useState("top");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [provenance, setProvenance] = useState<string>("");

  const fetchFeed = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ limit: "50", provider });
      if (symbol) params.set("symbol", symbol);
      const response = await fetch(`${API_BASE}/news?${params.toString()}`);
      const payload: NewsPayload = await response.json();
      if (!response.ok && payload.status !== "available") {
        throw new Error(payload.message || `HTTP ${response.status}`);
      }
      setStories(Array.isArray(payload.items) ? payload.items : []);
      setProvenance(
        payload.provenance
          ? `${payload.provenance.source ?? "—"} · ${payload.provenance.provider_version ?? "—"}`
          : "",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load news");
      setStories([]);
    } finally {
      setLoading(false);
    }
  }, [provider, symbol]);

  // Load the source picker once, and the feed whenever it opens/changes.
  useEffect(() => {
    if (!open) return;
    fetch(`${API_BASE}/news/sources`)
      .then((r) => r.json())
      .then((d) => setSources(Array.isArray(d.sources) ? d.sources : []))
      .catch(() => setSources([]));
    fetchFeed();
  }, [open, fetchFeed]);

  // Escape closes the overlay (standard dialog behaviour).
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const visible = useMemo(() => {
    const active = TOPIC_TABS.find((tab) => tab.id === topic);
    return stories.filter((story) => matchesTopic(story, active?.keywords ?? null));
  }, [stories, topic]);

  if (!open) return null;

  return (
    <div className="news-overlay" role="dialog" aria-modal="true" aria-label="All news">
      <div className="news-overlay-panel">
        <div className="news-overlay-head">
          <div className="news-overlay-title">
            <h2>News</h2>
            <span className="news-overlay-provenance">
              {symbol ? `${symbol} · ` : ""}
              {stories.length} stories{provenance ? ` · ${provenance}` : ""}
            </span>
          </div>
          <div className="news-overlay-controls">
            <label className="news-source-picker">
              <span>Source</span>
              <select value={provider} onChange={(event) => setProvider(event.target.value)}>
                <option value="auto">Auto (Finnhub → Yahoo)</option>
                {sources.map((source) => (
                  <option key={source.id} value={source.id} disabled={!source.available}>
                    {source.name}
                    {source.available ? "" : " (unavailable)"}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="btn-secondary" onClick={onClose}>
              Close
            </button>
          </div>
        </div>

        <div className="news-overlay-tabs">
          {TOPIC_TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={`filter-chip ${topic === tab.id ? "on" : ""}`}
              onClick={() => setTopic(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="news-overlay-scroll">
          {loading && <div className="news-loading">Loading news…</div>}
          {!loading && error && (
            <div className="news-error">
              <p>Failed to load news: {error}</p>
              <button type="button" className="retry-button" onClick={fetchFeed}>
                Retry
              </button>
            </div>
          )}
          {!loading && !error && visible.length === 0 && (
            <div className="empty-state">No stories in this category.</div>
          )}
          {!loading &&
            !error &&
            visible.map((story) => (
              <a
                key={story.id}
                className="news-row"
                href={story.url || "#"}
                target="_blank"
                rel="noopener noreferrer"
              >
                {story.thumbnail ? (
                  <img className="news-row-thumb" src={story.thumbnail} alt="" loading="lazy" />
                ) : (
                  <span className="news-row-thumb placeholder" aria-hidden="true">📰</span>
                )}
                <span className="news-row-body">
                  <span className="news-row-headline">{story.headline}</span>
                  <span className="news-row-meta">
                    {story.source}
                    {story.published_at ? ` · ${timeAgo(story.published_at)}` : ""}
                    {story.related_symbols?.length ? ` · ${story.related_symbols.slice(0, 3).join(", ")}` : ""}
                  </span>
                </span>
              </a>
            ))}
        </div>
      </div>
    </div>
  );
}
