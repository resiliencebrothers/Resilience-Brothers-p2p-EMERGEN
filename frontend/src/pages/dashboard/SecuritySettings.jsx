import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useTranslation, Trans } from "react-i18next";
import { API } from "@/App";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Shield, CheckCircle2, ShieldAlert, Copy, RefreshCw, AlertTriangle, KeyRound, Eye, EyeOff } from "lucide-react";
import ProfileSectionTabs from "@/components/ProfileSectionTabs";

export default function SecuritySettings() {
  const { t } = useTranslation();
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

  const loadStatus = useCallback(async () => {
    try {
      const [statusRes, profileRes] = await Promise.all([
        axios.get(`${API}/me/2fa/status`, { withCredentials: true }),
        axios.get(`${API}/profile/me`, { withCredentials: true }),
      ]);
      setStatus(statusRes.data);
      setProfile(profileRes.data);
    } catch (e) {
      toast.error(t("security.loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);
  useEffect(() => { loadStatus(); }, [loadStatus]);

  const startSetup = async () => {
    setBusy(true);
    try {
      const r = await axios.post(`${API}/me/2fa/setup`, {}, { withCredentials: true });
      setSetupData(r.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || t("security.setupError"));
    } finally {
      setBusy(false);
    }
  };

  const verifySetup = async () => {
    if (verifyCode.length !== 6) return toast.error(t("security.enterSixDigits"));
    setBusy(true);
    try {
      const r = await axios.post(`${API}/me/2fa/verify-setup`, { code: verifyCode }, { withCredentials: true });
      setRecoveryCodes(r.data.recovery_codes);
      setSetupData(null);
      setVerifyCode("");
      toast.success(t("security.activated"));
      await loadStatus();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("security.invalidCode"));
    } finally {
      setBusy(false);
    }
  };

  const disable2FA = async () => {
    if (!disableCode) return toast.error(t("security.enterCurrentTotp"));
    setBusy(true);
    try {
      await axios.post(`${API}/me/2fa/disable`, { code: disableCode }, { withCredentials: true });
      toast.success(t("security.disabled"));
      setDisableModal(false); setDisableCode("");
      await loadStatus();
    } catch (e) {
      toast.error(e.response?.data?.detail?.message || t("security.invalidCode"));
    } finally {
      setBusy(false);
    }
  };

  const regenerateCodes = async () => {
    if (!regenCode) return toast.error(t("security.enterCurrentTotp"));
    setBusy(true);
    try {
      const r = await axios.post(`${API}/me/2fa/regenerate-recovery-codes`, { code: regenCode }, { withCredentials: true });
      setRecoveryCodes(r.data.recovery_codes);
      setRegenModal(false); setRegenCode("");
      toast.success(t("security.codesRegenerated"));
      await loadStatus();
    } catch (e) {
      toast.error(e.response?.data?.detail?.message || t("security.invalidCode"));
    } finally {
      setBusy(false);
    }
  };

  const copyText = (text) => {
    navigator.clipboard.writeText(text);
    toast.success(t("security.copied"));
  };

  const submitPasswordChange = async () => {
    if (pwdNew.length < 8) {
      return toast.error(t("security.password.tooShort"));
    }
    if (pwdNew !== pwdConfirm) {
      return toast.error(t("security.password.mismatch"));
    }
    if (pwdCurrent === pwdNew) {
      return toast.error(t("security.password.mustDiffer"));
    }
    if (status?.enabled && pwdTotp.length !== 6) {
      return toast.error(t("security.password.enterTotp"));
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
          ? t("security.password.updatedWithSessions", { count: revoked })
          : t("security.password.updated")
      );
      setPwdCurrent(""); setPwdNew(""); setPwdConfirm(""); setPwdTotp("");
    } catch (e) {
      const detail = e.response?.data?.detail;
      if (detail && typeof detail === "object") {
        if (detail.code === "TOTP_SETUP_REQUIRED") {
          toast.error(t("security.password.setupRequired"));
          return;
        }
        if (detail.code === "TOTP_INVALID" || detail.code === "TOTP_CODE_REQUIRED") {
          toast.error(detail.message || t("security.password.totpInvalid"));
          return;
        }
      }
      const msg = typeof detail === "string"
        ? detail
        : (detail?.message || t("security.password.updateError"));
      toast.error(msg);
    } finally {
      setPwdBusy(false);
    }
  };

  if (loading) return <div className="text-neutral-500">{t("security.loading")}</div>;

  return (
    <div data-testid="security-settings" className="space-y-6 max-w-2xl">
      <ProfileSectionTabs />
      <div>
        <h1 className="font-display text-3xl">{t("security.title")}</h1>
        <p className="text-neutral-500 text-sm mt-1">
          {t("security.subtitle")}
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
                  <div className="text-white font-semibold" data-testid="security-status">{t("security.statusOn")}</div>
                  <div className="text-xs text-neutral-500">
                    {t("security.statusOnDetails", {
                      date: status.setup_at ? new Date(status.setup_at).toLocaleDateString() : "—",
                      count: status.recovery_codes_remaining || 0,
                    })}
                  </div>
                </div>
              </>
            ) : (
              <>
                <ShieldAlert className="w-6 h-6 text-[#8B5CF6]" />
                <div>
                  <div className="text-white font-semibold" data-testid="security-status">{t("security.statusOff")}</div>
                  <div className="text-xs text-neutral-500">{t("security.statusOffHint")}</div>
                </div>
              </>
            )}
          </div>
          {!status?.enabled && !setupData && (
            <Button data-testid="security-setup-btn" onClick={startSetup} disabled={busy}
              className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold h-10 px-4 uppercase tracking-wider text-xs">
              {busy ? t("security.buttonLoading") : t("security.activate2fa")}
            </Button>
          )}
          {status?.enabled && (
            <div className="flex gap-2">
              <Button data-testid="security-regen-btn" onClick={() => setRegenModal(true)}
                className="rounded-none bg-transparent border border-white/15 hover:border-[#8B5CF6]/60 text-white h-10 px-3 uppercase tracking-wider text-xs">
                <RefreshCw className="w-3.5 h-3.5 mr-2" /> {t("security.regenerateCodes")}
              </Button>
              <Button data-testid="security-disable-btn" onClick={() => setDisableModal(true)}
                className="rounded-none bg-transparent border border-[#EF4444]/40 hover:bg-[#EF4444]/10 text-[#EF4444] h-10 px-3 uppercase tracking-wider text-xs">
                {t("security.deactivate")}
              </Button>
            </div>
          )}
        </div>
      </div>

      {/* Setup flow */}
      {setupData && (
        <div className="tactile-card p-6" data-testid="security-setup-panel">
          <h2 className="font-display text-xl mb-4">{t("security.setup.step1")}</h2>
          <div className="flex flex-col sm:flex-row gap-6">
            <div className="bg-white p-3 rounded">
              <img src={setupData.qr_data_url} alt={t("security.setup.qrAlt")} className="w-48 h-48" />
            </div>
            <div className="flex-1 space-y-3 text-sm">
              <div>
                <div className="micro-label text-neutral-500 mb-1">{t("security.setup.recommendedApps")}</div>
                <div className="text-neutral-300">{t("security.setup.recommendedAppsValue")}</div>
              </div>
              <div>
                <div className="micro-label text-neutral-500 mb-1">{t("security.setup.cantScan")}</div>
                <div className="flex items-center gap-2 font-mono text-xs bg-[#0a0a0a] border border-white/10 p-2">
                  <code className="flex-1 break-all" data-testid="security-manual-secret">{setupData.secret}</code>
                  <button onClick={() => copyText(setupData.secret)}><Copy className="w-3.5 h-3.5 text-neutral-400" /></button>
                </div>
              </div>
            </div>
          </div>

          <h2 className="font-display text-xl mt-6 mb-3">{t("security.setup.step2")}</h2>
          <div className="flex gap-3 items-center">
            <Input data-testid="security-verify-input" maxLength={6} value={verifyCode}
              onChange={(e) => setVerifyCode(e.target.value.replace(/[^0-9]/g, ""))}
              placeholder={t("security.setup.verifyPlaceholder")}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-12 w-32 font-mono text-center text-xl tracking-widest" />
            <Button data-testid="security-verify-btn" onClick={verifySetup} disabled={busy || verifyCode.length !== 6}
              className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold h-12 px-6 uppercase tracking-wider text-xs">
              {busy ? t("security.setup.verifying") : t("security.setup.activate")}
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
              <div className="font-semibold text-[#8B5CF6]">{t("security.recovery.title")}</div>
              <div className="text-xs text-neutral-400 mt-1">
                <Trans i18nKey="security.recovery.warning" components={{ 1: <strong /> }} />
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
              {t("security.recovery.copyAll")}
            </button>
            <button onClick={() => setRecoveryCodes(null)} data-testid="security-codes-acknowledged" className="text-xs text-neutral-500 hover:text-white underline">
              {t("security.recovery.acknowledged")}
            </button>
          </div>
        </div>
      )}

      {/* Disable modal */}
      <Dialog open={disableModal} onOpenChange={setDisableModal}>
        <DialogContent className="bg-[#0c0c0c] border border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("security.disableDialog.title")}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-neutral-400">
            {t("security.disableDialog.body")}
          </p>
          <Input data-testid="security-disable-input" value={disableCode}
            onChange={(e) => setDisableCode(e.target.value)} placeholder={t("security.disableDialog.placeholder")}
            className="rounded-none bg-[#0a0a0a] border-white/10 h-12 font-mono" />
          <DialogFooter>
            <Button onClick={() => setDisableModal(false)} className="rounded-none bg-transparent border border-white/15 text-white">{t("security.disableDialog.cancel")}</Button>
            <Button data-testid="security-disable-confirm" onClick={disable2FA} disabled={busy}
              className="rounded-none bg-[#EF4444] hover:bg-[#EF4444]/90 text-white font-bold">
              {t("security.disableDialog.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Regenerate codes modal */}
      <Dialog open={regenModal} onOpenChange={setRegenModal}>
        <DialogContent className="bg-[#0c0c0c] border border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("security.regenDialog.title")}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-neutral-400">{t("security.regenDialog.body")}</p>
          <Input value={regenCode} onChange={(e) => setRegenCode(e.target.value)}
            placeholder={t("security.regenDialog.placeholder")}
            className="rounded-none bg-[#0a0a0a] border-white/10 h-12 font-mono" />
          <DialogFooter>
            <Button onClick={() => setRegenModal(false)} className="rounded-none bg-transparent border border-white/15 text-white">{t("security.regenDialog.cancel")}</Button>
            <Button onClick={regenerateCodes} disabled={busy}
              className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold">
              {t("security.regenDialog.regenerate")}
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
              <h2 className="font-display text-2xl">{t("security.password.title")}</h2>
              <p className="text-neutral-500 text-sm mt-1">
                {t("security.password.body")}
              </p>
            </div>
          </div>
          {!status?.enabled && (
            <div className="border border-[#F59E0B]/40 bg-[#F59E0B]/5 p-3 mb-4 flex items-start gap-3" data-testid="pwd-needs-2fa-hint">
              <AlertTriangle className="w-4 h-4 text-[#F59E0B] mt-0.5 shrink-0" />
              <div className="text-xs text-[#F59E0B] leading-relaxed">
                {t("security.password.needsTwofaHint")}
              </div>
            </div>
          )}
          <div className="space-y-3 max-w-md">
            <div>
              <Label className="micro-label text-neutral-500">{t("security.password.currentLabel")}</Label>
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
                  aria-label={pwdShow ? t("security.password.hidePasswords") : t("security.password.showPasswords")}
                >
                  {pwdShow ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("security.password.newLabel")}</Label>
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
              <Label className="micro-label text-neutral-500">{t("security.password.confirmLabel")}</Label>
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
                  {t("security.password.mismatchInline")}
                </div>
              )}
            </div>
            {status?.enabled && (
              <div>
                <Label className="micro-label text-neutral-500">{t("security.password.totpLabel")}</Label>
                <Input
                  data-testid="pwd-totp-input"
                  maxLength={6}
                  value={pwdTotp}
                  onChange={(e) => setPwdTotp(e.target.value.replace(/[^0-9]/g, ""))}
                  placeholder={t("security.password.totpPlaceholder")}
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
              {pwdBusy ? t("security.password.updating") : t("security.password.submit")}
            </Button>
          </div>
        </div>
      ) : profile ? (
        <div className="tactile-card p-5 opacity-70" data-testid="password-change-google">
          <div className="flex items-start gap-3">
            <KeyRound className="w-5 h-5 text-neutral-500 mt-0.5" />
            <div>
              <h2 className="font-display text-xl">{t("security.password.googleTitle")}</h2>
              <p className="text-neutral-500 text-sm mt-1">
                <Trans i18nKey="security.password.googleBody" components={{ 1: <strong className="text-white" /> }} />
              </p>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
