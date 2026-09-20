import { useEffect, useState, useCallback } from "react";

import { API_BASE } from "../../lib/constants";

interface NewsItem {
  id: string;
  headline: string;
  url?: string;
  source: string;
  published_at: string;
  fetched_at: string;
  categories: string[];
  related_symbols: string[];
  sentiment_score?: number | null;
  provider_version: string;
}

interface NewsResponse {
  items: NewsItem[];
  provenance: {
    source: string;
    provider_version: string;
    coverage: string;
    entitlement: string;
  };
  count: number;
}

export function NewsFeed({ ticker }: { ticker?: string }) {
  const [items, setItems] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [provenance, setProvenance] = useState<NewsResponse["provenance"] | null>(null);

  const fetchNews = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const url = ticker ? `${API_BASE}/news?symbol=${encodeURIComponent(ticker)}&limit=20` : `${API_BASE}/news?limit=20`;
      const response = await fetch(url);
      if (!response.ok) {
        if (response.status === 503) {
          // News endpoint not available yet (Phase 2)
          setItems([]);
          setProvenance({ source: "unavailable", provider_version: "N/A", coverage: "N/A", entitlement: "N/A" });
          return;
        }
        const errText = await response.text();
        throw new Error(errText || `HTTP ${response.status}`);
      }
      const data: NewsResponse = await response.json();
      setItems(data.items);
      setProvenance(data.provenance);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load news");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [ticker]);

  useEffect(() => {
    fetchNews();
  }, [fetchNews]);

  const formatDate = (isoString: string) => {
    const date = new Date(isoString);
    return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  };

  const formatAge = (isoString: string) => {
    const ageMs = Date.now() - new Date(isoString).getTime();
    const minutes = Math.floor(ageMs / 60000);
    const hours = Math.floor(ageMs / 3600000);
    const days = Math.floor(ageMs / 86400000);
    if (minutes < 60) return `${minutes}m ago`;
    if (hours < 24) return `${hours}h ago`;
    return `${days}d ago`;
  };

  const getSentimentClass = (score?: number | null) => {
    if (score === null || score === undefined) return "neutral";
    if (score > 0.2) return "positive";
    if (score < -0.2) return "negative";
    return "neutral";
  };

  const getSentimentLabel = (score?: number | null) => {
    if (score === null || score === undefined) return "—";
    if (score > 0.2) return `📈 ${(score * 100).toFixed(0)}%`;
    if (score < -0.2) return `📉 ${(score * 100).toFixed(0)}%`;
    return `➖ ${(score * 100).toFixed(0)}%`;
  };

  if (loading) {
    return (
      <div className="news-feed loading">
        <div className="news-loading">Loading news...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="news-feed error">
        <div className="news-error">
          <p>Failed to load news: {error}</p>
          <button onClick={fetchNews} className="retry-button">Retry</button>
        </div>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="news-feed empty">
        <div className="empty-state">
          <p>No news available</p>
          {provenance?.source === "unavailable" && (
            <p className="hint">News integration coming in Phase 2 (licensed provider required)</p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="news-feed">
      <div className="news-toolbar">
        <h2 className="news-title">News</h2>
        <div className="news-provenance">
          {provenance && (
            <span className="provenance-badge">
              Source: {provenance.source} · {provenance.provider_version} · {provenance.entitlement}
            </span>
          )}
        </div>
      </div>

      <div className="news-list">
        {items.map((item) => (
          <article key={item.id} className="news-card">
            <div className="news-card-header">
              <span className="news-source">{item.source}</span>
              <span className="news-age">{formatAge(item.published_at)}</span>
            </div>
            <a href={item.url || "#"} target="_blank" rel="noopener noreferrer" className="news-headline">
              {item.headline}
            </a>
            <div className="news-meta">
              <span className="news-timestamp">Published: {formatDate(item.published_at)}</span>
              {item.related_symbols.length > 0 && (
                <span className="news-symbols">
                  {item.related_symbols.map((s, i) => (
                    <span key={s} className="news-symbol" style={{ marginRight: i < item.related_symbols.length - 1 ? '6px' : 0 }}>
                      {s}
                    </span>
                  ))}
                </span>
              )}
              {item.sentiment_score !== null && item.sentiment_score !== undefined && (
                <span className={`news-sentiment ${getSentimentClass(item.sentiment_score)}`}>
                  {getSentimentLabel(item.sentiment_score)}
                </span>
              )}
            </div>
            {item.categories.length > 0 && (
              <div className="news-categories">
                {item.categories.map((c) => (
                  <span key={c} className="news-category">{c}</span>
                ))}
              </div>
            )}
          </article>
        ))}
      </div>
    </div>
  );
}