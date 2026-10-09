import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { API_BASE } from "../../lib/constants";
import { readProviderCache, writeProviderCache } from "../../lib/providerCache";
import { Markdown } from "../../lib/markdown";
import { useAuth } from "../../context/AuthContext";
import { useAuthUI } from "../../context/AuthUIContext";

/** OpenAI-compatible + foundation providers the chat can use. */
interface LlmProvider {
  id: string;
  label: string;
  group: "compatible" | "foundation";
  detail: string;
  base_url: string;
  key_required: boolean;
  docs: string;
  has_key: boolean;
  has_stored_key: boolean;
  configured: boolean;
  models: string[];
  default_model: string | null;
}

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
  /** Sections attached by the context feeder when the message was sent. */
  contextLabel?: string;
}

interface ChatSession {
  id: string;
  title: string;
  provider: string | null;
  model: string | null;
  updated_at: number;
  messages: ChatMessage[];
}

interface ContextSection {
  id: string;
  title: string;
  status: "ok" | "unavailable" | "error";
  text: string;
}

interface ContextPayload {
  symbol: string;
  sections: ContextSection[];
  context: string;
  ok_count: number;
}

const SECTION_OPTIONS = [
  { id: "quote", label: "Quote" },
  { id: "candles", label: "Candles" },
  { id: "indicators", label: "Indicators" },
  { id: "news", label: "News" },
  { id: "calendar", label: "Calendar" },
  { id: "portfolio", label: "Portfolio" },
  { id: "analysis", label: "Analysis" },
];

const SELECTION_KEY = "gateway_llm_selection";
const SESSIONS_KEY = "gateway_chat_sessions";

/**
 * Standing system policy injected on every turn — governs answer scope,
 * clarifying questions, fund privacy, and deep-linking into app features.
 */
const SYSTEM_POLICY = [
  "You are Gateway's in-app trading assistant. Follow these rules:",
  "1. Answer ONLY what the user asked. Be concise and do not volunteer extra analysis, metrics, or tangents they did not request.",
  "2. If the request is ambiguous, overly specific, or missing a symbol/ticker, timeframe, or key detail, ask a short clarifying question before answering instead of guessing.",
  "3. Never access, reveal, or act on the user's funds (real or simulated: cash, equity, buying power, balances, positions) unless the user explicitly requests it in this conversation.",
  "4. You can deep-link into app features when useful. Available in-app routes: Strategy Studio /app/strategies, Backtester /app/backtests, Agentic Lab /app/agentic-lab, AI Chat /app/chat, Trading /app/trading, Overview /app/overview, Calendar /app/calendar, News /app/news, Trade Journal /app/journal, Providers /app/settings. To help the user create a strategy, link them to [Strategy Studio](/app/strategies). Use markdown links like [Strategy Studio](/app/strategies).",
  "5. Format output with GitHub-flavored Markdown: headings, bold, bullet/numbered lists, tables for comparisons, and fenced code blocks for code.",
].join("\n");

/** Rough token estimate (~4 chars/token) for the context wheel. */
function estimateTokens(messages: ChatMessage[]): number {
  let chars = 0;
  for (const m of messages) chars += (m.content || "").length;
  return Math.ceil(chars / 4);
}

