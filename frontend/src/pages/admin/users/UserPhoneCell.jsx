export function UserPhoneCell({ user, canManageBlocklist, onVerify, onReject }) {
  if (!user.phone) {
    return <span className="text-neutral-600 text-xs">— legacy —</span>;
  }
  return (
    <div className="flex flex-col gap-1">
      <span className="font-mono text-xs text-neutral-300" data-testid={`phone-${user.user_id}`}>
        {user.phone}
      </span>
      {user.phone_verified ? (
        <span className="text-[0.6rem] uppercase tracking-widest px-1.5 py-0.5 border border-[#22C55E]/40 text-[#22C55E] bg-[#22C55E]/10 self-start">
          Verificado
        </span>
      ) : canManageBlocklist ? (
        <div className="flex gap-2 self-start">
          <button
            type="button"
            data-testid={`verify-phone-btn-${user.user_id}`}
            onClick={onVerify}
            className="text-[0.65rem] uppercase tracking-widest text-[#22C55E] hover:text-[#4ADE80] underline underline-offset-4"
            title="Marcar como verificado y activar cuenta (requiere 2FA)"
          >
            ✓ Verificar
          </button>
          <button
            type="button"
            data-testid={`reject-phone-btn-${user.user_id}`}
            onClick={onReject}
            className="text-[0.65rem] uppercase tracking-widest text-[#EF4444] hover:text-[#FCA5A5] underline underline-offset-4"
            title="Rechazar y bloquear (requiere 2FA)"
          >
            ✕ Rechazar
          </button>
        </div>
      ) : (
        <span
          className="text-[0.6rem] uppercase tracking-widest text-neutral-600 self-start"
          title="Sin permiso 'Bloqueos' — pídeselo a un admin"
        >
          Pendiente
        </span>
      )}
      {user.account_status &&
        user.account_status !== "active" &&
        user.role !== "admin" &&
        user.role !== "employee" && (
        <span
          data-testid={`account-status-${user.user_id}`}
          className={`text-[0.6rem] uppercase tracking-widest px-1.5 py-0.5 self-start ${
            user.account_status === "blocked"
              ? "border border-[#EF4444]/40 text-[#EF4444] bg-[#EF4444]/10"
              : "border border-[#8B5CF6]/40 text-[#8B5CF6] bg-[#8B5CF6]/10"
          }`}
        >
          {user.account_status === "blocked" ? "Bloqueada" : "En revisión"}
        </span>
      )}
    </div>
  );
}
