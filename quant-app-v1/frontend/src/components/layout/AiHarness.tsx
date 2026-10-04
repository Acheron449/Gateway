import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE } from "../../lib/constants";
import { useAuth } from "../../context/AuthContext";
import { useAuthUI } from "../../context/AuthUIContext";

/** OpenAI-compatible + foundation providers the harness can chat with. */
interface LlmProvider {
  id: string;
  label: string;
  group: "compatible" | "foundation";
  detail: string;
  base_url: string;
  base_url_editable: boolean;
  key_required: boolean;
  docs: string;
  has_key: boolean;
  has_stored_key: boolean;
  configured: boolean;
  models: string[];
  default_model: string | null;
}

interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
  /** Sections attached by the context feeder when the message was sent. */
  contextLabel?: string;
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

const STORAGE_KEY = "gateway_llm_selection";

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("gateway_auth_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function loadSelection(): { provider: string | null; model: string | null } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as { provider?: string; model?: string };
      return { provider: parsed.provider ?? null, model: parsed.model ?? null };
    }
  } catch {
    /* fall through to defaults */
  }
  return { provider: null, model: null };
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
  return text.slice(0, 300);
}

interface AiHarnessProps {
  selectedSymbol: string;
}

export function AiHarness({ selectedSymbol }: AiHarnessProps) {
  const { isAuthenticated } = useAuth();
  const { openAuth } = useAuthUI();

  const [providers, setProviders] = useState<LlmProvider[]>([]);
  const [defaultProvider, setDefaultProvider] = useState<string | null>(null);
  const [providerId, setProviderId] = useState<string | null>(null);
  const [model, setModel] = useState<string>("");
  const [popupOpen, setPopupOpen] = useState(false);
  const [providersError, setProvidersError] = useState<string | null>(null);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);

  const [contextOpen, setContextOpen] = useState(false);
  const [contextSymbol, setContextSymbol] = useState(selectedSymbol);
  const [contextSections, setContextSections] = useState<string[]>(["quote", "candles", "indicators"]);
  const [contextLoading, setContextLoading] = useState(false);
  const [context, setContext] = useState<ContextPayload | null>(null);
  const [contextError, setContextError] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const selected = useMemo(
    () => providers.find((p) => p.id === providerId) ?? null,
    [providers, providerId],
  );

  const fetchProviders = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/llm/providers`);
      if (!response.ok) throw new Error(await readError(response, "Failed to load providers"));
      const data = (await response.json()) as { providers: LlmProvider[]; default_provider: string | null };
      setProviders(data.providers);
      setDefaultProvider(data.default_provider);
      setProvidersError(null);
      setProviderId((current) => {
        if (current && data.providers.some((p) => p.id === current)) return current;
        const stored = loadSelection();
        if (stored.provider && data.providers.some((p) => p.id === stored.provider)) return stored.provider;
        return data.default_provider;
      });
    } catch (error) {
      setProvidersError(error instanceof Error ? error.message : "Failed to load providers");
    }
  }, []);

  useEffect(() => {
    void fetchProviders();
  }, [fetchProviders]);

  // Adopt the stored/default model once providers arrive.
  useEffect(() => {
    if (!selected) return;
    const stored = loadSelection();
    setModel((current) => {
      if (current) return current;
      if (stored.provider === selected.id && stored.model) return stored.model;
      return selected.default_model ?? selected.models[0] ?? "";
    });
  }, [selected]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ provider: providerId, model }));
  }, [providerId, model]);

  useEffect(() => {
    setContextSymbol((current) => current || selectedSymbol);
  }, [selectedSymbol]);

  useEffect(() => {
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages, streaming]);

  const pickProvider = useCallback((id: string) => {
    setProviderId(id);
    setModel("");
    setPopupOpen(false);
    setChatError(null);
  }, []);

  const loadContext = useCallback(async () => {
    if (!contextSymbol.trim()) return;
    setContextLoading(true);
    setContextError(null);
    try {
      const params = new URLSearchParams({ symbol: contextSymbol.trim().toUpperCase(), sections: contextSections.join(","), tf: "1d" });
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

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;
    if (!isAuthenticated) {
      setChatError("Sign in to chat — model calls spend API credits.");
      return;
    }
    if (!providerId || !model.trim()) {
      setChatError("Choose a provider and model first (top-right menu).");
      return;
    }

    const history: ChatMessage[] = [...messages];
    const outbound: { role: string; content: string }[] = [];
    if (context && context.ok_count > 0) {
      outbound.push({ role: "system", content: context.context });
    }
    for (const message of history) {
      outbound.push({ role: message.role, content: message.content });
    }
    outbound.push({ role: "user", content: text });

    const contextLabel =
      context && context.ok_count > 0 ? `${context.symbol} · ${context.ok_count} sections` : undefined;

    setMessages([...history, { role: "user", content: text, contextLabel }, { role: "assistant", content: "" }]);
    setInput("");
    setChatError(null);
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

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
            setMessages((current) => {
              const next = [...current];
              const last = next[next.length - 1];
              if (last && last.role === "assistant") {
                next[next.length - 1] = { ...last, content: last.content + payload.text };
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
      setMessages((current) => {
        const next = [...current];
        const last = next[next.length - 1];
        if (last && last.role === "assistant" && !last.content) {
          next[next.length - 1] = { ...last, content: "(empty reply)" };
        }
        return next;
      });
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        setChatError(error instanceof Error ? error.message : "Chat failed");
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }, [input, streaming, isAuthenticated, providerId, model, messages, context]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setStreaming(false);
  }, []);

  const grouped = useMemo(() => {
    const compatible = providers.filter((p) => p.group === "compatible");
    const foundation = providers.filter((p) => p.group === "foundation");
    return { compatible, foundation };
  }, [providers]);

  return (
    <div className="canvas-view-inner harness-view">
      <div className="view-header harness-header">
        <div className="harness-title">
          <h1>AI Harness</h1>
          <p className="view-description">Chat with your model about the market — feed it live context from Gateway.</p>
        </div>

        {/* Provider popup menu (requirement 5) */}
        <div className="provider-popup-anchor">
          <button
            type="button"
            className="provider-popup-button"
            onClick={() => setPopupOpen((open) => !open)}
            aria-expanded={popupOpen}
            title="Choose provider and model"
          >
            <span className="provider-popup-label">
              {selected ? selected.label : "Choose provider"}
              {model ? ` · ${model}` : ""}
            </span>
            <span aria-hidden="true">▾</span>
          </button>
          {popupOpen && (
            <div className="provider-popup-menu" role="menu">
              {(["compatible", "foundation"] as const).map((group) => (
                <div key={group} className="provider-popup-group">
                  <div className="provider-popup-group-title">
                    {group === "compatible" ? "OpenAI-compatible APIs" : "Foundation API keys"}
                  </div>
                  {grouped[group].map((provider) => (
                    <div key={provider.id} className={`provider-popup-item ${providerId === provider.id ? "selected" : ""}`}>
                      <button type="button" className="provider-popup-item-main" onClick={() => pickProvider(provider.id)}>
                        <span className={`status-dot ${provider.configured ? "on" : "off"}`} aria-hidden="true" />
                        <span className="provider-popup-item-label">{provider.label}</span>
                        {!provider.configured && <span className="provider-popup-item-note">not configured</span>}
                      </button>
                      {providerId === provider.id && (
                        <div className="provider-popup-model">
                          {provider.models.length > 0 ? (
                            <select value={model || provider.default_model || provider.models[0]} onChange={(event) => setModel(event.target.value)}>
                              {provider.models.map((entry) => (
                                <option key={entry} value={entry}>{entry}</option>
                              ))}
                            </select>
                          ) : (
                            <input
                              type="text"
                              value={model}
                              placeholder="Model id (e.g. gpt-4o-mini)"
                              onChange={(event) => setModel(event.target.value)}
                            />
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ))}
              <div className="provider-popup-footer">
                <a href="/app/settings" className="provider-popup-link">Manage keys in Providers →</a>
              </div>
            </div>
          )}
        </div>
      </div>

      {providersError && (
        <div className="settings-error" role="alert">
          <span>{providersError}</span>
          <button className="btn-secondary" onClick={() => void fetchProviders()}>Retry</button>
        </div>
      )}

      {/* Context feeder (requirement 6) */}
      <div className="context-feeder">
        <button type="button" className="context-feeder-toggle" onClick={() => setContextOpen((open) => !open)} aria-expanded={contextOpen}>
          <span aria-hidden="true">{contextOpen ? "▾" : "▸"}</span> Context feeder
          {context && context.ok_count > 0 && <span className="context-badge">{context.symbol} · {context.ok_count} sections</span>}
        </button>
        {contextOpen && (
          <div className="context-feeder-body">
            <div className="context-row">
              <label className="context-symbol-field">
                <span>Symbol</span>
                <input type="text" value={contextSymbol} onChange={(event) => setContextSymbol(event.target.value)} placeholder={selectedSymbol} />
              </label>
              <div className="context-chips">
                {SECTION_OPTIONS.map((section) => (
                  <button
                    key={section.id}
                    type="button"
                    className={`context-chip ${contextSections.includes(section.id) ? "on" : ""}`}
                    onClick={() =>
                      setContextSections((current) =>
                        current.includes(section.id) ? current.filter((id) => id !== section.id) : [...current, section.id],
                      )
                    }
                  >
                    {section.label}
                  </button>
                ))}
              </div>
              <button type="button" className="btn-primary" onClick={() => void loadContext()} disabled={contextLoading || contextSections.length === 0}>
                {contextLoading ? "Feeding…" : "Feed context"}
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
      </div>

      {/* Conversation */}
      <div className="chat-scroll" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="chat-empty">
            <p>Ask the model about a ticker, a setup, or your portfolio.</p>
            <p className="hint">
              {context ? `Context ready: ${context.symbol} · ${context.ok_count} sections will be attached.` : "Open the context feeder to attach live market data first."}
            </p>
          </div>
        )}
        {messages.map((message, index) => (
          <div key={index} className={`chat-message ${message.role}`}>
            <div className="chat-message-role">{message.role === "assistant" ? model || "model" : message.role === "system" ? "context" : "you"}</div>
            {message.contextLabel && <div className="chat-context-tag">📎 {message.contextLabel}</div>}
            <div className="chat-message-body">{message.content || (streaming && index === messages.length - 1 ? "…" : "")}</div>
          </div>
        ))}
      </div>

      {chatError && (
        <div className="settings-error" role="alert">
          <span>{chatError}</span>
          {!isAuthenticated && (
            <button className="btn-primary" onClick={() => openAuth("login")}>Sign in</button>
          )}
        </div>
      )}

      <div className="chat-composer">
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void send();
            }
          }}
          placeholder={isAuthenticated ? "Message your model… (Enter to send, Shift+Enter for newline)" : "Sign in to chat with a model"}
          rows={2}
        />
        {streaming ? (
          <button type="button" className="btn-danger" onClick={stop}>Stop</button>
        ) : (
          <button type="button" className="btn-primary" onClick={() => void send()} disabled={!input.trim()}>
            Send
          </button>
        )}
      </div>
    </div>
  );
}
