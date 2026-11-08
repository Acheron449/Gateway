import { lazy, Suspense, useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";

import { AuthModal } from "./components/auth/AuthModal";
import { AuthUIProvider, useAuthUI } from "./context/AuthUIContext";
import { AuthProvider, useAuth } from "./context/AuthContext";
import "./styles/app.css";
import "./styles/extensions.css";

const Landing = lazy(() =>
  import("./components/layout/Landing").then((module) => ({ default: module.Landing })),
);
const AppShellRoute = lazy(() => import("./components/layout/AppShell"));

function RouteLoading() {
  return (
    <div className="route-loading" role="status" aria-live="polite">
      <span>Loading Gateway…</span>
    </div>
  );
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

function AppRoutes() {
  return (
    <Suspense fallback={<RouteLoading />}>
      <Routes>
        <Route path="/" element={<LandingRedirect />} />
        <Route path="/login" element={<AuthRoute mode="login" />} />
        <Route path="/register" element={<AuthRoute mode="signup" />} />
        <Route path="/app" element={<Navigate to="/app/overview" replace />} />
        <Route path="/app/:viewParam" element={<AppShellRoute />} />
        <Route path="/app/:viewParam/*" element={<AppShellRoute />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}

function GatewayApp() {
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

export default function App() {
  return <GatewayApp />;
}
