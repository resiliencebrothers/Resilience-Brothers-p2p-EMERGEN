import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { AlertTriangle, ScanLine, Scale, TrendingDown, RefreshCw, Check, Eye, History, GitBranch, ChevronRight, ListTree } from "lucide-react";

const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
const fmtDate = (s) => { try { return new Date(s).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" }); } catch { return s || ""; } };
const DOT = { resuelta: "bg-emerald-400", en_revision: "bg-sky-400", pendiente: "bg-amber-400" };

const TYPE_META = {
  conteo_pendiente: { icon: ScanLine, cls: "text-sky-300 border-sky-500/30" },
  diferencia: { icon: Scale, cls: "text-amber-300 border-amber-500/30" },
  venta_bajo_costo: { icon: TrendingDown, cls: "text-red-400 border-red-500/30" },
};
const STATUS_CLS = {
  pendiente: "text-amber-300 border-amber-500/30",
  en_revision: "text-sky-300 border-sky-500/30",
  resuelta: "text-emerald-400 border-emerald-500/30",
};

// iter333 (IPV Fase 3) — Seguimiento de incidencias del inventario.
export default function InventoryIncidentsTab() {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [status, setStatus] = useState("");
  const [type, setType] = useState("");
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [acting, setActing] = useState(null); // {id, status}
  const [note, setNote] = useState("");
  const [expanded, setExpanded] = useState(() => new Set());
  const [highlight, setHighlight] = useState(null);
  const rowRefs = useRef({});

  const load = useCallback(() => {
    setLoading(true);
    axios.get(`${API}/admin/inventory/incidents`, {
      params: { ...(status ? { status } : {}), ...(type ? { type } : {}) },
      withCredentials: true,
    }).then((r) => setData(r.data)).catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [status, type]);
  useEffect(() => { load(); }, [load]);

  const sync = async () => {
    setSyncing(true);
    try {
      const r = await axios.post(`${API}/admin/inventory/incidents/sync`, {}, { withCredentials: true });
      toast.success(t("inventory.incidents.synced", { created: r.data.created, resolved: r.data.resolved }));
      load();
    } catch { toast.error(t("inventory.incidents.syncError")); }
    finally { setSyncing(false); }
  };

  const confirmAction = async () => {
    if (!acting) return;
    try {
      await axios.post(`${API}/admin/inventory/incidents/${acting.id}/status`,
        { status: acting.status, note: note.trim() }, { withCredentials: true });
      toast.success(t("inventory.incidents.updated"));
      setActing(null); setNote("");
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
  };

  const s = data?.summary;
  const rows = data?.incidents || [];

  // Episodios de una MISMA causa (base_key) agrupados → cadena predecesor/sucesor.
  const relatedByKey = useMemo(() => {
    const m = {};
    for (const r of rows) {
      const k = r.base_key || r.id;
      (m[k] = m[k] || []).push(r);
    }
    for (const k of Object.keys(m)) m[k].sort((a, b) => (a.episode || 1) - (b.episode || 1));
    return m;
  }, [rows]);

  const toggleExpand = (id) => setExpanded((prev) => {
    const n = new Set(prev);
    n.has(id) ? n.delete(id) : n.add(id);
    return n;
  });

  const jumpTo = (id) => {
    setExpanded((prev) => new Set(prev).add(id));
    setHighlight(id);
    requestAnimationFrame(() => {
      rowRefs.current[id]?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    setTimeout(() => setHighlight((h) => (h === id ? null : h)), 2200);
  };

  return (
    <div className="space-y-5" data-testid="inventory-incidents-tab">
      <div className="flex items-center gap-3 flex-wrap">
        <h3 className="font-display text-lg flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-[#8B5CF6]" /> {t("inventory.incidents.title")}
        </h3>
        <Button data-testid="incidents-sync-btn" onClick={sync} disabled={syncing}
          size="sm" variant="outline" className="ml-auto rounded-none border-white/10 text-xs">
          <RefreshCw className={`w-3.5 h-3.5 mr-1 ${syncing ? "animate-spin" : ""}`} />
          {t("inventory.incidents.sync")}
        </Button>
      </div>
      <p className="text-[0.7rem] text-neutral-500">{t("inventory.incidents.hint")}</p>

      {/* Resumen */}
      {s && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="incidents-summary">
          <Card label={t("inventory.incidents.open")} value={s.open} tone="amber" />
          <Card label={t("inventory.incidents.tConteo")} value={s.by_type?.conteo_pendiente || 0} />
          <Card label={t("inventory.incidents.tDif")} value={s.by_type?.diferencia || 0} />
          <Card label={t("inventory.incidents.tVenta")} value={s.by_type?.venta_bajo_costo || 0} tone="red" />
        </div>
      )}

      {/* Filtros */}
      <div className="flex items-center gap-2 flex-wrap">
        <select data-testid="incidents-filter-status" value={status} onChange={(e) => setStatus(e.target.value)}
          className="h-9 bg-[#14122A] border border-white/10 text-sm px-2 text-white">
          <option value="">{t("inventory.incidents.allStatus")}</option>
          <option value="pendiente">{t("inventory.incidents.stPendiente")}</option>
          <option value="en_revision">{t("inventory.incidents.stRevision")}</option>
          <option value="resuelta">{t("inventory.incidents.stResuelta")}</option>
        </select>
        <select data-testid="incidents-filter-type" value={type} onChange={(e) => setType(e.target.value)}
          className="h-9 bg-[#14122A] border border-white/10 text-sm px-2 text-white">
          <option value="">{t("inventory.incidents.allTypes")}</option>
          <option value="conteo_pendiente">{t("inventory.incidents.tConteo")}</option>
          <option value="diferencia">{t("inventory.incidents.tDif")}</option>
          <option value="venta_bajo_costo">{t("inventory.incidents.tVenta")}</option>
        </select>
      </div>

      {/* Listado */}
      <div className="border border-white/10 divide-y divide-white/5" data-testid="incidents-list">
        {loading && <p className="px-4 py-6 text-center text-neutral-500 text-sm">{t("inventory.incidents.loading")}</p>}
        {!loading && rows.length === 0 && (
          <p className="px-4 py-8 text-center text-neutral-500 text-sm" data-testid="incidents-empty">{t("inventory.incidents.empty")}</p>
        )}
        {rows.map((i) => {
          const meta = TYPE_META[i.type] || TYPE_META.diferencia;
          const Icon = meta.icon;
          const related = relatedByKey[i.base_key || i.id] || [i];
          const hasChain = related.length > 1 || i.predecessor_id;
          const isOpen = expanded.has(i.id);
          return (
            <div key={i.id} ref={(el) => { rowRefs.current[i.id] = el; }}
              className={`px-4 py-3 transition-colors duration-500 ${highlight === i.id ? "bg-fuchsia-500/10 ring-1 ring-fuchsia-500/40" : ""}`}
              data-testid={`incident-row-${i.id}`}>
              <div className="flex items-start gap-3 flex-wrap">
                <span className={`text-[0.6rem] uppercase tracking-wider px-2 py-0.5 border flex items-center gap-1 ${meta.cls}`}>
                  <Icon className="w-3 h-3" /> {t(`inventory.incidents.type_${i.type}`)}
                </span>
                <span className="text-sm text-white">{i.product_name || "—"}</span>
                {i.episode > 1 ? (
                  <span data-testid={`incident-episode-${i.id}`}
                    title={t("inventory.incidents.episodeTitle")}
                    className="text-[0.6rem] uppercase tracking-wider px-2 py-0.5 border border-fuchsia-500/30 text-fuchsia-300">
                    {t("inventory.incidents.episode", { n: i.episode })}
                  </span>
                ) : null}
                {i.amount ? <span className="text-xs font-mono text-red-400">{fmt(i.amount)} CUP</span> : null}
                <span className={`ml-auto text-[0.6rem] uppercase tracking-wider px-2 py-0.5 border ${STATUS_CLS[i.status]}`}
                  data-testid={`incident-status-${i.id}`}>
                  {t(`inventory.incidents.st_${i.status}`)}
                  {i.auto_resolved ? ` · ${t("inventory.incidents.auto")}` : ""}
                </span>
              </div>
              <p className="text-xs text-neutral-400 mt-1">{i.detail}</p>
              <div className="flex items-center gap-3 mt-0.5">
                <p className="text-[0.6rem] text-neutral-600">{i.ref_date}</p>
                <button data-testid={`incident-timeline-toggle-${i.id}`}
                  onClick={() => toggleExpand(i.id)}
                  className="text-[0.6rem] uppercase tracking-wider text-neutral-400 hover:text-white flex items-center gap-1">
                  {hasChain ? <ListTree className="w-3 h-3" /> : <History className="w-3 h-3" />}
                  {t("inventory.incidents.timeline")}
                  {related.length > 1 ? ` · ${related.length}` : ""}
                  <ChevronRight className={`w-3 h-3 transition-transform ${isOpen ? "rotate-90" : ""}`} />
                </button>
              </div>

              {isOpen && (
                <div className="mt-2 border-l border-white/10 pl-3 space-y-3" data-testid={`incident-timeline-${i.id}`}>
                  {related.length > 1 && (
                    <div>
                      <div className="text-[0.6rem] uppercase tracking-wider text-neutral-500 mb-1 flex items-center gap-1">
                        <GitBranch className="w-3 h-3" /> {t("inventory.incidents.relatedEpisodes")}
                      </div>
                      <div className="flex items-center gap-1 flex-wrap">
                        {related.map((ep, idx) => (
                          <span key={ep.id} className="flex items-center gap-1">
                            {idx > 0 && <ChevronRight className="w-3 h-3 text-neutral-600" />}
                            <button data-testid={`related-episode-${i.id}-${ep.episode}`}
                              onClick={() => jumpTo(ep.id)}
                              className={`text-[0.6rem] px-2 py-0.5 border flex items-center gap-1 ${ep.id === i.id ? "border-fuchsia-500/50 text-fuchsia-200 bg-fuchsia-500/10" : "border-white/15 text-neutral-300 hover:border-white/40"}`}>
                              <span className={`w-1.5 h-1.5 rounded-full ${DOT[ep.status] || "bg-neutral-500"}`} />
                              {t("inventory.incidents.episodeShort", { n: ep.episode })}
                            </button>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  {related.length <= 1 && i.predecessor_id && (
                    <p className="text-[0.6rem] text-neutral-500" data-testid={`incident-successor-note-${i.id}`}>
                      {t("inventory.incidents.successorOf")}
                    </p>
                  )}
                  <div>
                    <div className="text-[0.6rem] uppercase tracking-wider text-neutral-500 mb-1 flex items-center gap-1">
                      <History className="w-3 h-3" /> {t("inventory.incidents.observations")}
                    </div>
                    <ul className="space-y-1">
                      {(i.history || []).map((h, idx) => (
                        <li key={idx} className="flex items-start gap-2 text-[0.65rem]">
                          <span className={`mt-1 w-1.5 h-1.5 rounded-full shrink-0 ${DOT[h.status] || "bg-neutral-500"}`} />
                          <div>
                            <span className="text-neutral-300">{h.note}</span>
                            <span className="text-neutral-600 ml-1">· {fmtDate(h.at)}</span>
                          </div>
                        </li>
                      ))}
                      {(!i.history || i.history.length === 0) && (
                        <li className="text-[0.65rem] text-neutral-600">{t("inventory.incidents.noHistory")}</li>
                      )}
                    </ul>
                  </div>
                </div>
              )}

              {i.status !== "resuelta" && (
                acting?.id === i.id ? (
                  <div className="flex items-center gap-2 mt-2" data-testid={`incident-action-form-${i.id}`}>
                    <Input value={note} onChange={(e) => setNote(e.target.value)}
                      data-testid={`incident-note-${i.id}`}
                      placeholder={t("inventory.incidents.notePlaceholder")}
                      className="h-8 rounded-none bg-[#0a0a0a] border-white/10 text-xs" />
                    <Button size="sm" data-testid={`incident-confirm-${i.id}`} onClick={confirmAction}
                      className="h-8 bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none text-xs whitespace-nowrap">
                      {t(`inventory.incidents.st_${acting.status}`)} <Check className="w-3.5 h-3.5 ml-1" />
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => { setActing(null); setNote(""); }}
                      className="h-8 text-xs text-neutral-400">{t("inventory.incidents.cancel")}</Button>
                  </div>
                ) : (
                  <div className="flex items-center gap-2 mt-2">
                    {i.status === "pendiente" && (
                      <button data-testid={`incident-review-${i.id}`}
                        onClick={() => { setActing({ id: i.id, status: "en_revision" }); setNote(""); }}
                        className="text-[0.65rem] uppercase tracking-wider text-sky-300 hover:text-sky-200 flex items-center gap-1">
                        <Eye className="w-3 h-3" /> {t("inventory.incidents.toReview")}
                      </button>
                    )}
                    <button data-testid={`incident-resolve-${i.id}`}
                      onClick={() => { setActing({ id: i.id, status: "resuelta" }); setNote(""); }}
                      className="text-[0.65rem] uppercase tracking-wider text-emerald-400 hover:text-emerald-300 flex items-center gap-1">
                      <Check className="w-3 h-3" /> {t("inventory.incidents.toResolve")}
                    </button>
                  </div>
                )
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

const Card = ({ label, value, tone }) => {
  const cls = tone === "red" ? "text-red-400" : tone === "amber" ? "text-amber-300" : "text-white";
  return (
    <div className="border border-white/10 bg-[#14122A] px-3 py-3">
      <div className="text-neutral-500 text-[0.6rem] uppercase tracking-wider">{label}</div>
      <div className={`mt-1 text-2xl font-display ${cls}`}>{value}</div>
    </div>
  );
};
