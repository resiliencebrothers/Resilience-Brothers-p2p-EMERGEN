import { useState, useRef, useEffect } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
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
import { Turnstile } from "@marsidev/react-turnstile";
import { getTheme } from "@/lib/theme";
import { roleHome } from "@/lib/roleHome";
import { User, Building2, ArrowRight, AlertCircle } from "lucide-react";
import CompanySignupDialog from "./CompanySignupDialog";

export default function EmailAuthDialog({ open, onClose, initialEmail = "" }) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const { signInWithPassword, login } = useAuth();
  const [mode, setMode] = useState("login"); // "login" | "register" | "forgot"
  const [email, setEmail] = useState(initialEmail || "");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [accountType, setAccountType] = useState("personal"); // "personal" | "business"
  const [companyOpen, setCompanyOpen] = useState(false);
  const [remember24h, setRemember24h] = useState(false);
  const [loading, setLoading] = useState(false);
  const [successMsg, setSuccessMsg] = useState("");
  // Error visible EN el formulario (no solo un toast): con captcha el widget
  // de Cloudflare muestra su propio "¡Operación exitosa!" y el usuario no veía
  // el aviso de credenciales. Este banner deja claro "email o contraseña
  // incorrectos" dentro del diálogo.
  const [formError, setFormError] = useState("");
  // Tipo de error en el formulario: "credentials" muestra ayuda de recuperación
  // (¿olvidaste tu contraseña?); "session" es un fallo de red recuperable.
  const [formErrorKind, setFormErrorKind] = useState("");
  const [failCount, setFailCount] = useState(0);
  const [notice, setNotice] = useState(null); // {kind: 'register'|'google', message}
  const [resending, setResending] = useState(false);
  const nameInputRef = useRef(null);
  const errorRef = useRef(null);
  // iter246 — verificación "No soy un robot" (Cloudflare Turnstile).
  const [captchaCfg, setCaptchaCfg] = useState(null);
  const [captchaToken, setCaptchaToken] = useState("");
  const [captchaKey, setCaptchaKey] = useState(0);

  useEffect(() => {
    if (!open || captchaCfg !== null) return;
    axios.get(`${API}/captcha/config`)
      .then((r) => setCaptchaCfg(r.data))
      .catch(() => setCaptchaCfg({ enabled: false }));
  }, [open, captchaCfg]);

  // Un fallo de credenciales debe ser imposible de ignorar: con captcha el
  // widget de Cloudflare dibuja su propio "¡Operación exitosa!" (su check de
  // "no soy un robot"), así que llevamos el banner rojo a la vista.
  useEffect(() => {
    if (formError) errorRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [formError]);

  const reset = () => {
    setEmail(""); setPassword(""); setConfirmPassword(""); setShowPassword(false);
    setName(""); setPhone(""); setRemember24h(false); setLoading(false);
    setSuccessMsg(""); setNotice(null); setMode("login"); setAccountType("personal");
    setFormError(""); setFormErrorKind(""); setFailCount(0);
    setCaptchaToken(""); setCaptchaKey((k) => k + 1);
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
  // NOTE (auditoría 28/7/2026): the backend intentionally returns a single
  // generic INVALID_CREDENTIALS for both "no account" and "wrong password" to
  // prevent account enumeration — so there is no per-code register prompt here.
  const ERROR_CODE_HANDLERS = {
    EMAIL_NOT_VERIFIED: () => setSuccessMsg(t("auth.success.emailNotVerified")),
    USE_GOOGLE_LOGIN: () =>
      setNotice({ kind: "google", message: t("auth.notice.googleAccount") }),
  };

  // Backend error code → clave i18n (el mensaje se traduce en el FRONTEND según
  // el idioma elegido; el backend siempre responde en español).
  const ERROR_CODE_MESSAGES = {
    INVALID_CREDENTIALS: "auth.errors.invalidCredentials",
    CAPTCHA_REQUIRED: "auth.errors.captchaRequired",
    CAPTCHA_FAILED: "auth.errors.captchaFailed",
  };

  const handleAuthError = (err) => {
    const detail = err.response?.data?.detail;
    const code = typeof detail === "object" ? detail?.code : null;
    const message = typeof detail === "object" ? detail?.message : detail;
    const handler = code && ERROR_CODE_HANDLERS[code];
    if (handler) { handler(message); return; }
    // Traducimos por código; el 429 (límite de intentos) llega como string.
    let text;
    if (code && ERROR_CODE_MESSAGES[code]) text = t(ERROR_CODE_MESSAGES[code]);
    else if (err.response?.status === 429) text = t("auth.errors.rateLimited");
    else text = typeof message === "string" ? message : t("auth.errors.generic");
    // Los errores de captcha (CAPTCHA_REQUIRED / CAPTCHA_FAILED) NO son de
    // credenciales: se muestran sin la ayuda de "¿olvidaste tu contraseña?".
    const isCaptcha = code === "CAPTCHA_REQUIRED" || code === "CAPTCHA_FAILED";
    // Aviso INLINE persistente + toast: el usuario ve "email o contraseña
    // incorrectos" dentro del formulario, no solo el widget de Cloudflare.
    // Para credenciales marcamos el error para ofrecer recuperación
    // (¿olvidaste tu contraseña?) y reforzarla tras varios intentos fallidos.
    setFormError(text);
    setFormErrorKind(isCaptcha ? "captcha" : "credentials");
    if (!isCaptcha) setFailCount((c) => c + 1);
    toast.error(text);
  };

  const submit = async (e) => {
    e?.preventDefault?.();
    if (loading) return;
    if (mode === "register" && password !== confirmPassword) {
      toast.error(t("auth.errors.passwordsNoMatch"));
      return;
    }
    // Captcha obligatorio: si la verificación "No soy un robot" aún no se ha
    // completado, NO dejamos el botón inerte sin feedback (el usuario creía que
    // su contraseña estaba mal). Mostramos un aviso claro que lo guía al widget.
    if (captchaCfg?.enabled && captchaCfg?.enforced && mode !== "forgot" && !captchaToken) {
      setFormError(t("auth.errors.captchaIncomplete"));
      setFormErrorKind("captcha");
      toast.error(t("auth.errors.captchaIncompleteToast"));
      return;
    }
    setLoading(true);
    setFormError("");
    setFormErrorKind("");
    try {
      if (mode === "forgot") {
        await axios.post(`${API}/auth/forgot-password`, { email: email.trim() });
        setSuccessMsg(t("auth.success.forgotSent"));
        return;
      }
      const captcha = captchaCfg?.enabled && captchaToken ? { captcha_token: captchaToken } : {};
      if (mode === "register") {
        const body = { email: email.trim(), password, name: name.trim(), phone: phone.trim(), account_type: accountType, ...captcha };
        await axios.post(`${API}/auth/register`, body, { withCredentials: true });
        // iter17: registration no longer logs in — must verify email first
        const base = t("auth.success.registerDefault");
        setSuccessMsg(accountType === "business"
          ? `${base} ${t("auth.success.businessPending")}`
          : base);
        return;
      }
      // AUTH-03 — login is centralised in AuthContext: it validates the user
      // contract and confirms the session via /auth/me BEFORE we announce
      // success, so a resolved response alone can never claim "Sesión iniciada".
      const body = { email: email.trim(), password, ...(remember24h ? { remember_hours: 24 } : {}), ...captcha };
      const confirmed = await signInWithPassword(body);
      toast.success(t("auth.success.login"));
      onClose?.(); reset();
      navigate(roleHome(confirmed));
    } catch (err) {
      // R2 — intento de login obsoleto (logout u otro login lo invalidó
      // mientras esperaba): ignorar en silencio. Sin toast de éxito, sin
      // redirección y sin mensaje de contraseña incorrecta.
      if (err?.code === "AUTH_STALE") {
        return;
      }
      // AUTH-03 — credentials accepted but session not confirmed (cookie not
      // stored / network): recoverable, NEVER shown as "contraseña incorrecta".
      if (err?.code === "SESSION_UNCONFIRMED") {
        const msg = t("auth.errors.sessionUnconfirmed");
        setFormError(msg);
        setFormErrorKind("session");
        toast.error(msg);
      } else {
        handleAuthError(err);
      }
      // iter246 — el token Turnstile es de un solo uso: regenerar tras fallo.
      setCaptchaToken("");
      setCaptchaKey((k) => k + 1);
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => { onClose?.(); reset(); };
  const businessRegister = mode === "register" && accountType === "business";

  const switchToRegisterFromNotice = () => {
    setNotice(null);
    setSuccessMsg("");
    setPassword("");
    setMode("register");
    setTimeout(() => nameInputRef.current?.focus(), 50);
  };

  const useGoogleFromNotice = () => { onClose?.(); login(); };

  return (
    <>
    <Dialog open={open} onOpenChange={(o) => { if (!o) handleClose(); }}>
      <DialogContent
        data-testid="email-auth-dialog"
        className="bg-[#1A1730] border-white/10 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">{t(`auth.title.${mode}`)}</DialogTitle>
          <DialogDescription className="text-neutral-500 text-xs">
            {t(`auth.desc.${mode}`)}
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
            {formError && (
              <div
                data-testid="auth-error-banner"
                ref={errorRef}
                role="alert"
                className="auth-error-box flex items-start gap-2 text-sm px-3 py-2.5 rounded-none"
              >
                <AlertCircle className="auth-error-icon w-4 h-4 mt-0.5 shrink-0" />
                <div className="min-w-0">
                  <span className="font-medium">{formError}</span>
                  {formErrorKind === "credentials" && (
                    <div className="mt-2 flex flex-col gap-1.5" data-testid="auth-error-help">
                      <span className="auth-error-help text-xs">
                        {t("auth.errors.credentialsHelp")}
                      </span>
                      <button
                        type="button"
                        data-testid="auth-error-forgot"
                        onClick={() => { setFormError(""); setFormErrorKind(""); setMode("forgot"); }}
                        className="auth-error-cta self-start text-xs font-semibold underline underline-offset-4"
                      >
                        {t("auth.errors.forgotCta")}
                      </button>
                      {failCount >= 2 && (
                        <span data-testid="auth-error-repeated" className="auth-error-repeat text-xs">
                          {t("auth.errors.repeated", { count: failCount })}
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}
            <AuthNotice
              notice={notice}
              onSwitchToRegister={switchToRegisterFromNotice}
              onUseGoogle={useGoogleFromNotice}
            />

            <GoogleAuthButton onClick={() => { onClose?.(); login(); }} />

            {!businessRegister && (
              <div className="relative flex items-center text-[0.65rem] text-neutral-600 micro-label">
                <div className="flex-1 h-px bg-white/10" />
                <span className="px-3">{t("auth.or")}</span>
                <div className="flex-1 h-px bg-white/10" />
              </div>
            )}

            {mode === "register" && (
              <div data-testid="account-type-selector">
                <div className="micro-label text-neutral-500 mb-2">{t("auth.accountType.label")}</div>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    data-testid="account-type-personal"
                    onClick={() => setAccountType("personal")}
                    className={`flex items-center justify-center gap-2 py-3 text-sm font-medium border rounded-none transition-colors ${
                      accountType === "personal"
                        ? "border-[#8B5CF6] bg-[#8B5CF6]/10 text-white"
                        : "border-white/10 text-neutral-400 hover:text-white"
                    }`}
                  >
                    <User className="w-4 h-4" /> {t("auth.accountType.personal")}
                  </button>
                  <button
                    type="button"
                    data-testid="account-type-business"
                    onClick={() => setAccountType("business")}
                    className={`flex items-center justify-center gap-2 py-3 text-sm font-medium border rounded-none transition-colors ${
                      accountType === "business"
                        ? "border-[#8B5CF6] bg-[#8B5CF6]/10 text-white"
                        : "border-white/10 text-neutral-400 hover:text-white"
                    }`}
                  >
                    <Building2 className="w-4 h-4" /> {t("auth.accountType.business")}
                  </button>
                </div>
                {accountType === "business" && (
                  <p className="text-xs text-neutral-500 mt-2" data-testid="account-type-business-hint">
                    {t("auth.accountType.businessHint")}
                  </p>
                )}
              </div>
            )}

            {businessRegister ? (
              <div className="space-y-3" data-testid="company-signup-cta-panel">
                <Button
                  type="button"
                  data-testid="open-company-signup-btn"
                  onClick={() => { onClose?.(); reset(); setCompanyOpen(true); }}
                  className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-12"
                >
                  {t("auth.business.continue")} <ArrowRight className="w-4 h-4 ml-2" />
                </Button>
                <div className="text-center mt-3">
                  <a href="/empresa/seguimiento" data-testid="company-track-status-link"
                    className="text-xs text-neutral-400 hover:text-[#8B5CF6]">
                    {t("auth.business.trackStatus")}
                  </a>
                </div>
              </div>
            ) : (
              <>
            <AuthCredentialsFields
              mode={mode}
              name={name} setName={setName}
              phone={phone} setPhone={setPhone}
              email={email} setEmail={setEmail}
              password={password} setPassword={setPassword}
              confirmPassword={confirmPassword} setConfirmPassword={setConfirmPassword}
              showPassword={showPassword} setShowPassword={setShowPassword}
              nameInputRef={nameInputRef}
              onEmailChange={() => { if (notice) setNotice(null); if (formError) setFormError(""); }}
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
                  className="border-white/30 data-[state=checked]:bg-[#8B5CF6] data-[state=checked]:text-white data-[state=checked]:border-[#8B5CF6]"
                />
                {t("auth.remember24h")}
              </label>
            )}

            {captchaCfg?.enabled && mode !== "forgot" && (
              <div className="space-y-1.5" data-testid="captcha-widget">
                <p className="text-[0.7rem] text-neutral-500 text-center">
                  {t("auth.captchaLabel")}
                </p>
                <div className="flex justify-center">
                  <Turnstile
                    key={captchaKey}
                    siteKey={captchaCfg.site_key}
                    options={{ theme: getTheme() === "light" ? "light" : "dark", language: (i18n.language || "es").split("-")[0], appearance: "interaction-only" }}
                    onSuccess={(tok) => { setCaptchaToken(tok); if (formErrorKind === "captcha") { setFormError(""); setFormErrorKind(""); } }}
                    onExpire={() => setCaptchaToken("")}
                    onError={() => setCaptchaToken("")}
                  />
                </div>
              </div>
            )}

            <Button
              type="submit"
              data-testid="auth-submit"
              disabled={loading}
              className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-12"
            >
              {loading ? t("auth.submit.loading") : t(`auth.submit.${mode}`)}
            </Button>
              </>
            )}

            <div className="flex flex-col gap-2 items-center">
              <button
                type="button"
                data-testid="auth-toggle-mode"
                onClick={() => { setFormError(""); setFormErrorKind(""); setFailCount(0); setMode(mode === "login" ? "register" : "login"); }}
                className="text-xs text-neutral-400 hover:text-[#8B5CF6] underline underline-offset-4"
              >
                {mode === "register"
                  ? t("auth.toggle.haveAccount")
                  : mode === "forgot"
                    ? t("auth.toggle.backToLogin")
                    : t("auth.toggle.noAccount")}
              </button>
              {mode === "login" && (
                <>
                  <button
                    type="button"
                    data-testid="auth-forgot-link"
                    onClick={() => { setFormError(""); setFormErrorKind(""); setMode("forgot"); }}
                    className="text-xs text-neutral-500 hover:text-[#8B5CF6] underline underline-offset-4"
                  >
                    {t("auth.forgotLink")}
                  </button>
                  <button
                    type="button"
                    data-testid="auth-resend-verification-link"
                    onClick={handleResendVerification}
                    disabled={resending}
                    className="text-xs text-neutral-500 hover:text-[#8B5CF6] underline underline-offset-4 disabled:opacity-50"
                  >
                    {resending ? t("auth.resending") : t("auth.resend")}
                  </button>
                </>
              )}
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
    <CompanySignupDialog open={companyOpen} onClose={() => setCompanyOpen(false)} />
    </>
  );
}
