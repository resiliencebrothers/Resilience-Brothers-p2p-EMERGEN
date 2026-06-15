import { useEffect, useState } from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, useLocation, useNavigate, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import axios from "axios";
import Landing from "@/pages/Landing";
import Dashboard from "@/pages/Dashboard";
import AdminPanel from "@/pages/AdminPanel";
import AuthCallback from "@/pages/AuthCallback";
import InstallPrompt from "@/components/InstallPrompt";
import { AuthProvider, useAuth } from "@/context/AuthContext";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;
axios.defaults.withCredentials = true;

function AppRouter() {
  const location = useLocation();
  // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
  if (location.hash?.includes("session_id=")) {
    return <AuthCallback />;
  }
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/dashboard/*" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
      <Route path="/admin/*" element={<ProtectedRoute staffOnly><AdminPanel /></ProtectedRoute>} />
    </Routes>
  );
}

function ProtectedRoute({ children, staffOnly = false }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#0A0A0A]">
        <div className="text-neutral-400 micro-label">Cargando...</div>
      </div>
    );
  }
  if (!user) return <Navigate to="/" replace />;
  if (staffOnly && !["admin", "employee"].includes(user.role)) return <Navigate to="/dashboard" replace />;
  return children;
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Toaster theme="dark" position="top-right" toastOptions={{ style: { background: "#141414", border: "1px solid rgba(255,255,255,0.1)", color: "#fff" } }} />
        <AppRouter />
        <InstallPrompt />
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
