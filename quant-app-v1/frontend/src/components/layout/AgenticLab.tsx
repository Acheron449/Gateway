import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE } from "../../lib/constants";
import { readProviderCache, writeProviderCache } from "../../lib/providerCache";
import { useAuth } from "../../context/AuthContext";
import { useAuthUI } from "../../context/AuthUIContext";
import { PairsBacktestLauncher } from "../../components/features/PairsBacktestLauncher";

/* eslint-disable @typescript-eslint/no-explicit-any */

interface LlmProvider {
  id: string;
  label: string;
  group: "compatible" | "foundation";
  configured: boolean;
  models: string[];
  default_model: string | null;
}

interface LabAgent {
  id: string;
  name: string;
  kind: string;
  baseline: string | null;
  provider: string | null;
  model: string | null;
  prompt: string;
  symbol: string | null;
  tf: string;
  created_at: string;
}

interface LabRun {
  id: string;
  created_at: string;
  kind: string;
  strategy: string;
  agent_id: string | null;
  symbol: string;
  symbol_b?: string | null;
  pair_series?: { time: number; spread: number | null; zscore: number | null; beta: number | null; pvalue: number | null; cointegrated: boolean; signal: string }[];
  walk_forward?: { folds?: { fold: number; test_start: number; test_end: number; cointegration_pvalue: number | null; cointegrated: boolean; metrics: Record<string, any> }[]; out_of_sample_metrics?: Record<string, any> };
  tf: string;
  bars: number;
  capital: number;
  provider: string | null;
  model: string | null;
  decisions: {
    time: number;
    action: string;
    price: number;
    reason: string;
    risk?: { rule: string; proposed: string; approved: string; reason: string };
  }[];
  equity_curve: { time: number; equity: number }[];
  chart?: { points: RunChartPoint[]; markers: RunChartMarker[] };
  risk_rules?: { max_position_pct: number; max_drawdown_pct: number; allow_short: boolean };
  risk_events?: { time: number; rule: string; reason: string }[];
  metrics: Record<string, any>;
}

interface ResearchDoc {
  id: string;
  title: string;
  content: string;
  source: "typed" | "uploaded" | "model";
  symbol: string | null;
  provider: string | null;
  model: string | null;
  created_at: string;
  chars: number;
}

interface TaStatus {
  available: boolean;
  version: string | null;
  message: string | null;
  analysts: { id: string; label: string; detail: string }[];
  depths: { id: number; label: string; detail: string }[];
  providers: { id: string; label: string; configured: boolean }[];
}

const TABS = [
  { id: "dashboard", label: "LLMs" },
  { id: "research", label: "Research" },
  { id: "log", label: "Trading Log" },
  { id: "performance", label: "Performance" },
  { id: "trading-agents", label: "TradingAgents" },
] as const;
type TabId = (typeof TABS)[number]["id"];

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("gateway_auth_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function readError(response: Response, fallback: string): Promise<string> {
  const text = await response.text().catch(() => "");
  if (!text) return `${response.status} ${response.statusText}`.trim();
  try {
    const payload = JSON.parse(text) as any;
    if (payload && typeof payload === "object" && typeof payload.detail === "string") return payload.detail;
  } catch {
    /* not JSON */
  }
  return text.slice(0, 300) || fallback;
}

const DEFAULT_AGENT_PROMPT =
  "You are a systematic trader. Using only the market window provided, decide the next position: long, flat, or short. " +
  'Consider trend, momentum, and volatility. Answer with JSON only: {"action": "long|flat|short", "reason": "one sentence"}.';

