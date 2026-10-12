import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import Backtester, { type BtRun } from "./Backtester";
import { API_BASE } from "../../lib/constants";
import { readProviderCache, writeProviderCache } from "../../lib/providerCache";
import { useAuth } from "../../context/AuthContext";
import { useAuthUI } from "../../context/AuthUIContext";
import { PairsBacktestLauncher } from "../../components/features/PairsBacktestLauncher";

/* eslint-disable @typescript-eslint/no-explicit-any */
interface LlmProvider {
  id: string; label: string; group: "compatible" | "foundation"; configured: boolean; models: string[]; default_model: string | null;
}
interface LabAgent {
  id: string; name: string; kind: string; baseline: string | null; provider: string | null; model: string | null; prompt: string; symbol: string | null; tf: string; created_at: string;
}
interface LabRun extends BtRun {
  agent_id: string | null;
  risk_rules?: { max_position_pct: number; max_drawdown_pct: number; allow_short: boolean };
  owner_user_id?: string; research_job_id?: string; research_iteration?: number;
}
interface ResearchDoc {
  id: string; title: string; content: string; source: "typed" | "uploaded" | "model"; symbol: string | null; provider: string | null; model: string | null; created_at: string; chars: number;
}
const TABS = [
  { id: "dashboard", label: "LLMs" }, { id: "research", label: "Research" }, { id: "log", label: "Trading Log" },
  { id: "backtests", label: "Backtests" }, { id: "pairs", label: "Cointegration Pairs" },
] as const;
type TabId = (typeof TABS)[number]["id"];
const validTab = (value: string | null): TabId => TABS.some((tab) => tab.id === value) ? value as TabId : "dashboard";
function authHeaders(): Record<string, string> { const token = localStorage.getItem("gateway_auth_token"); return token ? { Authorization: `Bearer ${token}` } : {}; }
async function readError(response: Response, fallback: string): Promise<string> {
  const text = await response.text().catch(() => "");
  if (!text) return `${response.status} ${response.statusText}`.trim();
  try { const payload = JSON.parse(text) as any; if (payload && typeof payload === "object" && typeof payload.detail === "string") return payload.detail; } catch { /* not JSON */ }
  return text.slice(0, 300) || fallback;
}
const DEFAULT_AGENT_PROMPT = "You are a systematic trader. Using only the market window provided, decide the next position: long, flat, or short. Consider trend, momentum, and volatility. Answer with JSON only: {\"action\": \"long|flat|short\", \"reason\": \"one sentence\"}.";
function RiskBadge({ run }: { run: LabRun }) {
  const halted = run.metrics?.risk_halted === true, overrides = run.metrics?.risk_overrides ?? 0, rules = run.risk_rules;
  if (!rules) return null;
  const title = `${rules.max_position_pct}% position · ${rules.max_drawdown_pct > 0 ? `${rules.max_drawdown_pct}% halt` : "no halt"} · ${rules.allow_short ? "shorts on" : "no shorts"}`;
  return <span className={`risk-badge ${halted ? "halted" : overrides > 0 ? "touched" : "clean"}`} title={title}>🛡️ {halted ? "Halted by risk guard" : overrides > 0 ? `${overrides} risk overrides` : "Risk guard: clean"}</span>;
}
function StatGrid({ metrics }: { metrics: Record<string, any> }) {
  const stats = Array.isArray(metrics?.stats) ? metrics.stats : [];
  return stats.length ? <div className="stat-grid">{stats.map((stat: any) => <div key={stat.label} className="stat-cell" title={stat.hint}><span className="stat-label">{stat.label}</span><span className="stat-value">{stat.value}</span></div>)}</div> : null;
}
function VerdictChip({ metrics }: { metrics: Record<string, any> }) {
  if (!metrics?.verdict) return null;
  const tone = metrics.verdict_tone === "good" ? "good" : metrics.verdict_tone === "bad" ? "bad" : "neutral";
  return <span className={`verdict-chip ${tone}`}>{metrics.verdict}</span>;
}

