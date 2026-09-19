import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AlertTriangle, Eye, EyeOff, KeyRound } from "lucide-react";

/**
 * iter55.30/iter280 — Tarjeta de contraseña del perfil.
 * - Con contraseña existente → formulario de CAMBIO (exige la actual).
 * - Sin contraseña (cuenta Google) → formulario de ESTABLECER la primera
 *   contraseña, sin campo "actual" (iter280).
 */
export default function PasswordChangeCard({
  profile, status,
  pwd, setPwd,
  busy, onSubmit, onSetSubmit,
}) {
  if (profile?.has_password) {
    return (
      <PasswordChangeForm
        status={status}
        pwd={pwd}
        setPwd={setPwd}
        busy={busy}
        onSubmit={onSubmit}
      />
    );
  }
  if (profile) {
    return (
      <PasswordSetForm
        status={status}
        pwd={pwd}
        setPwd={setPwd}
        busy={busy}
        onSubmit={onSetSubmit}
      />
    );
  }
  return null;
}

function PasswordSetForm({ status, pwd, setPwd, busy, onSubmit }) {
  const { t } = useTranslation();
  const disabled = !status?.enabled;
  const canSubmit =
    !busy &&
    status?.enabled &&
    pwd.new.length >= 8 &&
    pwd.new === pwd.confirm;
  return (
    <div className="tactile-card p-5" data-testid="password-set-card">
      <div className="flex items-start gap-3 mb-5">
        <KeyRound className="w-6 h-6 text-[#22C55E] mt-0.5" />
        <div>
          <h2 className="font-display text-2xl">{t("security.password.setTitle")}</h2>
          <p className="text-neutral-500 text-sm mt-1">{t("security.password.setBody")}</p>
        </div>
      </div>
      {!status?.enabled && (
        <div className="border border-[#F59E0B]/40 bg-[#F59E0B]/5 p-3 mb-4 flex items-start gap-3" data-testid="pwd-set-needs-2fa-hint">
          <AlertTriangle className="w-4 h-4 text-[#F59E0B] mt-0.5 shrink-0" />
          <div className="text-xs text-[#F59E0B] leading-relaxed">
            {t("security.password.needsTwofaHint")}
          </div>
        </div>
      )}
      <div className="space-y-3 max-w-md">
        <div>
          <Label className="micro-label text-neutral-500">{t("security.password.newLabel")}</Label>
          <div className="relative">
            <Input
              data-testid="pwd-set-new-input"
              type={pwd.show ? "text" : "password"}
              value={pwd.new}
              onChange={(e) => setPwd({ ...pwd, new: e.target.value })}
              autoComplete="new-password"
              disabled={disabled}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-11 mt-1 font-mono pr-10"
            />
            <button
              type="button"
              onClick={() => setPwd({ ...pwd, show: !pwd.show })}
              data-testid="pwd-set-show-toggle"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-neutral-500 hover:text-[#8B5CF6] mt-0.5"
              aria-label={pwd.show ? t("security.password.hidePasswords") : t("security.password.showPasswords")}
            >
              {pwd.show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
        </div>
        <div>
          <Label className="micro-label text-neutral-500">{t("security.password.confirmLabel")}</Label>
          <Input
            data-testid="pwd-set-confirm-input"
            type={pwd.show ? "text" : "password"}
            value={pwd.confirm}
            onChange={(e) => setPwd({ ...pwd, confirm: e.target.value })}
            autoComplete="new-password"
            disabled={disabled}
            className="rounded-none bg-[#0a0a0a] border-white/10 h-11 mt-1 font-mono"
          />
          {pwd.confirm && pwd.new !== pwd.confirm && (
            <div className="text-xs text-[#EF4444] mt-1" data-testid="pwd-set-mismatch">
              {t("security.password.mismatchInline")}
            </div>
          )}
        </div>
        {status?.enabled && (
          <div>
            <Label className="micro-label text-neutral-500">{t("security.password.totpLabel")}</Label>
            <Input
              data-testid="pwd-set-totp-input"
              maxLength={6}
              value={pwd.totp}
              onChange={(e) => setPwd({ ...pwd, totp: e.target.value.replace(/[^0-9]/g, "") })}
              placeholder={t("security.password.totpPlaceholder")}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-11 mt-1 font-mono w-32 tracking-widest text-center"
            />
          </div>
        )}
        <Button
          data-testid="pwd-set-submit-btn"
          onClick={onSubmit}
          disabled={!canSubmit}
          className="rounded-none bg-[#22C55E] hover:bg-[#4ADE80] text-black font-bold h-11 px-6 uppercase tracking-wider text-xs mt-2 disabled:bg-neutral-700 disabled:text-white"
        >
          {busy ? t("security.password.updating") : t("security.password.setSubmit")}
        </Button>
      </div>
    </div>
  );
}

function PasswordChangeForm({ status, pwd, setPwd, busy, onSubmit }) {
  const { t } = useTranslation();
  const disabled = !status?.enabled;
  const canSubmit =
    !busy &&
    status?.enabled &&
    pwd.current &&
    pwd.new.length >= 8 &&
    pwd.new === pwd.confirm;
  return (
    <div className="tactile-card p-5" data-testid="password-change-card">
      <div className="flex items-start gap-3 mb-5">
        <KeyRound className="w-6 h-6 text-[#8B5CF6] mt-0.5" />
        <div>
          <h2 className="font-display text-2xl">{t("security.password.title")}</h2>
          <p className="text-neutral-500 text-sm mt-1">{t("security.password.body")}</p>
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
              type={pwd.show ? "text" : "password"}
              value={pwd.current}
              onChange={(e) => setPwd({ ...pwd, current: e.target.value })}
              autoComplete="current-password"
              disabled={disabled}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-11 mt-1 font-mono pr-10"
            />
            <button
              type="button"
              onClick={() => setPwd({ ...pwd, show: !pwd.show })}
              data-testid="pwd-show-toggle"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-neutral-500 hover:text-[#8B5CF6] mt-0.5"
              aria-label={pwd.show ? t("security.password.hidePasswords") : t("security.password.showPasswords")}
            >
              {pwd.show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
        </div>
        <div>
          <Label className="micro-label text-neutral-500">{t("security.password.newLabel")}</Label>
          <Input
            data-testid="pwd-new-input"
            type={pwd.show ? "text" : "password"}
            value={pwd.new}
            onChange={(e) => setPwd({ ...pwd, new: e.target.value })}
            autoComplete="new-password"
            disabled={disabled}
            className="rounded-none bg-[#0a0a0a] border-white/10 h-11 mt-1 font-mono"
          />
        </div>
        <div>
          <Label className="micro-label text-neutral-500">{t("security.password.confirmLabel")}</Label>
          <Input
            data-testid="pwd-confirm-input"
            type={pwd.show ? "text" : "password"}
            value={pwd.confirm}
            onChange={(e) => setPwd({ ...pwd, confirm: e.target.value })}
            autoComplete="new-password"
            disabled={disabled}
            className="rounded-none bg-[#0a0a0a] border-white/10 h-11 mt-1 font-mono"
          />
          {pwd.confirm && pwd.new !== pwd.confirm && (
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
              value={pwd.totp}
              onChange={(e) => setPwd({ ...pwd, totp: e.target.value.replace(/[^0-9]/g, "") })}
              placeholder={t("security.password.totpPlaceholder")}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-11 mt-1 font-mono w-32 tracking-widest text-center"
            />
          </div>
        )}
        <Button
          data-testid="pwd-submit-btn"
          onClick={onSubmit}
          disabled={!canSubmit}
          className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold h-11 px-6 uppercase tracking-wider text-xs mt-2 disabled:bg-neutral-700"
        >
          {busy ? t("security.password.updating") : t("security.password.submit")}
        </Button>
      </div>
    </div>
  );
}

