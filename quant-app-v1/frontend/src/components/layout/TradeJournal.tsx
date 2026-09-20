import { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../../lib/constants";

interface JournalEntry {
  id: string;
  strategy_id?: string;
  strategy_version?: number;
  symbol: string;
  side: "buy" | "sell";
  quantity: number;
  entry_price: number;
  exit_price?: number;
  entry_time: string;
  exit_time?: string;
  pnl?: number;
  pnl_pct?: number;
  hypothesis: string;
  entry_context: string;
  exit_context?: string;
  tags: string[];
  status: "open" | "closed";
  created_at: string;
  updated_at: string;
}

interface JournalStats {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  total_pnl: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number;
  avg_hold_time: string;
}

const SIDE_LABELS = { buy: "Buy", sell: "Sell" };
const STATUS_LABELS = { open: "Open", closed: "Closed" };

export function TradeJournal() {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [stats, setStats] = useState<JournalStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"list" | "create" | "review">("list");
  const [selectedEntry, setSelectedEntry] = useState<JournalEntry | null>(null);
  const [filters, setFilters] = useState({
    status: "all" as "all" | "open" | "closed",
    symbol: "",
    start_date: "",
    end_date: "",
    tag: "",
  });
  const [newEntryForm, setNewEntryForm] = useState({
    symbol: "",
    side: "buy" as "buy" | "sell",
    quantity: 1,
    entry_price: 0,
    hypothesis: "",
    entry_context: "",
    tags: "",
  });
  const [reviewForm, setReviewForm] = useState({
    exit_price: 0,
    exit_context: "",
    rating: 3,
    lessons: "",
  });

  const fetchEntries = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filters.status !== "all") params.append("status", filters.status);
      if (filters.symbol) params.append("symbol", filters.symbol);
      if (filters.start_date) params.append("start_date", filters.start_date);
      if (filters.end_date) params.append("end_date", filters.end_date);
      if (filters.tag) params.append("tag", filters.tag);
      
      const res = await fetch(`${API_BASE}/journal?${params.toString()}`);
      if (!res.ok) throw new Error(await res.text());
      const response = await res.json();
      setEntries(response.entries);
      setStats(response.stats);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load journal");
    } finally {
      setLoading(false);
    }
  }, [filters]);

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/journal/stats`);
      if (!res.ok) throw new Error(await res.text());
      const statsData = await res.json();
      setStats(statsData);
    } catch (err) {
      console.error("Failed to load stats:", err);
    }
  }, []);

  useEffect(() => {
    fetchEntries();
    fetchStats();
  }, [fetchEntries, fetchStats]);

  const handleCreateEntry = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const tags = newEntryForm.tags.split(",").map(s => s.trim()).filter(Boolean);
      const res = await fetch(`${API_BASE}/journal`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: newEntryForm.symbol.toUpperCase(),
          side: newEntryForm.side,
          quantity: newEntryForm.quantity,
          entry_price: newEntryForm.entry_price,
          hypothesis: newEntryForm.hypothesis,
          entry_context: newEntryForm.entry_context,
          tags,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      await res.json();
      fetchEntries();
      setActiveTab("list");
      setNewEntryForm({ symbol: "", side: "buy", quantity: 1, entry_price: 0, hypothesis: "", entry_context: "", tags: "" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create entry");
    } finally {
      setLoading(false);
    }
  };

  const handleCloseTrade = async (entryId: string) => {
    if (!reviewForm.exit_price) {
      setError("Exit price is required");
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/journal/${entryId}/close`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          exit_price: reviewForm.exit_price,
          exit_context: reviewForm.exit_context,
          rating: reviewForm.rating,
          lessons: reviewForm.lessons,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      fetchEntries();
      setSelectedEntry(null);
      setReviewForm({ exit_price: 0, exit_context: "", rating: 3, lessons: "" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to close trade");
    }
  };

  const handleDeleteEntry = async (id: string) => {
    if (!confirm("Delete this journal entry?")) return;
    try {
      const res = await fetch(`${API_BASE}/journal/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(await res.text());
      fetchEntries();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete entry");
    }
  };

  const formatPnL = (pnl?: number, pct?: number) => {
    if (pnl === undefined) return "—";
    const color = pnl >= 0 ? "text-green-600" : "text-red-600";
    return (
      <span className={color}>
        {pnl >= 0 ? "+" : ""}{pnl.toFixed(2)} {pct !== undefined ? `(${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%)` : ""}
      </span>
    );
  };

  const formatDate = (iso: string) => new Date(iso).toLocaleString();

  const filteredEntries = entries.filter(e => {
    if (filters.status !== "all" && e.status !== filters.status) return false;
    if (filters.symbol && !e.symbol.includes(filters.symbol.toUpperCase())) return false;
    if (filters.tag && !e.tags.includes(filters.tag)) return false;
    if (filters.start_date && new Date(e.created_at) < new Date(filters.start_date)) return false;
    if (filters.end_date && new Date(e.created_at) > new Date(filters.end_date)) return false;
    return true;
  });

  if (loading && entries.length === 0) {
    return <div className="journal-loading">Loading Trade Journal...</div>;
  }

  if (error) {
    return <div className="journal-error">Error: {error} <button onClick={fetchEntries}>Retry</button></div>;
  }

  return (
    <div className="trade-journal">
      <div className="journal-header">
        <h1>Trade Journal</h1>
        <div className="journal-actions">
          {activeTab !== "list" && (
            <button className="btn-secondary" onClick={() => { setActiveTab("list"); setSelectedEntry(null); }}>
              ← All Trades
            </button>
          )}
          {activeTab === "list" && (
            <button className="btn-primary" onClick={() => setActiveTab("create")}>+ New Trade</button>
          )}
        </div>
      </div>

      {activeTab === "list" && (
        <div className="journal-list">
          <div className="stats-bar">
            {stats && (
              <>
                <div className="stat-card">
                  <span className="stat-value">{stats.total_trades}</span>
                  <span className="stat-label">Total Trades</span>
                </div>
                <div className="stat-card">
                  <span className="stat-value text-green-600">{stats.win_rate.toFixed(1)}%</span>
                  <span className="stat-label">Win Rate</span>
                </div>
                <div className="stat-card">
                  <span className={`stat-value ${stats.total_pnl >= 0 ? "text-green-600" : "text-red-600"}`}>
                    {stats.total_pnl >= 0 ? "+" : ""}{stats.total_pnl.toFixed(2)}
                  </span>
                  <span className="stat-label">Total PnL</span>
                </div>
                <div className="stat-card">
                  <span className="stat-value">{stats.profit_factor.toFixed(2)}</span>
                  <span className="stat-label">Profit Factor</span>
                </div>
              </>
            )}
          </div>

          <div className="journal-filters">
            <select value={filters.status} onChange={e => setFilters({...filters, status: e.target.value as any})} className="filter-select">
              <option value="all">All Status</option>
              <option value="open">Open</option>
              <option value="closed">Closed</option>
            </select>
            <input type="text" placeholder="Symbol" value={filters.symbol} onChange={e => setFilters({...filters, symbol: e.target.value})} className="filter-input" />
            <input type="date" value={filters.start_date} onChange={e => setFilters({...filters, start_date: e.target.value})} className="filter-input" />
            <input type="date" value={filters.end_date} onChange={e => setFilters({...filters, end_date: e.target.value})} className="filter-input" />
            <input type="text" placeholder="Tag" value={filters.tag} onChange={e => setFilters({...filters, tag: e.target.value})} className="filter-input" />
          </div>

          <div className="entries-table">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th>Qty</th>
                  <th>Entry</th>
                  <th>Exit</th>
                  <th>PnL</th>
                  <th>Status</th>
                  <th>Tags</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredEntries.map(entry => (
                  <tr key={entry.id} className={entry.status === "open" ? "open-trade" : ""} onClick={() => { setSelectedEntry(entry); setActiveTab("review"); setReviewForm({exit_price: 0, exit_context: "", rating: 3, lessons: ""}); }}>
                    <td>{formatDate(entry.created_at)}</td>
                    <td className="symbol-cell">{entry.symbol}</td>
                    <td><span className={`side-badge ${entry.side}`}>{SIDE_LABELS[entry.side]}</span></td>
                    <td>{entry.quantity}</td>
                    <td>{entry.entry_price.toFixed(2)}</td>
                    <td>{entry.exit_price ? entry.exit_price.toFixed(2) : "—"}</td>
                    <td>{formatPnL(entry.pnl, entry.pnl_pct)}</td>
                    <td><span className={`status-badge ${entry.status}`}>{STATUS_LABELS[entry.status]}</span></td>
                    <td className="tags-cell">
                      {entry.tags.map(t => <span key={t} className="tag">{t}</span>)}
                    </td>
                    <td className="actions-cell">
                      <button className="btn-icon" onClick={e => { e.stopPropagation(); handleDeleteEntry(entry.id); }} title="Delete">🗑</button>
                    </td>
                  </tr>
                ))}
                {filteredEntries.length === 0 && (
                  <tr>
                    <td colSpan={10} className="empty-state">No trades found</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {activeTab === "create" && (
        <div className="journal-create">
          <h2>New Trade Entry</h2>
          <form onSubmit={handleCreateEntry} className="create-form">
            <div className="form-row">
              <div className="form-group">
                <label>Symbol</label>
                <input type="text" value={newEntryForm.symbol} onChange={e => setNewEntryForm({...newEntryForm, symbol: e.target.value.toUpperCase()})} required />
              </div>
              <div className="form-group">
                <label>Side</label>
                <select value={newEntryForm.side} onChange={e => setNewEntryForm({...newEntryForm, side: e.target.value as "buy" | "sell"})}>
                  <option value="buy">Buy</option>
                  <option value="sell">Sell</option>
                </select>
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label>Quantity</label>
                <input type="number" min="1" value={newEntryForm.quantity} onChange={e => setNewEntryForm({...newEntryForm, quantity: parseInt(e.target.value) || 1})} required />
              </div>
              <div className="form-group">
                <label>Entry Price</label>
                <input type="number" step="0.01" min="0.01" value={newEntryForm.entry_price} onChange={e => setNewEntryForm({...newEntryForm, entry_price: parseFloat(e.target.value) || 0})} required />
              </div>
            </div>
            <div className="form-group">
              <label>Hypothesis / Thesis</label>
              <textarea value={newEntryForm.hypothesis} onChange={e => setNewEntryForm({...newEntryForm, hypothesis: e.target.value})} rows={3} placeholder="Why are you taking this trade? What's your edge?" required />
            </div>
            <div className="form-group">
              <label>Entry Context (Market conditions, news, setup details)</label>
              <textarea value={newEntryForm.entry_context} onChange={e => setNewEntryForm({...newEntryForm, entry_context: e.target.value})} rows={3} placeholder="Market regime, key levels, catalysts, risk factors..." />
            </div>
            <div className="form-group">
              <label>Tags (comma-separated)</label>
              <input type="text" value={newEntryForm.tags} onChange={e => setNewEntryForm({...newEntryForm, tags: e.target.value})} placeholder="trend, breakout, earnings, etc." />
            </div>
            <div className="form-actions">
              <button type="button" className="btn-secondary" onClick={() => { setActiveTab("list"); setNewEntryForm({symbol:"",side:"buy",quantity:1,entry_price:0,hypothesis:"",entry_context:"",tags:""}) }}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={loading}>{loading ? "Creating..." : "Create Entry"}</button>
            </div>
          </form>
        </div>
      )}

      {activeTab === "review" && selectedEntry && (
        <div className="journal-review">
          <div className="review-header">
            <h2>Review Trade: {selectedEntry.symbol}</h2>
            <button className="btn-secondary" onClick={() => { setActiveTab("list"); setSelectedEntry(null); }}>← Back</button>
          </div>
          
          <div className="review-grid">
            <div className="review-summary">
              <h3>Trade Summary</h3>
              <div className="summary-row"><span>Side</span><span className={`side-badge ${selectedEntry.side}`}>{SIDE_LABELS[selectedEntry.side]}</span></div>
              <div className="summary-row"><span>Quantity</span><span>{selectedEntry.quantity}</span></div>
              <div className="summary-row"><span>Entry Price</span><span>{selectedEntry.entry_price.toFixed(2)}</span></div>
              <div className="summary-row"><span>Exit Price</span><span>{selectedEntry.exit_price?.toFixed(2) || "—"}</span></div>
              <div className="summary-row"><span>PnL</span><span>{formatPnL(selectedEntry.pnl, selectedEntry.pnl_pct)}</span></div>
              <div className="summary-row"><span>Status</span><span className={`status-badge ${selectedEntry.status}`}>{STATUS_LABELS[selectedEntry.status]}</span></div>
              <div className="summary-row"><span>Opened</span><span>{formatDate(selectedEntry.created_at)}</span></div>
              <div className="summary-row"><span>Closed</span><span>{selectedEntry.exit_time ? formatDate(selectedEntry.exit_time) : "—"}</span></div>
              <div className="summary-row"><span>Tags</span><span>{selectedEntry.tags.join(", ") || "—"}</span></div>
            </div>

            <div className="review-detail">
              <h3>Hypothesis</h3>
              <p>{selectedEntry.hypothesis || "No hypothesis recorded"}</p>
              
              <h3>Entry Context</h3>
              <p>{selectedEntry.entry_context || "No context recorded"}</p>
              
              {selectedEntry.status === "closed" && (
                <>
                  <h3>Exit Context</h3>
                  <p>{selectedEntry.exit_context || "No exit context recorded"}</p>
                </>
              )}
              
              {selectedEntry.status === "open" && (
                <div className="close-trade-form">
                  <h3>Close Trade</h3>
                  <form onSubmit={e => { e.preventDefault(); handleCloseTrade(selectedEntry.id); }} className="close-form">
                    <div className="form-group">
                      <label>Exit Price</label>
                      <input type="number" step="0.01" min="0.01" value={reviewForm.exit_price} onChange={e => setReviewForm({...reviewForm, exit_price: parseFloat(e.target.value) || 0})} required />
                    </div>
                    <div className="form-group">
                      <label>Exit Context</label>
                      <textarea value={reviewForm.exit_context} onChange={e => setReviewForm({...reviewForm, exit_context: e.target.value})} rows={3} placeholder="What happened? Why did you exit?" />
                    </div>
                    <div className="form-group">
                      <label>Trade Rating (1-5)</label>
                      <select value={reviewForm.rating} onChange={e => setReviewForm({...reviewForm, rating: parseInt(e.target.value)})}>
                        <option value={1}>1 - Poor</option>
                        <option value={2}>2 - Below Average</option>
                        <option value={3}>3 - Average</option>
                        <option value={4}>4 - Good</option>
                        <option value={5}>5 - Excellent</option>
                      </select>
                    </div>
                    <div className="form-group">
                      <label>Lessons Learned</label>
                      <textarea value={reviewForm.lessons} onChange={e => setReviewForm({...reviewForm, lessons: e.target.value})} rows={3} placeholder="What did you learn? What would you do differently?" />
                    </div>
                    <div className="form-actions">
                      <button type="button" className="btn-secondary" onClick={() => { setActiveTab("list"); setSelectedEntry(null); }}>Cancel</button>
                      <button type="submit" className="btn-primary" disabled={loading || !reviewForm.exit_price}>Close Trade</button>
                    </div>
                  </form>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}