import { useNavigate } from "react-router-dom";

import { useAuth } from "../../context/AuthContext";
import { useAuthUI } from "../../context/AuthUIContext";

const FEATURES = [
  {
    icon: "📈",
    title: "Native candle charts",
    copy: "TradingView-style charting rendered in-house from live feeds — no paid embeds, no iframes. Volume, timeframes, and event markers included.",
  },
  {
    icon: "🧭",
    title: "Scanner & watchlists",
    copy: "Filter instruments across providers, pin the symbols you care about, and jump straight from a ticker chip to a live chart.",
  },
  {
    icon: "🧪",
    title: "Backtesting with receipts",
    copy: "Credible, reproducible backtests. Every run keeps its data provenance so you can trust (and audit) the results.",
  },
  {
    icon: "📓",
    title: "Interactive trade journal",
    copy: "A calendar view of your month — green days, red days, and the thesis behind every entry. Close trades with lessons, ratings, and context.",
  },
  {
    icon: "🔮",
    title: "Forecasting & signals",
    copy: "Kronos-powered price forecasts, divergence scorecards, and an inspector that streams RSI, confidence, and provenance for the selected symbol.",
  },
  {
    icon: "🗞️",
    title: "News & economic calendar",
    copy: "Headlines and high-impact events annotated directly on your charts, so context never lives in another tab.",
  },
];

const WORKFLOW = [
  { step: "01", title: "Connect your data", copy: "Bring your own API keys (Finnhub, Alpaca, OpenBB) — encrypted at rest on your own server." },
  { step: "02", title: "Chart & scan", copy: "Watch the ticker strip, open a native candle chart, scan for setups across your watchlists." },
  { step: "03", title: "Backtest the idea", copy: "Run it against history with reproducible receipts before a single real dollar moves." },
  { step: "04", title: "Journal the result", copy: "Log every trade on the calendar, review the thesis, and let the stats compound." },
];

/**
 * Scrollable product promotion page shown before the app (issue #10).
 * Unauthenticated users land here; "Launch app" either enters the app or
 * opens the signup modal.
 */
export function Landing() {
  const { isAuthenticated } = useAuth();
  const { openAuth } = useAuthUI();
  const navigate = useNavigate();

  const launch = () => {
    if (isAuthenticated) navigate("/app/overview");
    else openAuth("signup");
  };

  const scrollTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <div className="landing">
      <header className="landing-nav">
        <div className="landing-brand">
          <span className="app-icon">⚡</span>
          <span className="app-name">Gateway</span>
        </div>
        <nav className="landing-links" aria-label="Landing sections">
          <button onClick={() => scrollTo("features")}>Features</button>
          <button onClick={() => scrollTo("workflow")}>Workflow</button>
          <button onClick={() => scrollTo("faq")}>FAQ</button>
        </nav>
        <div className="landing-nav-actions">
          {isAuthenticated ? (
            <button className="btn-primary" onClick={launch}>
              Open app
            </button>
          ) : (
            <>
              <button className="btn-ghost" onClick={() => openAuth("login")}>
                Sign in
              </button>
              <button className="btn-primary" onClick={launch}>
                Get started
              </button>
            </>
          )}
        </div>
      </header>

      <section className="landing-hero">
        <div className="hero-badge">Self-hosted quant workstation</div>
        <h1>
          Your markets, <span className="hero-gradient">your terminal</span>, zero middlemen.
        </h1>
        <p className="hero-sub">
          Gateway is a local-first trading research platform: native charts from live feeds, a
          disciplined trade journal, credible backtesting, and provider keys that never leave your
          machine. No paid chart embeds. No black boxes.
        </p>
        <div className="hero-ctas">
          <button className="btn-primary btn-lg" onClick={launch}>
            {isAuthenticated ? "Open the app" : "Start free — create account"}
          </button>
          <button className="btn-secondary btn-lg" onClick={() => scrollTo("features")}>
            See what's inside
          </button>
        </div>
        <div className="hero-ticker" aria-hidden="true">
          {["AAPL ▲ 212.44", "NVDA ▲ 131.18", "SPY ▲ 572.30", "TSLA ▼ 246.06", "QQQ ▲ 489.12", "BTC-USD ▲ 68,240"].map(
            (chip) => (
              <span key={chip} className={`hero-chip ${chip.includes("▲") ? "up" : "down"}`}>
                {chip}
              </span>
            ),
          )}
        </div>
      </section>

      <section id="features" className="landing-section">
        <h2>Everything a quant desk needs — under one roof</h2>
        <p className="landing-section-sub">Six modules, one dark theme, no tab-juggling.</p>
        <div className="feature-grid">
          {FEATURES.map((f) => (
            <article key={f.title} className="feature-card">
              <span className="feature-icon" aria-hidden="true">{f.icon}</span>
              <h3>{f.title}</h3>
              <p>{f.copy}</p>
            </article>
          ))}
        </div>
      </section>

      <section id="workflow" className="landing-section landing-section-alt">
        <h2>From idea to journal entry</h2>
        <p className="landing-section-sub">A repeatable loop that keeps you honest.</p>
        <div className="workflow-grid">
          {WORKFLOW.map((w) => (
            <article key={w.step} className="workflow-card">
              <span className="workflow-step">{w.step}</span>
              <h3>{w.title}</h3>
              <p>{w.copy}</p>
            </article>
          ))}
        </div>
      </section>

      <section id="faq" className="landing-section">
        <h2>Questions, answered</h2>
        <div className="faq-list">
          <details className="faq-item">
            <summary>Do I need paid market-data subscriptions?</summary>
            <p>
              No. Charts, quotes, and history fall back to free feeds (yfinance) when you haven't
              configured a paid provider. Add Alpaca or Finnhub keys later for real-time depth.
            </p>
          </details>
          <details className="faq-item">
            <summary>Where do my API keys live?</summary>
            <p>
              On your Gateway server, encrypted with Fernet. They are stored server-side and never
              sent back to the browser after saving.
            </p>
          </details>
          <details className="faq-item">
            <summary>How does paper trading work?</summary>
            <p>
              Every account starts with a $100,000 simulated portfolio. Orders run through the
              server-side risk engine, then fill against real market prices with modeled spread
              and commission — streamed live to the paper desk.
            </p>
          </details>
          <details className="faq-item">
            <summary>Can I collapse the interface for more chart room?</summary>
            <p>
              Yes — drag either sidebar's edge toward the screen edge and it snaps into a compact
              icon rail; drag back out to restore it. ⌘K opens the command palette anywhere.
            </p>
          </details>
        </div>
      </section>

      <section className="landing-cta">
        <h2>Ready to see your month at a glance?</h2>
        <p>Create an account, connect a provider, and open your first chart in under a minute.</p>
        <button className="btn-primary btn-lg" onClick={launch}>
          {isAuthenticated ? "Open Gateway" : "Get started free"}
        </button>
      </section>

      <footer className="landing-footer">
        <span>⚡ Gateway — self-hosted quant workstation</span>
        <span className="landing-footer-muted">Charts render natively from live feeds. Your keys stay yours.</span>
      </footer>
    </div>
  );
}