function Sparkline({ curve }: { curve: { time: number; equity: number }[] }) {
  if (!curve || curve.length < 2) return null;
  const values = curve.map((point) => point.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * 260;
      const y = 56 - ((value - min) / span) * 52;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const first = values[0] ?? 0;
  const last = values[values.length - 1] ?? 0;
  const rising = last >= first;
  return (
    <svg className="run-sparkline" viewBox="0 0 260 60" preserveAspectRatio="none" aria-hidden="true">
      <polyline points={points} fill="none" stroke={rising ? "var(--accent, #22c55e)" : "#ef4444"} strokeWidth="2" />
    </svg>
  );
}

interface RunChartPoint {
  t: number;
  c: number;
  s10: number | null;
  s30: number | null;
}
interface RunChartMarker {
  t: number;
  price: number | null;
  kind: "open_long" | "close_long" | "open_short" | "close_short" | "risk";
  label: string;
}

/** Reference-style results chart: price + SMA overlays + execution markers. */
function RunChart({ chart }: { chart: { points: RunChartPoint[]; markers: RunChartMarker[] } }) {
  const points = chart?.points ?? [];
  if (points.length < 2) return null;
  const W = 640;
  const H = 220;
  const pad = { l: 8, r: 8, t: 12, b: 18 };

  const times = points.map((p) => p.t);
  const tMin = Math.min(...times);
  const tMax = Math.max(...times);
  const spanT = tMax - tMin || 1;
  const values: number[] = [];
  for (const p of points) {
    values.push(p.c);
    if (p.s10 != null) values.push(p.s10);
    if (p.s30 != null) values.push(p.s30);
  }
  const vMin = Math.min(...values);
  const vMax = Math.max(...values);
  const spanV = vMax - vMin || 1;
  const x = (t: number) => pad.l + ((t - tMin) / spanT) * (W - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - (v - vMin) / spanV) * (H - pad.t - pad.b);

  const line = (pick: (p: RunChartPoint) => number | null) =>
    points
      .filter((p) => pick(p) != null)
      .map((p) => `${x(p.t).toFixed(1)},${y(pick(p) as number).toFixed(1)}`)
      .join(" ");

  const markerStyle: Record<RunChartMarker["kind"], { fill: string; shape: "up" | "down" | "ring" }> = {
    open_long: { fill: "#22c55e", shape: "up" },
    close_long: { fill: "#ef4444", shape: "down" },
    open_short: { fill: "#ef4444", shape: "down" },
    close_short: { fill: "#22c55e", shape: "up" },
    risk: { fill: "#f59e0b", shape: "ring" },
  };

  return (
    <div className="run-chart-wrap">
      <svg className="run-chart" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="Price, SMAs and trade markers">
        <polyline points={line((p) => p.s30)} fill="none" stroke="#f59e0b" strokeWidth="1.2" opacity="0.75" />
        <polyline points={line((p) => p.s10)} fill="none" stroke="#3b82f6" strokeWidth="1.2" opacity="0.85" />
        <polyline points={line((p) => p.c)} fill="none" stroke="#a1a1aa" strokeWidth="1.6" />
        {chart.markers.map((marker, index) => {
          if (marker.price == null) return null;
          const cx = x(marker.t);
          const cy = y(marker.price);
          const style = markerStyle[marker.kind];
          if (style.shape === "ring") {
            return <circle key={index} cx={cx} cy={cy} r="5" fill="none" stroke={style.fill} strokeWidth="2"><title>{marker.label}</title></circle>;
          }
          const d =
            style.shape === "up"
              ? `M${cx} ${cy - 5} L${cx + 4.5} ${cy + 3.5} L${cx - 4.5} ${cy + 3.5} Z`
              : `M${cx} ${cy + 5} L${cx + 4.5} ${cy - 3.5} L${cx - 4.5} ${cy - 3.5} Z`;
          return <path key={index} d={d} fill={style.fill}><title>{marker.label}</title></path>;
        })}
      </svg>
      <div className="run-chart-legend">
        <span><i className="lg price" />Price</span>
        <span><i className="lg sma10" />SMA 10</span>
        <span><i className="lg sma30" />SMA 30</span>
        <span><i className="lg buy" />▲ Open</span>
        <span><i className="lg sell" />▼ Close</span>
        <span><i className="lg risk" />Risk guard</span>
      </div>
    </div>
  );
}

function RiskBadge({ run }: { run: LabRun }) {
  const halted = run.metrics?.risk_halted === true;
  const overrides = run.metrics?.risk_overrides ?? 0;
  const rules = run.risk_rules;
  if (!rules) return null;
  const summary = `${rules.max_position_pct}% pos · ${rules.max_drawdown_pct > 0 ? `${rules.max_drawdown_pct}% halt` : "no halt"} · ${rules.allow_short ? "shorts on" : "no shorts"}`;
  return (
    <span className={`risk-badge ${halted ? "halted" : overrides > 0 ? "touched" : "clean"}`} title={summary}>
      🛡️ {halted ? "Halted by risk guard" : overrides > 0 ? `${overrides} risk override${overrides > 1 ? "s" : ""}` : "Risk guard: clean"}
    </span>
  );
}

function StatGrid({ metrics }: { metrics: Record<string, any> }) {
  const stats: { label: string; value: string; hint: string }[] = Array.isArray(metrics?.stats)
    ? metrics.stats
    : [];
  if (!stats.length) return null;
  return (
    <div className="stat-grid">
      {stats.map((stat) => (
        <div key={stat.label} className="stat-cell" title={stat.hint}>
          <span className="stat-label">{stat.label}</span>
          <span className="stat-value">{stat.value}</span>
        </div>
      ))}
    </div>
  );
}

function VerdictChip({ metrics }: { metrics: Record<string, any> }) {
  if (!metrics?.verdict) return null;
  const tone = metrics.verdict_tone === "good" ? "good" : metrics.verdict_tone === "bad" ? "bad" : "neutral";
  return <span className={`verdict-chip ${tone}`}>{metrics.verdict}</span>;
}

interface AgenticLabProps {
  selectedSymbol: string;
}

export function AgenticLab({ selectedSymbol }: AgenticLabProps) {
  const { isAuthenticated } = useAuth();
  const { openAuth } = useAuthUI();

  const [tab, setTab] = useState<TabId>("dashboard");
  const [providers, setProviders] = useState<LlmProvider[]>([]);
  const [agents, setAgents] = useState<LabAgent[]>([]);
  const [runs, setRuns] = useState<LabRun[]>([]);
  const [summary, setSummary] = useState<Record<string, any> | null>(null);
  const [research, setResearch] = useState<ResearchDoc[]>([]);
  const [taStatus, setTaStatus] = useState<TaStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  // dashboard state
  const [filter, setFilter] = useState<"all" | "ready" | "results">("all");
  // Risk-guard rules applied to every run launched from the dashboard.
  const [risk, setRisk] = useState({ max_position_pct: 100, max_drawdown_pct: 0, allow_short: true });
  const [configAgent, setConfigAgent] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobState, setJobState] = useState<Record<string, any> | null>(null);
  const [agentRuns, setAgentRuns] = useState<Record<string, LabRun>>({});

  // create-agent form
  const [creating, setCreating] = useState(false);
  const [draftName, setDraftName] = useState("");
  const [draftProvider, setDraftProvider] = useState("");
  const [draftModel, setDraftModel] = useState("");
  const [draftPrompt, setDraftPrompt] = useState(DEFAULT_AGENT_PROMPT);

  // research state
  const [researchMode, setResearchMode] = useState<"list" | "type" | "upload" | "generate">("list");
  const [researchTitle, setResearchTitle] = useState("");
  const [researchBody, setResearchBody] = useState("");
  const [researchTopic, setResearchTopic] = useState("");
  const [researchProvider, setResearchProvider] = useState("");
  const [researchModel, setResearchModel] = useState("");
  const [researchBusy, setResearchBusy] = useState(false);
  const [researchMsg, setResearchMsg] = useState<string | null>(null);
  const [openDoc, setOpenDoc] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // trading log state
  const [logDays, setLogDays] = useState(30);
  const [logSymbol, setLogSymbol] = useState("");
  const [log, setLog] = useState<Record<string, any> | null>(null);
  const [logLoading, setLogLoading] = useState(false);

  // TradingAgents state
  const [taTicker, setTaTicker] = useState(selectedSymbol);
  const [taDate, setTaDate] = useState(new Date().toISOString().slice(0, 10));
  const [taAnalysts, setTaAnalysts] = useState<string[]>(["market", "news", "fundamentals"]);
  const [taProvider, setTaProvider] = useState("");
  const [taModel, setTaModel] = useState("");
  const [taDepth, setTaDepth] = useState(1);
  const [taJobState, setTaJobState] = useState<Record<string, any> | null>(null);
  const [taBusy, setTaBusy] = useState(false);

  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const taPollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const configuredProviders = useMemo(() => providers.filter((p) => p.configured), [providers]);

  const refresh = useCallback(async () => {
    try {
      const [provRes, agentRes, runRes, researchRes, taRes] = await Promise.all([
        fetch(`${API_BASE}/llm/providers`),
        fetch(`${API_BASE}/agentic-lab/agents`),
        fetch(`${API_BASE}/agentic-lab/runs?limit=30`),
        fetch(`${API_BASE}/agentic-lab/research`),
        fetch(`${API_BASE}/agents/trading-agents`),
      ]);
      if (provRes.ok) {
        const data = (await provRes.json()) as { providers: LlmProvider[] };
        setProviders(data.providers);
        writeProviderCache("llm", data); // device cache: no secrets in it
      }
      if (agentRes.ok) setAgents(((await agentRes.json()) as { agents: LabAgent[] }).agents);
      if (runRes.ok) {
        const data = (await runRes.json()) as { runs: LabRun[]; summary: Record<string, any> };
        setRuns(data.runs);
        setSummary(data.summary);
        setAgentRuns((current) => {
          const next: Record<string, LabRun> = { ...current };
          for (const run of data.runs) {
            if (run.kind === "llm" && run.model) {
              const match = data.runs.find((r) => r.model === run.model);
              if (match) next[run.id] = match;
            }
          }
          return next;
        });
      }
      if (researchRes.ok) setResearch(((await researchRes.json()) as { research: ResearchDoc[] }).research);
      if (taRes.ok) setTaStatus((await taRes.json()) as TaStatus);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load the lab");
    }
  }, []);

  useEffect(() => {
    // Paint the provider picker from the device cache, then reconcile.
    const cached = readProviderCache<{ providers: LlmProvider[] }>("llm");
    if (cached?.providers?.length) setProviders(cached.providers);
    void refresh();
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
      if (taPollRef.current) clearTimeout(taPollRef.current);
    };
  }, [refresh]);

  useEffect(() => {
    setTaTicker((current) => current || selectedSymbol);
  }, [selectedSymbol]);

  useEffect(() => {
    const firstId = configuredProviders[0]?.id;
    if (!firstId) return;
    if (!draftProvider) setDraftProvider(firstId);
    if (!researchProvider) setResearchProvider(firstId);
    if (!taProvider) setTaProvider(firstId);
  }, [configuredProviders, draftProvider, researchProvider, taProvider]);

  const modelsFor = useCallback(
    (id: string) => providers.find((p) => p.id === id)?.models ?? [],
    [providers],
  );

  const requireAuth = useCallback(() => {
    if (isAuthenticated) return true;
    setError("Sign in to run lab actions — they spend API credits.");
    return false;
  }, [isAuthenticated]);

  // ---- backtest job polling ---------------------------------------------
  const runBacktest = useCallback(
    async (agent: LabAgent) => {
      if (!requireAuth()) return;
      setError(null);
      setConfigAgent(null);
      setJobId(null);
      setJobState(null);
      try {
        const response = await fetch(`${API_BASE}/agentic-lab/backtest`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders() },
          body: JSON.stringify({
            agent_id: agent.id,
            kind: agent.kind,
            baseline: agent.baseline,
            provider: agent.provider,
            model: agent.model,
            prompt: agent.prompt,
            symbol: (agent.symbol || selectedSymbol).toUpperCase(),
            tf: agent.tf || "1d",
            bars: 260,
            max_llm_calls: 12,
            risk,
          }),
        });
        if (!response.ok) throw new Error(await readError(response, "Could not start backtest"));
        const data = (await response.json()) as { job_id: string };
        setJobId(data.job_id);

        const poll = async () => {
          try {
            const jobRes = await fetch(`${API_BASE}/agentic-lab/jobs/${data.job_id}`);
            if (!jobRes.ok) return;
            const job = (await jobRes.json()) as Record<string, any>;
            setJobState(job);
            if (job.status === "queued" || job.status === "running") {
              pollRef.current = setTimeout(() => void poll(), 1200);
            } else if (job.status === "succeeded" && job.result) {
              setAgentRuns((current) => ({ ...current, [agent.id]: job.result as LabRun }));
              void refresh();
            }
          } catch (pollError) {
            setError(pollError instanceof Error ? pollError.message : "Polling failed");
          }
        };
        void poll();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not start backtest");
      }
    },
    [requireAuth, selectedSymbol, refresh, risk],
  );

  // ---- agent CRUD --------------------------------------------------------
  const createAgent = useCallback(async () => {
    if (!requireAuth()) return;
    try {
      const response = await fetch(`${API_BASE}/agentic-lab/agents`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({
          name: draftName.trim() || `${draftModel || "Untitled"} agent`,
          kind: "llm",
          provider: draftProvider,
          model: draftModel || (modelsFor(draftProvider)[0] ?? ""),
          prompt: draftPrompt.trim() || DEFAULT_AGENT_PROMPT,
          symbol: selectedSymbol,
          tf: "1d",
        }),
      });
      if (!response.ok) throw new Error(await readError(response, "Could not save agent"));
      setCreating(false);
      setDraftName("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save agent");
    }
  }, [requireAuth, draftName, draftProvider, draftModel, draftPrompt, selectedSymbol, modelsFor, refresh]);

  const updateAgent = useCallback(
    async (agent: LabAgent, changes: Partial<LabAgent>) => {
      if (!requireAuth()) return;
      try {
        const response = await fetch(`${API_BASE}/agentic-lab/agents`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders() },
          body: JSON.stringify({ ...agent, ...changes }),
        });
        if (!response.ok) throw new Error(await readError(response, "Could not update agent"));
        setConfigAgent(null);
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not update agent");
      }
    },
    [requireAuth, refresh],
  );

  const removeAgent = useCallback(
    async (agent: LabAgent) => {
      if (!window.confirm(`Delete agent "${agent.name}"?`)) return;
      if (!requireAuth()) return;
      try {
        const response = await fetch(`${API_BASE}/agentic-lab/agents/${agent.id}`, {
          method: "DELETE",
          headers: authHeaders(),
        });
        if (!response.ok) throw new Error(await readError(response, "Delete failed"));
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Delete failed");
      }
    },
    [requireAuth, refresh],
  );

  // ---- research ----------------------------------------------------------
  const saveResearch = useCallback(
    async (source: "typed" | "model", title: string, content: string) => {
      if (!requireAuth()) return;
      try {
        const response = await fetch(`${API_BASE}/agentic-lab/research`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders() },
          body: JSON.stringify({ title, content, source, symbol: selectedSymbol }),
        });
        if (!response.ok) throw new Error(await readError(response, "Save failed"));
        setResearchMsg("Saved to your research library.");
        setResearchMode("list");
        setResearchTitle("");
        setResearchBody("");
        await refresh();
      } catch (err) {
        setResearchMsg(err instanceof Error ? err.message : "Save failed");
      }
    },
    [requireAuth, selectedSymbol, refresh],
  );

  const uploadResearch = useCallback(
    async (file: File) => {
      if (!requireAuth()) return;
      setResearchBusy(true);
      setResearchMsg(null);
      try {
        const form = new FormData();
        form.append("file", file);
        const response = await fetch(`${API_BASE}/agentic-lab/research/upload`, {
          method: "POST",
          headers: authHeaders(),
          body: form,
        });
        if (!response.ok) throw new Error(await readError(response, "Upload failed"));
        setResearchMsg(`Uploaded "${file.name}".`);
        setResearchMode("list");
        await refresh();
      } catch (err) {
        setResearchMsg(err instanceof Error ? err.message : "Upload failed");
      } finally {
        setResearchBusy(false);
      }
    },
    [requireAuth, refresh],
  );

  const generateResearch = useCallback(async () => {
    if (!requireAuth()) return;
    setResearchBusy(true);
    setResearchMsg(null);
    try {
      const response = await fetch(`${API_BASE}/agentic-lab/research/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({
          topic: researchTopic,
          provider: researchProvider,
          model: researchModel || (modelsFor(researchProvider)[0] ?? ""),
          symbol: selectedSymbol,
        }),
      });
      if (!response.ok) throw new Error(await readError(response, "Model request failed"));
      const data = (await response.json()) as { draft: { title: string; content: string } };
      setResearchTitle(data.draft.title);
      setResearchBody(data.draft.content);
      setResearchMode("type");
      setResearchMsg("Draft ready — review it, then save.");
    } catch (err) {
      setResearchMsg(err instanceof Error ? err.message : "Model request failed");
    } finally {
      setResearchBusy(false);
    }
  }, [requireAuth, researchTopic, researchProvider, researchModel, selectedSymbol, modelsFor]);

  const removeResearch = useCallback(
    async (doc: ResearchDoc) => {
      if (!window.confirm(`Delete "${doc.title}"?`)) return;
      if (!requireAuth()) return;
      const response = await fetch(`${API_BASE}/agentic-lab/research/${doc.id}`, {
        method: "DELETE",
        headers: authHeaders(),
      });
      if (response.ok) void refresh();
    },
    [requireAuth, refresh],
  );

  // ---- trading log -------------------------------------------------------
  const loadLog = useCallback(async () => {
    setLogLoading(true);
    try {
      const params = new URLSearchParams({ days: String(logDays) });
      if (logSymbol.trim()) params.set("symbol", logSymbol.trim().toUpperCase());
      const response = await fetch(`${API_BASE}/agentic-lab/trading-log?${params.toString()}`);
      if (!response.ok) throw new Error(await readError(response, "Could not load the trading log"));
      setLog((await response.json()) as Record<string, any>);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the trading log");
    } finally {
      setLogLoading(false);
    }
  }, [logDays, logSymbol]);

  useEffect(() => {
    if (tab === "log" && !log) void loadLog();
  }, [tab, log, loadLog]);

  // ---- TradingAgents -----------------------------------------------------
  const startTradingAgents = useCallback(async () => {
    if (!requireAuth()) return;
    setTaBusy(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/agents/trading-agents/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({
          ticker: taTicker,
          date: taDate,
          analysts: taAnalysts,
          provider: taProvider,
          model: taModel || null,
          depth: taDepth,
        }),
      });
      if (!response.ok) throw new Error(await readError(response, "Could not start the analysis"));
      const data = (await response.json()) as { job_id: string };
      const poll = async () => {
        try {
          const jobRes = await fetch(`${API_BASE}/agents/jobs/${data.job_id}`);
          if (!jobRes.ok) return;
          const job = (await jobRes.json()) as Record<string, any>;
          setTaJobState(job);
          if (job.status === "queued" || job.status === "running") {
            taPollRef.current = setTimeout(() => void poll(), 1500);
          } else {
            setTaBusy(false);
          }
        } catch {
          setTaBusy(false);
        }
      };
      void poll();
    } catch (err) {
      setTaBusy(false);
      setError(err instanceof Error ? err.message : "Could not start the analysis");
    }
  }, [requireAuth, taTicker, taDate, taAnalysts, taProvider, taModel, taDepth]);

  // ---- derived lists -----------------------------------------------------
  const visibleAgents = useMemo(() => {
    if (filter === "ready") return agents.filter((a) => providers.find((p) => p.id === a.provider)?.configured);
    if (filter === "results") return agents.filter((a) => agentRuns[a.id] || runs.some((r) => r.agent_id === a.id));
    return agents;
  }, [agents, filter, providers, agentRuns, runs]);

  const lastRunFor = useCallback(
    (agent: LabAgent): LabRun | null => {
      if (agentRuns[agent.id]) return agentRuns[agent.id] ?? null;
      return runs.find((r) => r.agent_id === agent.id) ?? null;
    },
    [agentRuns, runs],
  );

  return (
    <div className="lab-page">
      <div className="view-header lab-header">
        <div>
          <h1>🧪 Agentic Trading Lab</h1>
          <p className="view-description">
            Prototype model strategies, backtest them on real market data, and measure performance in plain numbers.
          </p>
        </div>
        {summary && summary.runs > 0 && (
          <div className="lab-summary-chips">
            <span className="summary-chip" title="Runs stored">{summary.runs} runs</span>
            <span className="summary-chip" title="Model-driven runs">{summary.model_runs} model runs</span>
            <span className="summary-chip" title="Best total return">
              Best {summary.best_return_pct > 0 ? "+" : ""}
              {summary.best_return_pct}%
            </span>
            <span className="summary-chip" title="Share of runs that beat buy & hold">
              {summary.beat_market_pct}% beat market
            </span>
          </div>
        )}
      </div>

      <PairsBacktestLauncher initialSymbol={selectedSymbol} onComplete={() => void refresh()} />

      <nav className="lab-tabs" role="tablist">
        {TABS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            role="tab"
            aria-selected={tab === entry.id}
            className={`lab-tab ${tab === entry.id ? "active" : ""}`}
            onClick={() => setTab(entry.id)}
          >
            {entry.label}
          </button>
        ))}
      </nav>

      {error && (
        <div className="settings-error" role="alert">
          <span>{error}</span>
          {!isAuthenticated && (
            <button className="btn-primary" onClick={() => openAuth("login")}>
              Sign in
            </button>
          )}
          <button className="btn-secondary" onClick={() => setError(null)}>Dismiss</button>
        </div>
      )}

      {/* ---------------------------------------------------------------- */}
      {/* LLM dashboard                                                     */}
      {/* ---------------------------------------------------------------- */}
      {tab === "dashboard" && (
        <section className="lab-section">
          <div className="lab-section-head">
            <span className="lab-section-icon" aria-hidden="true">✏️</span>
            <div>
              <h2>LLMs</h2>
              <p>Write a trading instruction for an AI model and backtest it on market data.</p>
            </div>
            <span className="agents-badge">{agents.length} agents</span>
          </div>

          <div className="filter-chips">
            {([
              { id: "all", label: "All" },
              { id: "ready", label: "Ready" },
              { id: "results", label: "With results" },
            ] as const).map((chip) => (
              <button
                key={chip.id}
                type="button"
                className={`filter-chip ${filter === chip.id ? "on" : ""}`}
                onClick={() => setFilter(chip.id)}
              >
                {chip.label}
              </button>
            ))}
          </div>

          {/* RiskGuard-style gate applied to every run */}
          <div className="risk-guard-bar">
            <span className="risk-guard-title" title="Every proposal is checked before execution — inspired by the RiskGuard agent in kweinmeister/agentic-trading">
              🛡️ Risk guard
            </span>
            <label className="risk-field">
              <span>Max position %</span>
              <input
                type="number"
                min={1}
                max={100}
                step={5}
                value={risk.max_position_pct}
                onChange={(event) => setRisk((r) => ({ ...r, max_position_pct: Number(event.target.value) || 100 }))}
              />
            </label>
            <label className="risk-field">
              <span>Drawdown halt % (0 = off)</span>
              <input
                type="number"
                min={0}
                max={100}
                step={5}
                value={risk.max_drawdown_pct}
                onChange={(event) => setRisk((r) => ({ ...r, max_drawdown_pct: Number(event.target.value) || 0 }))}
              />
            </label>
            <label className="risk-field risk-check">
              <input
                type="checkbox"
                checked={risk.allow_short}
                onChange={(event) => setRisk((r) => ({ ...r, allow_short: event.target.checked }))}
              />
              <span>Allow short selling</span>
            </label>
            <span className="risk-guard-note">Checked before every trade · rejections are logged</span>
          </div>

          <div className="agent-grid">
            {visibleAgents.map((agent) => {
              const provider = providers.find((p) => p.id === agent.provider);
              const ready = !!provider?.configured && !!agent.model;
              const run = lastRunFor(agent);
              const running = jobId && jobState && (jobState.status === "queued" || jobState.status === "running");
              return (
                <div key={agent.id} className="agent-card">
                  <div className="agent-card-head">
                    <span className="agent-avatar" aria-hidden="true">🤖</span>
                    <span className="agent-name">{agent.name}</span>
                    <span className={`ready-badge ${ready ? "on" : ""}`}>
                      <span className="status-dot" aria-hidden="true" />
                      {ready ? "READY" : "NO KEY"}
                    </span>
                  </div>
                  <div className="agent-provider-line">
                    {provider?.label ?? agent.provider} · {agent.model ?? "no model"}
                  </div>

                  <div className="agent-capital">
                    <span className="agent-capital-label">Backtesting</span>
                    <span className="agent-capital-value">
                      ${(agentRuns[agent.id]?.capital ?? run?.capital ?? 10000).toLocaleString()}
                    </span>
                    <span className="agent-capital-note">Simulated · {agent.symbol ?? selectedSymbol} · {agent.tf}</span>
                  </div>

                  <div className="agent-result-box">
                    {running ? (
                      <div className="agent-running">
                        <div className="progress-bar">
                          <div className="progress-fill" style={{ width: `${Math.round((jobState?.progress ?? 0) * 100)}%` }} />
                        </div>
                        <span>{jobState?.message || "Running…"}</span>
                      </div>
                    ) : run ? (
                      <div className="agent-run-summary">
                        <span className={`run-return ${run.metrics.total_return_pct >= 0 ? "up" : "down"}`}>
                          {run.metrics.total_return_pct >= 0 ? "+" : ""}
                          {run.metrics.total_return_pct}%
                        </span>
                        <VerdictChip metrics={run.metrics} />
                        <StatGrid metrics={run.metrics} />
                      </div>
                    ) : (
                      <div className="agent-empty">
                        <span className="agent-empty-icon" aria-hidden="true">📈</span>
                        <strong>No backtests yet</strong>
                        <span>Test this agent on historical market data.</span>
                      </div>
                    )}
                  </div>

                  <div className="agent-actions">
                    <button
                      type="button"
                      className="btn-secondary agent-configure"
                      onClick={() => setConfigAgent(configAgent === agent.id ? null : agent.id)}
                    >
                      {configAgent === agent.id ? "Close" : "Configure"}
                    </button>
                    <div className="agent-run-row">
                      <button
                        type="button"
                        className="btn-run-backtest"
                        disabled={!!running || !ready}
                        title={ready ? "Run this agent over historical bars" : "Configure a provider key first (Providers page)"}
                        onClick={() => void runBacktest(agent)}
                      >
                        {running ? "Running…" : "Run Backtest"}
                      </button>
                      <button type="button" className="btn-more" onClick={() => void removeAgent(agent)} title="Delete agent">
                        ⋯
                      </button>
                    </div>
                  </div>

                  {configAgent === agent.id && (
                    <div className="agent-config">
                      <label>
                        <span>Instruction (system prompt)</span>
                        <textarea
                          value={agent.prompt}
                          onChange={(event) => setAgents((current) => current.map((a) => (a.id === agent.id ? { ...a, prompt: event.target.value } : a)))}
                          rows={5}
                        />
                      </label>
                      <div className="agent-config-row">
                        <label>
                          <span>Provider</span>
                          <select value={agent.provider ?? ""} onChange={(event) => setAgents((current) => current.map((a) => (a.id === agent.id ? { ...a, provider: event.target.value, model: "" } : a)))}>
                            <option value="">Choose…</option>
                            {providers.map((p) => (
                              <option key={p.id} value={p.id}>{p.label}{p.configured ? "" : " (not configured)"}</option>
                            ))}
                          </select>
                        </label>
                        <label>
                          <span>Model</span>
                          {modelsFor(agent.provider ?? "").length > 0 ? (
                            <select value={agent.model ?? ""} onChange={(event) => setAgents((current) => current.map((a) => (a.id === agent.id ? { ...a, model: event.target.value } : a)))}>
                              <option value="">Choose…</option>
                              {modelsFor(agent.provider ?? "").map((m) => (
                                <option key={m} value={m}>{m}</option>
                              ))}
                            </select>
                          ) : (
                            <input type="text" value={agent.model ?? ""} placeholder="model id" onChange={(event) => setAgents((current) => current.map((a) => (a.id === agent.id ? { ...a, model: event.target.value } : a)))} />
                          )}
                        </label>
                        <label>
                          <span>Symbol</span>
                          <input type="text" value={agent.symbol ?? selectedSymbol} onChange={(event) => setAgents((current) => current.map((a) => (a.id === agent.id ? { ...a, symbol: event.target.value.toUpperCase() } : a)))} />
                        </label>
                        <label>
                          <span>Timeframe</span>
                          <select value={agent.tf} onChange={(event) => setAgents((current) => current.map((a) => (a.id === agent.id ? { ...a, tf: event.target.value } : a)))}>
                            <option value="1d">Daily</option>
                            <option value="1h">Hourly</option>
                            <option value="1wk">Weekly</option>
                          </select>
                        </label>
                      </div>
                      <div className="action-buttons">
                        <button className="btn-primary" onClick={() => void updateAgent(agent, { prompt: agent.prompt, provider: agent.provider, model: agent.model, symbol: agent.symbol, tf: agent.tf })}>
                          Save configuration
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}

            {/* create-agent card */}
            <div className="agent-card agent-card-create">
              {!creating ? (
                <button type="button" className="agent-create-prompt" onClick={() => setCreating(true)}>
                  <span aria-hidden="true">＋</span>
                  New LLM agent
                </button>
              ) : (
                <div className="agent-config open">
                  <strong>New LLM agent</strong>
                  <label>
                    <span>Name</span>
                    <input type="text" value={draftName} placeholder="e.g. MomentumGPT" onChange={(event) => setDraftName(event.target.value)} />
                  </label>
                  <div className="agent-config-row">
                    <label>
                      <span>Provider</span>
                      <select value={draftProvider} onChange={(event) => setDraftProvider(event.target.value)}>
                        <option value="">Choose…</option>
                        {providers.map((p) => (
                          <option key={p.id} value={p.id}>{p.label}{p.configured ? "" : " (not configured)"}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      <span>Model</span>
                      {modelsFor(draftProvider).length > 0 ? (
                        <select value={draftModel} onChange={(event) => setDraftModel(event.target.value)}>
                          <option value="">Choose…</option>
                          {modelsFor(draftProvider).map((m) => (
                            <option key={m} value={m}>{m}</option>
                          ))}
                        </select>
                      ) : (
                        <input type="text" value={draftModel} placeholder="model id" onChange={(event) => setDraftModel(event.target.value)} />
                      )}
                    </label>
                  </div>
                  <label>
                    <span>Trading instruction</span>
                    <textarea value={draftPrompt} onChange={(event) => setDraftPrompt(event.target.value)} rows={5} />
                  </label>
                  <div className="action-buttons">
                    <button className="btn-primary" onClick={() => void createAgent()}>Create agent</button>
                    <button className="btn-secondary" onClick={() => setCreating(false)}>Cancel</button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </section>
      )}

      {/* ---------------------------------------------------------------- */}
      {/* Research                                                          */}
      {/* ---------------------------------------------------------------- */}
      {tab === "research" && (
        <section className="lab-section">
          <div className="lab-section-head">
            <span className="lab-section-icon" aria-hidden="true">📚</span>
            <div>
              <h2>Research</h2>
              <p>Upload files, type notes, or ask your model to draft research. Saved research feeds LLM backtests.</p>
            </div>
            <div className="lab-section-actions">
              <button className={`btn-secondary ${researchMode === "type" ? "active" : ""}`} onClick={() => setResearchMode(researchMode === "type" ? "list" : "type")}>
                ✍️ Type
              </button>
              <button className="btn-secondary" onClick={() => fileRef.current?.click()} disabled={researchBusy}>
                ⬆ Upload
              </button>
              <button className={`btn-secondary ${researchMode === "generate" ? "active" : ""}`} onClick={() => setResearchMode(researchMode === "generate" ? "list" : "generate")}>
                ✦ Ask model
              </button>
              <input
                ref={fileRef}
                type="file"
                accept=".txt,.md,.csv,.log,text/plain"
                style={{ display: "none" }}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void uploadResearch(file);
                  event.target.value = "";
                }}
              />
            </div>
          </div>

          {researchMsg && <div className="research-msg">{researchMsg}</div>}

          {researchMode === "type" && (
            <div className="research-editor">
              <input type="text" value={researchTitle} placeholder="Research title" onChange={(event) => setResearchTitle(event.target.value)} />
              <textarea value={researchBody} placeholder="Type or paste your research…" rows={10} onChange={(event) => setResearchBody(event.target.value)} />
              <div className="action-buttons">
                <button className="btn-primary" disabled={!researchBody.trim()} onClick={() => void saveResearch("typed", researchTitle || "Untitled research", researchBody)}>
                  Save research
                </button>
                <button className="btn-secondary" onClick={() => setResearchMode("list")}>Cancel</button>
              </div>
            </div>
          )}

          {researchMode === "generate" && (
            <div className="research-editor">
              <label>
                <span>Topic</span>
                <input type="text" value={researchTopic} placeholder={`e.g. ${selectedSymbol} outlook and risks`} onChange={(event) => setResearchTopic(event.target.value)} />
              </label>
              <div className="agent-config-row">
                <label>
                  <span>Provider</span>
                  <select value={researchProvider} onChange={(event) => setResearchProvider(event.target.value)}>
                    <option value="">Choose…</option>
                    {configuredProviders.map((p) => (
                      <option key={p.id} value={p.id}>{p.label}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Model</span>
                  {modelsFor(researchProvider).length > 0 ? (
                    <select value={researchModel} onChange={(event) => setResearchModel(event.target.value)}>
                      <option value="">Choose…</option>
                      {modelsFor(researchProvider).map((m) => (
                        <option key={m} value={m}>{m}</option>
                      ))}
                    </select>
                  ) : (
                    <input type="text" value={researchModel} placeholder="model id" onChange={(event) => setResearchModel(event.target.value)} />
                  )}
                </label>
              </div>
              <div className="action-buttons">
                <button className="btn-primary" disabled={researchBusy || !researchTopic.trim() || !researchProvider} onClick={() => void generateResearch()}>
                  {researchBusy ? "Asking model…" : "Generate draft via harness"}
                </button>
                <button className="btn-secondary" onClick={() => setResearchMode("list")}>Cancel</button>
              </div>
            </div>
          )}

          <div className="research-list">
            {research.length === 0 && <p className="empty-state">No research yet — type, upload, or ask your model.</p>}
            {research.map((doc) => (
              <div key={doc.id} className="research-card">
                <button type="button" className="research-card-head" onClick={() => setOpenDoc(openDoc === doc.id ? null : doc.id)}>
                  <span className={`research-source ${doc.source}`}>
                    {doc.source === "uploaded" ? "⬆ file" : doc.source === "model" ? "✦ model" : "✍️ typed"}
                  </span>
                  <span className="research-title">{doc.title}</span>
                  <span className="research-meta">
                    {doc.symbol ? `${doc.symbol} · ` : ""}
                    {doc.created_at?.slice(0, 10)} · {doc.chars} chars
                  </span>
                  <span className="research-chevron" aria-hidden="true">{openDoc === doc.id ? "▾" : "▸"}</span>
                </button>
                {openDoc === doc.id && (
                  <div className="research-card-body">
                    <pre>{doc.content}</pre>
                    <div className="action-buttons">
                      <button className="btn-secondary" onClick={() => { setResearchTitle(doc.title); setResearchBody(doc.content); setResearchMode("type"); setOpenDoc(null); }}>
                        Edit
                      </button>
                      <button className="btn-danger" onClick={() => void removeResearch(doc)}>Delete</button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ---------------------------------------------------------------- */}
      {/* Trading log                                                       */}
      {/* ---------------------------------------------------------------- */}
      {tab === "log" && (
        <section className="lab-section">
          <div className="lab-section-head">
            <span className="lab-section-icon" aria-hidden="true">📒</span>
            <div>
              <h2>Trading Log</h2>
              <p>What the models chose to do over your chosen duration.</p>
            </div>
          </div>

          <div className="log-controls">
            <label>
              <span>Duration</span>
              <select value={logDays} onChange={(event) => { setLogDays(Number(event.target.value)); setLog(null); }}>
                <option value={1}>Last 24 hours</option>
                <option value={7}>Last 7 days</option>
                <option value={30}>Last 30 days</option>
                <option value={90}>Last 90 days</option>
                <option value={365}>Last year</option>
              </select>
            </label>
            <label>
              <span>Symbol filter</span>
              <input type="text" value={logSymbol} placeholder="e.g. AAPL" onChange={(event) => { setLogSymbol(event.target.value.toUpperCase()); setLog(null); }} />
            </label>
            <button className="btn-primary" onClick={() => void loadLog()} disabled={logLoading}>
              {logLoading ? "Loading…" : "Refresh"}
            </button>
          </div>

          {log && (
            <>
              <div className="log-counts">
                <span className="log-count long">▲ {log.counts.long} long</span>
                <span className="log-count flat">■ {log.counts.flat} flat</span>
                <span className="log-count short">▼ {log.counts.short} short</span>
                <span className="log-count total">{log.total} decisions · {log.runs_covered} runs</span>
                {log.risk_overrides > 0 && (
                  <span className="log-count risk" title="Proposals the risk guard modified">
                    🛡️ {log.risk_overrides} risk override{log.risk_overrides > 1 ? "s" : ""}
                  </span>
                )}
              </div>
              <div className="log-table-wrap">
                <table className="log-table">
                  <thead>
                    <tr>
                      <th>When (UTC)</th>
                      <th>Symbol</th>
                      <th>Strategy</th>
                      <th>Decision</th>
                      <th>Price</th>
                      <th>Risk guard</th>
                      <th>Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(log.entries || []).length === 0 && (
                      <tr>
                        <td colSpan={7} className="empty-state">
                          No model decisions in this window — run a backtest first.
                        </td>
                      </tr>
                    )}
                    {(log.entries || []).map((entry: any, index: number) => (
                      <tr key={`${entry.run_id}-${entry.time}-${index}`}>
                        <td>{String(entry.time).replace("T", " ").slice(0, 16)}</td>
                        <td>{entry.symbol}</td>
                        <td title={entry.strategy}>{entry.strategy}</td>
                        <td>
                          <span className={`action-pill ${entry.action}`}>{entry.action}</span>
                        </td>
                        <td>{typeof entry.price === "number" ? entry.price.toFixed(2) : "—"}</td>
                        <td>
                          {entry.risk ? (
                            <span className="risk-chip" title={entry.risk.reason}>
                              {entry.risk.rule === "short_rejected" ? "short blocked" : entry.risk.rule === "drawdown_halt" ? "halted" : entry.risk.rule}
                              {entry.risk.proposed !== entry.risk.approved ? `: ${entry.risk.proposed}→${entry.risk.approved}` : ""}
                            </span>
                          ) : (
                            <span className="risk-chip clean" title="Approved unchanged by the risk guard">approved</span>
                          )}
                        </td>
                        <td className="log-reason" title={entry.reason}>{entry.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </section>
      )}

      {/* ---------------------------------------------------------------- */}
      {/* Performance                                                       */}
      {/* ---------------------------------------------------------------- */}
      {tab === "performance" && (
        <section className="lab-section">
          <div className="lab-section-head">
            <span className="lab-section-icon" aria-hidden="true">📊</span>
            <div>
              <h2>Performance</h2>
              <p>Market performance of model strategies in easy-to-understand numbers.</p>
            </div>
          </div>

          {runs.length === 0 && <p className="empty-state">No runs yet — run a baseline or an LLM agent from the LLMs tab.</p>}

          <div className="performance-grid">
            {runs.map((run) => (
              <div key={run.id} className="performance-card">
                <div className="performance-head">
                  <span className="performance-strategy">{run.strategy}</span>
                  <span className="performance-meta">
                    {run.symbol} · {run.tf} · {run.bars} bars · {run.created_at?.slice(0, 10)}
                  </span>
                </div>
                <div className="performance-return-row">
                  <span className={`performance-return ${run.metrics.total_return_pct >= 0 ? "up" : "down"}`}>
                    {run.metrics.total_return_pct >= 0 ? "+" : ""}
                    {run.metrics.total_return_pct}%
                  </span>
                  <VerdictChip metrics={run.metrics} />
                  <span className="performance-risk">{run.metrics.risk_note}</span>
                </div>
                <StatGrid metrics={run.metrics} />
                {run.chart ? <RunChart chart={run.chart} /> : null}
                <Sparkline curve={run.equity_curve} />
                <div className="performance-foot">
                  <RiskBadge run={run} />
                  <span>vs market {run.metrics.benchmark_return_pct >= 0 ? "+" : ""}{run.metrics.benchmark_return_pct}%</span>
                  <span>Sharpe {run.metrics.sharpe_ratio}</span>
                  <span>Max drop {run.metrics.max_drawdown_pct}%</span>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ---------------------------------------------------------------- */}
      {/* TradingAgents                                                     */}
      {/* ---------------------------------------------------------------- */}
      {tab === "trading-agents" && (
        <section className="lab-section">
          <div className="lab-section-head">
            <span className="lab-section-icon" aria-hidden="true">🤝</span>
            <div>
              <h2>TradingAgents <span className="ta-credit">by Tauric Research</span></h2>
              <p>Multi-agent debate: analysts → bull vs bear researchers → trader → risk team → portfolio manager.</p>
            </div>
          </div>

          {taStatus && !taStatus.available && (
            <div className="settings-error" role="alert">
              <span>{taStatus.message}</span>
            </div>
          )}

          {taStatus && (
            <div className="ta-form">
              <div className="ta-form-row">
                <label>
                  <span>Ticker</span>
                  <input type="text" value={taTicker} onChange={(event) => setTaTicker(event.target.value.toUpperCase())} />
                </label>
                <label>
                  <span>Analysis date</span>
                  <input type="date" value={taDate} onChange={(event) => setTaDate(event.target.value)} />
                </label>
                <label>
                  <span>Model provider</span>
                  <select value={taProvider} onChange={(event) => setTaProvider(event.target.value)}>
                    <option value="">Choose…</option>
                    {(taStatus.providers || []).map((p) => (
                      <option key={p.id} value={p.id}>{p.label}{p.configured ? "" : " (not configured)"}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Model</span>
                  {modelsFor(taProvider).length > 0 ? (
                    <select value={taModel} onChange={(event) => setTaModel(event.target.value)}>
                      <option value="">Default</option>
                      {modelsFor(taProvider).map((m) => (
                        <option key={m} value={m}>{m}</option>
                      ))}
                    </select>
                  ) : (
                    <input type="text" value={taModel} placeholder="model id" onChange={(event) => setTaModel(event.target.value)} />
                  )}
                </label>
                <label>
                  <span>Research depth</span>
                  <select value={taDepth} onChange={(event) => setTaDepth(Number(event.target.value))}>
                    {(taStatus.depths || []).map((depth) => (
                      <option key={depth.id} value={depth.id}>{depth.label} — {depth.detail}</option>
                    ))}
                  </select>
                </label>
              </div>

              <div className="ta-analysts">
                {(taStatus.analysts || []).map((analyst) => (
                  <label key={analyst.id} className="ta-analyst" title={analyst.detail}>
                    <input
                      type="checkbox"
                      checked={taAnalysts.includes(analyst.id)}
                      onChange={() =>
                        setTaAnalysts((current) =>
                          current.includes(analyst.id)
                            ? current.filter((id) => id !== analyst.id)
                            : [...current, analyst.id],
                        )
                      }
                    />
                    {analyst.label}
                  </label>
                ))}
              </div>

              <div className="action-buttons">
                <button
                  type="button"
                  className="btn-run-backtest"
                  disabled={taBusy || !taStatus.available || !taProvider || taAnalysts.length === 0}
                  onClick={() => void startTradingAgents()}
                >
                  {taBusy ? "Running agent team…" : `Run analysis on ${taTicker}`}
                </button>
                {!isAuthenticated && (
                  <button className="btn-secondary" onClick={() => openAuth("login")}>Sign in required</button>
                )}
              </div>

              {taJobState && (
                <div className="ta-progress">
                  <div className="progress-bar">
                    <div className="progress-fill" style={{ width: `${Math.round((taJobState.progress ?? 0) * 100)}%` }} />
                  </div>
                  <span>{taJobState.message}</span>
                </div>
              )}

              {taJobState?.status === "failed" && (
                <div className="settings-error" role="alert">
                  <span>{taJobState.error}</span>
                </div>
              )}

              {taJobState?.result && (
                <div className="ta-result">
                  <div className="ta-result-head">
                    <span className={`ta-signal ${String(taJobState.result.signal || "").toLowerCase()}`}>
                      {taJobState.result.signal}
                    </span>
                    <div className="ta-result-meta">
                      <strong>{taJobState.result.ticker}</strong> · {taJobState.result.date} ·{" "}
                      {taJobState.result.model} · {taJobState.result.llm_calls} model calls
                    </div>
                  </div>
                  <div className="ta-sections">
                    {(taJobState.result.sections || []).map((section: any) => (
                      <details key={section.id} className="ta-section">
                        <summary>{section.label}</summary>
                        <pre>{section.text}</pre>
                      </details>
                    ))}
                  </div>
                  <p className="ta-disclaimer">{taJobState.result.disclaimer}</p>
                </div>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
