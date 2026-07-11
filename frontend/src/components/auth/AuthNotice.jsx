export function AuthNotice({ notice, onSwitchToRegister, onUseGoogle }) {
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
          → Crear cuenta con este email
        </button>
      )}
      {notice.kind === "google" && (
        <button
          type="button"
          data-testid="auth-notice-google-btn"
          onClick={onUseGoogle}
          className="text-[#60A5FA] hover:text-[#93C5FD] font-semibold underline underline-offset-4"
        >
          → Continuar con Google
        </button>
      )}
    </div>
  );
}
