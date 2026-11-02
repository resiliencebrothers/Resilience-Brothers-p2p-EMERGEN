import { useTranslation } from "react-i18next";

export function AuthNotice({ notice, onSwitchToRegister, onUseGoogle, onSetPassword }) {
  const { t } = useTranslation();
  if (!notice) return null;
  return (
    <div
      data-testid="auth-notice"
      className={`border-l-2 px-3 py-3 text-xs ${
        notice.kind === "register"
          ? "border-[#8B5CF6] bg-[#8B5CF6]/5 text-[#FEF3C7]"
          : "border-[#3B82F6] bg-[#3B82F6]/5 text-[#DBEAFE]"
      }`}
    >
      <p className="leading-relaxed mb-2">{notice.message}</p>
      {notice.kind === "register" && (
        <button
          type="button"
          data-testid="auth-notice-register-btn"
          onClick={onSwitchToRegister}
          className="text-[#8B5CF6] hover:text-[#A78BFA] font-semibold underline underline-offset-4"
        >
          {t("auth.notice.registerCta")}
        </button>
      )}
      {notice.kind === "google" && (
        <div className="flex flex-col gap-2">
          <button
            type="button"
            data-testid="auth-notice-google-btn"
            onClick={onUseGoogle}
            className="text-[#60A5FA] hover:text-[#93C5FD] font-semibold underline underline-offset-4 self-start"
          >
            {t("auth.notice.googleCta")}
          </button>
          <button
            type="button"
            data-testid="auth-notice-google-setpw-btn"
            onClick={onSetPassword}
            className="text-[#A78BFA] hover:text-[#C4B5FD] font-semibold underline underline-offset-4 self-start"
          >
            {t("auth.notice.googleSetPasswordCta")}
          </button>
        </div>
      )}
    </div>
  );
}