interface AgenticLabProps { selectedSymbol: string; runs: BtRun[]; error: string | null; onRefresh: () => void }
export function AgenticLab({ selectedSymbol, runs: sharedRuns, error: runsError, onRefresh }: AgenticLabProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const { isAuthenticated } = useAuth();
  const { openAuth } = useAuthUI();
  const runs = sharedRuns as LabRun[];
  const [backtestsLoading, setBacktestsLoading] = useState(true);
  const [tab, setTab] = useState<TabId>(() => validTab(searchParams.get("tab")));
  const sessionHeaders = useCallback((): Record<string, string> => {
    const token = localStorage.getItem("gateway_auth_token");
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, []);
  const [providers, setProviders] = useState<LlmProvider[]>([]), [agents, setAgents] = useState<LabAgent[]>([]), [research, setResearch] = useState<ResearchDoc[]>([]), [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "ready" | "results">("all"), [risk] = useState({ max_position_pct: 100, max_drawdown_pct: 0, allow_short: true });
  const [configAgent, setConfigAgent] = useState<string | null>(null), [, setJobId] = useState<string | null>(null), [, setJobState] = useState<Record<string, any> | null>(null), [agentRuns, setAgentRuns] = useState<Record<string, LabRun>>({});
  const [creating, setCreating] = useState(false), [draftName, setDraftName] = useState(""), [draftProvider, setDraftProvider] = useState(""), [draftModel, setDraftModel] = useState(""), [draftPrompt, setDraftPrompt] = useState(DEFAULT_AGENT_PROMPT);
  const [researchMode, setResearchMode] = useState<"list" | "type" | "upload" | "generate">("list"), [researchTitle, setResearchTitle] = useState(""), [researchBody, setResearchBody] = useState(""), [researchTopic, setResearchTopic] = useState(""), [researchProvider, setResearchProvider] = useState(""), [researchModel, setResearchModel] = useState(""), [researchBusy, setResearchBusy] = useState(false), [researchMsg, setResearchMsg] = useState<string | null>(null), [openDoc, setOpenDoc] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [loopObjective, setLoopObjective] = useState(""), [loopIterations, setLoopIterations] = useState(3), [loopCallCap, setLoopCallCap] = useState(8), [loopTf, setLoopTf] = useState("1d"), [loopBars, setLoopBars] = useState(260), [loopJobId, setLoopJobId] = useState<string | null>(null), [loopJobState, setLoopJobState] = useState<Record<string, any> | null>(null), [loopBusy, setLoopBusy] = useState(false);
  const loopPollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [logDays, setLogDays] = useState(30), [logSymbol, setLogSymbol] = useState(""), [log, setLog] = useState<Record<string, any> | null>(null), [logLoading, setLogLoading] = useState(false);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const configuredProviders = useMemo(() => providers.filter((provider) => provider.configured), [providers]);
  const refresh = useCallback(async () => {
    try {
      const [providerResponse, agentResponse, researchResponse] = await Promise.all([fetch(`${API_BASE}/llm/providers`), fetch(`${API_BASE}/agentic-lab/agents`), fetch(`${API_BASE}/agentic-lab/research`, { headers: sessionHeaders() })]);
      if (providerResponse.ok) { const data = await providerResponse.json() as { providers: LlmProvider[] }; setProviders(data.providers); writeProviderCache("llm", data); }
      if (agentResponse.ok) setAgents(((await agentResponse.json()) as { agents: LabAgent[] }).agents);
      if (researchResponse.ok) setResearch(((await researchResponse.json()) as { research: ResearchDoc[] }).research);
    } catch (err) { setError(err instanceof Error ? err.message : "Failed to load the lab"); }
    await onRefresh();
  }, [onRefresh, sessionHeaders]);
  useEffect(() => {
    const cached = readProviderCache<{ providers: LlmProvider[] }>("llm");
    if (cached?.providers?.length) setProviders(cached.providers);
    void refresh();
    return () => { if (pollRef.current) clearTimeout(pollRef.current); if (loopPollRef.current) clearTimeout(loopPollRef.current); };
  }, [refresh]);
  useEffect(() => { const next = validTab(searchParams.get("tab")); if (next !== tab) setTab(next); }, [searchParams, tab]);
  useEffect(() => { if (!runsError) setBacktestsLoading(false); }, [runsError, sharedRuns]);
  const selectTab = (next: TabId) => { setTab(next); setSearchParams(next === "dashboard" ? {} : { tab: next }, { replace: true }); };
  useEffect(() => {
    const provider = configuredProviders[0]?.id;
    if (provider) { if (!draftProvider) setDraftProvider(provider); if (!researchProvider) setResearchProvider(provider); }
  }, [configuredProviders, draftProvider, researchProvider]);
  const modelsFor = useCallback((id: string) => providers.find((provider) => provider.id === id)?.models ?? [], [providers]);
  const requireAuth = useCallback(() => { if (isAuthenticated) return true; setError("Sign in to run lab actions — they spend API credits."); return false; }, [isAuthenticated]);

  const runBacktest = useCallback(async (agent: LabAgent) => {
    if (!requireAuth()) return;
    setError(null); setConfigAgent(null); setJobId(null); setJobState(null);
    try {
      const response = await fetch(`${API_BASE}/agentic-lab/backtest`, { method: "POST", headers: { "Content-Type": "application/json", ...authHeaders() }, body: JSON.stringify({ agent_id: agent.id, kind: agent.kind, baseline: agent.baseline, provider: agent.provider, model: agent.model, prompt: agent.prompt, symbol: (agent.symbol || selectedSymbol).toUpperCase(), tf: agent.tf || "1d", bars: 260, max_llm_calls: 12, risk }) });
      if (!response.ok) throw new Error(await readError(response, "Could not start backtest"));
      const { job_id } = await response.json() as { job_id: string }; setJobId(job_id);
      const poll = async () => { try { const response = await fetch(`${API_BASE}/agentic-lab/jobs/${job_id}`); if (!response.ok) return; const state = await response.json() as Record<string, any>; setJobState(state); if (state.status === "queued" || state.status === "running") pollRef.current = setTimeout(() => void poll(), 1200); else if (state.status === "succeeded" && state.result) { setAgentRuns((current) => ({ ...current, [agent.id]: state.result as LabRun })); await refresh(); } } catch (err) { setError(err instanceof Error ? err.message : "Polling failed"); } };
      void poll();
    } catch (err) { setError(err instanceof Error ? err.message : "Could not start backtest"); }
  }, [requireAuth, selectedSymbol, refresh, risk]);

  const createAgent = useCallback(async () => {
    if (!requireAuth()) return;
    try { const response = await fetch(`${API_BASE}/agentic-lab/agents`, { method: "POST", headers: { "Content-Type": "application/json", ...authHeaders() }, body: JSON.stringify({ name: draftName.trim() || `${draftModel || "Untitled"} agent`, kind: "llm", provider: draftProvider, model: draftModel || (modelsFor(draftProvider)[0] ?? ""), prompt: draftPrompt.trim() || DEFAULT_AGENT_PROMPT, symbol: selectedSymbol, tf: "1d" }) }); if (!response.ok) throw new Error(await readError(response, "Could not save agent")); setCreating(false); setDraftName(""); await refresh(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not save agent"); }
  }, [requireAuth, draftName, draftProvider, draftModel, draftPrompt, selectedSymbol, modelsFor, refresh]);
  const updateAgent = useCallback(async (agent: LabAgent, changes: Partial<LabAgent>) => {
    if (!requireAuth()) return;
    try { const response = await fetch(`${API_BASE}/agentic-lab/agents`, { method: "POST", headers: { "Content-Type": "application/json", ...authHeaders() }, body: JSON.stringify({ ...agent, ...changes }) }); if (!response.ok) throw new Error(await readError(response, "Could not update agent")); setConfigAgent(null); await refresh(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not update agent"); }
  }, [requireAuth, refresh]);
  const removeAgent = useCallback(async (agent: LabAgent) => {
    if (!window.confirm(`Delete agent "${agent.name}"?`) || !requireAuth()) return;
    try { const response = await fetch(`${API_BASE}/agentic-lab/agents/${agent.id}`, { method: "DELETE", headers: authHeaders() }); if (!response.ok) throw new Error(await readError(response, "Could not delete agent")); await refresh(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not delete agent"); }
  }, [requireAuth, refresh]);

  const saveResearch = useCallback(async (source: string, title: string, content: string) => {
    if (!requireAuth()) return;
    setResearchBusy(true); setResearchMsg(null);
    try { const response = await fetch(`${API_BASE}/agentic-lab/research`, { method: "POST", headers: { "Content-Type": "application/json", ...authHeaders() }, body: JSON.stringify({ source, title, content, symbol: selectedSymbol }) }); if (!response.ok) throw new Error(await readError(response, "Could not save research")); setResearchMode("list"); setResearchBody(""); await refresh(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not save research"); }
    finally { setResearchBusy(false); }
  }, [requireAuth, selectedSymbol, refresh]);
  const uploadResearch = useCallback(async (file: File) => {
    if (!requireAuth()) return;
    setResearchBusy(true); setResearchMsg(null);
    try { const form = new FormData(); form.append("file", file); const response = await fetch(`${API_BASE}/agentic-lab/research/upload`, { method: "POST", headers: authHeaders(), body: form }); if (!response.ok) throw new Error(await readError(response, "Could not upload research")); setResearchMsg(`${file.name} saved to the research library.`); await refresh(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not upload research"); }
    finally { setResearchBusy(false); }
  }, [requireAuth, refresh]);
  const generateResearch = useCallback(async () => {
    if (!requireAuth()) return;
    setResearchBusy(true); setResearchMsg(null);
    try { const response = await fetch(`${API_BASE}/agentic-lab/research/generate`, { method: "POST", headers: { "Content-Type": "application/json", ...authHeaders() }, body: JSON.stringify({ topic: researchTopic, provider: researchProvider, model: researchModel || modelsFor(researchProvider)[0], symbol: selectedSymbol }) }); if (!response.ok) throw new Error(await readError(response, "Could not generate research")); const data = await response.json() as { draft: { title: string; content: string; source: string } }; setResearchTitle(data.draft.title); setResearchBody(data.draft.content); setResearchMode("type"); setResearchMsg("Draft ready — review and save it when you are satisfied."); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not generate research"); }
    finally { setResearchBusy(false); }
  }, [requireAuth, researchTopic, researchProvider, researchModel, modelsFor, selectedSymbol]);
  const removeResearch = useCallback(async (doc: ResearchDoc) => {
    if (!requireAuth()) return;
    try { const response = await fetch(`${API_BASE}/agentic-lab/research/${doc.id}`, { method: "DELETE", headers: authHeaders() }); if (!response.ok) throw new Error(await readError(response, "Could not delete research")); await refresh(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not delete research"); }
  }, [requireAuth, refresh]);
  const loadLog = useCallback(async () => {
    setLogLoading(true);
    try { const params = new URLSearchParams({ days: String(logDays) }); if (logSymbol.trim()) params.set("symbol", logSymbol.trim().toUpperCase()); const response = await fetch(`${API_BASE}/agentic-lab/trading-log?${params.toString()}`, { headers: sessionHeaders() }); if (!response.ok) throw new Error(await readError(response, "Could not load the trading log")); setLog(await response.json() as Record<string, any>); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not load the trading log"); }
    finally { setLogLoading(false); }
  }, [logDays, logSymbol, sessionHeaders]);
  useEffect(() => { if (tab === "log" && !log) void loadLog(); }, [tab, log, loadLog]);

  const startResearchLoop = useCallback(async () => {
    if (!requireAuth()) return;
    const provider = researchProvider || draftProvider;
    const model = researchModel || draftModel || modelsFor(provider)[0] || "";
    setLoopBusy(true); setLoopJobState(null); setError(null);
    try {
      const response = await fetch(`${API_BASE}/agentic-lab/research-jobs`, { method: "POST", headers: { "Content-Type": "application/json", ...authHeaders() }, body: JSON.stringify({ provider, model, symbol: selectedSymbol.toUpperCase(), tf: loopTf, bars: loopBars, objective: loopObjective, max_iterations: loopIterations, max_model_calls: loopCallCap, capital: 10000 }) });
      if (!response.ok) throw new Error(await readError(response, "Could not start iterative research"));
      const { job_id } = await response.json() as { job_id: string }; setLoopJobId(job_id);
      const poll = async () => {
        try {
          const result = await fetch(`${API_BASE}/agentic-lab/research-jobs/${job_id}`, { headers: authHeaders() });
          if (!result.ok) throw new Error(await readError(result, "Could not poll research job"));
          const state = await result.json() as Record<string, any>; setLoopJobState(state);
          if (state.status === "queued" || state.status === "running") loopPollRef.current = setTimeout(() => void poll(), 1200);
          else { setLoopBusy(false); await refresh(); }
        } catch (err) { setLoopBusy(false); setError(err instanceof Error ? err.message : "Research polling failed"); }
      };
      void poll();
    } catch (err) { setLoopBusy(false); setError(err instanceof Error ? err.message : "Could not start iterative research"); }
  }, [requireAuth, researchProvider, researchModel, draftProvider, draftModel, modelsFor, selectedSymbol, loopTf, loopBars, loopObjective, loopIterations, loopCallCap, refresh]);
  const cancelResearchLoop = useCallback(async () => {
    if (!loopJobId) return;
    try { const response = await fetch(`${API_BASE}/agentic-lab/research-jobs/${loopJobId}/cancel`, { method: "POST", headers: authHeaders() }); if (!response.ok) throw new Error(await readError(response, "Could not cancel research")); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not cancel research"); }
  }, [loopJobId]);

  const visibleAgents = useMemo(() => filter === "ready" ? agents.filter((agent) => providers.find((provider) => provider.id === agent.provider)?.configured) : filter === "results" ? agents.filter((agent) => agentRuns[agent.id] || runs.some((run) => run.agent_id === agent.id)) : agents, [agents, filter, providers, agentRuns, runs]);
  const lastRunFor = useCallback((agent: LabAgent): LabRun | null => agentRuns[agent.id] ?? runs.find((run) => run.agent_id === agent.id) ?? null, [agentRuns, runs]);

  return <div className="lab-page">
    <div className="view-header lab-header"><div><h1>🧪 Agentic Trading Lab</h1><p className="view-description">Prototype model strategies, backtest them on real market data, and measure performance in plain numbers.</p></div>{runs.length > 0 && <div className="lab-summary-chips"><span className="summary-chip" title="Runs stored">{runs.length} runs</span><span className="summary-chip" title="Model-driven runs">{runs.filter((run) => run.kind === "llm").length} model runs</span><span className="summary-chip" title="Best total return">Best {Math.max(...runs.map((run) => Number(run.metrics?.total_return_pct ?? -Infinity))).toFixed(2)}%</span><span className="summary-chip" title="Share of runs that beat buy & hold">{(runs.filter((run) => Number(run.metrics?.excess_return_pct ?? 0) > 0).length / runs.length * 100).toFixed(1)}% beat market</span></div>}</div>
    <nav className="lab-tabs" role="tablist" aria-label="Agentic Lab sections">{TABS.map((entry) => <button key={entry.id} type="button" role="tab" aria-selected={tab === entry.id} className={`lab-tab ${tab === entry.id ? "active" : ""}`} onClick={() => selectTab(entry.id)}>{entry.label}</button>)}</nav>
    {(error || runsError) && <div className="settings-error" role="alert"><span>{error || runsError}</span>{!isAuthenticated && <button className="btn-primary" onClick={() => openAuth("login")}>Sign in</button>}<button className="btn-secondary" onClick={() => setError(null)}>Dismiss</button></div>}
    {tab === "dashboard" && <section className="lab-section"><div className="lab-section-head"><span className="lab-section-icon" aria-hidden="true">✏️</span><div><h2>LLMs</h2><p>Write a trading instruction for an AI model and backtest it on market data.</p></div><span className="agents-badge">{agents.length} agents</span></div><div className="filter-chips">{([{ id: "all", label: "All" }, { id: "ready", label: "Ready" }, { id: "results", label: "With results" }] as const).map((chip) => <button key={chip.id} type="button" className={`filter-chip ${filter === chip.id ? "on" : ""}`} onClick={() => setFilter(chip.id)}>{chip.label}</button>)}</div>
      {creating ? <div className="agent-form"><label><span>Name</span><input value={draftName} onChange={(event) => setDraftName(event.target.value)} placeholder="e.g. MomentumGPT"/></label><div className="agent-config-row"><label><span>Provider</span><select value={draftProvider} onChange={(event) => setDraftProvider(event.target.value)}>{providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.label}{provider.configured ? "" : " (not configured)"}</option>)}</select></label><label><span>Model</span>{modelsFor(draftProvider).length ? <select value={draftModel} onChange={(event) => setDraftModel(event.target.value)}><option value="">Choose…</option>{modelsFor(draftProvider).map((model) => <option key={model}>{model}</option>)}</select> : <input value={draftModel} onChange={(event) => setDraftModel(event.target.value)} placeholder="model id"/>}</label></div><label><span>Trading instruction</span><textarea value={draftPrompt} onChange={(event) => setDraftPrompt(event.target.value)} rows={5}/></label><div className="action-buttons"><button className="btn-primary" onClick={() => void createAgent()}>Create agent</button><button className="btn-secondary" onClick={() => setCreating(false)}>Cancel</button></div></div> : <button className="btn-primary" onClick={() => setCreating(true)}>+ Create model agent</button>}
      <div className="agent-grid">{visibleAgents.map((agent) => { const latest = lastRunFor(agent); return <article className="agent-card" key={agent.id}><header><h3>{agent.name}</h3><span>{agent.kind === "baseline" ? agent.baseline : `${agent.provider} · ${agent.model}`}</span></header><p>{agent.prompt}</p><div className="action-buttons"><button className="btn-primary" onClick={() => void runBacktest(agent)}>Run backtest on {agent.symbol || selectedSymbol}</button><button className="btn-secondary" onClick={() => { setConfigAgent(configAgent === agent.id ? null : agent.id); }}>Configure</button><button className="btn-danger" onClick={() => void removeAgent(agent)}>Delete</button></div>{latest && <div className="agent-run-result"><VerdictChip metrics={latest.metrics}/><StatGrid metrics={latest.metrics}/><RiskBadge run={latest}/></div>}{configAgent === agent.id && <div className="agent-config-row"><label>Name<input value={agent.name} onChange={(event) => void updateAgent(agent, { name: event.target.value })}/></label><label>Prompt<textarea value={agent.prompt} onChange={(event) => void updateAgent(agent, { prompt: event.target.value })}/></label></div>}</article>; })}{visibleAgents.length === 0 && <p className="empty-state">No agents in this filter yet.</p>}</div>
    </section>}
    {tab === "research" && <section className="lab-section"><div className="lab-section-head"><span className="lab-section-icon" aria-hidden="true">📚</span><div><h2>Research</h2><p>Upload files, type notes, or ask your model to draft research. Saved research feeds LLM backtests.</p></div><div className="lab-section-actions"><button className="btn-secondary" onClick={() => setResearchMode(researchMode === "type" ? "list" : "type")}>✍️ Type</button><button className="btn-secondary" onClick={() => fileRef.current?.click()} disabled={researchBusy}>⬆ Upload</button><button className="btn-secondary" onClick={() => setResearchMode(researchMode === "generate" ? "list" : "generate")}>✦ Ask model</button><input ref={fileRef} type="file" accept=".txt,.md,.csv,.log,text/plain" style={{ display: "none" }} onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadResearch(file); event.target.value = ""; }}/></div></div>
      {researchMsg && <div className="research-msg">{researchMsg}</div>}{researchMode === "type" && <div className="research-editor"><input value={researchTitle} onChange={(event) => setResearchTitle(event.target.value)} placeholder="Research title"/><textarea value={researchBody} onChange={(event) => setResearchBody(event.target.value)} placeholder="Type or paste your research…" rows={8}/><div className="action-buttons"><button className="btn-primary" disabled={!researchBody.trim()} onClick={() => void saveResearch("typed", researchTitle || "Untitled research", researchBody)}>Save research</button><button className="btn-secondary" onClick={() => setResearchMode("list")}>Cancel</button></div></div>}
      {researchMode === "generate" && <div className="research-editor"><label>Topic<input value={researchTopic} onChange={(event) => setResearchTopic(event.target.value)} placeholder={`${selectedSymbol} outlook and risks`}/></label><div className="agent-config-row"><label>Provider<select value={researchProvider} onChange={(event) => setResearchProvider(event.target.value)}>{configuredProviders.map((provider) => <option key={provider.id} value={provider.id}>{provider.label}</option>)}</select></label><label>Model<input value={researchModel} onChange={(event) => setResearchModel(event.target.value)} placeholder={modelsFor(researchProvider)[0] ?? "model"}/></label></div><div className="action-buttons"><button className="btn-primary" disabled={researchBusy || !researchTopic.trim() || !researchProvider} onClick={() => void generateResearch()}>{researchBusy ? "Asking model…" : "Generate draft via harness"}</button><button className="btn-secondary" onClick={() => setResearchMode("list")}>Cancel</button></div></div>}
      <div className="research-loop-card"><h3>Iterative strategy research</h3><p>Model-generated hypotheses are tested only against public historical market data. No portfolio, broker, or order access.</p><label>Research objective<textarea value={loopObjective} maxLength={400} onChange={(event) => setLoopObjective(event.target.value)} placeholder="e.g. Test a trend-following strategy with modest drawdowns" rows={3}/></label><div className="agent-config-row"><label>Timeframe<select value={loopTf} onChange={(event) => setLoopTf(event.target.value)}><option value="1d">Daily</option><option value="1h">Hourly</option><option value="1wk">Weekly</option></select></label><label>Bars<input type="number" min={40} max={1000} value={loopBars} onChange={(event) => setLoopBars(Number(event.target.value))}/></label><label>Iterations<input type="number" min={1} max={10} value={loopIterations} onChange={(event) => setLoopIterations(Number(event.target.value))}/></label><label>Total model calls<input type="number" min={2} max={40} value={loopCallCap} onChange={(event) => setLoopCallCap(Number(event.target.value))}/></label></div><div className="action-buttons"><button className="btn-primary" disabled={loopBusy || loopObjective.trim().length < 3 || !(researchProvider || draftProvider)} onClick={() => void startResearchLoop()}>{loopBusy ? "Researching…" : `Research ${selectedSymbol}`}</button>{loopBusy && <button className="btn-danger" onClick={() => void cancelResearchLoop()}>Cancel job</button>}</div>{loopJobState && <div className="research-loop-progress"><div className="progress-bar"><div className="progress-fill" style={{ width: `${Math.round((loopJobState.progress ?? 0) * 100)}%` }}/></div><p>{loopJobState.message}</p><p>Iteration {loopJobState.iteration ?? 0}/{loopJobState.iterations ?? loopIterations} · {loopJobState.model_calls ?? 0}/{loopJobState.max_model_calls ?? loopCallCap} model calls · {loopJobState.status}</p>{loopJobState.error && <p className="settings-error" role="alert">{loopJobState.error}</p>}{loopJobState.result?.iterations?.map((result: any, index: number) => <p key={result.run_id}>Iteration {index + 1}: <a href={`/app/agentic-lab?tab=backtests`}>View saved run</a></p>)}</div>}</div>
      <div className="research-list">{research.length === 0 && <p className="empty-state">No research yet — type, upload, or ask your model.</p>}{research.map((doc) => <div key={doc.id} className="research-card"><button type="button" className="research-card-head" onClick={() => setOpenDoc(openDoc === doc.id ? null : doc.id)}><span className={`research-source ${doc.source}`}>{doc.source === "uploaded" ? "⬆ file" : doc.source === "model" ? "✦ model" : "✍️ typed"}</span><span className="research-title">{doc.title}</span><span className="research-meta">{doc.symbol ? `${doc.symbol} · ` : ""}{doc.created_at?.slice(0, 10)} · {doc.chars} chars</span></button>{openDoc === doc.id && <div className="research-card-body"><pre>{doc.content}</pre><div className="action-buttons"><button className="btn-secondary" onClick={() => { setResearchTitle(doc.title); setResearchBody(doc.content); setResearchMode("type"); }}>Edit</button><button className="btn-danger" onClick={() => void removeResearch(doc)}>Delete</button></div></div>}</div>)}</div>
    </section>}
    {tab === "log" && <section className="lab-section"><div className="lab-section-head"><h2>Trading Log</h2><p>What the models chose over your chosen duration.</p></div><div className="log-controls"><label>Duration<select value={logDays} onChange={(event) => { setLogDays(Number(event.target.value)); setLog(null); }}><option value={1}>Last 24 hours</option><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option><option value={365}>Last year</option></select></label><label>Symbol filter<input value={logSymbol} onChange={(event) => { setLogSymbol(event.target.value.toUpperCase()); setLog(null); }}/></label><button className="btn-primary" onClick={() => void loadLog()} disabled={logLoading}>{logLoading ? "Loading…" : "Refresh"}</button></div>{log && <><div className="log-counts"><span className="log-count long">▲ {log.counts.long} long</span><span className="log-count flat">■ {log.counts.flat} flat</span><span className="log-count short">▼ {log.counts.short} short</span><span className="log-count total">{log.total} decisions · {log.runs_covered} runs</span></div><div className="log-table-wrap"><table className="log-table"><thead><tr><th>When</th><th>Symbol</th><th>Strategy</th><th>Decision</th><th>Price</th><th>Reason</th></tr></thead><tbody>{(log.entries || []).map((entry: any, index: number) => <tr key={`${entry.run_id}-${index}`}><td>{String(entry.time).replace("T", " ").slice(0, 16)}</td><td>{entry.symbol}</td><td>{entry.strategy}</td><td><span className={`action-pill ${entry.action}`}>{entry.action}</span></td><td>{entry.price?.toFixed?.(2) ?? "—"}</td><td>{entry.reason}</td></tr>)}</tbody></table></div></>}</section>}
    {tab === "backtests" && <Backtester runs={runs} loading={backtestsLoading} error={error || runsError} onRefresh={onRefresh}/> }
    {tab === "pairs" && <section className="lab-section"><PairsBacktestLauncher initialSymbol={selectedSymbol} onComplete={() => void refresh()}/></section>}
  </div>;
}
