import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Shield, CheckCircle2, ShieldAlert, Copy, RefreshCw, AlertTriangle, KeyRound, Eye, EyeOff } from "lucide-react";
import ProfileSectionTabs from "@/components/ProfileSectionTabs";

export default function SecuritySettings() {
  const [status, setStatus] = useState(null);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [setupData, setSetupData] = useState(null); // { qr_data_url, secret, provisioning_uri }
  const [verifyCode, setVerifyCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [recoveryCodes, setRecoveryCodes] = useState(null); // shown once after activation
  const [disableModal, setDisableModal] = useState(false);
  const [disableCode, setDisableCode] = useState("");
  const [regenModal, setRegenModal] = useState(false);
  const [regenCode, setRegenCode] = useState("");

  // iter55.30 — password change state
  const [pwdCurrent, setPwdCurrent] = useState("");
  const [pwdNew, setPwdNew] = useState("");
  const [pwdConfirm, setPwdConfirm] = useState("");
  const [pwdTotp, setPwdTotp] = useState("");
  const [pwdShow, setPwdShow] = useState(false);
  const [pwdBusy, setPwdBusy] = useState(false);

  const loadStatus = async () => {
    try {
      const [statusRes, profileRes] = await Promise.all([
        axios.get(`${API}/me/2fa/status`, { withCredentials: true }),
        axios.get(`${API}/profile/me`, { withCredentials: true }),
      ]);
      setStatus(statusRes.data);
      setProfile(profileRes.data);
    } catch (e) {
      toast.error("Error al cargar estado 2FA");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { loadStatus(); }, []);

  const startSetup = async () => {
    setBusy(true);
    try {
      const r = await axios.post(`${API}/me/2fa/setup`, {}, { withCredentials: true });
      setSetupData(r.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error al iniciar setup");
    } finally {
      setBusy(false);
    }
  };

  const verifySetup = async () => {
    if (verifyCode.length !== 6) return toast.error("Ingresa 6 dígitos");
    setBusy(true);
    try {
      const r = await axios.post(`${API}/me/2fa/verify-setup`, { code: verifyCode }, { withCredentials: true });
      setRecoveryCodes(r.data.recovery_codes);
      setSetupData(null);
      setVerifyCode("");
      toast.success("2FA activado correctamente");
      await loadStatus();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Código inválido");
    } finally {
      setBusy(false);
    }
  };

  const disable2FA = async () => {
    if (!disableCode) return toast.error("Ingresa tu código 2FA actual");
    setBusy(true);
    try {
      await axios.post(`${API}/me/2fa/disable`, { code: disableCode }, { withCredentials: true });
      toast.success("2FA desactivado");
      setDisableModal(false); setDisableCode("");
      await loadStatus();
    } catch (e) {
      toast.error(e.response?.data?.detail?.message || "Código inválido");
    } finally {
      setBusy(false);
    }
  };

  const regenerateCodes = async () => {
    if (!regenCode) return toast.error("Ingresa tu código 2FA actual");
    setBusy(true);
    try {
      const r = await axios.post(`${API}/me/2fa/regenerate-recovery-codes`, { code: regenCode }, { withCredentials: true });
      setRecoveryCodes(r.data.recovery_codes);
      setRegenModal(false); setRegenCode("");
      toast.success("Códigos de recuperación renovados");
      await loadStatus();
    } catch (e) {
      toast.error(e.response?.data?.detail?.message || "Código inválido");
    } finally {
      setBusy(false);
    }
  };

  const copyText = (text) => {
    navigator.clipboard.writeText(text);
    toast.success("Copiado");
  };

  const submitPasswordChange = async () => {
    if (pwdNew.length < 8) {
      return toast.error("La nueva contraseña debe tener al menos 8 caracteres.");
    }
    if (pwdNew !== pwdConfirm) {
      return toast.error("La confirmación no coincide con la nueva contraseña.");
    }
    if (pwdCurrent === pwdNew) {
      return toast.error("La nueva contraseña debe ser diferente de la actual.");
    }
    if (status?.enabled && pwdTotp.length !== 6) {
      return toast.error("Ingresa tu código 2FA de 6 dígitos.");
    }
    setPwdBusy(true);
    try {
      const r = await axios.post(
        `${API}/profile/password/change`,
        {
          current_password: pwdCurrent,
          new_password: pwdNew,
          totp_code: status?.enabled ? pwdTotp : undefined,
        },
        { withCredentials: true },
      );
      const revoked = r.data?.other_sessions_revoked || 0;
      toast.success(
        revoked > 0
          ? `Contraseña actualizada. Se cerraron ${revoked} sesiones adicionales.`
          : "Contraseña actualizada correctamente."
      );
      setPwdCurrent(""); setPwdNew(""); setPwdConfirm(""); setPwdTotp("");
    } catch (e) {
      const detail = e.response?.data?.detail;
      if (detail && typeof detail === "object") {
        if (detail.code === "TOTP_SETUP_REQUIRED") {
          toast.error("Activa la verificación en dos pasos (2FA) antes de cambiar tu contraseña.");
          return;
        }
        if (detail.code === "TOTP_INVALID" || detail.code === "TOTP_CODE_REQUIRED") {
          toast.error(detail.message || "Código 2FA inválido.");
          return;
        }
      }
      const msg = typeof detail === "string"
        ? detail
        : (detail?.message || "Error al cambiar la contraseña.");
      toast.error(msg);
    } finally {
      setPwdBusy(false);
    }
  };

  if (loading) return <div className="text-neutral-500">Cargando...</div>;

  return (
    <div data-testid="security-settings" className="space-y-6 max-w-2xl">
      <ProfileSectionTabs />
      <div>
        <h1 className="font-display text-3xl">Verificación en Dos Pasos</h1>
        <p className="text-neutral-500 text-sm mt-1">
          Protege tus retiros con un código generado por una app de autenticador (Google Authenticator, Authy, 1Password, etc.). Obligatorio para realizar retiros.
        </p>
      </div>

      {/* Status card */}
      <div className="tactile-card p-5">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3">
            {status?.enabled ? (
              <>
                <CheckCircle2 className="w-6 h-6 text-[#22C55E]" />
                <div>
                  <div className="text-white font-semibold" data-testid="security-status">2FA activado</div>
                  <div className="text-xs text-neutral-500">
                    Configurado el {status.setup_at ? new Date(status.setup_at).toLocaleDateString() : "—"} · {status.recovery_codes_remaining || 0} códigos de recuperación restantes
                  </div>
                </div>
              </>
            ) : (
              <>
                <ShieldAlert className="w-6 h-6 text-[#8B5CF6]" />
                <div>
                  <div className="text-white font-semibold" data-testid="security-status">2FA no configurado</div>
                  <div className="text-xs text-neutral-500">No podrás realizar retiros hasta activarlo.</div>
                </div>
              </>
            )}
          </div>
          {!status?.enabled && !setupData && (
            <Button data-testid="security-setup-btn" onClick={startSetup} disabled={busy}
              className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold h-10 px-4 uppercase tracking-wider text-xs">
              {busy ? "Cargando..." : "Activar 2FA"}
            </Button>
          )}
          {status?.enabled && (
            <div className="flex gap-2">
              <Button data-testid="security-regen-btn" onClick={() => setRegenModal(true)}
                className="rounded-none bg-transparent border border-white/15 hover:border-[#8B5CF6]/60 text-white h-10 px-3 uppercase tracking-wider text-xs">
                <RefreshCw className="w-3.5 h-3.5 mr-2" /> Regenerar códigos
              </Button>
              <Button data-testid="security-disable-btn" onClick={() => setDisableModal(true)}
                className="rounded-none bg-transparent border border-[#EF4444]/40 hover:bg-[#EF4444]/10 text-[#EF4444] h-10 px-3 uppercase tracking-wider text-xs">
                Desactivar
              </Button>
            </div>
          )}
        </div>
      </div>

      {/* Setup flow */}
      {setupData && (
        <div className="tactile-card p-6" data-testid="security-setup-panel">
          <h2 className="font-display text-xl mb-4">Paso 1: Escanea el QR</h2>
          <div className="flex flex-col sm:flex-row gap-6">
            <div className="bg-white p-3 rounded">
              <img src={setupData.qr_data_url} alt="QR 2FA" className="w-48 h-48" />
            </div>
            <div className="flex-1 space-y-3 text-sm">
              <div>
                <div className="micro-label text-neutral-500 mb-1">Apps recomendadas</div>
                <div className="text-neutral-300">Google Authenticator · Authy · 1Password · Bitwarden</div>
              </div>
              <div>
                <div className="micro-label text-neutral-500 mb-1">¿No puedes escanear? Pega este código:</div>
                <div className="flex items-center gap-2 font-mono text-xs bg-[#0a0a0a] border border-white/10 p-2">
                  <code className="flex-1 break-all" data-testid="security-manual-secret">{setupData.secret}</code>
                  <button onClick={() => copyText(setupData.secret)}><Copy className="w-3.5 h-3.5 text-neutral-400" /></button>
                </div>
              </div>
            </div>
          </div>

          <h2 className="font-display text-xl mt-6 mb-3">Paso 2: Confirma con el primer código</h2>
          <div className="flex gap-3 items-center">
            <Input data-testid="security-verify-input" maxLength={6} value={verifyCode}
              onChange={(e) => setVerifyCode(e.target.value.replace(/[^0-9]/g, ""))}
              placeholder="123456"
              className="rounded-none bg-[#0a0a0a] border-white/10 h-12 w-32 font-mono text-center text-xl tracking-widest" />
            <Button data-testid="security-verify-btn" onClick={verifySetup} disabled={busy || verifyCode.length !== 6}
              className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold h-12 px-6 uppercase tracking-wider text-xs">
              {busy ? "Verificando..." : "Activar"}
            </Button>
          </div>
        </div>
      )}

      {/* Recovery codes (shown after activation) */}
      {recoveryCodes && (
        <div className="border border-[#8B5CF6]/40 bg-[#8B5CF6]/5 p-5" data-testid="security-recovery-codes">
          <div className="flex items-start gap-3 mb-3">
            <AlertTriangle className="w-5 h-5 text-[#8B5CF6] mt-0.5" />
            <div>
              <div className="font-semibold text-[#8B5CF6]">Guarda estos códigos de recuperación</div>
              <div className="text-xs text-neutral-400 mt-1">
                Solo se muestran <strong>una vez</strong>. Úsalos para entrar si pierdes tu autenticador. Cada código sirve una sola vez.
              </div>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 font-mono text-sm">
            {recoveryCodes.map((c) => (
              <div key={c} className="bg-[#0a0a0a] border border-white/10 px-3 py-2 flex items-center justify-between">
                <code>{c}</code>
                <button onClick={() => copyText(c)}><Copy className="w-3 h-3 text-neutral-500" /></button>
              </div>
            ))}
          </div>
          <div className="flex justify-end mt-3 gap-2">
            <button onClick={() => copyText(recoveryCodes.join("\n"))} className="text-xs text-[#8B5CF6] underline">
              Copiar todos
            </button>
            <button onClick={() => setRecoveryCodes(null)} data-testid="security-codes-acknowledged" className="text-xs text-neutral-500 hover:text-white underline">
              Ya los guardé
            </button>
          </div>
        </div>
      )}

      {/* Disable modal */}
      <Dialog open={disableModal} onOpenChange={setDisableModal}>
        <DialogContent className="bg-[#0c0c0c] border border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Desactivar 2FA</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-neutral-400">
            Si desactivas 2FA, no podrás realizar retiros hasta volver a activarlo. Ingresa tu código actual para confirmar.
          </p>
          <Input data-testid="security-disable-input" value={disableCode}
            onChange={(e) => setDisableCode(e.target.value)} placeholder="Código 2FA o de recuperación"
            className="rounded-none bg-[#0a0a0a] border-white/10 h-12 font-mono" />
          <DialogFooter>
            <Button onClick={() => setDisableModal(false)} className="rounded-none bg-transparent border border-white/15 text-white">Cancelar</Button>
            <Button data-testid="security-disable-confirm" onClick={disable2FA} disabled={busy}
              className="rounded-none bg-[#EF4444] hover:bg-[#EF4444]/90 text-white font-bold">
              Desactivar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Regenerate codes modal */}
      <Dialog open={regenModal} onOpenChange={setRegenModal}>
        <DialogContent className="bg-[#0c0c0c] border border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Regenerar códigos de recuperación</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-neutral-400">Los códigos viejos quedarán invalidados.</p>
          <Input value={regenCode} onChange={(e) => setRegenCode(e.target.value)}
            placeholder="Código 2FA actual"
            className="rounded-none bg-[#0a0a0a] border-white/10 h-12 font-mono" />
          <DialogFooter>
            <Button onClick={() => setRegenModal(false)} className="rounded-none bg-transparent border border-white/15 text-white">Cancelar</Button>
            <Button onClick={regenerateCodes} disabled={busy}
              className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold">
              Regenerar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* iter55.30 — Password change (only for email/password accounts) */}
      {profile?.auth_provider === "password" ? (
        <div className="tactile-card p-5" data-testid="password-change-card">
          <div className="flex items-start gap-3 mb-5">
            <KeyRound className="w-6 h-6 text-[#8B5CF6] mt-0.5" />
            <div>
              <h2 className="font-display text-2xl">Cambiar contraseña</h2>
              <p className="text-neutral-500 text-sm mt-1">
                Al cambiarla se cerrarán todas tus otras sesiones activas. Recibirás una notificación por email.
              </p>
            </div>
          </div>
          {!status?.enabled && (
            <div className="border border-[#F59E0B]/40 bg-[#F59E0B]/5 p-3 mb-4 flex items-start gap-3" data-testid="pwd-needs-2fa-hint">
              <AlertTriangle className="w-4 h-4 text-[#F59E0B] mt-0.5 shrink-0" />
              <div className="text-xs text-[#F59E0B] leading-relaxed">
                Para cambiar tu contraseña primero debes activar la verificación en dos pasos (2FA) arriba.
                Esto protege tu cuenta contra cambios no autorizados.
              </div>
            </div>
          )}
          <div className="space-y-3 max-w-md">
            <div>
              <Label className="micro-label text-neutral-500">Contraseña actual</Label>
              <div className="relative">
                <Input
                  data-testid="pwd-current-input"
                  type={pwdShow ? "text" : "password"}
                  value={pwdCurrent}
                  onChange={(e) => setPwdCurrent(e.target.value)}
                  autoComplete="current-password"
                  disabled={!status?.enabled}
                  className="rounded-none bg-[#0a0a0a] border-white/10 h-11 mt-1 font-mono pr-10"
                />
                <button
                  type="button"
                  onClick={() => setPwdShow((s) => !s)}
                  data-testid="pwd-show-toggle"
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-neutral-500 hover:text-[#8B5CF6] mt-0.5"
                  aria-label={pwdShow ? "Ocultar contraseñas" : "Mostrar contraseñas"}
                >
                  {pwdShow ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">Nueva contraseña (mín. 8 caracteres)</Label>
              <Input
                data-testid="pwd-new-input"
                type={pwdShow ? "text" : "password"}
                value={pwdNew}
                onChange={(e) => setPwdNew(e.target.value)}
                autoComplete="new-password"
                disabled={!status?.enabled}
                className="rounded-none bg-[#0a0a0a] border-white/10 h-11 mt-1 font-mono"
              />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">Confirma la nueva contraseña</Label>
              <Input
                data-testid="pwd-confirm-input"
                type={pwdShow ? "text" : "password"}
                value={pwdConfirm}
                onChange={(e) => setPwdConfirm(e.target.value)}
                autoComplete="new-password"
                disabled={!status?.enabled}
                className="rounded-none bg-[#0a0a0a] border-white/10 h-11 mt-1 font-mono"
              />
              {pwdConfirm && pwdNew !== pwdConfirm && (
                <div className="text-xs text-[#EF4444] mt-1" data-testid="pwd-mismatch">
                  La confirmación no coincide.
                </div>
              )}
            </div>
            {status?.enabled && (
              <div>
                <Label className="micro-label text-neutral-500">Código 2FA actual (6 dígitos)</Label>
                <Input
                  data-testid="pwd-totp-input"
                  maxLength={6}
                  value={pwdTotp}
                  onChange={(e) => setPwdTotp(e.target.value.replace(/[^0-9]/g, ""))}
                  placeholder="123456"
                  className="rounded-none bg-[#0a0a0a] border-white/10 h-11 mt-1 font-mono w-32 tracking-widest text-center"
                />
              </div>
            )}
            <Button
              data-testid="pwd-submit-btn"
              onClick={submitPasswordChange}
              disabled={pwdBusy || !status?.enabled || !pwdCurrent || pwdNew.length < 8 || pwdNew !== pwdConfirm}
              className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold h-11 px-6 uppercase tracking-wider text-xs mt-2 disabled:bg-neutral-700"
            >
              {pwdBusy ? "Actualizando..." : "Cambiar contraseña"}
            </Button>
          </div>
        </div>
      ) : profile ? (
        <div className="tactile-card p-5 opacity-70" data-testid="password-change-google">
          <div className="flex items-start gap-3">
            <KeyRound className="w-5 h-5 text-neutral-500 mt-0.5" />
            <div>
              <h2 className="font-display text-xl">Cambiar contraseña</h2>
              <p className="text-neutral-500 text-sm mt-1">
                Tu cuenta usa inicio de sesión con <strong className="text-white">Google</strong>.
                Cambia tu contraseña desde tu cuenta de Google.
              </p>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
