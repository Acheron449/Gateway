import { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../../lib/constants";
import { useAuth } from "../../context/AuthContext";

interface ProviderMeta {
  name: string;
  version: string;
  endpoint: string;
  requires_api_key: boolean;
  rate_limit_per_min: number | null;
}

interface ProviderStatus {
  name: string;
  meta: ProviderMeta;
  configured: boolean;
  has_stored_key: boolean;
}

interface TestResult {
  success: boolean;
  message: string;
  configured: boolean;
  news_count?: number;
  calendar_count?: number;
}

interface ProviderCardProps {
  provider: ProviderStatus;
  selectedProvider: string | null;
  onSelect: (name: string) => void;
  inputApiKey: string;
  showKey: boolean;
  setInputApiKey: (value: string) => void;
  setShowKey: (value: boolean) => void;
  loading: boolean;
  canManage: boolean;
  testResult: TestResult | null;
  onSaveKey: () => Promise<void>;
  onTestKey: () => Promise<void>;
  onDeleteKey: () => Promise<void>;
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("gateway_auth_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isProviderStatus(value: unknown): value is ProviderStatus {
  if (!isRecord(value) || !isRecord(value.meta)) return false;

  return (
    typeof value.name === "string" &&
    typeof value.meta.name === "string" &&
    typeof value.meta.version === "string" &&
    typeof value.meta.endpoint === "string" &&
    typeof value.meta.requires_api_key === "boolean" &&
    (typeof value.meta.rate_limit_per_min === "number" || value.meta.rate_limit_per_min === null) &&
    typeof value.configured === "boolean" &&
    typeof value.has_stored_key === "boolean"
  );
}

function toErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

async function readResponseError(response: Response): Promise<string> {
  const text = await response.text().catch(() => "");
  if (!text) return `${response.status} ${response.statusText}`.trim();

  try {
    const payload: unknown = JSON.parse(text);
    if (isRecord(payload) && typeof payload.detail === "string" && payload.detail) {
      return payload.detail;
    }
    if (typeof payload === "string" && payload) {
      return payload;
    }
  } catch {
    return text;
  }

  return text;
}

function normalizeTestResult(value: unknown): TestResult {
  if (!isRecord(value)) {
    throw new Error("Invalid provider test response");
  }

  const success = value.success === true;
  const result: TestResult = {
    success,
    message:
      typeof value.message === "string" && value.message
        ? value.message
        : success
          ? "Provider test completed"
          : "Provider test failed",
    configured: value.configured === true,
  };

  if (typeof value.news_count === "number" && Number.isFinite(value.news_count)) {
    result.news_count = value.news_count;
  }
  if (typeof value.calendar_count === "number" && Number.isFinite(value.calendar_count)) {
    result.calendar_count = value.calendar_count;
  }

  return result;
}

function ProviderCard({
  provider,
  selectedProvider,
  onSelect,
  inputApiKey,
  showKey,
  setInputApiKey,
  setShowKey,
  loading,
  canManage,
  testResult,
  onSaveKey,
  onTestKey,
  onDeleteKey,
}: ProviderCardProps) {
  const selected = selectedProvider === provider.name;

  const renderDetails = () => (
    <div className="provider-details">
      <div className="provider-meta">
        <div className="meta-item">
          <span className="meta-label">Endpoint</span>
          <span className="meta-value">{provider.meta.endpoint}</span>
        </div>
        <div className="meta-item">
          <span className="meta-label">Rate Limit</span>
          <span className="meta-value">{provider.meta.rate_limit_per_min ? `${provider.meta.rate_limit_per_min} req/min` : "N/A"}</span>
        </div>
        <div className="meta-item">
          <span className="meta-label">Requires API Key</span>
          <span className="meta-value">{provider.meta.requires_api_key ? "Yes" : "No"}</span>
        </div>
      </div>

      <div className="provider-actions">
        {provider.meta.requires_api_key ? (
          <div className="key-management">
            <div className="key-input-group">
              <label>
                API Key {showKey ? "(visible)" : "(hidden)"}
                <input
                  type={showKey ? "text" : "password"}
                  value={inputApiKey}
                  onChange={(event) => setInputApiKey(event.target.value)}
                  disabled={!canManage}
                  placeholder="Enter API key"
                  className="api-key-input"
                />
              </label>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={showKey}
                  onChange={(event) => setShowKey(event.target.checked)}
                  disabled={!canManage}
                />
                Show Key
              </label>
            </div>
            <div className="action-buttons">
              <button
                className="btn-primary"
                onClick={onSaveKey}
                disabled={loading || !canManage || !inputApiKey.trim()}
              >
                {loading ? "Saving..." : "Save Key"}
              </button>
              <button
                className="btn-secondary"
                onClick={onTestKey}
                disabled={loading || !canManage || !provider.has_stored_key}
                title={provider.has_stored_key ? "Test the stored API key" : "Save an API key before testing"}
              >
                Test Stored Key
              </button>
              <button
                className="btn-danger"
                onClick={onDeleteKey}
                disabled={loading || !canManage || !provider.has_stored_key}
              >
                Delete Key
              </button>
            </div>
            {testResult && (
              <div className={`test-result ${testResult.success ? "success" : "error"}`}>
                <span>{testResult.message}</span>
                {(testResult.news_count !== undefined || testResult.calendar_count !== undefined) && (
                  <span className="test-details">
                    News: {testResult.news_count ?? "N/A"}, Calendar: {testResult.calendar_count ?? "N/A"}
                  </span>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="no-key-info">
            <p>This provider does not support browser-managed API keys.</p>
            <p className="hint">TradingView requires a paid subscription. No BYOK available.</p>
          </div>
        )}
      </div>
    </div>
  );

  return (
    <div className={`provider-card ${selected ? "selected" : ""}`}>
      <div className="provider-header" onClick={() => onSelect(provider.name)}>
        <div className="provider-info">
          <h3>{provider.name}</h3>
          <span className="provider-version">{provider.meta.version}</span>
        </div>
        <div className="provider-status">
          <span className={`status-badge ${provider.configured ? "configured" : "not-configured"}`}>
            {provider.configured ? "Configured" : "Not Configured"}
          </span>
          {provider.has_stored_key && <span className="stored-badge">Key Stored</span>}
        </div>
      </div>

      {selected && renderDetails()}
    </div>
  );
}

export function ProviderSettings() {
  const { isAuthenticated } = useAuth();
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null);
  const [inputApiKey, setInputApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [loadingProviders, setLoadingProviders] = useState(true);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  const fetchProviders = useCallback(async () => {
    setLoadingProviders(true);
    setLoadError(null);

    try {
      const response = await fetch(`${API_BASE}/settings/providers`);
      if (!response.ok) {
        throw new Error(await readResponseError(response));
      }

      const data: unknown = await response.json();
      if (!Array.isArray(data)) {
        throw new Error("Invalid provider settings response");
      }

      const statuses = data.filter(isProviderStatus);
      setProviders(statuses);
      setSelectedProvider((current) =>
        current && statuses.some((provider) => provider.name === current) ? current : null,
      );
    } catch (error) {
      const message = toErrorMessage(error, "Failed to load provider settings");
      setLoadError(message);
      setProviders([]);
    } finally {
      setLoadingProviders(false);
    }
  }, []);

  const refreshProviderStatus = useCallback(async (name: string) => {
    try {
      const response = await fetch(`${API_BASE}/settings/providers/${encodeURIComponent(name)}`);
      if (!response.ok) {
        throw new Error(await readResponseError(response));
      }

      const data: unknown = await response.json();
      if (!isProviderStatus(data)) {
        throw new Error("Invalid provider status response");
      }

      setProviders((current) => {
        if (current.some((provider) => provider.name === data.name)) {
          return current.map((provider) => (provider.name === data.name ? data : provider));
        }
        return [data, ...current];
      });
    } catch (error) {
      setActionError(toErrorMessage(error, "Failed to refresh provider status"));
    }
  }, []);

  useEffect(() => {
    void fetchProviders();
  }, [fetchProviders]);

  const handleSelectProvider = useCallback(
    (name: string) => {
      setSelectedProvider(name);
      setInputApiKey("");
      setShowKey(false);
      setTestResult(null);
      setActionError(null);
      void refreshProviderStatus(name);
    },
    [refreshProviderStatus],
  );

  const handleSaveKey = useCallback(async () => {
    const name = selectedProvider;
    const apiKey = inputApiKey.trim();
    if (!name || !apiKey || loading) return;

    setLoading(true);
    setActionError(null);
    try {
      const response = await fetch(`${API_BASE}/settings/providers/${encodeURIComponent(name)}/key`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ api_key: apiKey }),
      });
      if (!response.ok) {
        throw new Error(await readResponseError(response));
      }

      const data: unknown = await response.json();
      if (!isRecord(data) || data.stored !== true) {
        throw new Error("Provider key was not stored");
      }

      setInputApiKey("");
      setShowKey(false);
      setTestResult(null);
      await fetchProviders();
    } catch (error) {
      setActionError(toErrorMessage(error, "Failed to save API key"));
    } finally {
      setLoading(false);
    }
  }, [selectedProvider, inputApiKey, loading, fetchProviders]);

  const handleTestKey = useCallback(async () => {
    const name = selectedProvider;
    if (!name || loading) return;

    setLoading(true);
    setActionError(null);
    setTestResult(null);

    try {
      const response = await fetch(`${API_BASE}/settings/providers/${encodeURIComponent(name)}/test`, {
        headers: authHeaders(),
      });
      if (!response.ok) {
        throw new Error(await readResponseError(response));
      }

      const data: unknown = await response.json();
      setTestResult(normalizeTestResult(data));
      await refreshProviderStatus(name);
    } catch (error) {
      setTestResult({
        success: false,
        message: toErrorMessage(error, "Provider test failed"),
        configured: false,
      });
    } finally {
      setLoading(false);
    }
  }, [selectedProvider, loading, refreshProviderStatus]);

  const handleDeleteKey = useCallback(async () => {
    const name = selectedProvider;
    if (!name || loading) return;
    if (!window.confirm(`Delete stored API key for ${name}?`)) return;

    setLoading(true);
    setActionError(null);
    try {
      const response = await fetch(`${API_BASE}/settings/providers/${encodeURIComponent(name)}/key`, {
        method: "DELETE",
        headers: authHeaders(),
      });
      if (!response.ok) {
        throw new Error(await readResponseError(response));
      }

      setSelectedProvider(null);
      setInputApiKey("");
      setShowKey(false);
      setTestResult(null);
      await fetchProviders();
    } catch (error) {
      setActionError(toErrorMessage(error, "Failed to delete API key"));
    } finally {
      setLoading(false);
    }
  }, [selectedProvider, loading, fetchProviders]);

  if (loadingProviders && providers.length === 0) {
    return <div className="settings-loading">Loading provider settings...</div>;
  }

  return (
    <div className="provider-settings">
      <div className="settings-header">
        <h1>Data Provider Settings</h1>
        <p className="settings-description">
          Configure your data providers. Finnhub provides news and economic calendar data.
          <br />API keys are encrypted at rest using Fernet encryption.
        </p>
      </div>

      {!isAuthenticated && (
        <div className="settings-error" role="alert">
          <span>Sign in to save, test, or delete provider API keys.</span>
        </div>
      )}
      {loadError && (
        <div className="settings-error" role="alert">
          <span>Failed to load providers: {loadError}</span>
          <button className="btn-secondary" onClick={() => void fetchProviders()}>Retry</button>
        </div>
      )}
      {actionError && (
        <div className="settings-error" role="alert">
          <span>{actionError}</span>
          <button className="btn-secondary" onClick={() => setActionError(null)}>Dismiss</button>
        </div>
      )}

      <div className="providers-list">
        {providers.map((provider) => (
          <ProviderCard
            key={provider.name}
            provider={provider}
            selectedProvider={selectedProvider}
            onSelect={handleSelectProvider}
            inputApiKey={inputApiKey}
            showKey={showKey}
            setInputApiKey={setInputApiKey}
            setShowKey={setShowKey}
            loading={loading}
            canManage={isAuthenticated}
            testResult={testResult}
            onSaveKey={handleSaveKey}
            onTestKey={handleTestKey}
            onDeleteKey={handleDeleteKey}
          />
        ))}
      </div>

      <div className="settings-section">
        <h2>Encryption Key Management</h2>
        <p className="settings-description">
          API keys are encrypted at rest using Fernet symmetric encryption.
          The encryption key is managed by the Gateway server in the{" "}
          <code>GATEWAY_PROVIDER_KEY</code> environment variable or its configured key file.
          Generated encryption keys are never sent to the browser.
        </p>
      </div>
    </div>
  );
}
