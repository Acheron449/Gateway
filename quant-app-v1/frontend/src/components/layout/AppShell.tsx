import { useCallback, useEffect, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";

import { CenterCanvas } from "./CenterCanvas";
import { CommandPalette } from "./CommandPalette";
import { LeftSidebar } from "./LeftSidebar";
import { LegalNotice, NoticeAcceptanceGate } from "./LegalNotice";
import { ResizeHandle } from "./ResizeHandle";
import { RightInspector } from "./RightInspector";
import { TopBar } from "./TopBar";
import { isView } from "../../lib/views";

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

function useNarrowLayout(): boolean {
  const [narrow, setNarrow] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(max-width: 1024px)").matches,
  );
  useEffect(() => {
    const query = window.matchMedia("(max-width: 1024px)");
    const onChange = () => setNarrow(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);
  return narrow;
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

function AppShell({ viewParam }: { viewParam?: string }) {
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [selectedSymbol, setSelectedSymbol] = useState("AAPL");
  const [leftWidth, setLeftWidth] = useState(() =>
    readWidth("gateway_ui_left_width", LEFT_DEFAULT, LEFT_COLLAPSED, 420),
  );
  const [rightWidth, setRightWidth] = useState(() =>
    readWidth("gateway_ui_right_width", RIGHT_DEFAULT, RIGHT_COLLAPSED, 480),
  );
  const narrowLayout = useNarrowLayout();

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
          <LeftSidebar activeView={activeView} collapsed={narrowLayout || leftWidth <= LEFT_COLLAPSED} />
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

        {/* On paper-trading the inspector is embedded in the desk ticket as
            its "Overview" tab, so the standalone shell is suppressed there. */}
        {activeView !== "paper-trading" && (
          <div className="side-panel right-panel-shell" style={{ width: rightWidth }}>
            <RightInspector activeView={activeView} selectedSymbol={selectedSymbol} collapsed={narrowLayout || rightWidth <= RIGHT_COLLAPSED} />
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
        )}

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
      <LegalNotice />
      <NoticeAcceptanceGate />
    </div>
  );
}

/** Route wrapper: validates /app/:view and lazily resolves the dashboard shell. */
export default function AppShellRoute() {
  const { viewParam } = useParams<{ viewParam?: string }>();
  if (viewParam && !isView(viewParam)) {
    return <Navigate to="/app/overview" replace />;
  }
  return <AppShell viewParam={viewParam} />;
}
