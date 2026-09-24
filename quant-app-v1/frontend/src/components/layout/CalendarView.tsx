import { useEffect, useState, useCallback } from "react";
import { API_BASE } from "../../lib/constants";

interface EconomicEvent {
  id: string;
  title: string;
  country: string;
  currency: string;
  importance: "low" | "medium" | "high";
  scheduled_at: string;
  actual?: number | null;
  forecast?: number | null;
  prior?: number | null;
  revisions: Array<{ timestamp: string; value: number }>;
  related_symbols: string[];
  provider_version: string;
}

interface CalendarResponse {
  events: EconomicEvent[];
  provenance: {
    source: string;
    provider_version: string;
    coverage: string;
    entitlement: string;
    message?: string;
  };
  count: number;
  status?: string;
  message?: string;
}

function formatDateTime(isoString: string): { date: string; time: string } {
  const date = new Date(isoString);
  return {
    date: date.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }),
    time: date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", timeZoneName: "short" }),
  };
}

function getImportanceClass(importance: string): string {
  switch (importance) {
    case "high": return "importance-high";
    case "medium": return "importance-medium";
    case "low": return "importance-low";
    default: return "";
  }
}

function getImportanceLabel(importance: string): string {
  return importance.charAt(0).toUpperCase() + importance.slice(1);
}

function EventRow({ event, onClick, formatDateTime, getImportanceClass, getImportanceLabel }: {
  event: EconomicEvent;
  onClick: () => void;
  formatDateTime: (iso: string) => { date: string; time: string };
  getImportanceClass: (imp: string) => string;
  getImportanceLabel: (imp: string) => string;
}) {
  const { date, time } = formatDateTime(event.scheduled_at);
  const importanceClass = getImportanceClass(event.importance);
  const importanceLabel = getImportanceLabel(event.importance);

  return (
    <div
      key={event.id}
      className={`calendar-event ${importanceClass}`}
      onClick={onClick}
    >
      <div className="event-time">
        <span className="event-date">{date}</span>
        <span className="event-time">{time}</span>
      </div>
      <div className="event-details">
        <span className="event-title">{event.title}</span>
        <div className="event-meta">
          <span className="event-country">{event.country}</span>
          <span className={`event-importance ${importanceClass}`}>{importanceLabel}</span>
        </div>
      </div>
      <div className="event-values">
        {event.forecast !== null && event.forecast !== undefined && (
          <span className="event-value forecast">F: {event.forecast}</span>
        )}
        {event.prior !== null && event.prior !== undefined && (
          <span className="event-value prior">P: {event.prior}</span>
        )}
        {event.actual !== null && event.actual !== undefined && (
          <span className="event-value actual">A: {event.actual}</span>
        )}
      </div>
    </div>
  );
}

function EventDetailPanel({ 
  event, 
  onClose, 
  provenance, 
  getImportanceClass, 
  getImportanceLabel 
}: {
  event: EconomicEvent;
  onClose: () => void;
  provenance: CalendarResponse["provenance"] | null;
  getImportanceClass: (imp: string) => string;
  getImportanceLabel: (imp: string) => string;
}) {
  return (
    <div className="event-detail-overlay" onClick={onClose}>
      <div className="event-detail-panel" onClick={(e) => e.stopPropagation()}>
        <button className="close-button" onClick={onClose} aria-label="Close">×</button>
        <h3>{event.title}</h3>
        <div className="detail-meta">
          <div><strong>Country:</strong> {event.country} ({event.currency})</div>
          <div><strong>Importance:</strong> <span className={getImportanceClass(event.importance)}>{getImportanceLabel(event.importance)}</span></div>
          <div><strong>Scheduled:</strong> {new Date(event.scheduled_at).toLocaleString()}</div>
          {event.forecast !== null && event.forecast !== undefined && (
            <div><strong>Forecast:</strong> {event.forecast}</div>
          )}
          {event.prior !== null && event.prior !== undefined && (
            <div><strong>Prior:</strong> {event.prior}</div>
          )}
          {event.actual !== null && event.actual !== undefined && (
            <div><strong>Actual:</strong> {event.actual}</div>
          )}
          {event.revisions && event.revisions.length > 0 && (
            <div>
              <strong>Revisions:</strong>
              <ul>
                {event.revisions.map((rev, i) => (
                  <li key={i}>{new Date(rev.timestamp).toLocaleString()}: {rev.value}</li>
                ))}
              </ul>
            </div>
          )}
          {event.related_symbols && event.related_symbols.length > 0 && (
            <div><strong>Related Symbols:</strong> {event.related_symbols.join(", ")}</div>
          )}
        </div>
        <div className="detail-provenance">
          <strong>Provenance:</strong>
          <ul>
            <li>Source: {provenance?.source ?? "—"}</li>
            <li>Provider Version: {provenance?.provider_version ?? "—"}</li>
            <li>Coverage: {provenance?.coverage ?? "—"}</li>
            <li>Entitlement: {provenance?.entitlement ?? "—"}</li>
          </ul>
        </div>
      </div>
    </div>
  );
}

