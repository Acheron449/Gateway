import { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../../lib/constants";

interface Strategy {
  id: string;
  name: string;
  description: string;
  status: string;
  version: number;
  universe: string[];
  timeframe: string;
  tags: string[];
  created_at: string;
  updated_at: string;
}

type Tab = "list" | "create" | "editor" | "versions" | "backtest";

const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"];

interface DefaultRule {
  id: string;
  type: string;
  condition?: any;
  method?: string;
  parameters?: any;
  allowed_sessions?: string[];
  event_importance?: string[];
  blackout_minutes_before?: number;
  blackout_minutes_after?: number;
  enabled: boolean;
}

export function StrategyStudio() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState<Strategy | null>(null);
  const [versions, setVersions] = useState<any[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<any | null>(null);
  const [spec, setSpec] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("list");
  const [newStrategyForm, setNewStrategyForm] = useState({
    name: "",
    description: "",
    universe: "",
    timeframe: "1h",
    tags: "",
  });

  const fetchStrategies = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/strategies`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setStrategies(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load strategies");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStrategies();
  }, [fetchStrategies]);

  const handleCreateStrategy = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const universe = newStrategyForm.universe.split(",").map(s => s.trim().toUpperCase()).filter(Boolean);
      const tags = newStrategyForm.tags.split(",").map(s => s.trim()).filter(Boolean);
      
      const res = await fetch(`${API_BASE}/strategies`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: newStrategyForm.name,
          description: newStrategyForm.description,
          universe,
          timeframe: newStrategyForm.timeframe,
          tags,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setSelectedStrategy(data);
      setActiveTab("editor");
      fetchStrategies();
      setNewStrategyForm({ name: "", description: "", universe: "", timeframe: "1h", tags: "" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create strategy");
    } finally {
      setLoading(false);
    }
  };

  const loadStrategyVersions = useCallback(async (strategyId: string) => {
    try {
      const res = await fetch(`${API_BASE}/strategies/${strategyId}/versions`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setVersions(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load versions");
    }
  }, []);

  const loadVersionSpec = useCallback(async (strategyId: string, version: number) => {
    try {
      const res = await fetch(`${API_BASE}/strategies/${strategyId}/versions/${version}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setSpec(data.spec);
      setSelectedVersion({ version, spec: data.spec });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load version");
    }
  }, []);

  const handleSelectStrategy = (strategy: Strategy) => {
    setSelectedStrategy(strategy);
    setActiveTab("editor");
    loadStrategyVersions(strategy.id);
    loadStrategyVersions(strategy.id).then(() => {
      if (versions.length > 0) {
        loadVersionSpec(strategy.id, versions[0].version);
      }
    });
  };

  const handleSaveVersion = async () => {
    if (!selectedStrategy || !spec) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/strategies/${selectedStrategy.id}/versions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(spec),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      loadStrategyVersions(selectedStrategy.id);
      loadVersionSpec(selectedStrategy.id, data.version);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save version");
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteStrategy = async (id: string) => {
    if (!confirm("Delete this strategy and all its versions?")) return;
    try {
      const res = await fetch(`${API_BASE}/strategies/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(await res.text());
      fetchStrategies();
      if (selectedStrategy?.id === id) {
        setSelectedStrategy(null);
        setSpec(null);
        setVersions([]);
        setActiveTab("list");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete strategy");
    }
  };

  const renderRuleEditor = (rules: DefaultRule[], type: string) => (
    <div className="rule-section">
      <h4>{type.charAt(0).toUpperCase() + type.slice(1)} Rules</h4>
      {rules.map((rule, i) => (
        <div key={`${type}-${i}`} className="rule-editor">
          <div className="rule-header">
            <span>Rule {i + 1}</span>
            <button className="btn-danger btn-sm" onClick={() => removeRule(type, i)}>Remove</button>
          </div>
          <textarea
            value={JSON.stringify(rule, null, 2)}
            onChange={(e) => updateRule(type, i, JSON.parse(e.target.value))}
            rows={6}
            className="rule-textarea"
          />
        </div>
      ))}
      <button className="btn-secondary" onClick={() => addRule(type)}>+ Add {type} Rule</button>
    </div>
  );

  const addRule = (type: string) => {
    const newRule = getDefaultRule(type);
    setSpec((prev: any) => ({
      ...prev,
      [`${type}_rules`]: [...(prev[`${type}_rules`] || []), newRule]
    }));
  };

  const removeRule = (type: string, index: number) => {
    setSpec((prev: any) => ({
      ...prev,
      [`${type}_rules`]: prev[`${type}_rules`].filter((_: any, i: number) => i !== index)
    }));
  };

  const updateRule = (type: string, index: number, newRule: DefaultRule) => {
    setSpec((prev: any) => ({
      ...prev,
      [`${type}_rules`]: prev[`${type}_rules`].map((r: DefaultRule, i: number) => i === index ? newRule : r)
    }));
  };

  const getDefaultRule = (type: string): DefaultRule => {
    switch (type) {
      case "entry":
        return { id: `e${Date.now()}`, type: "entry", condition: { indicator: "RSI", operator: "<", value: 30 }, enabled: true };
      case "exit":
        return { id: `x${Date.now()}`, type: "exit", condition: { indicator: "RSI", operator: ">", value: 70 }, enabled: true };
      case "sizing":
        return { id: `s${Date.now()}`, type: "sizing", method: "fixed_fractional", parameters: { risk_per_trade: 0.02 }, enabled: true };
      case "invalidation":
        return { id: `i${Date.now()}`, type: "invalidation", condition: {}, enabled: true };
      case "session":
        return { id: `se${Date.now()}`, type: "session", allowed_sessions: ["RTH"], enabled: true };
      case "event":
        return { id: `ev${Date.now()}`, type: "event", event_importance: ["high"], blackout_minutes_before: 15, blackout_minutes_after: 15, enabled: true };
      default:
        return { id: `${type}${Date.now()}`, type, enabled: true };
    }
  };

  if (loading && strategies.length === 0) {
    return <div className="studio-loading">Loading Strategy Studio...</div>;
  }

  if (error) {
    return <div className="studio-error">Error: {error} <button onClick={fetchStrategies}>Retry</button></div>;
  }

  return (
    <div className="strategy-studio">
      <div className="studio-header">
        <h1>Strategy Studio</h1>
        <div className="studio-actions">
          {activeTab !== "list" && (
            <button className="btn-secondary" onClick={() => { setActiveTab("list"); setSelectedStrategy(null); }}>
              \u2190 All Strategies
            </button>
          )}
          {activeTab === "list" && (
            <button className="btn-primary" onClick={() => setActiveTab("create")}>+ New Strategy</button>
          )}
          {activeTab === "editor" && selectedStrategy && (
            <button className="btn-primary" onClick={handleSaveVersion} disabled={loading}>
              Save Version
            </button>
          )}
        </div>
      </div>

      {activeTab === "list" && (
        <div className="strategy-list">
          <div className="list-header">
            <h2>Strategies</h2>
            <input
              type="text"
              placeholder="Search strategies..."
              className="search-input"
              onChange={(_e) => {/* filter logic */}}
            />
          </div>
          <div className="strategy-cards">
            {strategies.map(s => (
              <div key={s.id} className={`strategy-card ${selectedStrategy?.id === s.id ? "selected" : ""}`} onClick={() => handleSelectStrategy(s)}>
                <div className="card-header">
                  <h3>{s.name}</h3>
                  <span className={`status-badge ${s.status}`}>{s.status}</span>
                </div>
                <p className="card-desc">{s.description || "No description"}</p>
                <div className="card-meta">
                  <span>v{s.version}</span>
                  <span>{s.universe.length} symbols</span>
                  <span>{s.timeframe}</span>
                </div>
                <div className="card-actions">
                  <button className="btn-icon" onClick={(_e) => { _e.stopPropagation(); handleDeleteStrategy(s.id); }} title="Delete">&#x1F5D1;</button>
                </div>
              </div>
            ))}
            {strategies.length === 0 && (
              <div className="empty-state">No strategies yet. Click "New Strategy" to create one.</div>
            )}
          </div>
        </div>
      )}

      {activeTab === "create" && (
        <div className="strategy-create">
          <h2>Create New Strategy</h2>
          <form onSubmit={handleCreateStrategy} className="create-form">
            <div className="form-group">
              <label>Name</label>
              <input type="text" value={newStrategyForm.name} onChange={e => setNewStrategyForm({...newStrategyForm, name: e.target.value})} required />
            </div>
            <div className="form-group">
              <label>Description</label>
              <textarea value={newStrategyForm.description} onChange={e => setNewStrategyForm({...newStrategyForm, description: e.target.value})} />
            </div>
            <div className="form-group">
              <label>Universe (comma-separated symbols)</label>
              <input type="text" value={newStrategyForm.universe} onChange={e => setNewStrategyForm({...newStrategyForm, universe: e.target.value})} placeholder="AAPL, MSFT, NVDA" />
            </div>
            <div className="form-group">
              <label>Timeframe</label>
              <select value={newStrategyForm.timeframe} onChange={e => setNewStrategyForm({...newStrategyForm, timeframe: e.target.value})}>
                {TIMEFRAMES.map(tf => <option key={tf} value={tf}>{tf}</option>)}
              </select>
            </div>
            <div className="form-group">
              <label>Tags (comma-separated)</label>
              <input type="text" value={newStrategyForm.tags} onChange={e => setNewStrategyForm({...newStrategyForm, tags: e.target.value})} />
            </div>
            <div className="form-actions">
              <button type="button" className="btn-secondary" onClick={() => { setActiveTab("list"); setNewStrategyForm({name:"",description:"",universe:"",timeframe:"1h",tags:""}) }}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={loading}>{loading ? "Creating..." : "Create Strategy"}</button>
            </div>
          </form>
        </div>
      )}

      {activeTab === "editor" && selectedStrategy && (
        <div className="strategy-editor">
          <div className="editor-header">
            <h2>{selectedStrategy.name} <span className="version-badge">v{selectedStrategy.version}</span></h2>
            <div className="editor-tabs">
              <button className={activeTab === "editor" ? "active" : ""} onClick={() => setActiveTab("editor")}>Editor</button>
              <button className={(activeTab as Tab) === "versions" ? "active" : ""} onClick={() => setActiveTab("versions")}>Versions</button>
              <button className={(activeTab as Tab) === "backtest" ? "active" : ""} onClick={() => setActiveTab("backtest")}>Backtest</button>
            </div>
          </div>

          {activeTab === "editor" && (
            <div className="editor-content">
              <div className="spec-panel">
                <div className="form-group">
                  <label>Name</label>
                  <input type="text" value={spec?.name || selectedStrategy.name} onChange={e => setSpec({...spec, name: e.target.value})} />
                </div>
                <div className="form-group">
                  <label>Description</label>
                  <textarea value={spec?.description || selectedStrategy.description} onChange={e => setSpec({...spec, description: e.target.value})} />
                </div>
                <div className="form-group">
                  <label>Universe</label>
                  <input type="text" value={spec?.universe?.join(", ") || selectedStrategy.universe.join(", ")} onChange={e => setSpec({...spec, universe: e.target.value.split(",").map(s => s.trim().toUpperCase()).filter(Boolean)})} />
                </div>
                <div className="form-group">
                  <label>Timeframe</label>
                  <select value={spec?.timeframe || selectedStrategy.timeframe} onChange={e => setSpec({...spec, timeframe: e.target.value})}>
                    {TIMEFRAMES.map(tf => <option key={tf} value={tf}>{tf}</option>)}
                  </select>
                </div>

                {renderRuleEditor(spec?.entry_rules || [], "entry")}
                {renderRuleEditor(spec?.exit_rules || [], "exit")}
                {renderRuleEditor(spec?.sizing_rules || [], "sizing")}
                {renderRuleEditor(spec?.invalidation_rules || [], "invalidation")}
                {renderRuleEditor(spec?.session_rules || [], "session")}
                {renderRuleEditor(spec?.event_rules || [], "event")}

                <div className="rule-section">
                  <h4>Assumptions</h4>
                  <div className="assumptions-grid">
                    <input type="number" step="0.0001" placeholder="Commission per share" value={spec?.assumptions?.commission_per_share || 0.005} onChange={e => setSpec({...spec, assumptions: {...spec.assumptions, commission_per_share: parseFloat(e.target.value)}}) } />
                    <input type="number" step="0.1" placeholder="Spread (bps)" value={spec?.assumptions?.spread_bps || 1.0} onChange={e => setSpec({...spec, assumptions: {...spec.assumptions, spread_bps: parseFloat(e.target.value)}}) } />
                    <input type="number" step="0.1" placeholder="Slippage (bps)" value={spec?.assumptions?.slippage_bps || 2.0} onChange={e => setSpec({...spec, assumptions: {...spec.assumptions, slippage_bps: parseFloat(e.target.value)}}) } />
                    <input type="number" placeholder="Latency (ms)" value={spec?.assumptions?.latency_ms || 50} onChange={e => setSpec({...spec, assumptions: {...spec.assumptions, latency_ms: parseInt(e.target.value)}}) } />
                  </div>
                </div>
              </div>
            </div>
          )}

          {(activeTab as Tab) === "versions" && (
            <div className="versions-panel">
              <h3>Strategy Versions</h3>
              {versions.map(v => (
                <div key={v.version} className={`version-row ${selectedVersion?.version === v.version ? "selected" : ""}`} onClick={() => loadVersionSpec(selectedStrategy!.id, v.version)}>
                  <span>Version {v.version}</span>
                  <span>{new Date(v.created_at).toLocaleString()}</span>
                  <span className="version-spec-preview">{JSON.stringify(v.spec).slice(0, 80)}...</span>
                </div>
              ))}
              <button className="btn-secondary" onClick={() => { /* promote logic */ }}>Promote Selected to Latest</button>
            </div>
          )}

          {(activeTab as Tab) === "backtest" && (
            <div className="backtest-panel">
              <h3>Run Backtest</h3>
              <p className="backtest-note">Select a version and configure backtest parameters to run a simulation.</p>
              <div className="backtest-config">
                <div className="form-group">
                  <label>Version to Test</label>
                  <select>
                    {versions.map(v => <option key={v.version} value={v.version}>Version {v.version}</option>)}
                  </select>
                </div>
                <div className="form-group">
                  <label>Date Range</label>
                  <div className="date-range">
                    <input type="date" />
                    <span>to</span>
                    <input type="date" />
                  </div>
                </div>
                <div className="form-group">
                  <label>Data Source</label>
                  <select>
                    <option value="yfinance">Yahoo Finance (Daily)</option>
                    <option value="alpaca">Alpaca (Hourly)</option>
                  </select>
                </div>
                <button className="btn-primary" onClick={() => { /* run backtest */ }}>Run Backtest</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}