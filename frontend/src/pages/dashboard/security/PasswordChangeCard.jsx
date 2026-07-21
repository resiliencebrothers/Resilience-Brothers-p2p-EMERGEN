import { Trans, useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AlertTriangle, Eye, EyeOff, KeyRound } from "lucide-react";

/**
 * iter55.30 — Password-change card, shown ONLY for email/password accounts.
 * If the profile is Google-linked, `GoogleAccountNotice` is rendered instead.
 */
export default function PasswordChangeCard({
  profile, status,
  pwd, setPwd,
  busy, onSubmit,
}) {
  if (profile?.auth_provider === "password") {
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
  if (profile) return <GoogleAccountNotice />;
  return null;
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

function GoogleAccountNotice() {
  const { t } = useTranslation();
  return (
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
  );
}
