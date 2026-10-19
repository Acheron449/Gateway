import { useEffect, useRef, useState } from "react";
import { API_BASE } from "../../lib/constants";

export interface ProviderModel {
  id: string;
  is_free: boolean;
}

interface ModelPickerProps {
  providerId: string;
  configured: boolean;
  value: string;
  onChange: (model: string) => void;
  className?: string;
}

const catalogueCache = new Map<string, ProviderModel[]>();
const catalogueRequests = new Map<string, Promise<ProviderModel[]>>();

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("gateway_auth_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function readError(response: Response): Promise<string> {
  const body = await response.text().catch(() => "");
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    if (typeof parsed.detail === "string" && parsed.detail) return parsed.detail;
  } catch {
    // Fall through to a concise response message.
  }
  return body.slice(0, 300) || `${response.status} ${response.statusText}`.trim();
}

async function fetchCatalogue(providerId: string): Promise<ProviderModel[]> {
  const cached = catalogueCache.get(providerId);
  if (cached) return cached;
  const inFlight = catalogueRequests.get(providerId);
  if (inFlight) return inFlight;

  const request = fetch(`${API_BASE}/llm/providers/${encodeURIComponent(providerId)}/models`, {
    headers: authHeaders(),
  }).then(async (response) => {
    if (!response.ok) throw new Error(await readError(response));
    const payload = (await response.json()) as { models?: unknown };
    if (!Array.isArray(payload.models)) throw new Error("Provider returned an invalid model list");
    const catalogue = payload.models
      .filter((entry): entry is { id: string; is_free?: unknown } =>
        !!entry && typeof entry === "object" && typeof (entry as { id?: unknown }).id === "string",
      )
      .map((entry) => ({ id: entry.id.trim(), is_free: entry.is_free === true }))
      .filter((entry) => entry.id.length > 0);
    if (!catalogue.length) throw new Error("Provider returned no models");
    catalogueCache.set(providerId, catalogue);
    return catalogue;
  }).finally(() => {
    catalogueRequests.delete(providerId);
  });
  catalogueRequests.set(providerId, request);
  return request;
}

export function ModelPicker({ providerId, configured, value, onChange, className }: ModelPickerProps) {
  const [freeModelsOnly, setFreeModelsOnly] = useState(false);
  const [hasLoadedCatalogue, setHasLoadedCatalogue] = useState(() => catalogueCache.has(providerId));
  const [providerFailed, setProviderFailed] = useState(false);
  const [models, setModels] = useState<ProviderModel[]>(() => catalogueCache.get(providerId) ?? []);
  const [catalogueProviderId, setCatalogueProviderId] = useState(() => catalogueCache.has(providerId) ? providerId : "");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    let active = true;
    setModels(catalogueCache.get(providerId) ?? []);
    setCatalogueProviderId(catalogueCache.has(providerId) ? providerId : "");
    setError(null);
    setHasLoadedCatalogue(catalogueCache.has(providerId));
    setProviderFailed(false);
    if (!providerId || !configured) {
      setLoading(false);
      return () => { active = false; };
    }
    const cached = catalogueCache.get(providerId);
    if (cached) {
      setModels(cached);
      setCatalogueProviderId(providerId);
      setLoading(false);
      return () => { active = false; };
    }
    setLoading(true);
    setCatalogueProviderId("");
    void fetchCatalogue(providerId)
      .then((catalogue) => {
        if (!active) return;
        setModels(catalogue);
        setCatalogueProviderId(providerId);
        setHasLoadedCatalogue(true);
        setError(null);
      })
      .catch((cause: unknown) => {
        if (!active) return;
        setModels([]);
        setCatalogueProviderId(providerId);
        setHasLoadedCatalogue(false);
        setProviderFailed(true);
        setError(cause instanceof Error ? cause.message : "Could not load provider models");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [providerId, configured, retry]);

  const activeModels = catalogueProviderId === providerId ? models : [];
  const visibleModels = freeModelsOnly ? activeModels.filter((entry) => entry.is_free) : activeModels;

  useEffect(() => {
    if (!providerId) return;
    if (configured && catalogueProviderId !== providerId) {
      if (value) onChangeRef.current("");
      return;
    }
    if (configured && providerFailed && !freeModelsOnly) return;
    if (loading) return;
    if (visibleModels.length === 0) {
      if ((freeModelsOnly || (configured && !error)) && value) onChangeRef.current("");
      return;
    }
    if (!visibleModels.some((entry) => entry.id === value)) {
      onChangeRef.current(visibleModels[0]?.id ?? "");
    }
  }, [providerId, configured, catalogueProviderId, loading, error, freeModelsOnly, visibleModels, value, providerFailed]);

  const manualEntry = !loading && !freeModelsOnly && visibleModels.length === 0 && (!configured || providerFailed || !hasLoadedCatalogue);

  return (
    <div className={`model-choice-control${className ? ` ${className}` : ""}`}>
      <label className="model-choice-filter">
        <input
          type="checkbox"
          checked={freeModelsOnly}
          onChange={(event) => setFreeModelsOnly(event.target.checked)}
          aria-label="Free models only"
        />
        <span>Free models only</span>
      </label>
      {loading && <div className="model-choice-status" role="status">Loading provider models…</div>}
      {error && (
        <div className="model-choice-error" role="status">
          <span>{error}</span>
          <button type="button" className="btn-secondary" onClick={() => setRetry((current) => current + 1)}>Retry</button>
        </div>
      )}
      {visibleModels.length > 0 ? (
        <select
          className="model-picker-select"
          aria-label="Model"
          value={visibleModels.some((entry) => entry.id === value) ? value : ""}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">Choose a model…</option>
          {visibleModels.map((entry) => (
            <option key={entry.id} value={entry.id}>{entry.id}</option>
          ))}
        </select>
      ) : freeModelsOnly ? (
        <div className="model-choice-status" role="status">
          {loading ? "Checking free model availability…" : "No models explicitly marked free by this provider."}
        </div>
      ) : manualEntry ? (
        <label className="model-choice-manual">
          <span>{configured ? "Model ID (catalogue unavailable)" : "Model ID"}</span>
          <input
            className="model-picker-input"
            type="text"
            value={value}
            placeholder="Enter model ID"
            spellCheck={false}
            onChange={(event) => onChange(event.target.value)}
          />
        </label>
      ) : null}
    </div>
  );
}
