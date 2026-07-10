import { useState, useRef, useEffect } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { toast } from "sonner";

import { AuthSuccessPanel } from "./auth/AuthSuccessPanel";
import { GoogleAuthButton } from "./auth/GoogleAuthButton";
import { AuthNotice } from "./auth/AuthNotice";
import { AuthCredentialsFields } from "./auth/AuthCredentialsFields";

const TITLES = {
  register: "Crear cuenta",
  forgot: "Recuperar contraseña",
  login: "Iniciar con email",
};

const DESCRIPTIONS = {
  register: "¿Aún no tienes cuenta en Resilience? Regístrate con tu email.",
  forgot: "Te enviaremos un enlace para crear una nueva contraseña.",
  login: "Acceso con email y contraseña.",
};

const SUBMIT_LABELS = {
  register: "Crear cuenta",
  forgot: "Enviar enlace",
  login: "Iniciar sesión",
};

export default function EmailAuthDialog({ open, onClose, initialEmail = "" }) {
  const navigate = useNavigate();
  const { setUser, login } = useAuth();
  const [mode, setMode] = useState("login"); // "login" | "register" | "forgot"
  const [email, setEmail] = useState(initialEmail || "");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [remember24h, setRemember24h] = useState(false);
  const [loading, setLoading] = useState(false);
  const [successMsg, setSuccessMsg] = useState("");
  const [notice, setNotice] = useState(null); // {kind: 'register'|'google', message}
  const [resending, setResending] = useState(false);
  const nameInputRef = useRef(null);

  const reset = () => {
    setEmail(""); setPassword(""); setConfirmPassword(""); setShowPassword(false);
    setName(""); setPhone(""); setRemember24h(false); setLoading(false);
    setSuccessMsg(""); setNotice(null); setMode("login");
  };

  // When the dialog opens with a prefilled email (from the verify-email flow),
  // populate the email field and force login mode so the user can sign in.
  useEffect(() => {
    if (open && initialEmail) {
      setEmail(initialEmail);
      setMode("login");
      setNotice(null);
      setSuccessMsg("");
    }
  }, [open, initialEmail]);

  const handleResendVerification = async () => {
    const target = email.trim();
    if (!target) {
      toast.error("Ingresa tu email primero");
      return;
    }
    if (resending) return;
    setResending(true);
    try {
      const r = await axios.post(`${API}/auth/resend-verification`, { email: target });
      toast.success(
        r.data?.message || "Si la cuenta existe y no está verificada, te reenviamos el correo.",
        { duration: 6000 }
      );
    } catch (err) {
      const detail = err.response?.data?.detail;
      const msg = typeof detail === "string" ? detail : "No pudimos reenviar el correo. Intenta de nuevo.";
      toast.error(msg);
    } finally {
      setResending(false);
    }
  };

  // Map backend error codes → UI side-effects. Reduces submit() complexity.
  const ERROR_CODE_HANDLERS = {
    EMAIL_NOT_VERIFIED: (msg) =>
      setSuccessMsg(msg || "Verifica tu correo antes de iniciar sesión."),
    USER_NOT_FOUND: (msg) =>
      setNotice({
        kind: "register",
        message: msg || "No existe una cuenta con este email. Crea una cuenta para continuar.",
      }),
    USE_GOOGLE_LOGIN: (msg) =>
      setNotice({
        kind: "google",
        message: msg || "Esta cuenta fue creada con Google.",
      }),
  };

  const handleAuthError = (err) => {
    const detail = err.response?.data?.detail;
    const code = typeof detail === "object" ? detail?.code : null;
    const message = typeof detail === "object" ? detail?.message : detail;
    const handler = code && ERROR_CODE_HANDLERS[code];
    if (handler) { handler(message); return; }
    toast.error(typeof message === "string" ? message : "Error de autenticación");
  };

  const submit = async (e) => {
    e?.preventDefault?.();
    if (loading) return;
    if (mode === "register" && password !== confirmPassword) {
      toast.error("Las contraseñas no coinciden");
      return;
    }
    setLoading(true);
    try {
      if (mode === "forgot") {
        await axios.post(`${API}/auth/forgot-password`, { email: email.trim() });
        setSuccessMsg("Si la cuenta existe, recibirás un correo con el enlace para crear una nueva contraseña.");
        return;
      }
      const url = mode === "register" ? "/auth/register" : "/auth/login";
      const body = mode === "register"
        ? { email: email.trim(), password, name: name.trim(), phone: phone.trim() }
        : { email: email.trim(), password, ...(remember24h ? { remember_hours: 24 } : {}) };
      const r = await axios.post(`${API}${url}`, body, { withCredentials: true });
      if (mode === "register") {
        // iter17: registration no longer logs in — must verify email first
        setSuccessMsg(r.data.message || "Cuenta creada. Revisa tu correo para verificar.");
        return;
      }
      setUser(r.data);
      toast.success("Sesión iniciada");
      onClose?.(); reset();
      navigate(r.data.role === "admin" || r.data.role === "employee" ? "/admin" : "/dashboard");
    } catch (err) {
      handleAuthError(err);
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => { onClose?.(); reset(); };

  const switchToRegisterFromNotice = () => {
    setNotice(null);
    setSuccessMsg("");
    setPassword("");
    setMode("register");
    setTimeout(() => nameInputRef.current?.focus(), 50);
  };

  const useGoogleFromNotice = () => { onClose?.(); login(); };

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) handleClose(); }}>
      <DialogContent
        data-testid="email-auth-dialog"
        className="bg-[#141414] border-white/10 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">{TITLES[mode]}</DialogTitle>
          <DialogDescription className="text-neutral-500 text-xs">
            {DESCRIPTIONS[mode]}
          </DialogDescription>
        </DialogHeader>

        {successMsg ? (
          <AuthSuccessPanel
            message={successMsg}
            mode={mode}
            resending={resending}
            onResend={handleResendVerification}
            onClose={handleClose}
          />
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <AuthNotice
              notice={notice}
              onSwitchToRegister={switchToRegisterFromNotice}
              onUseGoogle={useGoogleFromNotice}
            />

            <GoogleAuthButton onClick={() => { onClose?.(); login(); }} />

            <div className="relative flex items-center text-[0.65rem] text-neutral-600 micro-label">
              <div className="flex-1 h-px bg-white/10" />
              <span className="px-3">o</span>
              <div className="flex-1 h-px bg-white/10" />
            </div>

            <AuthCredentialsFields
              mode={mode}
              name={name} setName={setName}
              phone={phone} setPhone={setPhone}
              email={email} setEmail={setEmail}
              password={password} setPassword={setPassword}
              confirmPassword={confirmPassword} setConfirmPassword={setConfirmPassword}
              showPassword={showPassword} setShowPassword={setShowPassword}
              nameInputRef={nameInputRef}
              onEmailChange={() => { if (notice) setNotice(null); }}
            />

            {mode === "login" && (
              <label
                htmlFor="auth-remember-24h"
                className="flex items-center gap-2 cursor-pointer select-none text-xs text-neutral-400 hover:text-white transition-colors"
              >
                <Checkbox
                  id="auth-remember-24h"
                  data-testid="auth-remember-24h"
                  checked={remember24h}
                  onCheckedChange={(v) => setRemember24h(v === true)}
                  className="border-white/30 data-[state=checked]:bg-[#EAB308] data-[state=checked]:text-black data-[state=checked]:border-[#EAB308]"
                />
                Mantener sesión 24 horas (entrar 1 vez al día)
              </label>
            )}

            <Button
              type="submit"
              data-testid="auth-submit"
              disabled={loading}
              className="w-full bg-[#EAB308] hover:bg-[#FACC15] text-black font-bold rounded-none h-12"
            >
              {loading ? "..." : SUBMIT_LABELS[mode]}
            </Button>

            <div className="flex flex-col gap-2 items-center">
              <button
                type="button"
                data-testid="auth-toggle-mode"
                onClick={() => setMode(mode === "login" ? "register" : "login")}
                className="text-xs text-neutral-400 hover:text-[#EAB308] underline underline-offset-4"
              >
                {mode === "register"
                  ? "Ya tengo cuenta, iniciar sesión"
                  : mode === "forgot"
                    ? "Volver a iniciar sesión"
                    : "¿No tienes cuenta? Crear una"}
              </button>
              {mode === "login" && (
                <>
                  <button
                    type="button"
                    data-testid="auth-forgot-link"
                    onClick={() => setMode("forgot")}
                    className="text-xs text-neutral-500 hover:text-[#EAB308] underline underline-offset-4"
                  >
                    ¿Olvidaste tu contraseña?
                  </button>
                  <button
                    type="button"
                    data-testid="auth-resend-verification-link"
                    onClick={handleResendVerification}
                    disabled={resending}
                    className="text-xs text-neutral-500 hover:text-[#EAB308] underline underline-offset-4 disabled:opacity-50"
                  >
                    {resending ? "Reenviando..." : "¿No recibiste el correo de verificación?"}
                  </button>
                </>
              )}
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
