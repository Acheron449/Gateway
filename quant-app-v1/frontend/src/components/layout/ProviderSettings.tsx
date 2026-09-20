import { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../../lib/constants";

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
  provider: {
    name: string;
    meta: {
      name: string;
      version: string;
      endpoint: string;
      requires_api_key: boolean;
      rate_limit_per_min: number | null;
    };
    configured: boolean;
    has_stored_key: boolean;
  };
  selectedProvider: string | null;
  onSelect: (name: string) => void;
  inputApiKey: string;
  showKey: boolean;
  setInputApiKey: (value: string) => void;
  setShowKey: (value: boolean) => void;
  loading: boolean;
  testResult: { success: boolean; message: string; configured: boolean; news_count?: number; calendar_count?: number } | null;
  onSaveKey: () => Promise<void>;
  onTestKey: () => Promise<void>;
  onDeleteKey: () => Promise<void>;
  providers: Array<{ name: string; has_stored_key: boolean }>;
  selectedProvider: string | null;
  inputApiKey: string;
  showKey: boolean;
  setInputApiKey: (value: string) => void;
  setShowKey: (value: boolean) => void;
  onSaveKey: () => Promise<void>;
  onTestKey: () => Promise<void>;
  onDeleteKey: () => Promise<void>;
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
  testResult,
  onSaveKey,
  onTestKey,
  onDeleteKey,
}: ProviderCardProps) {
  const selected = selectedProvider === provider.name;
  const hasStoredKey = provider.has_stored_key;

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
                  onChange={e => setInputApiKey(e.target.value)}
                  placeholder="Enter API key"
                  className="api-key-input"
                />
              </label>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={showKey}
                  onChange={e => setShowKey(e.target.checked)}
                />
                Show Key
              </label>
            </div>
            <div className="action-buttons">
              <button
                className="btn-primary"
                onClick={onSaveKey}
                disabled={loading || !inputApiKey.trim()}
              >
                {loading ? "Saving..." : "Save Key"}
              </button>
              <button
                className="btn-secondary"
                onClick={onTestKey}
                disabled={loading}
              >
                Test Key
              </button>
              <button
                className="btn-danger"
                onClick={onDeleteKey}
                disabled={loading}
              >
                Delete Key
              </button>
            </div>
            {testResult && (
              <div className={`test-result ${testResult.success ? "success" : "error"}`}>
                <span>{testResult.message}</span>
                {testResult.news_count !== undefined && (
                  <span className="test-details">
                    News: {testResult.news_count}, Calendar: {testResult.calendar_count}
                  </span>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="no-key-info">
            <p>This provider does not require an API key or is not yet implemented.</p>
            <p className="hint">TradingView requires a paid subscription. No BYOK available.</p>
          </div>
        )}
      </div>
    );
  };

  const selected = selectedProvider === provider.name;
  const hasStoredKey = provider.has_stored_key;

  return (
    <div key={provider.name} className={`provider-card ${selected ? "selected" : ""}`}>
      <div className="provider-header" onClick={() => onSelect(provider.name)}>
        <div className="provider-info">
          <h3>{provider.name}</h3>
          <span className="provider-version">{provider.meta.version}</span>
        </div>
        <div className="provider-status">
          <span className={`status-badge ${provider.configured ? "configured" : "not-configured"}`}>
            {provider.configured ? "Configured" : "Not Configured"}
          </span>
          {provider.has_stored_key && (
            <span className="stored-badge">Key Stored</span>
          )}
        </div>
      </div>

      {selectedProvider === provider.name && renderDetails()}
    </div>
  );
}

export function ProviderSettings() {
  const [providers, setProviders] = useState<Array<{
    name: string;
    meta: ProviderMeta;
    configured: boolean;
    has_stored_key: boolean;
  }>>([]);
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null);
  const [inputApiKey, setInputApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string; configured: boolean; news_count?: number; calendar_count?: number } | null>(null);
  const [generatingKey, setGeneratingKey] = useState(false);
  const [newFernetKey, setNewFernetKey] = useState<string | null>(null);

  const fetchProviders = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/settings/providers`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setProviders(data);
    } catch (err) {
      console.error("Failed to load providers:", err);
    }
  }, []);

  useEffect(() => {
    fetchProviders();
  }, [fetchProviders]);

  const handleSelectProvider = (name: string) => {
    setSelectedProvider(name);
    setInputApiKey("");
    setTestResult(null);
  };

  const handleSaveKey = async () => {
    if (!selectedProvider || !inputApiKey.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/settings/providers/${selectedProvider}/key`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: inputApiKey.trim() }),
      });
      if (!res.ok) throw new Error(await res.text());
      fetchProviders();
      setInputApiKey("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save key");
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteKey = async () => {
    if (!selectedProvider) return;
    if (!confirm(`Delete stored API key for ${selectedProvider}?`)) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/settings/providers/${selectedProvider}/key`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error(await res.text());
      fetchProviders();
      setSelectedProvider(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete key");
    } finally {
      setLoading(false);
    }
  };

  const handleTestKey = async () => {
    if (!selectedProvider) return;
    setLoading(true);
    setTestResult(null);
    try {
      const res = await fetch(`${API_BASE}/settings/providers/${selectedProvider}/test`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setTestResult(data);
    } catch (err) {
      setTestResult({
        success: false,
        message: err instanceof Error ? err.message : "Test failed",
        configured: false,
      });
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateFernetKey = async () => {
    setGeneratingKey(true);
    try {
      const res = await fetch(`${API_BASE}/settings/providers/generate-fernet-key`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setNewFernetKey(data.fernet_key);
    } catch (err) {
      console.error("Failed to generate key:", err);
    } finally {
      setGeneratingKey(false);
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    alert("Copied to clipboard!");
  };

  if (loading && providers.length === 0) {
    return <div className="settings-loading">Loading provider settings...</div>;
  }

  if (error) {
    return <div className="settings-error">Error: {error} <button onClick={fetchProviders}>Retry</button></div>;
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

      {newFernetKey && (
        <div className="fernet-key-banner">
          <h3>New Fernet Key Generated</h3>
          <p className="fernet-key">
            <code>{newFernetKey}</code>
            <button onClick={() => copyToClipboard(newFernetKey!)} className="btn-secondary btn-sm">
              Copy
            </button>
          </p>
          <p className="warning">
            <strong>Important:</strong> Store this key in the <code>GATEWAY_PROVIDER_KEY</code> environment variable.
            Rotate rarely - changing it will make all stored API keys undecryptable.
          </p>
          <button className="btn-secondary" onClick={() => setNewFernetKey(null)}>Dismiss</button>
        </div>
      )}

      <div className="providers-list">
        {providers.map(provider => (
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
            testResult={testResult}
            onSaveKey={handleSaveKey}
            onTestKey={handleTestKey}
            onDeleteKey={handleDeleteKey}
            providers={providers}
            selectedProvider={selectedProvider}
            inputApiKey={inputApiKey}
            showKey={showKey}
            setInputApiKey={setInputApiKey}
            setShowKey={setShowKey}
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
          The encryption key is stored in the <code>GATEWAY_PROVIDER_KEY</code> environment variable.
        </p>
        <button className="btn-secondary" onClick={handleGenerateFernetKey} disabled={generatingKey}>
          {generatingKey ? "Generating..." : "Generate New Fernet Key"}
        </button>
        {newFernetKey && (
          <div className="fernet-key-display">
            <code>{newFernetKey}</code>
            <button className="btn-secondary btn-sm" onClick={() => copyToClipboard(newFernetKey!)}>Copy</button>
          </div>
        )}
      </div>
    </div>
  );
}