import { useState, useEffect, useCallback, useMemo } from "react";
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

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;

const SIDE_LABELS = { buy: "Buy", sell: "Sell" };

function ymd(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function entryDay(entry: JournalEntry): string {
  // Use exit day for closed trades (the day PnL landed) and entry day otherwise.
  const source = entry.status === "closed" && entry.exit_time ? entry.exit_time : entry.entry_time;
  return ymd(new Date(source));
}

function formatPnL(pnl?: number, pct?: number): { text: string; cls: string } {
  if (pnl === undefined || pnl === null) return { text: "—", cls: "" };
  const cls = pnl >= 0 ? "positive" : "negative";
  const pctText = pct !== undefined ? ` (${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%)` : "";
  return { text: `${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}${pctText}`, cls };
}

function buildMonthCells(year: number, month: number): Date[] {
  const first = new Date(year, month, 1);
  const startOffset = (first.getDay() + 6) % 7; // Monday-first grid
  const start = new Date(year, month, 1 - startOffset);
  return Array.from({ length: 42 }, (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
}

export function TradeJournal() {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [stats, setStats] = useState<JournalStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"calendar" | "table">("calendar");
  const [statusFilter, setStatusFilter] = useState<"all" | "open" | "closed">("all");

  const today = new Date();
  const [viewYear, setViewYear] = useState(today.getFullYear());
  const [viewMonth, setViewMonth] = useState(today.getMonth());
  const [selectedDay, setSelectedDay] = useState<string | null>(ymd(today));
  const [detailEntry, setDetailEntry] = useState<JournalEntry | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [reviewForm, setReviewForm] = useState({ exit_price: 0, exit_context: "", rating: 3, lessons: "" });

  const [newEntryForm, setNewEntryForm] = useState({
    symbol: "",
    side: "buy" as "buy" | "sell",
    quantity: 1,
    entry_price: 0,
    hypothesis: "",
    entry_context: "",
    tags: "",
  });

  const fetchEntries = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (statusFilter !== "all") params.append("status", statusFilter);
      const res = await fetch(`${API_BASE}/journal?${params.toString()}`);
      if (!res.ok) throw new Error(await res.text());
      const response = await res.json();
      setEntries(Array.isArray(response.entries) ? response.entries : []);
      if (response.stats) setStats(response.stats);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load journal");
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/journal/stats`);
      if (!res.ok) return;
      setStats(await res.json());
    } catch {
      /* stats are optional decoration */
    }
  }, []);

  useEffect(() => {
    fetchEntries();
  }, [fetchEntries]);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  const handleCreateEntry = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const tags = newEntryForm.tags.split(",").map((s) => s.trim()).filter(Boolean);
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
      setShowCreate(false);
      setNewEntryForm({ symbol: "", side: "buy", quantity: 1, entry_price: 0, hypothesis: "", entry_context: "", tags: "" });
      fetchEntries();
      fetchStats();
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
      setDetailEntry(null);
      setReviewForm({ exit_price: 0, exit_context: "", rating: 3, lessons: "" });
      fetchEntries();
      fetchStats();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to close trade");
    }
  };

  const handleDeleteEntry = async (id: string) => {
    if (!confirm("Delete this journal entry?")) return;
    try {
      const res = await fetch(`${API_BASE}/journal/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(await res.text());
      setDetailEntry(null);
      fetchEntries();
      fetchStats();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete entry");
    }
  };

  const filteredEntries = useMemo(
    () => entries.filter((e) => statusFilter === "all" || e.status === statusFilter),
    [entries, statusFilter],
  );

  const byDay = useMemo(() => {
    const map = new Map<string, JournalEntry[]>();
    for (const entry of filteredEntries) {
      const day = entryDay(entry);
      const list = map.get(day);
      if (list) list.push(entry);
      else map.set(day, [entry]);
    }
    for (const list of map.values()) list.sort((a, b) => a.entry_time.localeCompare(b.entry_time));
    return map;
  }, [filteredEntries]);

  const monthCells = useMemo(() => buildMonthCells(viewYear, viewMonth), [viewYear, viewMonth]);
  const monthLabel = new Date(viewYear, viewMonth, 1).toLocaleString(undefined, { month: "long", year: "numeric" });
  const dayEntries = selectedDay ? byDay.get(selectedDay) ?? [] : [];

  const shiftMonth = (delta: number) => {
    const next = new Date(viewYear, viewMonth + delta, 1);
    setViewYear(next.getFullYear());
    setViewMonth(next.getMonth());
  };

  const dayTotals = (list: JournalEntry[]) =>
    list.reduce(
      (acc, e) => {
        if (e.status === "closed" && typeof e.pnl === "number") {
          acc.realized += e.pnl;
          acc.closed += 1;
        } else if (e.status === "open") {
          acc.open += 1;
        }
        return acc;
      },
      { realized: 0, open: 0, closed: 0 },
    );

  const openDayDetail = (entry: JournalEntry) => {
    setDetailEntry(entry);
    setReviewForm({ exit_price: 0, exit_context: "", rating: 3, lessons: "" });
  };

  if (loading && entries.length === 0) {
    return <div className="journal-loading">Loading Trade Journal…</div>;
  }

  return (
    <div className="trade-journal">
      <div className="journal-header">
        <div>
          <h1>Trade Journal</h1>
          <p className="view-description">Log trades, review the thesis, and see your month at a glance.</p>
        </div>
        <div className="journal-actions">
          <div className="journal-mode-toggle" role="group" aria-label="Journal layout">
            <button className={mode === "calendar" ? "active" : ""} onClick={() => setMode("calendar")}>
              Calendar
            </button>
            <button className={mode === "table" ? "active" : ""} onClick={() => setMode("table")}>
              Table
            </button>
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as "all" | "open" | "closed")}
            className="filter-select"
            aria-label="Filter by status"
          >
            <option value="all">All</option>
            <option value="open">Open</option>
            <option value="closed">Closed</option>
          </select>
          <button className="btn-primary" onClick={() => setShowCreate(true)}>
            + New trade
          </button>
        </div>
      </div>

      {error && (
        <div className="journal-error" role="alert">
          {error}
          <button onClick={() => setError(null)}>Dismiss</button>
        </div>
      )}

      {stats && (
        <div className="stats-bar">
          <div className="stat-card">
            <span className="stat-value">{stats.total_trades}</span>
            <span className="stat-label">Trades</span>
          </div>
          <div className="stat-card">
            <span className={`stat-value ${stats.win_rate >= 50 ? "positive" : "negative"}`}>
              {stats.win_rate.toFixed(1)}%
            </span>
            <span className="stat-label">Win rate</span>
          </div>
          <div className="stat-card">
            <span className={`stat-value ${stats.total_pnl >= 0 ? "positive" : "negative"}`}>
              {stats.total_pnl >= 0 ? "+" : ""}
              {stats.total_pnl.toFixed(2)}
            </span>
            <span className="stat-label">Total PnL</span>
          </div>
          <div className="stat-card">
            <span className="stat-value">{stats.profit_factor.toFixed(2)}</span>
            <span className="stat-label">Profit factor</span>
          </div>
        </div>
      )}

      {mode === "calendar" ? (
        <div className="journal-calendar-layout">
          <div className="journal-calendar">
            <div className="calendar-nav">
              <button className="btn-secondary" onClick={() => shiftMonth(-1)} aria-label="Previous month">
                ‹
              </button>
              <span className="calendar-month-label">{monthLabel}</span>
              <div className="calendar-nav-right">
                <button
                  className="btn-secondary"
                  onClick={() => {
                    setViewYear(today.getFullYear());
                    setViewMonth(today.getMonth());
                    setSelectedDay(ymd(today));
                  }}
                >
                  Today
                </button>
                <button className="btn-secondary" onClick={() => shiftMonth(1)} aria-label="Next month">
                  ›
                </button>
              </div>
            </div>

            <div className="calendar-weekdays" aria-hidden="true">
              {WEEKDAYS.map((w) => (
                <span key={w}>{w}</span>
              ))}
            </div>

            <div className="calendar-grid" role="grid" aria-label={`Trades in ${monthLabel}`}>
              {monthCells.map((cell) => {
                const key = ymd(cell);
                const inMonth = cell.getMonth() === viewMonth;
                const isToday = key === ymd(today);
                const dayList = byDay.get(key) ?? [];
                const totals = dayTotals(dayList);
                return (
                  <button
                    key={key}
                    className={[
                      "calendar-cell",
                      inMonth ? "" : "outside",
                      isToday ? "today" : "",
                      selectedDay === key ? "selected" : "",
                      totals.realized > 0 ? "green-day" : totals.realized < 0 ? "red-day" : "",
                    ].join(" ")}
                    onClick={() => setSelectedDay(key)}
                    role="gridcell"
                    aria-selected={selectedDay === key}
                    aria-label={`${key}, ${dayList.length} trade${dayList.length === 1 ? "" : "s"}`}
                  >
                    <span className="cell-date">{cell.getDate()}</span>
                    {dayList.length > 0 && (
                      <span className="cell-chips" aria-hidden="true">
                        {dayList.slice(0, 3).map((e) => (
                          <span
                            key={e.id}
                            className={`cell-chip ${e.status === "closed" ? (e.pnl ?? 0) >= 0 ? "win" : "loss" : "open"}`}
                          >
                            {e.symbol}
                          </span>
                        ))}
                        {dayList.length > 3 && <span className="cell-more">+{dayList.length - 3}</span>}
                      </span>
                    )}
                    {totals.closed > 0 && (
                      <span className={`cell-pnl ${totals.realized >= 0 ? "positive" : "negative"}`}>
                        {totals.realized >= 0 ? "+" : ""}
                        {totals.realized.toFixed(0)}
                      </span>
                    )}
                    {totals.closed === 0 && totals.open > 0 && <span className="cell-open-count">{totals.open} open</span>}
                  </button>
                );
              })}
            </div>
          </div>

          <aside className="journal-day-panel" aria-label="Selected day trades">
            <h3 className="day-panel-title">
              {selectedDay
                ? new Date(`${selectedDay}T12:00:00`).toLocaleDateString(undefined, {
                    weekday: "long",
                    month: "short",
                    day: "numeric",
                  })
                : "Pick a day"}
            </h3>
            {dayEntries.length === 0 ? (
              <p className="empty-state">No trades on this day.</p>
            ) : (
              <ul className="day-trade-list">
                {dayEntries.map((entry) => {
                  const pnl = formatPnL(entry.pnl, entry.pnl_pct);
                  return (
                    <li key={entry.id}>
                      <button className="day-trade-card" onClick={() => openDayDetail(entry)}>
                        <div className="day-trade-top">
                          <span className="day-trade-symbol">{entry.symbol}</span>
                          <span className={`side-badge ${entry.side}`}>{SIDE_LABELS[entry.side]}</span>
                          <span className={`status-badge ${entry.status}`}>{entry.status === "open" ? "Open" : "Closed"}</span>
                        </div>
                        <div className="day-trade-meta">
                          {entry.quantity} @ {entry.entry_price.toFixed(2)}
                          {entry.exit_price ? ` → ${entry.exit_price.toFixed(2)}` : ""}
                        </div>
                        {entry.status === "closed" && (
                          <div className={`day-trade-pnl ${pnl.cls}`}>{pnl.text}</div>
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </aside>
        </div>
      ) : (
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
              </tr>
            </thead>
            <tbody>
              {filteredEntries.map((entry) => {
                const pnl = formatPnL(entry.pnl, entry.pnl_pct);
                return (
                  <tr key={entry.id} className={entry.status === "open" ? "open-trade" : ""} onClick={() => openDayDetail(entry)}>
                    <td>{new Date(entry.entry_time).toLocaleDateString()}</td>
                    <td className="symbol-cell">{entry.symbol}</td>
                    <td>
                      <span className={`side-badge ${entry.side}`}>{SIDE_LABELS[entry.side]}</span>
                    </td>
                    <td>{entry.quantity}</td>
                    <td>{entry.entry_price.toFixed(2)}</td>
                    <td>{entry.exit_price ? entry.exit_price.toFixed(2) : "—"}</td>
                    <td className={pnl.cls}>{pnl.text}</td>
                    <td>
                      <span className={`status-badge ${entry.status}`}>{entry.status === "open" ? "Open" : "Closed"}</span>
                    </td>
                    <td className="tags-cell">
                      {entry.tags.map((t) => (
                        <span key={t} className="tag">
                          {t}
                        </span>
                      ))}
                    </td>
                  </tr>
                );
              })}
              {filteredEntries.length === 0 && (
                <tr>
                  <td colSpan={9} className="empty-state">
                    No trades found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && (
        <div className="journal-modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && setShowCreate(false)}>
          <div className="journal-modal" role="dialog" aria-modal="true" aria-label="New trade entry">
            <div className="journal-modal-header">
              <h2>New trade entry</h2>
              <button className="auth-close" onClick={() => setShowCreate(false)} aria-label="Close">
                ✕
              </button>
            </div>
            <form onSubmit={handleCreateEntry} className="create-form">
              <div className="form-row">
                <div className="form-group">
                  <label>Symbol</label>
                  <input
                    type="text"
                    value={newEntryForm.symbol}
                    onChange={(e) => setNewEntryForm({ ...newEntryForm, symbol: e.target.value.toUpperCase() })}
                    required
                  />
                </div>
                <div className="form-group">
                  <label>Side</label>
                  <select
                    value={newEntryForm.side}
                    onChange={(e) => setNewEntryForm({ ...newEntryForm, side: e.target.value as "buy" | "sell" })}
                  >
                    <option value="buy">Buy</option>
                    <option value="sell">Sell</option>
                  </select>
                </div>
              </div>
              <div className="form-row">
                <div className="form-group">
                  <label>Quantity</label>
                  <input
                    type="number"
                    min="1"
                    value={newEntryForm.quantity}
                    onChange={(e) => setNewEntryForm({ ...newEntryForm, quantity: parseInt(e.target.value) || 1 })}
                    required
                  />
                </div>
                <div className="form-group">
                  <label>Entry price</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0.01"
                    value={newEntryForm.entry_price}
                    onChange={(e) => setNewEntryForm({ ...newEntryForm, entry_price: parseFloat(e.target.value) || 0 })}
                    required
                  />
                </div>
              </div>
              <div className="form-group">
                <label>Hypothesis / thesis</label>
                <textarea
                  value={newEntryForm.hypothesis}
                  onChange={(e) => setNewEntryForm({ ...newEntryForm, hypothesis: e.target.value })}
                  rows={3}
                  placeholder="Why are you taking this trade? What's your edge?"
                  required
                />
              </div>
              <div className="form-group">
                <label>Entry context (market conditions, news, setup)</label>
                <textarea
                  value={newEntryForm.entry_context}
                  onChange={(e) => setNewEntryForm({ ...newEntryForm, entry_context: e.target.value })}
                  rows={2}
                  placeholder="Market regime, key levels, catalysts, risk factors…"
                />
              </div>
              <div className="form-group">
                <label>Tags (comma-separated)</label>
                <input
                  type="text"
                  value={newEntryForm.tags}
                  onChange={(e) => setNewEntryForm({ ...newEntryForm, tags: e.target.value })}
                  placeholder="trend, breakout, earnings…"
                />
              </div>
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={() => setShowCreate(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn-primary" disabled={loading}>
                  {loading ? "Creating…" : "Create entry"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {detailEntry && (
        <div className="journal-modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && setDetailEntry(null)}>
          <div className="journal-modal" role="dialog" aria-modal="true" aria-label={`Review ${detailEntry.symbol}`}>
            <div className="journal-modal-header">
              <h2>
                Review {detailEntry.symbol} <span className={`side-badge ${detailEntry.side}`}>{SIDE_LABELS[detailEntry.side]}</span>
              </h2>
              <div className="journal-modal-header-actions">
                <button className="btn-icon" onClick={() => handleDeleteEntry(detailEntry.id)} title="Delete entry">
                  🗑
                </button>
                <button className="auth-close" onClick={() => setDetailEntry(null)} aria-label="Close">
                  ✕
                </button>
              </div>
            </div>

            <div className="review-grid">
              <div className="review-summary">
                <div className="summary-row"><span>Quantity</span><span>{detailEntry.quantity}</span></div>
                <div className="summary-row"><span>Entry price</span><span>{detailEntry.entry_price.toFixed(2)}</span></div>
                <div className="summary-row"><span>Exit price</span><span>{detailEntry.exit_price?.toFixed(2) || "—"}</span></div>
                <div className="summary-row">
                  <span>PnL</span>
                  <span className={formatPnL(detailEntry.pnl, detailEntry.pnl_pct).cls}>
                    {formatPnL(detailEntry.pnl, detailEntry.pnl_pct).text}
                  </span>
                </div>
                <div className="summary-row"><span>Opened</span><span>{new Date(detailEntry.entry_time).toLocaleString()}</span></div>
                <div className="summary-row">
                  <span>Closed</span>
                  <span>{detailEntry.exit_time ? new Date(detailEntry.exit_time).toLocaleString() : "—"}</span>
                </div>
                <div className="summary-row"><span>Tags</span><span>{detailEntry.tags.join(", ") || "—"}</span></div>
              </div>

              <div className="review-detail">
                <h3>Hypothesis</h3>
                <p>{detailEntry.hypothesis || "No hypothesis recorded"}</p>
                <h3>Entry context</h3>
                <p>{detailEntry.entry_context || "No context recorded"}</p>
                {detailEntry.status === "closed" && (
                  <>
                    <h3>Exit context</h3>
                    <p>{detailEntry.exit_context || "No exit context recorded"}</p>
                  </>
                )}
              </div>
            </div>

            {detailEntry.status === "open" && (
              <div className="close-trade-form">
                <h3>Close trade</h3>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    handleCloseTrade(detailEntry.id);
                  }}
                  className="close-form"
                >
                  <div className="form-row">
                    <div className="form-group">
                      <label>Exit price</label>
                      <input
                        type="number"
                        step="0.01"
                        min="0.01"
                        value={reviewForm.exit_price}
                        onChange={(e) => setReviewForm({ ...reviewForm, exit_price: parseFloat(e.target.value) || 0 })}
                        required
                      />
                    </div>
                    <div className="form-group">
                      <label>Rating (1–5)</label>
                      <select value={reviewForm.rating} onChange={(e) => setReviewForm({ ...reviewForm, rating: parseInt(e.target.value) })}>
                        <option value={1}>1 — Poor</option>
                        <option value={2}>2 — Below average</option>
                        <option value={3}>3 — Average</option>
                        <option value={4}>4 — Good</option>
                        <option value={5}>5 — Excellent</option>
                      </select>
                    </div>
                  </div>
                  <div className="form-group">
                    <label>Exit context</label>
                    <textarea
                      value={reviewForm.exit_context}
                      onChange={(e) => setReviewForm({ ...reviewForm, exit_context: e.target.value })}
                      rows={2}
                      placeholder="What happened? Why did you exit?"
                    />
                  </div>
                  <div className="form-group">
                    <label>Lessons learned</label>
                    <textarea
                      value={reviewForm.lessons}
                      onChange={(e) => setReviewForm({ ...reviewForm, lessons: e.target.value })}
                      rows={2}
                      placeholder="What would you do differently?"
                    />
                  </div>
                  <div className="form-actions">
                    <button type="button" className="btn-secondary" onClick={() => setDetailEntry(null)}>
                      Cancel
                    </button>
                    <button type="submit" className="btn-primary" disabled={loading || !reviewForm.exit_price}>
                      Close trade
                    </button>
                  </div>
                </form>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
