import { useCallback, useEffect, useState } from "react";
import { API_BASE } from "../../lib/constants";
import { useAuth } from "../../context/AuthContext";
import { useAuthUI } from "../../context/AuthUIContext";

export interface LlmProvider {
  id: string;
  label: string;
  group: "compatible" | "foundation";
  detail: string;
  base_url: string;
  base_url_editable: boolean;
  key_required: boolean;
  key_env: string | null;
  docs: string;
  placeholder: string;
  has_key: boolean;
  has_stored_key: boolean;
  configured: boolean;
  models: string[];
  default_model: string | null;
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("gateway_auth_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
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
  return text || fallback;
}

interface CardState {
  baseUrl: string;
  apiKey: string;
  showKey: boolean;
  modelInput: string;
  defaultModel: string;
  loading: boolean;
  message: { ok: boolean; text: string } | null;
}

function LlmProviderCard({
  provider,
  selected,
  onSelect,
  state,
  setState,
  onSave,
  onTest,
  onFetchModels,
  onDeleteKey,
  isAuthenticated,
  onSignIn,
}: {
  provider: LlmProvider;
  selected: boolean;
  onSelect: () => void;
  state: CardState;
  setState: (next: CardState) => void;
  onSave: () => void;
  onTest: () => void;
  onFetchModels: () => void;
  onDeleteKey: () => void;
  isAuthenticated: boolean;
  onSignIn: () => void;
}) {
  const patch = (changes: Partial<CardState>) => setState({ ...state, ...changes });

  return (
    <div className={`llm-card ${selected ? "selected" : ""}`}>
      <button type="button" className="llm-card-header" onClick={onSelect} aria-expanded={selected}>
        <div className="llm-card-title">
          <h4>{provider.label}</h4>
          <span className="llm-card-detail">{provider.detail}</span>
        </div>
        <div className="llm-card-status">
          {provider.has_stored_key && <span className="stored-badge">Key stored</span>}
          <span className={`status-badge ${provider.configured ? "configured" : "not-configured"}`}>
            <span className="status-dot" aria-hidden="true" />
            {provider.configured ? "Ready" : "Not configured"}
          </span>
          <span className={`provider-chevron ${selected ? "open" : ""}`} aria-hidden="true">▸</span>
        </div>
      </button>

      {selected && (
        <div className="llm-card-body">
          <label className="llm-field">
            <span>Base URL {provider.base_url_editable ? "(editable)" : "(official endpoint)"}</span>
            <input
              type="text"
              value={state.baseUrl}
              onChange={(event) => patch({ baseUrl: event.target.value })}
              placeholder={provider.base_url}
              readOnly={!provider.base_url_editable}
              spellCheck={false}
            />
          </label>
          <p className="llm-hint">{provider.detail}{provider.key_required ? "" : " — API key optional"}</p>

          <div className="llm-field-row">
            <label className="llm-field">
              <span>API key {state.showKey ? "(visible)" : "(hidden)"}</span>
              <input
                type={state.showKey ? "text" : "password"}
                value={state.apiKey}
                onChange={(event) => patch({ apiKey: event.target.value })}
                placeholder={provider.has_stored_key ? "••••••••  (stored — type to replace)" : provider.placeholder}
                autoComplete="off"
                spellCheck={false}
              />
            </label>
            <label className="checkbox-label">
              <input type="checkbox" checked={state.showKey} onChange={(event) => patch({ showKey: event.target.checked })} />
              Show
            </label>
          </div>

          <div className="llm-models">
            <div className="llm-field-row">
              <label className="llm-field">
                <span>Default model</span>
                <input
                  type="text"
                  value={state.defaultModel}
                  onChange={(event) => patch({ defaultModel: event.target.value })}
                  placeholder="model id used by chat & lab"
                  spellCheck={false}
                />
              </label>
              <button type="button" className="btn-secondary" onClick={onFetchModels} disabled={state.loading || !provider.configured}>
                Fetch models
              </button>
            </div>
            {provider.models.length > 0 && (
              <div className="llm-model-chips">
                {provider.models.slice(0, 30).map((entry) => (
                  <button
                    key={entry}
                    type="button"
                    className={`context-chip ${state.defaultModel === entry ? "on" : ""}`}
                    onClick={() => patch({ defaultModel: entry })}
                    title="Click to make this the default model"
                  >
                    {entry}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="action-buttons">
            <button className="btn-primary" onClick={onSave} disabled={state.loading || !isAuthenticated}>
              {isAuthenticated ? "Save" : "Sign in to save"}
            </button>
            <button className="btn-secondary" onClick={onTest} disabled={state.loading || !provider.configured || !isAuthenticated}>
              Test connection
            </button>
            <button className="btn-danger" onClick={onDeleteKey} disabled={state.loading || !provider.has_stored_key || !isAuthenticated}>
              Delete key
            </button>
            {!isAuthenticated && (
              <button className="btn-secondary" onClick={onSignIn}>Sign in</button>
            )}
            {provider.docs && (
              <a className="llm-docs-link" href={provider.docs} target="_blank" rel="noreferrer">
                Get a key ↗
              </a>
            )}
          </div>

          {state.message && (
            <div className={`test-result ${state.message.ok ? "success" : "error"}`}>
              <span>{state.message.text}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * The "LLM APIs" panel of the Providers page: every OpenAI-compatible
 * gateway plus the foundation API keys, all key entry lives here.
 */
export function LlmProviderSettings() {
  const { isAuthenticated } = useAuth();
  const { openAuth } = useAuthUI();
  const [providers, setProviders] = useState<LlmProvider[]>([]);
  const [open, setOpen] = useState<Record<string, CardState>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const fetchProviders = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/llm/providers`);
      if (!response.ok) throw new Error(await readError(response, "Failed to load LLM providers"));
      const data = (await response.json()) as { providers: LlmProvider[] };
      setProviders(data.providers);
      setLoadError(null);
      setOpen((current) => {
        const next = { ...current };
        for (const provider of data.providers) {
          if (!next[provider.id]) {
            next[provider.id] = {
              baseUrl: provider.base_url,
              apiKey: "",
              showKey: false,
              modelInput: "",
              defaultModel: provider.default_model ?? "",
              loading: false,
              message: null,
            };
          }
        }
        return next;
      });
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Failed to load LLM providers");
    }
  }, []);

  useEffect(() => {
    void fetchProviders();
  }, [fetchProviders]);

  const mutate = async (id: string, run: (state: CardState) => Promise<CardState>) => {
    const state = open[id];
    if (!state) return;
    setOpen((current) => {
      const existing = current[id];
      if (!existing) return current;
      return { ...current, [id]: { ...existing, loading: true, message: null } };
    });
    try {
      const next = await run({ ...state, loading: true });
      setOpen((current) => ({ ...current, [id]: { ...next, loading: false } }));
      await fetchProviders();
    } catch (error) {
      setOpen((current) => ({
        ...current,
        [id]: {
          ...state,
          loading: false,
          message: { ok: false, text: error instanceof Error ? error.message : "Request failed" },
        },
      }));
    }
  };

  const save = (id: string) =>
    mutate(id, async (state) => {
      const response = await fetch(`${API_BASE}/llm/providers/${encodeURIComponent(id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({
          base_url: state.baseUrl.trim() || null,
          api_key: state.apiKey.trim() || null,
          default_model: state.defaultModel.trim() || null,
        }),
      });
      if (!response.ok) throw new Error(await readError(response, "Save failed"));
      return {
        ...state,
        apiKey: "",
        message: { ok: true, text: state.apiKey.trim() ? "Saved — key encrypted at rest." : "Saved." },
      };
    });

  const test = (id: string) =>
    mutate(id, async (state) => {
      const response = await fetch(`${API_BASE}/llm/providers/${encodeURIComponent(id)}/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ model: state.defaultModel.trim() || null }),
      });
      const payload = (await response.json()) as { success?: boolean; message?: string };
      if (!response.ok) throw new Error(await readError(response, "Test failed"));
      return { ...state, message: { ok: payload.success === true, text: payload.message || "Test finished" } };
    });

  const fetchModels = (id: string) =>
    mutate(id, async (state) => {
      const response = await fetch(`${API_BASE}/llm/providers/${encodeURIComponent(id)}/models`, {
        headers: authHeaders(),
      });
      if (!response.ok) throw new Error(await readError(response, "Model list failed"));
      const payload = (await response.json()) as { models: string[] };
      return {
        ...state,
        defaultModel: state.defaultModel || payload.models[0] || "",
        message: { ok: true, text: `Found ${payload.models.length} models.` },
      };
    });

  const deleteKey = async (id: string) => {
    if (!window.confirm("Delete the stored API key for this provider?")) return;
    await mutate(id, async (state) => {
      const response = await fetch(`${API_BASE}/llm/providers/${encodeURIComponent(id)}/key`, {
        method: "DELETE",
        headers: authHeaders(),
      });
      if (!response.ok) throw new Error(await readError(response, "Delete failed"));
      return { ...state, apiKey: "", message: { ok: true, text: "Key deleted." } };
    });
  };

  const compatible = providers.filter((p) => p.group === "compatible");
  const foundation = providers.filter((p) => p.group === "foundation");

  return (
    <div className="llm-settings">
      {loadError && (
        <div className="settings-error" role="alert">
          <span>{loadError}</span>
          <button className="btn-secondary" onClick={() => void fetchProviders()}>Retry</button>
        </div>
      )}

      <details className="api-group" open>
        <summary className="api-group-summary">
          <span className="api-group-icon" aria-hidden="true">🧠</span>
          <span className="api-group-text">
            <strong>LLM APIs — OpenAI-compatible</strong>
            <span>OpenRouter · Ollama · OpenCode Zen · Cloudflare AI Gateway · Groq · Kilo Gateway · custom</span>
          </span>
          <span className={`api-group-count ${compatible.filter((p) => p.configured).length ? "on" : ""}`}>
            {compatible.filter((p) => p.configured).length}/{compatible.length} ready
          </span>
        </summary>
        <div className="api-group-body">
          {compatible.map((provider) => {
            const cardState = open[provider.id];
            if (!cardState) return null;
            return (
              <LlmProviderCard
                key={provider.id}
                provider={provider}
                selected={selected === provider.id}
                onSelect={() => setSelected((current) => (current === provider.id ? null : provider.id))}
                state={cardState}
                setState={(next) => setOpen((current) => ({ ...current, [provider.id]: next }))}
                onSave={() => save(provider.id)}
                onTest={() => test(provider.id)}
                onFetchModels={() => fetchModels(provider.id)}
                onDeleteKey={() => void deleteKey(provider.id)}
                isAuthenticated={isAuthenticated}
                onSignIn={() => openAuth("login")}
              />
            );
          })}
        </div>
      </details>

      <details className="api-group" open>
        <summary className="api-group-summary">
          <span className="api-group-icon" aria-hidden="true">🏛️</span>
          <span className="api-group-text">
            <strong>LLM APIs — Foundation keys</strong>
            <span>OpenAI · Anthropic · Google Gemini first-party keys</span>
          </span>
          <span className={`api-group-count ${foundation.filter((p) => p.configured).length ? "on" : ""}`}>
            {foundation.filter((p) => p.configured).length}/{foundation.length} ready
          </span>
        </summary>
        <div className="api-group-body">
          {foundation.map((provider) => {
            const cardState = open[provider.id];
            if (!cardState) return null;
            return (
              <LlmProviderCard
                key={provider.id}
                provider={provider}
                selected={selected === provider.id}
                onSelect={() => setSelected((current) => (current === provider.id ? null : provider.id))}
                state={cardState}
                setState={(next) => setOpen((current) => ({ ...current, [provider.id]: next }))}
                onSave={() => save(provider.id)}
                onTest={() => test(provider.id)}
                onFetchModels={() => fetchModels(provider.id)}
                onDeleteKey={() => void deleteKey(provider.id)}
                isAuthenticated={isAuthenticated}
                onSignIn={() => openAuth("login")}
              />
            );
          })}
        </div>
      </details>
    </div>
  );
}
