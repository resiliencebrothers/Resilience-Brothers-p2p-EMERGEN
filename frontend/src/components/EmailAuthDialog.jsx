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
  const { setUser } = useAuth();
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
