import { useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Mail, Lock, User as UserIcon } from "lucide-react";
import { toast } from "sonner";

export default function EmailAuthDialog({ open, onClose }) {
  const navigate = useNavigate();
  const { setUser, login } = useAuth();
  const [mode, setMode] = useState("login"); // "login" | "register"
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);

  const reset = () => {
    setEmail(""); setPassword(""); setName(""); setLoading(false);
  };

  const submit = async (e) => {
    e?.preventDefault?.();
    if (loading) return;
    setLoading(true);
    try {
      const url = mode === "register" ? "/auth/register" : "/auth/login";
      const body = mode === "register"
        ? { email: email.trim(), password, name: name.trim() }
        : { email: email.trim(), password };
      const r = await axios.post(`${API}${url}`, body, { withCredentials: true });
      setUser(r.data);
      toast.success(mode === "register" ? "Cuenta creada" : "Sesión iniciada");
      onClose?.();
      reset();
      navigate(r.data.role === "admin" || r.data.role === "employee" ? "/admin" : "/dashboard");
    } catch (err) {
      const detail = err.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "Error de autenticación");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) { onClose?.(); reset(); } }}>
      <DialogContent
        data-testid="email-auth-dialog"
        className="bg-[#141414] border-white/10 text-white rounded-none max-w-md"
      >
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">
            {mode === "register" ? "Crear cuenta" : "Iniciar con email"}
          </DialogTitle>
          <DialogDescription className="text-neutral-500 text-xs">
            {mode === "register"
              ? "Para usuarios en regiones con restricciones de Google."
              : "Acceso con email y contraseña."}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <button
            type="button"
            data-testid="auth-google-btn"
            onClick={() => { onClose?.(); login(); }}
            className="w-full border border-white/20 hover:border-[#EAB308] hover:bg-white/5 text-white rounded-none h-11 text-sm font-semibold flex items-center justify-center gap-2 transition-colors"
          >
            <svg className="w-4 h-4" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">
              <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.4 6.2 29.5 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"/>
              <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.6 16.2 19 13 24 13c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.4 6.2 29.5 4 24 4c-7.7 0-14.3 4.4-17.7 10.7z"/>
              <path fill="#4CAF50" d="M24 44c5.3 0 10.1-2 13.8-5.4l-6.4-5.4C29.2 35 26.7 36 24 36c-5.1 0-9.5-3.2-11.2-7.8l-6.5 5C9.6 39.6 16.3 44 24 44z"/>
              <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.3 4.3-4.2 5.7l6.4 5.4C42 35 44 30 44 24c0-1.3-.1-2.4-.4-3.5z"/>
            </svg>
            Continuar con Google
          </button>
          <div className="relative flex items-center text-[0.65rem] text-neutral-600 micro-label">
            <div className="flex-1 h-px bg-white/10" />
            <span className="px-3">o</span>
            <div className="flex-1 h-px bg-white/10" />
          </div>
          {mode === "register" && (
            <div>
              <Label className="micro-label text-neutral-500">Nombre</Label>
              <div className="relative mt-1">
                <UserIcon className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
                <Input
                  data-testid="auth-name-input"
                  required
                  minLength={2}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Tu nombre"
                  className="rounded-none bg-[#0a0a0a] border-white/10 h-11 pl-9"
                />
              </div>
            </div>
          )}
          <div>
            <Label className="micro-label text-neutral-500">Email</Label>
            <div className="relative mt-1">
              <Mail className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
              <Input
                data-testid="auth-email-input"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="tu@email.com"
                autoComplete="email"
                className="rounded-none bg-[#0a0a0a] border-white/10 h-11 pl-9"
              />
            </div>
          </div>
          <div>
            <Label className="micro-label text-neutral-500">Contraseña</Label>
            <div className="relative mt-1">
              <Lock className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
              <Input
                data-testid="auth-password-input"
                type="password"
                required
                minLength={mode === "register" ? 8 : 1}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={mode === "register" ? "mín. 8 caracteres" : "Tu contraseña"}
                autoComplete={mode === "register" ? "new-password" : "current-password"}
                className="rounded-none bg-[#0a0a0a] border-white/10 h-11 pl-9"
              />
            </div>
          </div>
          <Button
            type="submit"
            data-testid="auth-submit"
            disabled={loading}
            className="w-full bg-[#EAB308] hover:bg-[#FACC15] text-black font-bold rounded-none h-12"
          >
            {loading ? "..." : mode === "register" ? "Crear cuenta" : "Iniciar sesión"}
          </Button>
          <button
            type="button"
            data-testid="auth-toggle-mode"
            onClick={() => setMode(mode === "login" ? "register" : "login")}
            className="w-full text-xs text-neutral-400 hover:text-[#EAB308] underline underline-offset-4"
          >
            {mode === "login" ? "¿No tienes cuenta? Crear una" : "Ya tengo cuenta, iniciar sesión"}
          </button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