/** Max context window for the selected model (best-effort, conservative default). */
function maxContextTokens(model: string): number {
  const name = (model || "").toLowerCase();
  if (name.includes("128k") || name.includes("gpt-4o") || name.includes("claude-3-5-sonnet") || name.includes("gemini-1.5-pro")) return 128000;
  if (name.includes("16k") || name.includes("gpt-4")) return 16384;
  if (name.includes("8k") || name.includes("llama-3.1-70b")) return 8192;
  if (name.includes("32k")) return 32768;
  return 16384; // sensible default
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("gateway_auth_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function loadSessions(): ChatSession[] {
  try {
    const raw = localStorage.getItem(SESSIONS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ChatSession[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveSessions(sessions: ChatSession[]) {
  try {
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions.slice(0, 40)));
  } catch {
    /* quota — sessions stay in memory */
  }
}

function newSessionId(): string {
  return `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

async function readError(response: Response, fallback: string): Promise<string> {
  const text = await response.text().catch(() => "");
  if (!text) return `${response.status} ${response.statusText}`.trim();
  try {
    const payload = JSON.parse(text) as unknown;
    if (payload && typeof payload === "object" && "detail" in payload) {
      const detail = (payload as { detail: unknown }).detail;
      if (typeof detail === "string" && detail) return detail;
    }
  } catch {
    /* not JSON */
  }
  return text.slice(0, 300) || fallback;
}

interface AiHarnessProps {
  selectedSymbol: string;
}

export function AiHarness({ selectedSymbol }: AiHarnessProps) {
  const { isAuthenticated } = useAuth();
  const { openAuth } = useAuthUI();

  const [providers, setProviders] = useState<LlmProvider[]>([]);
  const [providersError, setProvidersError] = useState<string | null>(null);
  const [providerId, setProviderId] = useState<string | null>(null);
  const [model, setModel] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);

  const [sessions, setSessions] = useState<ChatSession[]>(() => loadSessions());
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);

  const [panel, setPanel] = useState<"none" | "context">("none");
  const [contextSymbol, setContextSymbol] = useState(selectedSymbol);
  const [contextSections, setContextSections] = useState<string[]>(["quote", "candles", "indicators"]);
  const [contextLoading, setContextLoading] = useState(false);
  const [context, setContext] = useState<ContextPayload | null>(null);
  const [contextError, setContextError] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const selected = useMemo(() => providers.find((p) => p.id === providerId) ?? null, [providers, providerId]);

  // ---- providers ---------------------------------------------------------
  const applyProviders = useCallback(
    (data: { providers: LlmProvider[]; default_provider: string | null }) => {
      setProviders(data.providers);
      setProvidersError(null);
      setProviderId((current) => {
        if (current && data.providers.some((p) => p.id === current)) return current;
        try {
          const stored = JSON.parse(localStorage.getItem(SELECTION_KEY) || "{}") as { provider?: string };
          if (stored.provider && data.providers.some((p) => p.id === stored.provider)) return stored.provider;
        } catch {
          /* ignore */
        }
        return data.default_provider;
      });
    },
    [],
  );

  const fetchProviders = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/llm/providers`);
      if (!response.ok) throw new Error(await readError(response, "Failed to load providers"));
      const data = (await response.json()) as { providers: LlmProvider[]; default_provider: string | null };
      applyProviders(data);
      writeProviderCache("llm", data); // device cache: full payload, no secrets
    } catch (error) {
      setProvidersError(error instanceof Error ? error.message : "Failed to load providers");
    }
  }, [applyProviders]);

  useEffect(() => {
    // Instant provider picker from the device cache, then reconcile.
    const cached = readProviderCache<{ providers: LlmProvider[]; default_provider: string | null }>("llm");
    if (cached?.providers?.length) applyProviders(cached);
    void fetchProviders();
  }, [fetchProviders, applyProviders]);

  useEffect(() => {
    if (!selected) return;
    setModel((current) => {
      if (current) return current;
      try {
        const stored = JSON.parse(localStorage.getItem(SELECTION_KEY) || "{}") as { provider?: string; model?: string };
        if (stored.provider === selected.id && stored.model) return stored.model;
      } catch {
        /* ignore */
      }
      return selected.default_model ?? selected.models[0] ?? "";
    });
  }, [selected]);

  useEffect(() => {
    localStorage.setItem(SELECTION_KEY, JSON.stringify({ provider: providerId, model }));
  }, [providerId, model]);

  useEffect(() => {
    setContextSymbol((current) => current || selectedSymbol);
  }, [selectedSymbol]);

  useEffect(() => {
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages, streaming]);

  // ---- sessions ----------------------------------------------------------
  const persistSession = useCallback(
    (id: string, nextMessages: ChatMessage[]) => {
      if (nextMessages.length === 0) return;
      const title =
        nextMessages.find((m) => m.role === "user")?.content.slice(0, 48) || "Untitled chat";
      const updated: ChatSession[] = [];
      let found = false;
      for (const session of sessions) {
        if (session.id === id) {
          updated.push({ ...session, title, messages: nextMessages, updated_at: Date.now() });
          found = true;
        } else {
          updated.push(session);
        }
      }
      if (!found) {
        updated.unshift({
          id,
          title,
          provider: providerId,
          model: model || null,
          updated_at: Date.now(),
          messages: nextMessages,
        });
      }
      updated.sort((a, b) => b.updated_at - a.updated_at);
      setSessions(updated);
      saveSessions(updated);
    },
    [sessions, providerId, model],
  );

  const startNewChat = useCallback(() => {
    setSessionId(null);
    setMessages([]);
    setChatError(null);
    setContext(null);
    setPanel("none");
  }, []);

  const openSession = useCallback(
    (session: ChatSession) => {
      setSessionId(session.id);
      setMessages(session.messages);
      setChatError(null);
      if (session.provider) setProviderId(session.provider);
      if (session.model) setModel(session.model);
    },
    [],
  );

  const deleteSession = useCallback((id: string) => {
    setSessions((current) => {
      const next = current.filter((session) => session.id !== id);
      saveSessions(next);
      return next;
    });
    setSessionId((current) => (current === id ? null : current));
  }, []);

  // ---- context feeder ----------------------------------------------------
  const loadContext = useCallback(async () => {
    if (!contextSymbol.trim()) return;
    setContextLoading(true);
    setContextError(null);
    try {
      const params = new URLSearchParams({
        symbol: contextSymbol.trim().toUpperCase(),
        sections: contextSections.join(","),
        tf: "1d",
      });
      const response = await fetch(`${API_BASE}/llm/context?${params.toString()}`);
      if (!response.ok) throw new Error(await readError(response, "Context feed failed"));
      const data = (await response.json()) as ContextPayload;
      setContext(data);
      if (data.ok_count === 0) setContextError("No context sources answered — check provider keys in Providers.");
    } catch (error) {
      setContextError(error instanceof Error ? error.message : "Context feed failed");
    } finally {
      setContextLoading(false);
    }
  }, [contextSymbol, contextSections]);

  // ---- chat --------------------------------------------------------------
  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;
    if (!isAuthenticated) {
      setChatError("Sign in to chat — model calls spend API credits.");
      return;
    }
    if (!providerId || !model.trim()) {
      setChatError("Choose a model first (the picker below the composer).");
      return;
    }

    const contextLabel =
      context && context.ok_count > 0 ? `${context.symbol} · ${context.ok_count} sections` : undefined;
    const nextMessages: ChatMessage[] = [
      ...messages,
      { role: "user", content: text, contextLabel },
      { role: "assistant", content: "" },
    ];
    setMessages(nextMessages);
    setInput("");
    setChatError(null);
    setStreaming(true);

    const outbound: { role: string; content: string }[] = [{ role: "system", content: SYSTEM_POLICY }];
    if (context && context.ok_count > 0) outbound.push({ role: "system", content: context.context });
    for (const message of messages) {
      if (message.role !== "system") outbound.push({ role: message.role, content: message.content });
    }
    outbound.push({ role: "user", content: text });

    const activeId = sessionId ?? newSessionId();
    if (!sessionId) setSessionId(activeId);

    const controller = new AbortController();
    abortRef.current = controller;
    let assembled = "";

    try {
      const response = await fetch(`${API_BASE}/llm/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ provider: providerId, model: model.trim(), messages: outbound }),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(await readError(response, "Chat request failed"));
      if (!response.body) throw new Error("No response stream from the server");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finished = false;

      while (!finished) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() ?? "";
        for (const event of events) {
          const line = event.split("\n").find((l) => l.startsWith("data:"));
          if (!line) continue;
          const payload = JSON.parse(line.slice(5).trim()) as { type: string; text?: string; message?: string };
          if (payload.type === "delta" && payload.text) {
            assembled += payload.text;
            const snapshot = assembled;
            setMessages((current) => {
              const next = [...current];
              const last = next[next.length - 1];
              if (last && last.role === "assistant") {
                next[next.length - 1] = { ...last, content: snapshot };
              }
              return next;
            });
          } else if (payload.type === "error") {
            throw new Error(payload.message || "Model error");
          } else if (payload.type === "done") {
            finished = true;
          }
        }
      }
      if (!assembled) assembled = "(empty reply)";
      const finalMessages: ChatMessage[] = nextMessages.map((message, index) =>
        index === nextMessages.length - 1 ? { ...message, content: assembled } : message,
      );
      setMessages(finalMessages);
      persistSession(activeId, finalMessages);
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        setChatError(error instanceof Error ? error.message : "Chat failed");
      }
      if (assembled) persistSession(activeId, [...messages, { role: "user", content: text, contextLabel }, { role: "assistant", content: assembled }]);
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }, [input, streaming, isAuthenticated, providerId, model, messages, context, sessionId, persistSession]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setStreaming(false);
  }, []);

  // ---- context wheel: token usage + compact ------------------------------
  const [wheelOpen, setWheelOpen] = useState(false);
  const [compacting, setCompacting] = useState(false);
  const tokens = estimateTokens(messages);
  const maxTokens = maxContextTokens(model);
  const tokenPct = Math.min(100, Math.round((tokens / maxTokens) * 100));
  const wheelColor = tokenPct >= 90 ? "var(--accent-danger)" : tokenPct >= 70 ? "#f59e0b" : "var(--accent-primary)";

  const compact = useCallback(async () => {
    if (streaming || compacting) return;
    if (messages.filter((m) => m.role !== "system").length < 2) return;
    setCompacting(true);
    setChatError(null);
    try {
      const outbound: { role: string; content: string }[] = [
        {
          role: "system",
          content:
            "You are a conversation compressor. Summarize the following conversation into a tight context brief: keep every symbol, decision, number, and preference in bullet points, drop pleasantries. Under 300 words. Output only the summary.",
        },
      ];
      for (const m of messages) if (m.role !== "system") outbound.push({ role: m.role, content: m.content });

      const response = await fetch(`${API_BASE}/llm/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ provider: providerId, model: model.trim(), messages: outbound }),
      });
      if (!response.ok || !response.body) throw new Error(await readError(response, "Compaction failed"));

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let assembled = "";
      let finished = false;
      while (!finished) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() ?? "";
        for (const event of events) {
          const line = event.split("\n").find((l) => l.startsWith("data:"));
          if (!line) continue;
          const payload = JSON.parse(line.slice(5).trim()) as { type: string; text?: string; message?: string };
          if (payload.type === "delta" && payload.text) assembled += payload.text;
          else if (payload.type === "error") throw new Error(payload.message || "Compaction error");
          else if (payload.type === "done") finished = true;
        }
      }
      if (!assembled.trim()) throw new Error("Compaction produced an empty summary");

      const condensed: ChatMessage[] = [
        { role: "system", content: SYSTEM_POLICY },
        { role: "system", content: `Compacted conversation context:\n${assembled.trim()}` },
      ];
      setMessages(condensed);
      const id = sessionId ?? newSessionId();
      if (!sessionId) setSessionId(id);
      persistSession(id, condensed);
      setWheelOpen(false);
    } catch (error) {
      setChatError(error instanceof Error ? error.message : "Compaction failed");
    } finally {
      setCompacting(false);
    }
  }, [streaming, compacting, messages, providerId, model, sessionId, persistSession]);

  const grouped = useMemo(() => {
    const compatible = providers.filter((p) => p.group === "compatible");
    const foundation = providers.filter((p) => p.group === "foundation");
    return { compatible, foundation };
  }, [providers]);

  const composer = (
    <div className={`chat-composer-card ${panel === "context" ? "raised" : ""}`}>
      <textarea
        className="chat-composer-input"
        value={input}
        onChange={(event) => setInput(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            void send();
          }
        }}
        placeholder="Ask anything — tickers, setups, your portfolio… (@ for context)"
        rows={panel === "context" ? 3 : 2}
      />

      {panel === "context" && (
        <div className="chat-context-panel">
          <div className="context-row">
            <label className="context-symbol-field">
              <span>Symbol</span>
              <input
                type="text"
                value={contextSymbol}
                onChange={(event) => setContextSymbol(event.target.value)}
                placeholder={selectedSymbol}
              />
            </label>
            <div className="context-chips">
              {SECTION_OPTIONS.map((section) => (
                <button
                  key={section.id}
                  type="button"
                  className={`context-chip ${contextSections.includes(section.id) ? "on" : ""}`}
                  onClick={() =>
                    setContextSections((current) =>
                      current.includes(section.id)
                        ? current.filter((id) => id !== section.id)
                        : [...current, section.id],
                    )
                  }
                >
                  {section.label}
                </button>
              ))}
            </div>
            <button
              type="button"
              className="btn-primary"
              onClick={() => void loadContext()}
              disabled={contextLoading || contextSections.length === 0}
            >
              {contextLoading ? "Feeding…" : "Feed"}
            </button>
          </div>
          {contextError && <div className="context-error">{contextError}</div>}
          {context && (
            <div className="context-preview">
              {context.sections.map((section) => (
                <span key={section.id} className={`context-section-chip ${section.status}`}>
                  {section.title}: {section.status === "ok" ? "ready" : "unavailable"}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="chat-composer-bar">
        <button
          type="button"
          className={`chat-composer-icon ${panel === "context" ? "on" : ""}`}
          onClick={() => setPanel((current) => (current === "context" ? "none" : "context"))}
          title="Attach market context"
          aria-label="Attach market context"
        >
          +
        </button>

        {/* model picker (provider popup inside the composer) */}
        <div className="model-picker-anchor">
          <button
            type="button"
            className="model-picker-button"
            onClick={() => setPickerOpen((open) => !open)}
            aria-expanded={pickerOpen}
            title="Choose provider and model"
          >
            <span aria-hidden="true">✦</span>
            {selected ? `${selected.label} · ${model || "pick model"}` : "Choose model"}
            <span aria-hidden="true">▾</span>
          </button>
          {pickerOpen && (
            <div className="model-picker-menu" role="menu">
              {(["compatible", "foundation"] as const).map((group) => (
                <div key={group} className="model-picker-group">
                  <div className="model-picker-group-title">
                    {group === "compatible" ? "OpenAI-compatible APIs" : "Foundation API keys"}
                  </div>
                  {grouped[group].map((provider) => (
                    <div key={provider.id} className={`model-picker-item ${providerId === provider.id ? "selected" : ""}`}>
                      <button
                        type="button"
                        className="model-picker-item-main"
                        onClick={() => {
                          setProviderId(provider.id);
                          setModel(provider.default_model ?? provider.models[0] ?? "");
                        }}
                      >
                        <span className={`status-dot ${provider.configured ? "on" : "off"}`} aria-hidden="true" />
                        <span>{provider.label}</span>
                        {!provider.configured && <span className="model-picker-note">not configured</span>}
                      </button>
                      {providerId === provider.id && provider.models.length > 0 && (
                        <select
                          className="model-picker-select"
                          value={model || provider.default_model || provider.models[0]}
                          onChange={(event) => setModel(event.target.value)}
                        >
                          {provider.models.map((entry) => (
                            <option key={entry} value={entry}>
                              {entry}
                            </option>
                          ))}
                        </select>
                      )}
                      {providerId === provider.id && provider.models.length === 0 && (
                        <input
                          className="model-picker-input"
                          type="text"
                          value={model}
                          placeholder="model id"
                          onChange={(event) => setModel(event.target.value)}
                        />
                      )}
                    </div>
                  ))}
                </div>
              ))}
              <div className="model-picker-footer">
                <a href="/app/settings" className="provider-popup-link">
                  Manage API keys in Providers →
                </a>
              </div>
            </div>
          )}
        </div>

        <span className="chat-composer-hint">{context && context.ok_count > 0 ? `📎 ${context.symbol} context on` : ""}</span>

        {/* context wheel: hover/click → token usage, max context, compact */}
        <div
          className="ctx-pop-anchor"
          onMouseEnter={() => setWheelOpen(true)}
          onMouseLeave={() => setWheelOpen(false)}
        >
          <button
            type="button"
            className="ctx-wheel"
            style={{ "--wheel-pct": tokenPct, "--wheel-color": wheelColor } as CSSProperties}
            onClick={() => setWheelOpen((v) => !v)}
            aria-label="Context usage"
            title="Context usage"
          >
            <span className="ctx-wheel-label">{tokenPct}%</span>
          </button>
          {wheelOpen && (
            <>
              <div className="ctx-pop-bridge" aria-hidden="true" />
              <div
                className="ctx-pop"
                role="dialog"
                aria-label="Context usage"
                onMouseEnter={() => setWheelOpen(true)}
                onMouseLeave={() => setWheelOpen(false)}
              >
                <div className="ctx-pop-title">Context usage</div>
                <div className="ctx-rows"><span>Tokens used</span><span>{tokens.toLocaleString()}</span></div>
                <div className="ctx-bar"><div className="ctx-bar-fill" style={{ width: `${tokenPct}%`, background: wheelColor }} /></div>
                <div className="ctx-rows"><span>Max context</span><span>{maxTokens.toLocaleString()}</span></div>
                <div className="ctx-rows"><span>Remaining</span><span>{Math.max(0, maxTokens - tokens).toLocaleString()}</span></div>
                <button type="button" className="ctx-compact" onClick={() => void compact()} disabled={compacting || streaming}>
                  {compacting ? "Compacting…" : "⤨ Compact chat"}
                </button>
              </div>
            </>
          )}
        </div>

        {streaming ? (
          <button type="button" className="chat-send stop" onClick={stop} aria-label="Stop">
            ■
          </button>
        ) : (
          <button
            type="button"
            className="chat-send"
            onClick={() => void send()}
            disabled={!input.trim()}
            aria-label="Send"
          >
            ↑
          </button>
        )}
      </div>
    </div>
  );

  return (
    <div className="chat-page">
      <aside className="chat-sessions">
        <button type="button" className="chat-new-btn" onClick={startNewChat}>
          + New chat
        </button>
        <div className="chat-sessions-label">Past chats</div>
        <div className="chat-sessions-list">
          {sessions.length === 0 && <p className="chat-sessions-empty">No chats yet.</p>}
          {sessions.map((session) => (
            <div key={session.id} className={`chat-session-item ${sessionId === session.id ? "active" : ""}`}>
              <button type="button" className="chat-session-main" onClick={() => openSession(session)} title={session.title}>
                <span className="chat-session-title">{session.title}</span>
                <span className="chat-session-meta">
                  {new Date(session.updated_at).toLocaleDateString()} · {session.model || "model"}
                </span>
              </button>
              <button
                type="button"
                className="chat-session-delete"
                onClick={() => deleteSession(session.id)}
                title="Delete chat"
              >
                ×
              </button>
            </div>
          ))}
        </div>
        <a href="/app/agentic-lab" className="chat-sessions-link">
          🧪 Agentic Lab →
        </a>
      </aside>

      <main className="chat-main">
        <div className="chat-topbar">
          <span className="chat-topbar-title">AI Chat</span>
          {providersError ? (
            <span className="chat-topbar-error">{providersError}</span>
          ) : (
            <span className="chat-topbar-model">
              {selected ? `${selected.label} · ${model || "no model"}` : "no model selected"}
            </span>
          )}
          {!isAuthenticated && (
            <button type="button" className="btn-secondary" onClick={() => openAuth("login")}>
              Sign in
            </button>
          )}
        </div>

        <div className="chat-scroll" ref={scrollRef}>
          {messages.length === 0 ? (
            // Empty-state hero: the two guidance lines only — the old
            // "gateway" watermark wordmark was removed as pure decoration.
            <div className="chat-hero">
              <div className="chat-hero-copy">
                <p>Ask about a ticker, a setup, or your portfolio.</p>
                <p className="hint">
                  {context && context.ok_count > 0
                    ? `Context ready: ${context.symbol} · ${context.ok_count} sections attach automatically.`
                    : "Press + to feed live market context, or open a past chat on the left."}
                </p>
              </div>
            </div>
          ) : (
            messages.map((message, index) => (
              <div key={index} className={`chat-turn ${message.role}`}>
                <div className="chat-turn-role">
                  {message.role === "assistant" ? `✦ ${model || "model"}` : message.role === "system" ? "context" : "you"}
                </div>
                {message.contextLabel && <div className="chat-context-tag">📎 {message.contextLabel}</div>}
                <div className="chat-turn-body">
                  {message.role === "assistant" ? (
                    message.content ? (
                      <Markdown content={message.content} />
                    ) : streaming && index === messages.length - 1 ? (
                      <span className="chat-cursor" />
                    ) : null
                  ) : (
                    message.content ||
                    (streaming && index === messages.length - 1 ? <span className="chat-cursor" /> : "")
                  )}
                </div>
              </div>
            ))
          )}
        </div>

        {chatError && (
          <div className="settings-error chat-error" role="alert">
            <span>{chatError}</span>
            {!isAuthenticated && (
              <button className="btn-primary" onClick={() => openAuth("login")}>
                Sign in
              </button>
            )}
            <button className="btn-secondary" onClick={() => setChatError(null)}>
                Dismiss
              </button>
          </div>
        )}

        {composer}
      </main>
    </div>
  );
}
