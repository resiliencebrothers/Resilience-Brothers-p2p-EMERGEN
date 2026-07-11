import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Lock, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

export default function ResetPassword() {
  const { token } = useParams();
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (password.length < 8) return toast.error("Mínimo 8 caracteres");
    if (password !== confirm) return toast.error("Las contraseñas no coinciden");
    setLoading(true);
    try {
      await axios.post(`${API}/auth/reset-password`, { token, password }, { withCredentials: true });
      setDone(true);
      toast.success("Contraseña actualizada");
      setTimeout(() => navigate("/"), 1500);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    } finally { setLoading(false); }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0a0a0a] text-white p-4">
      <div className="tactile-card p-8 max-w-md w-full" data-testid="reset-password-page">
        {done ? (
          <div className="text-center">
            <ShieldCheck className="w-12 h-12 text-[#22C55E] mx-auto mb-4" />
            <h1 className="font-display text-2xl mb-2">Listo</h1>
            <p className="text-neutral-400 text-sm">Tu contraseña fue actualizada.</p>
          </div>
        ) : (
          <>
            <div className="micro-label text-[#8B5CF6] mb-2">/ recuperar acceso</div>
            <h1 className="font-display text-2xl mb-6">Crear nueva contraseña</h1>
            <form onSubmit={submit} className="space-y-4">
              <div>
                <Label className="micro-label text-neutral-500">Nueva contraseña</Label>
                <div className="relative mt-1">
                  <Lock className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
                  <Input type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} data-testid="reset-pwd-input" placeholder="mín. 8 caracteres" className="rounded-none bg-[#0a0a0a] border-white/10 h-11 pl-9" />
                </div>
              </div>
              <div>
                <Label className="micro-label text-neutral-500">Confirmar</Label>
                <Input type="password" required minLength={8} value={confirm} onChange={(e) => setConfirm(e.target.value)} data-testid="reset-confirm-input" className="rounded-none bg-[#0a0a0a] border-white/10 h-11 mt-1" />
              </div>
              <Button type="submit" disabled={loading} data-testid="reset-submit" className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-11">
                {loading ? "..." : "Guardar nueva contraseña"}
              </Button>
              <Link to="/" className="block text-center text-xs text-neutral-500 hover:text-[#8B5CF6] underline underline-offset-4">← Volver al inicio</Link>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
