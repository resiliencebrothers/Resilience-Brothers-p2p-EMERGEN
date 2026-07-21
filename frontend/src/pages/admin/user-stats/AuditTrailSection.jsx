import { useEffect, useState } from "react";
import axios from "axios";
import { ScrollText } from "lucide-react";
import { API } from "@/App";

export default function AuditTrailSection({ userId, onOpenInAudit }) {
  const [trail, setTrail] = useState(null);
  const [trailDays, setTrailDays] = useState(30);
  const [trailLoading, setTrailLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setTrailLoading(true);
      try {
        const r = await axios.get(
          `${API}/admin/users/${userId}/audit-trail`,
          { params: { days: trailDays, limit: 100 }, withCredentials: true },
        );
        if (!cancelled) setTrail(r.data);
      } catch (e) {
        // 403s already handled at stats-page level — silently no-op here.
        if (e.response?.status !== 403 && !cancelled) {
          setTrail({ entries: [], total: 0, window_days: trailDays });
        }
      } finally {
        if (!cancelled) setTrailLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [userId, trailDays]);

  return (
    <div className="tactile-card p-5" data-testid="user-stats-audit-trail">
      <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
        <h2 className="font-display text-xl flex items-center gap-2">
          <ScrollText className="w-5 h-5 text-[#8B5CF6]" /> Historial de cambios
        </h2>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex gap-1" role="tablist" aria-label="Ventana temporal">
            {[7, 30, 90].map((d) => (
              <button
                key={d}
                onClick={() => setTrailDays(d)}
                data-testid={`audit-trail-window-${d}`}
                className={
                  "text-[0.65rem] uppercase tracking-widest px-3 py-1 border transition-all " +
                  (trailDays === d
                    ? "border-[#8B5CF6] bg-[#8B5CF6]/10 text-[#8B5CF6]"
                    : "border-white/10 text-neutral-500 hover:text-white hover:border-white/20")
                }
              >
                {d}d
              </button>
            ))}
          </div>
          <button
            onClick={onOpenInAudit}
            data-testid="audit-trail-open-in-audit"
            className="text-[0.65rem] uppercase tracking-widest px-3 py-1 border border-emerald-500/40 hover:border-emerald-500 hover:bg-emerald-500/10 text-emerald-400 transition-all"
            title="Abrir esta trazabilidad en el módulo global de Auditoría"
          >
            Abrir en Auditoría →
          </button>
        </div>
      </div>
      {trailLoading && !trail ? (
        <div className="text-sm text-neutral-500">Cargando historial…</div>
      ) : !trail || trail.entries.length === 0 ? (
        <div className="text-sm text-neutral-500 py-6 text-center border border-white/5 bg-[#0a0a0a]">
          Sin cambios registrados en los últimos {trailDays} días.
        </div>
      ) : (
        <TrailList trail={trail} />
      )}
    </div>
  );
}

function TrailList({ trail }) {
  return (
    <>
      <div className="text-xs text-neutral-500 mb-3">
        {trail.total} evento{trail.total === 1 ? "" : "s"} en los últimos {trail.window_days} días
        {trail.entries.length === 100 ? " (mostrando los 100 más recientes)" : ""}
      </div>
      <ol className="relative border-l border-white/10 ml-2 space-y-4">
        {trail.entries.map((e) => (
          <TrailEntry key={e.id} entry={e} />
        ))}
      </ol>
    </>
  );
}

function TrailEntry({ entry: e }) {
  const isAdminActor = e.actor_role === "admin";
  const dotCls = isAdminActor ? "bg-[#8B5CF6]" : "bg-emerald-500";
  return (
    <li className="ml-4" data-testid={`audit-trail-entry-${e.id}`}>
      <span className={`absolute -left-[5px] w-2.5 h-2.5 rounded-full ${dotCls}`} />
      <div className="flex items-baseline justify-between gap-2 flex-wrap">
        <div className="font-medium text-sm">{e.summary || e.action}</div>
        <time className="text-[0.65rem] text-neutral-500 whitespace-nowrap tabular-nums">
          {new Date(e.created_at).toLocaleString()}
        </time>
      </div>
      <div className="text-xs text-neutral-500 mt-1 flex items-center gap-2 flex-wrap">
        <span className={isAdminActor ? "text-[#8B5CF6]" : "text-emerald-400"}>
          {e.actor_name || e.actor_email || "sistema"}
        </span>
        <span className="text-neutral-600">·</span>
        <span className="font-mono text-[0.65rem] uppercase tracking-widest text-neutral-500">
          {e.action}
        </span>
      </div>
    </li>
  );
}
