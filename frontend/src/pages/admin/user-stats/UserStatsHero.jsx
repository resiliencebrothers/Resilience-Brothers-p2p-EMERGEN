import { ArrowLeft, User as UserIcon } from "lucide-react";
import { ROLE_LABELS, STATUS_META, fmtDate } from "./userStatsMeta";

export default function UserStatsHero({ user, onBack }) {
  const status = STATUS_META[user.account_status] || STATUS_META.active;
  return (
    <div>
      <button
        onClick={onBack}
        data-testid="user-stats-back-btn"
        className="text-xs uppercase tracking-widest text-neutral-500 hover:text-[#8B5CF6] flex items-center gap-2 mb-3"
      >
        <ArrowLeft className="w-3.5 h-3.5" /> Volver a Usuarios
      </button>
      <div className="micro-label text-[#8B5CF6] mb-2">/ Estadísticas del usuario</div>
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="font-display text-3xl">{user.name || "(sin nombre)"}</h1>
          <div className="text-sm text-neutral-400 mt-1">
            {user.email}
            {user.phone ? ` · ${user.phone}` : ""}
          </div>
          <div className="mt-2 flex items-center gap-2 text-xs">
            <span className="border border-white/10 px-2 py-0.5 uppercase tracking-widest text-white/70">
              {ROLE_LABELS[user.role] || user.role}
            </span>
            <span className={`border border-white/10 px-2 py-0.5 uppercase tracking-widest ${status.cls}`}>
              {status.label}
            </span>
            <span className="text-neutral-600">alta {fmtDate(user.created_at)}</span>
          </div>
        </div>
        <UserIcon className="w-12 h-12 text-[#8B5CF6]/40" />
      </div>
    </div>
  );
}
