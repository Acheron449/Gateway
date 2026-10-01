import { BrowserRouter, Navigate, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { useEffect, useState, useCallback } from "react";

import { LeftSidebar } from "./components/layout/LeftSidebar";
import { CenterCanvas } from "./components/layout/CenterCanvas";
import { RightInspector } from "./components/layout/RightInspector";
import { TopBar } from "./components/layout/TopBar";
import { CommandPalette } from "./components/layout/CommandPalette";
import { Landing } from "./components/layout/Landing";
import { ResizeHandle } from "./components/layout/ResizeHandle";
import { AuthModal } from "./components/auth/AuthModal";
import { AuthUIProvider, useAuthUI } from "./context/AuthUIContext";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { isView } from "./lib/views";
import "./styles/app.css";
import "./styles/extensions.css";

const LEFT_COLLAPSED = 52;
const LEFT_MIN = 180;
const LEFT_DEFAULT = 240;
const RIGHT_COLLAPSED = 52;
const RIGHT_MIN = 260;
const RIGHT_DEFAULT = 320;

function readWidth(key: string, fallback: number, min: number, max: number): number {
  try {
    const raw = localStorage.getItem(key);
    const parsed = raw ? Number.parseInt(raw, 10) : NaN;
    if (Number.isFinite(parsed)) return Math.min(max, Math.max(min, parsed));
  } catch {
    /* ignore */
  }
  return fallback;
}

function LandingRedirect() {
  const { isAuthenticated } = useAuth();
  if (isAuthenticated) return <Navigate to="/app/overview" replace />;
  return <Landing />;
}

/** Deep links /login and /register open the auth modal over the landing page. */
function AuthRoute({ mode }: { mode: "login" | "signup" }) {
  const { openAuth } = useAuthUI();
  const navigate = useNavigate();

  useEffect(() => {
    openAuth(mode);
    navigate("/", { replace: true });
  }, [mode, openAuth, navigate]);

  return null;
}

function AppShell() {
  const { viewParam } = useParams<{ viewParam?: string }>();
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [selectedSymbol, setSelectedSymbol] = useState("AAPL");
  const [leftWidth, setLeftWidth] = useState(() =>
    readWidth("gateway_ui_left_width", LEFT_DEFAULT, LEFT_COLLAPSED, 420),
  );
  const [rightWidth, setRightWidth] = useState(() =>
    readWidth("gateway_ui_right_width", RIGHT_DEFAULT, RIGHT_COLLAPSED, 480),
  );

  const activeView = isView(viewParam) ? viewParam : "overview";

  // ⌘K / Ctrl+K opens the command palette from anywhere (issue #4).
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCommandPaletteOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const { navigateTo } = useNavigator();

  const handleNavigate = useCallback(
    (view: string) => {
      setCommandPaletteOpen(false);
      navigateTo(view);
    },
    [navigateTo],
  );

  return (
    <div className={`app-shell view-accent-${activeView}`}>
      <TopBar
        activeView={activeView}
        selectedSymbol={selectedSymbol}
        onSymbolSelect={setSelectedSymbol}
        onOpenSearch={() => setCommandPaletteOpen(true)}
      />
      <div className="app-body">
        <div className="side-panel left-panel-shell" style={{ width: leftWidth }}>
          <LeftSidebar activeView={activeView} collapsed={leftWidth <= LEFT_COLLAPSED} />
          <ResizeHandle
            side="left"
            width={leftWidth}
            minWidth={LEFT_MIN}
            collapseBelow={160}
            collapsedWidth={LEFT_COLLAPSED}
            maxWidth={420}
            onChange={setLeftWidth}
            storageKey="gateway_ui_left_width"
            ariaLabel="Resize workspace sidebar"
          />
        </div>

        <CenterCanvas activeView={activeView} selectedSymbol={selectedSymbol} />

        <div className="side-panel right-panel-shell" style={{ width: rightWidth }}>
          <RightInspector activeView={activeView} selectedSymbol={selectedSymbol} collapsed={rightWidth <= RIGHT_COLLAPSED} />
          <ResizeHandle
            side="right"
            width={rightWidth}
            minWidth={RIGHT_MIN}
            collapseBelow={220}
            collapsedWidth={RIGHT_COLLAPSED}
            maxWidth={480}
            onChange={setRightWidth}
            storageKey="gateway_ui_right_width"
            ariaLabel="Resize inspector"
          />
        </div>

        {commandPaletteOpen && (
          <CommandPalette
            onClose={() => setCommandPaletteOpen(false)}
            onNavigate={handleNavigate}
            onSymbolSelect={(symbol) => {
              setSelectedSymbol(symbol);
              setCommandPaletteOpen(false);
            }}
            activeView={activeView}
            selectedSymbol={selectedSymbol}
          />
        )}
      </div>
    </div>
  );
}

/** Tiny helper so AppShell can navigate without prop drilling. */
function useNavigator() {
  const navigate = useNavigate();
  const navigateTo = useCallback(
    (view: string) => {
      navigate(`/app/${view}`);
    },
    [navigate],
  );
  return { navigateTo };
}

/** Validates /app/:view and renders the shell. */
function ShellRoute() {
  const { viewParam } = useParams<{ viewParam?: string }>();
  if (viewParam && !isView(viewParam)) {
    return <Navigate to="/app/overview" replace />;
  }
  return <AppShell />;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<LandingRedirect />} />
      <Route path="/login" element={<AuthRoute mode="login" />} />
      <Route path="/register" element={<AuthRoute mode="signup" />} />
      <Route path="/app" element={<Navigate to="/app/overview" replace />} />
      <Route path="/app/:viewParam" element={<ShellRoute />} />
      <Route path="/app/:viewParam/*" element={<ShellRoute />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AuthUIProvider>
          <AppRoutes />
          <AuthModal />
        </AuthUIProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