export function CalendarView() {
  const [events, setEvents] = useState<EconomicEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<EconomicEvent | null>(null);
  const [provenance, setProvenance] = useState<CalendarResponse["provenance"] | null>(null);
  const [filterImportance, setFilterImportance] = useState<"all" | "high" | "medium" | "low">("all");
  const [filterCurrency, setFilterCurrency] = useState<string>("all");

  const fetchEvents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/news/calendar?limit=50`);
      if (!response.ok) {
        const errText = await response.text();
        throw new Error(errText || `HTTP ${response.status}`);
      }
      const data: CalendarResponse = await response.json();
      setEvents(data.events);
      setProvenance(data.provenance);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load calendar events");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchEvents();
  }, [fetchEvents]);

  const filteredEvents = events.filter((event) => {
    if (filterImportance !== "all" && event.importance !== filterImportance) return false;
    if (filterCurrency !== "all" && event.currency !== filterCurrency) return false;
    return true;
  });

  const currencies = Array.from(new Set(events.map((e) => e.currency))).sort();

  if (loading) {
    return <div className="calendar-view loading"><div className="calendar-loading">Loading calendar events...</div></div>;
  }

  if (error) {
    return (
      <div className="calendar-view error">
        <div className="calendar-error">
          <p>Failed to load calendar: {error}</p>
          <button onClick={fetchEvents} className="retry-button">Retry</button>
        </div>
      </div>
    );
  }

  if (filteredEvents.length === 0) {
    return <div className="calendar-view empty"><p className="empty-state">No calendar events found</p></div>;
  }

  return (
    <div className="calendar-view">
      <div className="calendar-toolbar">
        <div className="toolbar-filters">
          <select
            value={filterImportance}
            onChange={(e) => setFilterImportance(e.target.value as "all" | "high" | "medium" | "low")}
            className="filter-select"
            aria-label="Filter by importance"
          >
            <option value="all">All Importance</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
          <select
            value={filterCurrency}
            onChange={(e) => setFilterCurrency(e.target.value)}
            className="filter-select"
            aria-label="Filter by currency"
          >
            <option value="all">All Currencies</option>
            {currencies.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>
        <div className="toolbar-provenance">
          {provenance && (
            <span className="provenance-badge">
              Source: {provenance.source} · {provenance.provider_version} · {provenance.entitlement}
            </span>
          )}
        </div>
      </div>

      <div className="calendar-events">
        {filteredEvents.map((event) => (
          <EventRow
            key={event.id}
            event={event}
            onClick={() => setSelectedEvent(event)}
            formatDateTime={formatDateTime}
            getImportanceClass={getImportanceClass}
            getImportanceLabel={getImportanceLabel}
          />
        ))}
      </div>

      {selectedEvent && (
        <EventDetailPanel
          event={selectedEvent}
          onClose={() => setSelectedEvent(null)}
          provenance={provenance}
          getImportanceClass={getImportanceClass}
          getImportanceLabel={getImportanceLabel}
        />
      )}
    </div>
  );
}