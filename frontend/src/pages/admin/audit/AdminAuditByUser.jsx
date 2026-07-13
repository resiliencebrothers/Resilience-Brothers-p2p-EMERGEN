import { useEffect, useState, useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { UserSearch, ScrollText, X } from "lucide-react";

const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString() : "—");

/**
 * iter55.35 — "Por usuario" tab inside AdminAuditHub. Provides a debounced
 * autocomplete over the actor picker + reuses the per-user audit trail
 * endpoint (`/admin/users/:id/audit-trail`) that already powers the section
 * inside the stats page. Also accepts `?user_id=X` in the URL so the stats
 * page can deep-link into this view.
 */
export default function AdminAuditByUser() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialUserId = searchParams.get("user_id") || "";
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [selectedUserId, setSelectedUserId] = useState(initialUserId);
  const [selectedActor, setSelectedActor] = useState(null); // {actor_id, name, email}
  const [trail, setTrail] = useState(null);
  const [trailLoading, setTrailLoading] = useState(false);
  const [windowDays, setWindowDays] = useState(30);

  // -------- Debounced actor search --------
  useEffect(() => {
    if (query.trim().length < 2) {
      setSuggestions([]);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const r = await axios.get(`${API}/admin/audit/actors`, {
          params: { q: query, limit: 10 }, withCredentials: true,
        });
        setSuggestions(r.data || []);
      } catch (_e) {
        setSuggestions([]);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [query]);

  // -------- Load per-target trail whenever selectedUserId or window changes --------
  const loadTrail = useCallback(async () => {
    if (!selectedUserId) {
      setTrail(null);
      return;
    }
    setTrailLoading(true);
    try {
      const r = await axios.get(
        `${API}/admin/users/${selectedUserId}/audit-trail`,
        { params: { days: windowDays, limit: 200 }, withCredentials: true },
      );
      setTrail(r.data);
    } catch (e) {
      if (e.response?.status === 404) {
        toast.error("Ese usuario no existe en la plataforma.");
        clearSelection();
      } else {
        toast.error(e.response?.data?.detail || "Error al cargar el historial.");
      }
      setTrail(null);
    } finally {
      setTrailLoading(false);
    }
  }, [selectedUserId, windowDays]);
  useEffect(() => { loadTrail(); }, [loadTrail]);

  const pick = (row) => {
    setSelectedUserId(row.actor_id);
    setSelectedActor(row);
    setQuery("");
    setSuggestions([]);
    setSearchParams({ tab: "by-user", user_id: row.actor_id }, { replace: true });
  };

  const clearSelection = () => {
    setSelectedUserId("");
    setSelectedActor(null);
    setTrail(null);
    setSearchParams({ tab: "by-user" }, { replace: true });
  };

  const grouped = useMemo(() => {
    if (!trail?.entries) return [];
    // Group entries by day for readable timeline
    const buckets = new Map();
    for (const e of trail.entries) {
      const day = new Date(e.created_at).toISOString().slice(0, 10);
      if (!buckets.has(day)) buckets.set(day, []);
      buckets.get(day).push(e);
    }
    return Array.from(buckets.entries()); // [[day, entries], ...]
  }, [trail]);

  return (
    <div className="space-y-4" data-testid="audit-by-user">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="micro-label text-neutral-500 mb-1">/ Por usuario</div>
          <h2 className="font-display text-xl">Historial forense por usuario</h2>
          <p className="text-sm text-neutral-500 mt-1 max-w-xl">
            Elige a un usuario y visualiza cronológicamente cada acción que el equipo
            realizó sobre su cuenta. Ideal para trazabilidad ante disputas o auditorías.
          </p>
        </div>
        <div className="flex gap-1" role="tablist" aria-label="Ventana temporal">
          {[7, 30, 90, 180].map((d) => (
            <button
              key={d}
              onClick={() => setWindowDays(d)}
              data-testid={`audit-user-window-${d}`}
              className={
                "text-[0.65rem] uppercase tracking-widest px-3 py-1 border transition-all " +
                (windowDays === d
                  ? "border-[#8B5CF6] bg-[#8B5CF6]/10 text-[#8B5CF6]"
                  : "border-white/10 text-neutral-500 hover:text-white hover:border-white/20")
              }
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {/* Actor picker */}
      {!selectedUserId ? (
        <div className="tactile-card p-5">
          <div className="micro-label text-neutral-500 mb-2 flex items-center gap-2">
            <UserSearch className="w-3.5 h-3.5" /> Buscar usuario
          </div>
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Nombre, email o user_id..."
            className="rounded-none bg-[#0a0a0a] border-white/10 h-11 font-mono"
            data-testid="audit-user-search"
            autoFocus
          />
          {suggestions.length > 0 && (
            <div className="mt-2 border border-white/10 bg-[#0a0a0a] divide-y divide-white/5"
                   data-testid="audit-user-suggestions">
              {suggestions.map((s) => (
                <button
                  key={s.actor_id}
                  type="button"
                  onClick={() => pick(s)}
                  data-testid={`audit-user-suggestion-${s.actor_id}`}
                  className="w-full text-left px-4 py-3 hover:bg-white/5 transition-colors"
                >
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div>
                      <div className="text-sm">
                        {s.actor_name || <span className="text-neutral-500">(sin nombre)</span>}
                        <span className={
                          "ml-2 text-[0.6rem] uppercase tracking-widest border px-1.5 py-0.5 " +
                          (s.actor_role === "admin"
                            ? "border-[#8B5CF6]/50 text-[#8B5CF6]"
                            : s.actor_role === "employee"
                            ? "border-emerald-500/40 text-emerald-400"
                            : "border-white/10 text-neutral-400")
                        }>
                          {s.actor_role || "user"}
                        </span>
                      </div>
                      <div className="text-xs text-neutral-500 font-mono">{s.actor_email}</div>
                    </div>
                    <div className="text-right text-xs text-neutral-500">
                      <div>{s.count} acciones</div>
                      <div>últ. {fmtDate(s.last_seen)}</div>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
          {query.length >= 2 && suggestions.length === 0 && (
            <div className="mt-2 text-sm text-neutral-500 text-center py-4">
              Sin coincidencias.
            </div>
          )}
          <div className="mt-3 text-[0.65rem] text-neutral-600">
            Sólo aparecen usuarios que han sido AFECTADOS por alguna acción del equipo.
            Para consultar cualquier user_id manualmente, escríbelo completo en el buscador.
          </div>
        </div>
      ) : (
        <>
          <div className="tactile-card p-4 flex items-center justify-between gap-3 flex-wrap"
                 data-testid="audit-user-selected">
            <div>
              <div className="micro-label text-neutral-500 mb-1">Investigando</div>
              <div className="text-lg font-display">
                {selectedActor?.actor_name || selectedUserId}
              </div>
              <div className="text-xs text-neutral-500 font-mono">
                {selectedActor?.actor_email || ""} · {selectedUserId}
              </div>
            </div>
            <Button
              onClick={clearSelection}
              data-testid="audit-user-clear"
              className="rounded-none bg-transparent border border-white/15 hover:border-[#8B5CF6]/60 text-white h-9 px-4 text-xs"
            >
              <X className="w-3.5 h-3.5 mr-2" /> Cambiar usuario
            </Button>
          </div>

          {trailLoading ? (
            <div className="text-neutral-500 p-6">Cargando historial…</div>
          ) : !trail || trail.entries.length === 0 ? (
            <div className="tactile-card p-10 text-center text-neutral-500">
              Sin cambios registrados en los últimos {windowDays} días.
            </div>
          ) : (
            <div className="tactile-card p-5">
              <div className="flex items-center gap-2 mb-4">
                <ScrollText className="w-4 h-4 text-[#8B5CF6]" />
                <span className="text-sm text-neutral-400">
                  {trail.total} evento{trail.total === 1 ? "" : "s"} en los últimos {trail.window_days} días
                </span>
              </div>
              <div className="space-y-6">
                {grouped.map(([day, entries]) => (
                  <div key={day}>
                    <div className="micro-label text-[#8B5CF6] mb-3 tabular-nums">{day}</div>
                    <ol className="relative border-l border-white/10 ml-2 space-y-3">
                      {entries.map((e) => {
                        const isAdminActor = e.actor_role === "admin";
                        const dotCls = isAdminActor ? "bg-[#8B5CF6]" : "bg-emerald-500";
                        return (
                          <li key={e.id} className="ml-4" data-testid={`audit-user-entry-${e.id}`}>
                            <span className={`absolute -left-[5px] w-2.5 h-2.5 rounded-full ${dotCls}`} />
                            <div className="flex items-baseline justify-between gap-2 flex-wrap">
                              <div className="font-medium text-sm">{e.summary || e.action}</div>
                              <time className="text-[0.65rem] text-neutral-500 whitespace-nowrap tabular-nums">
                                {new Date(e.created_at).toLocaleTimeString()}
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
                      })}
                    </ol>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
