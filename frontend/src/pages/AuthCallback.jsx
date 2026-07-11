import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";

export default function AuthCallback() {
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const processed = useRef(false);

  useEffect(() => {
    if (processed.current) return;
    processed.current = true;
    const hash = window.location.hash;
    const m = hash.match(/session_id=([^&]+)/);
    if (!m) {
      navigate("/", { replace: true });
      return;
    }
    const session_id = m[1];
    axios.post(`${API}/auth/session`, { session_id }, { withCredentials: true })
      .then((res) => {
        setUser(res.data);
        window.history.replaceState({}, "", "/dashboard");
        navigate("/dashboard", { replace: true, state: { user: res.data } });
      })
      .catch(() => {
        navigate("/", { replace: true });
      });
  }, [navigate, setUser]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0A0A0F]">
      <div className="text-center">
        <div className="w-12 h-12 border-2 border-[#8B5CF6] border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
        <p className="text-neutral-400 micro-label">Autenticando sesión segura</p>
      </div>
    </div>
  );
}
