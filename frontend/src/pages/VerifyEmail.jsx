import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { ShieldCheck, AlertTriangle, Loader2 } from "lucide-react";

export default function VerifyEmail() {
  const { token } = useParams();
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const [state, setState] = useState("loading"); // loading | ok | err
  const [msg, setMsg] = useState("");
  const didRun = useRef(false);

  useEffect(() => {
    if (didRun.current) return;
    didRun.current = true;
    axios.get(`${API}/auth/verify-email/${token}`, { withCredentials: true })
      .then((r) => { setUser(r.data); setState("ok");
        setTimeout(() => navigate(r.data.role === "admin" || r.data.role === "employee" ? "/admin" : "/dashboard"), 1800);
      })
      .catch((e) => { setState("err"); setMsg(e.response?.data?.detail || "Token inválido"); });
  }, [token, navigate, setUser]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0a0a0a] text-white p-4">
      <div className="tactile-card p-10 max-w-md w-full text-center" data-testid="verify-email-page">
        {state === "loading" && <><Loader2 className="w-10 h-10 text-[#EAB308] animate-spin mx-auto mb-4" /><p className="text-neutral-400">Verificando tu correo...</p></>}
        {state === "ok" && <><ShieldCheck className="w-12 h-12 text-[#22C55E] mx-auto mb-4" /><h1 className="font-display text-2xl mb-2">¡Correo verificado!</h1><p className="text-neutral-400 text-sm">Redirigiendo...</p></>}
        {state === "err" && <><AlertTriangle className="w-12 h-12 text-[#EF4444] mx-auto mb-4" /><h1 className="font-display text-2xl mb-2">No se pudo verificar</h1><p className="text-neutral-400 text-sm mb-6">{msg}</p><Link to="/" className="text-[#EAB308] hover:underline text-sm">← Volver al inicio</Link></>}
      </div>
    </div>
  );
}
