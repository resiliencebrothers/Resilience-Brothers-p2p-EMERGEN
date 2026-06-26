import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import { ShieldCheck, AlertTriangle, Loader2 } from "lucide-react";

export default function VerifyEmail() {
  const { token } = useParams();
  const navigate = useNavigate();
  const [state, setState] = useState("loading"); // loading | ok | err
  const [msg, setMsg] = useState("");
  const didRun = useRef(false);

  useEffect(() => {
    if (didRun.current) return;
    didRun.current = true;
    axios.get(`${API}/auth/verify-email/${token}`, { withCredentials: true })
      .then((r) => {
        setState("ok");
        const email = encodeURIComponent(r.data?.email || "");
        setTimeout(() => navigate(`/?verified=1&email=${email}`, { replace: true }), 1800);
      })
      .catch((e) => { setState("err"); setMsg(e.response?.data?.detail || "Token inválido"); });
  }, [token, navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0a0a0a] text-white p-4">
      <div className="tactile-card p-10 max-w-md w-full text-center" data-testid="verify-email-page">
        {state === "loading" && <><Loader2 className="w-10 h-10 text-[#EAB308] animate-spin mx-auto mb-4" /><p className="text-neutral-400">Verificando tu correo...</p></>}
        {state === "ok" && <><ShieldCheck className="w-12 h-12 text-[#22C55E] mx-auto mb-4" data-testid="verify-email-success-icon" /><h1 className="font-display text-2xl mb-2" data-testid="verify-email-success-title">¡Correo verificado!</h1><p className="text-neutral-400 text-sm">Ya puedes iniciar sesión. Redirigiendo...</p></>}
        {state === "err" && <><AlertTriangle className="w-12 h-12 text-[#EF4444] mx-auto mb-4" data-testid="verify-email-error-icon" /><h1 className="font-display text-2xl mb-2" data-testid="verify-email-error-title">No se pudo verificar</h1><p className="text-neutral-400 text-sm mb-6" data-testid="verify-email-error-msg">{msg}</p><Link to="/" className="text-[#EAB308] hover:underline text-sm" data-testid="verify-email-back-link">← Volver al inicio</Link></>}
      </div>
    </div>
  );
}
