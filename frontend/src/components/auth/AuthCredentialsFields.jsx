import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useTranslation } from "react-i18next";
import { Mail, Lock, User as UserIcon, Eye, EyeOff, Phone } from "lucide-react";

export function AuthCredentialsFields({
  mode,
  name, setName,
  phone, setPhone,
  email, setEmail,
  password, setPassword,
  confirmPassword, setConfirmPassword,
  showPassword, setShowPassword,
  nameInputRef,
  onEmailChange,
}) {
  const { t } = useTranslation();
  const isRegister = mode === "register";
  const isForgot = mode === "forgot";

  return (
    <>
      {isRegister && (
        <div>
          <Label className="micro-label text-neutral-500">{t("auth.fields.name")}</Label>
          <div className="relative mt-1">
            <UserIcon className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
            <Input
              ref={nameInputRef}
              data-testid="auth-name-input"
              required
              minLength={2}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("auth.fields.namePlaceholder")}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-11 pl-9"
            />
          </div>
        </div>
      )}

      {isRegister && (
        <div>
          <Label className="micro-label text-neutral-500">{t("auth.fields.phone")}</Label>
          <div className="relative mt-1">
            <Phone className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
            <Input
              data-testid="auth-phone-input"
              type="tel"
              required
              inputMode="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder={t("auth.fields.phonePlaceholder")}
              autoComplete="tel"
              className="rounded-none bg-[#0a0a0a] border-white/10 h-11 pl-9 font-mono"
            />
          </div>
          <p className="text-[0.65rem] text-neutral-600 mt-1">
            {t("auth.fields.phoneHint")}
          </p>
        </div>
      )}

      <div>
        <Label className="micro-label text-neutral-500">{t("auth.fields.email")}</Label>
        <div className="relative mt-1">
          <Mail className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
          <Input
            data-testid="auth-email-input"
            type="email"
            required
            value={email}
            onChange={(e) => { setEmail(e.target.value); onEmailChange?.(); }}
            placeholder={t("auth.fields.emailPlaceholder")}
            autoComplete="email"
            className="rounded-none bg-[#0a0a0a] border-white/10 h-11 pl-9"
          />
        </div>
      </div>

      {!isForgot && (
        <div>
          <Label className="micro-label text-neutral-500">{t("auth.fields.password")}</Label>
          <div className="relative mt-1">
            <Lock className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
            <Input
              data-testid="auth-password-input"
              type={showPassword ? "text" : "password"}
              required
              minLength={isRegister ? 8 : 1}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={isRegister ? t("auth.fields.passwordPlaceholderRegister") : t("auth.fields.passwordPlaceholderLogin")}
              autoComplete={isRegister ? "new-password" : "current-password"}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-11 pl-9 pr-10"
            />
            <button
              type="button"
              data-testid="auth-toggle-password-visibility"
              onClick={() => setShowPassword((v) => !v)}
              aria-label={showPassword ? t("auth.fields.hidePassword") : t("auth.fields.showPassword")}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-neutral-500 hover:text-[#8B5CF6] transition-colors"
            >
              {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
        </div>
      )}

      {isRegister && (
        <div>
          <Label className="micro-label text-neutral-500">{t("auth.fields.confirmPassword")}</Label>
          <div className="relative mt-1">
            <Lock className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
            <Input
              data-testid="auth-confirm-password-input"
              type={showPassword ? "text" : "password"}
              required
              minLength={8}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder={t("auth.fields.confirmPlaceholder")}
              autoComplete="new-password"
              className={`rounded-none bg-[#0a0a0a] h-11 pl-9 ${
                confirmPassword && confirmPassword !== password
                  ? "border-[#EF4444]"
                  : "border-white/10"
              }`}
            />
          </div>
          {confirmPassword && confirmPassword !== password && (
            <p data-testid="auth-password-mismatch" className="text-[0.7rem] text-[#EF4444] mt-1">
              {t("auth.fields.passwordMismatch")}
            </p>
          )}
        </div>
      )}
    </>
  );
}
