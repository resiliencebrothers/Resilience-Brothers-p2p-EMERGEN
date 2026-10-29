import { useEffect, useState } from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, useLocation, useNavigate, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import { toast } from "sonner";
import axios from "axios";
import Landing from "@/pages/Landing";
import VerifyEmail from "@/pages/VerifyEmail";
import ResetPassword from "@/pages/ResetPassword";
import CompanyRequestStatus from "@/pages/CompanyRequestStatus";
import CompanyResubmit from "@/pages/CompanyResubmit";
import PrivacyPolicy from "@/pages/PrivacyPolicy";
import TermsOfService from "@/pages/TermsOfService";
import Dashboard from "@/pages/Dashboard";
import CompanyPanel from "@/pages/CompanyPanel";
import { DefensiveBanner } from "@/components/DefensiveModePanel";
import AdminPanel from "@/pages/AdminPanel";
import AuthCallback from "@/pages/AuthCallback";
import InstallPrompt from "@/components/InstallPrompt";
import { AuthProvider, useAuth, AUTH_STATUS } from "@/context/AuthContext";
import { applyTheme, getTheme } from "@/lib/theme";
import { roleHome } from "@/lib/roleHome";
import { currentPanelBase } from "@/lib/profilePaths";

// iter241 — aplica el tema guardado antes del primer render.
applyTheme(getTheme());
import { LiveStreamProvider } from "@/hooks/useLiveStream";
import LiveToaster from "@/components/LiveToaster";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;
axios.defaults.withCredentials = true;

// iter117 — Global safety net: any staff mutation blocked because the actor
// hasn't enabled 2FA returns 412 TOTP_SETUP_REQUIRED. Surface a single toast
// with a shortcut to the security page so the flow is obvious app-wide. Local
// component handlers still run (we re-reject the promise).
axios.interceptors.response.use(
  (response) => response,
  (error) => {
    const detail = error?.response?.data?.detail;
    if (error?.response?.status === 412 && detail?.code === "TOTP_SETUP_REQUIRED") {
      toast.error(detail.message || "Activa la verificación en dos pasos (2FA) para continuar.", {
        id: "totp-setup-required",
        action: {
          label: "Activar 2FA",
          onClick: () => { window.location.href = `${currentPanelBase()}/security`; },
        },
      });
    }
    return Promise.reject(error);
  }
);

function AppRouter() {
  const location = useLocation();
  // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
  if (location.hash?.includes("session_id=")) {
    return <AuthCallback />;
  }
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/privacy" element={<PrivacyPolicy />} />
      <Route path="/terms" element={<TermsOfService />} />
      <Route path="/auth/verify-email/:token" element={<VerifyEmail />} />
      <Route path="/auth/reset-password/:token" element={<ResetPassword />} />
      <Route path="/empresa/seguimiento" element={<CompanyRequestStatus />} />
      <Route path="/empresa/seguimiento/:token" element={<CompanyRequestStatus />} />
      <Route path="/empresa/reenviar/:token" element={<CompanyResubmit />} />
      <Route path="/dashboard/*" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
      <Route path="/company/*" element={<ProtectedRoute companyRoute><CompanyPanel /></ProtectedRoute>} />
      <Route path="/admin/*" element={<ProtectedRoute staffOnly><AdminPanel /></ProtectedRoute>} />
    </Routes>
  );
}

function ProtectedRoute({ children, staffOnly = false, companyRoute = false }) {
  const { user, status, loading, retry } = useAuth();
  const [retrying, setRetrying] = useState(false);
  if (loading || status === AUTH_STATUS.CHECKING) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#14101F]">
        <div className="text-neutral-400 micro-label">Cargando...</div>
      </div>
    );
  }
  // AUTH-02 — a transient network/5xx error while checking the session must NOT
  // be treated as "logged out". Offer a recoverable retry instead of bouncing
  // the user to the login screen (which falsely implies their session ended).
  if (status === AUTH_STATUS.ERROR && !user) {
    const onRetry = async () => {
      if (retrying) return;
      setRetrying(true);
      try { await retry?.(); } finally { setRetrying(false); }
    };
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#14101F] px-6" data-testid="auth-check-error">
        <div className="text-center max-w-sm">
          <p className="text-white font-display text-xl mb-2">No se pudo verificar tu sesión</p>
          <p className="text-neutral-400 text-sm mb-6">
            Hubo un problema de conexión al comprobar tu sesión. No hemos cerrado tu sesión.
          </p>
          <button
            type="button"
            data-testid="auth-check-retry-btn"
            onClick={onRetry}
            disabled={retrying}
            className="px-6 py-3 bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none transition-colors disabled:opacity-50"
          >
            {retrying ? "Reintentando..." : "Reintentar"}
          </button>
        </div>
      </div>
    );
  }
  if (!user) return <Navigate to="/" replace />;
  if (staffOnly && !["admin", "employee"].includes(user.role)) return <Navigate to={roleHome(user)} replace />;
  // El panel Empresa es exclusivo del rol business; los demás van a su home.
  if (companyRoute && user.role !== "empresa") return <Navigate to={roleHome(user)} replace />;
  // Las cuentas Empresa no usan el dashboard de cliente: redirige a su panel.
  if (!companyRoute && !staffOnly && user.role === "empresa") return <Navigate to="/company" replace />;
  return children;
}

const TOAST_OPTIONS = {
  style: {
    background: "#1A1730",
    border: "1px solid rgba(255,255,255,0.1)",
    color: "#fff",
  },
};

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <LiveStreamProvider>
          <LiveToaster />
          <Toaster theme="dark" position="top-right" toastOptions={TOAST_OPTIONS} />
          <DefensiveBanner />
          <AppRouter />
          <InstallPrompt />
        </LiveStreamProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
