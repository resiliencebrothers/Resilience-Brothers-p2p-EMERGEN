import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";
import CopyableText from "@/components/CopyableText";
import ProfileSectionTabs from "@/components/ProfileSectionTabs";
import {
  User, Mail, Phone, Globe, ShieldCheck, IdCard, Clock, CheckCircle2,
  AlertTriangle, Pencil,
} from "lucide-react";


/**
 * iter55.20 — Client "Mi Perfil".
 *
 * Central page grouping personal data, verification (KYC) and security (2FA)
 * so the client can review + update every piece of info they registered with:
 *  · Name / registration date (read-only)
 *  · Email → dual-notification change (code to new + alert to old)
 *  · Phone → 2FA-guarded change with admin approval
 *  · Country → free, but resets KYC to pending if was approved
 *  · Verification (link to /dashboard/kyc)
 *  · Security (link to /dashboard/security)
 */
export default function ProfileView() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [emailDialog, setEmailDialog] = useState(false);
  const [phoneDialog, setPhoneDialog] = useState(false);
  const [countryDialog, setCountryDialog] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/profile/me`, { withCredentials: true });
      setProfile(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Error al cargar perfil");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading || !profile) {
    return (
      <div className="p-8 text-neutral-500 text-sm" data-testid="profile-loading">
        Cargando perfil...
      </div>
    );
  }

  const kycBadge = KYC_BADGE[profile.kyc_status] || KYC_BADGE.not_started;

  return (
    <div className="space-y-6" data-testid="profile-view">
      <ProfileSectionTabs />
      <div>
        <h1 className="font-display text-3xl">Datos personales</h1>
        <p className="text-neutral-400 mt-2 text-sm max-w-2xl">
          Todos los datos con los que te registraste. Puedes actualizarlos si
          cambias de país, celular o email — solo pedimos verificación adicional
          para proteger tu cuenta.
        </p>
      </div>

      {/* --- Personal data card --- */}
      <section className="tactile-card p-6 space-y-4" data-testid="profile-personal">
        <div className="flex items-center gap-2 border-b border-white/5 pb-3">
          <User className="w-4 h-4 text-[#8B5CF6]" />
          <span className="micro-label text-neutral-500">Datos personales</span>
        </div>
        <PersonalRow icon={User} label="Nombre" value={profile.name || "—"} readOnly />
        <PersonalRow icon={Mail} label="Email" value={profile.email}
                     onEdit={() => setEmailDialog(true)}
                     pending={profile.pending_email_change ? "Pendiente confirmar código" : null}
                     testid="profile-email-row" />
        <PersonalRow icon={Phone} label="Teléfono"
                     value={profile.phone || "No registrado"}
                     verified={profile.phone_verified}
                     onEdit={() => setPhoneDialog(true)}
                     pending={profile.pending_phone_change ? "Pendiente revisión admin" : null}
                     testid="profile-phone-row" />
        <PersonalRow icon={Globe} label="País" value={profile.country || "—"}
                     onEdit={() => setCountryDialog(true)}
                     testid="profile-country-row" />
        <PersonalRow icon={Clock} label="Cuenta creada"
                     value={new Date(profile.created_at).toLocaleDateString("es")}
                     readOnly />
      </section>

      {/* --- KYC card --- */}
      <section className="tactile-card p-6 space-y-3" data-testid="profile-kyc">
        <div className="flex items-center justify-between gap-2 border-b border-white/5 pb-3">
          <div className="flex items-center gap-2">
            <IdCard className="w-4 h-4 text-[#8B5CF6]" />
            <span className="micro-label text-neutral-500">Verificación de identidad</span>
          </div>
          <span className={`text-[0.65rem] uppercase tracking-widest border px-2 py-0.5 ${kycBadge.className}`}>
            {kycBadge.label}
          </span>
        </div>
        <p className="text-xs text-neutral-400 leading-relaxed">
          Sube tus documentos para desbloquear límites más altos y operar sin
          fricciones. La revisión suele tomar entre 30 min y 24 h.
        </p>
        <Button
          onClick={() => navigate("/dashboard/kyc")}
          data-testid="profile-open-kyc"
          className="rounded-none bg-transparent border border-white/15 hover:border-[#8B5CF6]/60 hover:bg-[#8B5CF6]/5 text-white h-9 px-4 font-mono text-xs uppercase tracking-wider"
        >
          Abrir verificación
        </Button>
      </section>

      {/* --- Security card --- */}
      <section className="tactile-card p-6 space-y-3" data-testid="profile-security">
        <div className="flex items-center justify-between gap-2 border-b border-white/5 pb-3">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-[#8B5CF6]" />
            <span className="micro-label text-neutral-500">Seguridad</span>
          </div>
          <span className={`text-[0.65rem] uppercase tracking-widest border px-2 py-0.5 ${
            profile.twofa_enabled
              ? "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30"
              : "bg-[#8B5CF6]/10 text-[#8B5CF6] border-[#8B5CF6]/30"
          }`}>
            {profile.twofa_enabled ? "2FA activo" : "2FA no configurado"}
          </span>
        </div>
        <p className="text-xs text-neutral-400 leading-relaxed">
          Gestiona tu autenticación de dos factores, cambia tu contraseña y
          revisa las sesiones abiertas.
        </p>
        <Button
          onClick={() => navigate("/dashboard/security")}
          data-testid="profile-open-security"
          className="rounded-none bg-transparent border border-white/15 hover:border-[#8B5CF6]/60 hover:bg-[#8B5CF6]/5 text-white h-9 px-4 font-mono text-xs uppercase tracking-wider"
        >
          Abrir seguridad
        </Button>
      </section>

      {/* --- Change dialogs --- */}
      <EmailChangeDialog
        open={emailDialog}
        onClose={() => { setEmailDialog(false); load(); }}
        currentEmail={profile.email}
        navigate={navigate}
      />
      <PhoneChangeDialog
        open={phoneDialog}
        onClose={() => { setPhoneDialog(false); load(); }}
        currentPhone={profile.phone}
        pending={profile.pending_phone_change}
        navigate={navigate}
      />
      <CountryChangeDialog
        open={countryDialog}
        onClose={() => { setCountryDialog(false); load(); }}
        currentCountry={profile.country}
        kycStatus={profile.kyc_status}
      />
    </div>
  );
}


const KYC_BADGE = {
  not_started: { label: "No iniciada", className: "bg-neutral-500/10 text-neutral-400 border-neutral-500/30" },
  pending_review: { label: "En revisión", className: "bg-[#8B5CF6]/10 text-[#8B5CF6] border-[#8B5CF6]/30" },
  approved: { label: "Verificada", className: "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30" },
  rejected: { label: "Rechazada", className: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30" },
};


function PersonalRow({ icon: Icon, label, value, onEdit, readOnly, verified, pending, testid }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2" data-testid={testid}>
      <div className="flex items-center gap-3 min-w-0 flex-1">
        <Icon className="w-4 h-4 text-neutral-500 flex-shrink-0" />
        <div className="min-w-0">
          <div className="text-[0.65rem] uppercase tracking-widest text-neutral-500">{label}</div>
          <div className="text-sm text-white font-mono truncate flex items-center gap-2">
            <span className="truncate">{value}</span>
            {verified && <CheckCircle2 className="w-3.5 h-3.5 text-[#22C55E] flex-shrink-0" />}
          </div>
          {pending && (
            <div className="text-[0.65rem] text-[#8B5CF6] mt-0.5 flex items-center gap-1">
              <AlertTriangle className="w-2.5 h-2.5" /> {pending}
            </div>
          )}
        </div>
      </div>
      {!readOnly && onEdit && (
        <button
          type="button"
          onClick={onEdit}
          data-testid={`${testid}-edit`}
          className="flex-shrink-0 text-[0.65rem] uppercase tracking-widest text-[#8B5CF6] hover:text-[#A78BFA] border border-[#8B5CF6]/40 hover:border-[#8B5CF6] px-3 py-1.5 flex items-center gap-1"
        >
          <Pencil className="w-3 h-3" /> Cambiar
        </button>
      )}
    </div>
  );
}


// ============================================================
// Email change dialog — 2-step: request code + confirm code
// ============================================================
function EmailChangeDialog({ open, onClose, currentEmail, navigate }) {
  const [step, setStep] = useState(1);
  const [newEmail, setNewEmail] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [totpCode, setTotpCode] = useState("");
  const [maskedTarget, setMaskedTarget] = useState("");

  useEffect(() => {
    if (open) { setStep(1); setNewEmail(""); setCode(""); setTotpCode(""); setMaskedTarget(""); }
  }, [open]);

  const requestCode = async () => {
    if (!newEmail || !newEmail.includes("@")) return toast.error("Email inválido");
    if (!totpCode || totpCode.length < 6) return toast.error("Ingresa tu código 2FA");
    setBusy(true);
    try {
      const r = await axios.post(`${API}/profile/email/request-change`, {
        new_email: newEmail.trim().toLowerCase(),
        totp_code: totpCode.trim(),
      }, { withCredentials: true });
      setMaskedTarget(r.data.sent_to_masked || "");
      setStep(2);
      toast.success("Código enviado. Revisa tu email nuevo.");
    } catch (e) {
      if (!handleTotpError(e, navigate)) {
        toast.error(e?.response?.data?.detail || "Error al solicitar cambio");
      }
    } finally { setBusy(false); }
  };

  const confirmCode = async () => {
    if (!code || code.length !== 6) return toast.error("Ingresa el código de 6 dígitos");
    setBusy(true);
    try {
      await axios.post(`${API}/profile/email/confirm-change`, {
        code: code.trim(),
      }, { withCredentials: true });
      toast.success("Email actualizado ✓");
      onClose();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Código incorrecto");
    } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="bg-[#1A1730] border border-white/10 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto" data-testid="email-change-dialog">
        <DialogHeader>
          <DialogTitle className="font-display text-xl">Cambiar email</DialogTitle>
        </DialogHeader>
        {step === 1 ? (
          <div className="space-y-4">
            <p className="text-xs text-neutral-400 leading-relaxed">
              Enviaremos un código de 6 dígitos al email nuevo + un aviso al
              actual ({currentEmail}) para que puedas revertir si alguien intenta
              secuestrar tu cuenta.
            </p>
            <div>
              <Label className="micro-label text-neutral-500">Email nuevo</Label>
              <Input value={newEmail} onChange={(e) => setNewEmail(e.target.value)}
                     data-testid="email-change-new-input"
                     placeholder="tu.nuevo@email.com"
                     className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-11" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">Código 2FA (o recuperación)</Label>
              <Input value={totpCode} onChange={(e) => setTotpCode(e.target.value)}
                     data-testid="email-change-totp-input"
                     placeholder="123456"
                     className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-11 font-mono" />
            </div>
            <Button onClick={requestCode} disabled={busy}
                    data-testid="email-change-send-btn"
                    className="w-full rounded-none bg-[#8B5CF6] hover:bg-[#8B5CF6]/90 text-white h-11 font-mono uppercase tracking-wider">
              {busy ? "Enviando..." : "Enviar código"}
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            <p className="text-xs text-neutral-400 leading-relaxed">
              Enviamos un código a <strong className="text-white font-mono">{maskedTarget}</strong>.
              Ingrésalo abajo para confirmar el cambio.
            </p>
            <div>
              <Label className="micro-label text-neutral-500">Código de 6 dígitos</Label>
              <Input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                     maxLength={6} inputMode="numeric" pattern="[0-9]{6}"
                     data-testid="email-change-code-input"
                     placeholder="000000"
                     className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-11 font-mono text-center text-xl tracking-widest" />
            </div>
            <div className="flex gap-2">
              <Button onClick={() => setStep(1)} disabled={busy}
                      className="flex-1 rounded-none bg-transparent border border-white/15 text-white h-11 font-mono uppercase tracking-wider">
                Volver
              </Button>
              <Button onClick={confirmCode} disabled={busy}
                      data-testid="email-change-confirm-btn"
                      className="flex-1 rounded-none bg-[#22C55E] hover:bg-[#22C55E]/90 text-black h-11 font-mono uppercase tracking-wider">
                {busy ? "Confirmando..." : "Confirmar"}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}


// ============================================================
// Phone change dialog — sends to admin review queue
// ============================================================
function PhoneChangeDialog({ open, onClose, currentPhone, pending, navigate }) {
  const [newPhone, setNewPhone] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) { setNewPhone(""); setTotpCode(""); }
  }, [open]);

  const submit = async () => {
    if (!newPhone || newPhone.length < 6) return toast.error("Teléfono inválido");
    if (!totpCode || totpCode.length < 6) return toast.error("Ingresa tu código 2FA");
    setBusy(true);
    try {
      await axios.post(`${API}/profile/phone/request-change`, {
        new_phone: newPhone.trim(),
        totp_code: totpCode.trim(),
      }, { withCredentials: true });
      toast.success("Solicitud enviada. Espera aprobación del equipo.");
      onClose();
    } catch (e) {
      if (!handleTotpError(e, navigate)) {
        toast.error(e?.response?.data?.detail || "Error al solicitar cambio");
      }
    } finally { setBusy(false); }
  };

  const cancelPending = async () => {
    setBusy(true);
    try {
      await axios.delete(`${API}/profile/phone/pending`, { withCredentials: true });
      toast.success("Solicitud cancelada");
      onClose();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Error al cancelar");
    } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="bg-[#1A1730] border border-white/10 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto" data-testid="phone-change-dialog">
        <DialogHeader>
          <DialogTitle className="font-display text-xl">Cambiar teléfono</DialogTitle>
        </DialogHeader>
        {pending ? (
          <div className="space-y-3">
            <div className="border border-[#8B5CF6]/40 bg-[#8B5CF6]/5 p-4">
              <div className="micro-label text-[#8B5CF6] mb-2">Solicitud pendiente</div>
              <div className="text-xs text-neutral-400">
                Ya tienes una solicitud de cambio a <strong className="text-white font-mono">{pending.new_phone_masked}</strong>.
                El equipo la revisará y aprobará manualmente.
              </div>
            </div>
            <Button onClick={cancelPending} disabled={busy}
                    data-testid="phone-cancel-pending-btn"
                    className="w-full rounded-none bg-transparent border border-[#EF4444]/40 hover:bg-[#EF4444]/10 text-[#EF4444] h-11 font-mono uppercase tracking-wider">
              Cancelar solicitud
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            <p className="text-xs text-neutral-400 leading-relaxed">
              Actual: <strong className="text-white font-mono">{currentPhone || "no registrado"}</strong>.
              El equipo verificará el nuevo número antes de aplicarlo — igual que
              en tu registro inicial.
            </p>
            <div>
              <Label className="micro-label text-neutral-500">Teléfono nuevo (con código de país)</Label>
              <Input value={newPhone} onChange={(e) => setNewPhone(e.target.value)}
                     data-testid="phone-change-new-input"
                     placeholder="+53 5555 9999"
                     className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-11 font-mono" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">Código 2FA (o recuperación)</Label>
              <Input value={totpCode} onChange={(e) => setTotpCode(e.target.value)}
                     data-testid="phone-change-totp-input"
                     placeholder="123456"
                     className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-11 font-mono" />
            </div>
            <Button onClick={submit} disabled={busy}
                    data-testid="phone-change-submit-btn"
                    className="w-full rounded-none bg-[#8B5CF6] hover:bg-[#8B5CF6]/90 text-white h-11 font-mono uppercase tracking-wider">
              {busy ? "Enviando..." : "Solicitar cambio"}
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}


// ============================================================
// Country change dialog — frictionless + KYC awareness
// ============================================================
function CountryChangeDialog({ open, onClose, currentCountry, kycStatus }) {
  const [newCountry, setNewCountry] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (open) setNewCountry(""); }, [open]);

  const submit = async () => {
    if (!newCountry || newCountry.trim().length < 2) return toast.error("País inválido");
    setBusy(true);
    try {
      const r = await axios.post(`${API}/profile/country/change`, {
        new_country: newCountry.trim(),
      }, { withCredentials: true });
      if (r.data.kyc_reset) {
        toast.warning("País actualizado. Tu KYC volvió a estado 'en revisión'.");
      } else {
        toast.success("País actualizado ✓");
      }
      onClose();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Error al cambiar país");
    } finally { setBusy(false); }
  };

  const willResetKyc = kycStatus === "approved";

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="bg-[#1A1730] border border-white/10 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto" data-testid="country-change-dialog">
        <DialogHeader>
          <DialogTitle className="font-display text-xl">Cambiar país</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <p className="text-xs text-neutral-400 leading-relaxed">
            Actual: <strong className="text-white font-mono">{currentCountry || "—"}</strong>.
            Puedes actualizarlo cuando cambies de residencia.
          </p>
          {willResetKyc && (
            <div className="border border-[#8B5CF6]/40 bg-[#8B5CF6]/5 p-3">
              <div className="micro-label text-[#8B5CF6] mb-1 flex items-center gap-1">
                <AlertTriangle className="w-3 h-3" /> Impacto en verificación
              </div>
              <p className="text-[0.7rem] text-neutral-400 leading-relaxed">
                Tu KYC está aprobado. Al cambiar de país volverá a
                <strong className="text-white"> &ldquo;En revisión&rdquo;</strong> para que el equipo
                confirme los documentos en la nueva jurisdicción.
              </p>
            </div>
          )}
          <div>
            <Label className="micro-label text-neutral-500">País nuevo</Label>
            <Input value={newCountry} onChange={(e) => setNewCountry(e.target.value)}
                   data-testid="country-change-new-input"
                   placeholder="Ej. Cuba, España, México..."
                   className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-11" />
          </div>
          <Button onClick={submit} disabled={busy}
                  data-testid="country-change-submit-btn"
                  className="w-full rounded-none bg-[#8B5CF6] hover:bg-[#8B5CF6]/90 text-white h-11 font-mono uppercase tracking-wider">
            {busy ? "Guardando..." : "Guardar"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
