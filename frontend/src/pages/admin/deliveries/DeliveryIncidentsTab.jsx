import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { AlertTriangle, CheckCircle2, Package, User, MapPin, DollarSign, ArrowRightLeft } from "lucide-react";

// Incidencias de mensajería: entregas con movimiento físico cuyo origen quedó
// rechazado/cancelado (origin_conflict). Lista ABIERTAS + historial de RESUELTAS,
// con resumen del origen para gestión manual + marcar resuelta.
const fmt = (v) => (v === null || v === undefined || v === "" ? "—" : String(v));

// Resumen curado del origen (canje/retiro/envío Empresa) para verificar efectivo/producto.
function OriginSummary({ origin, t }) {
  if (!origin || Object.keys(origin).length === 0) return null;
  if (origin.missing)
    return (
      <div className="text-xs text-neutral-500 italic" data-testid="incident-origin-missing">
        {t("admin.deliveries.incidents.originMissing")}
      </div>
    );
  const money =
    origin.total_usd != null ? `${origin.total_usd} USD`
      : origin.amount_usd != null ? `${origin.amount_usd} ${origin.currency || "USD"}`
      : null;
  const rows = [
    origin.product_name && { icon: Package, label: t("admin.deliveries.incidents.fProduct"), val: `${origin.product_name}${origin.quantity ? ` ×${origin.quantity}` : ""}` },
    money && { icon: DollarSign, label: t("admin.deliveries.incidents.fAmount"), val: money },
    (origin.user_name || origin.user_email || origin.company_name || origin.receiver_name) && {
      icon: User, label: t("admin.deliveries.incidents.fParty"),
      val: fmt(origin.company_name || origin.user_name || origin.receiver_name) + (origin.user_email ? ` · ${origin.user_email}` : ""),
    },
    (origin.municipality || origin.province) && { icon: MapPin, label: t("admin.deliveries.incidents.fLocation"), val: [origin.municipality, origin.province].filter(Boolean).join(", ") },
    origin.method && { icon: DollarSign, label: t("admin.deliveries.incidents.fMethod"), val: origin.method },
  ].filter(Boolean);
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1 mt-2 pt-2 border-t border-white/5"
      data-testid="incident-origin-summary">
      <div className="text-[0.7rem] text-neutral-500 sm:col-span-2">
        {t("admin.deliveries.incidents.fOriginStatus")}: <span className="text-neutral-300 font-mono">{fmt(origin.status)}</span>
      </div>
      {rows.map((r, i) => {
        const Icon = r.icon;
        return (
          <div key={i} className="flex items-start gap-1.5 text-xs">
            <Icon className="w-3.5 h-3.5 mt-0.5 text-neutral-500 shrink-0" />
            <span className="text-neutral-500">{r.label}:</span>
            <span className="text-neutral-200 break-words min-w-0">{r.val}</span>
          </div>
        );
      })}
    </div>
  );
}

export default function DeliveryIncidentsTab() {
  const { t } = useTranslation();
  const [view, setView] = useState("open"); // open | resolved
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [picked, setPicked] = useState({});

  const load = useCallback((v) => {
    setLoading(true);
    axios.get(`${API}/admin/delivery-incidents`, {
      params: { resolved: v === "resolved" }, withCredentials: true,
    })
      .then((r) => setRows(r.data || []))
      .catch(() => toast.error(t("admin.deliveries.incidents.loadError")))
      .finally(() => setLoading(false));
  }, [t]);

  useEffect(() => { load(view); }, [view, load]);

  const resolve = async (did) => {
    const note = window.prompt(t("admin.deliveries.incidents.resolvePrompt")) ?? "";
    setBusy(did);
    try {
      await axios.post(`${API}/admin/delivery-incidents/${did}/resolve`,
        { note }, { withCredentials: true });
      toast.success(t("admin.deliveries.incidents.resolved"));
      load(view);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    } finally { setBusy(""); }
  };

  const reassign = async (did) => {
    const storeId = picked[did];
    if (!storeId) return;
    const note = window.prompt(t("admin.deliveries.incidents.reassignNote")) ?? "";
    setBusy(did);
    try {
      const r = await axios.post(`${API}/admin/delivery-incidents/${did}/reassign-inventory`,
        { store_id: storeId, note }, { withCredentials: true });
      toast.success(t("admin.deliveries.incidents.reassigned", { store: r.data?.store_name || "" }));
      load(view);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    } finally { setBusy(""); }
  };

  const isOpen = view === "open";

  return (
    <div className="space-y-4" data-testid="delivery-incidents-tab">
      <div className="flex items-center gap-2">
        <AlertTriangle className="w-5 h-5 text-amber-400" />
        <h2 className="text-lg font-semibold">{t("admin.deliveries.incidents.title")}</h2>
      </div>
      <p className="text-sm text-neutral-400">{t("admin.deliveries.incidents.desc")}</p>

      <div className="flex gap-2">
        <button
          onClick={() => setView("open")} data-testid="incidents-view-open"
          className={`px-3 py-1.5 text-sm border rounded-none transition-colors ${isOpen ? "border-amber-500 text-amber-300 bg-amber-500/10" : "border-white/10 text-neutral-400 hover:text-neutral-200"}`}>
          {t("admin.deliveries.incidents.viewOpen")}
        </button>
        <button
          onClick={() => setView("resolved")} data-testid="incidents-view-resolved"
          className={`px-3 py-1.5 text-sm border rounded-none transition-colors ${!isOpen ? "border-emerald-500 text-emerald-300 bg-emerald-500/10" : "border-white/10 text-neutral-400 hover:text-neutral-200"}`}>
          {t("admin.deliveries.incidents.viewResolved")}
        </button>
      </div>

      {loading ? (
        <div className="text-sm text-neutral-500" data-testid="incidents-loading">{t("admin.deliveries.incidents.loading")}</div>
      ) : rows.length === 0 ? (
        <div className="border border-white/10 bg-[#0d0d0d] p-8 text-center text-neutral-500"
          data-testid="delivery-incidents-empty">
          <CheckCircle2 className="w-6 h-6 mx-auto mb-2 text-emerald-400" />
          {isOpen ? t("admin.deliveries.incidents.empty") : t("admin.deliveries.incidents.emptyResolved")}
        </div>
      ) : (
        <div className="space-y-3">
          {rows.map((d) => {
            const oc = d.origin_conflict || {};
            const border = isOpen ? "border-amber-500/30 bg-amber-500/5" : "border-emerald-500/20 bg-emerald-500/5";
            return (
              <div key={d.id} data-testid={`delivery-incident-${d.id}`}
                className={`border ${border} p-4 flex flex-col sm:flex-row sm:items-start gap-3 justify-between`}>
                <div className="space-y-1 min-w-0 flex-1">
                  <div className="text-sm font-semibold flex items-center gap-2 flex-wrap">
                    <span className="font-mono text-amber-300">{(d.id || "").slice(0, 8)}</span>
                    <span className="text-neutral-400">· {d.client_name || d.receiver_name || "—"}</span>
                  </div>
                  <div className="text-xs text-neutral-400">
                    {t("admin.deliveries.incidents.row", {
                      kind: oc.kind || d.kind || "—",
                      status: d.status || "—",
                    })}
                  </div>
                  {oc.note && <div className="text-[0.7rem] text-amber-200/80 break-words" data-testid={`incident-note-${d.id}`}>{oc.note}</div>}
                  {oc.at && <div className="text-[0.65rem] text-neutral-500 font-mono">{new Date(oc.at).toLocaleString("es")}</div>}
                  <OriginSummary origin={d.origin} t={t} />
                  {!isOpen && (
                    <div className="mt-2 pt-2 border-t border-white/5 text-[0.7rem] text-emerald-300/90" data-testid={`incident-resolution-${d.id}`}>
                      <CheckCircle2 className="w-3.5 h-3.5 inline mr-1" />
                      {t("admin.deliveries.incidents.resolvedOn", {
                        when: oc.resolved_at ? new Date(oc.resolved_at).toLocaleString("es") : "—",
                      })}
                      {oc.resolution_note ? ` — “${oc.resolution_note}”` : ""}
                    </div>
                  )}
                </div>
                {isOpen && (
                  <div className="flex flex-col gap-2 shrink-0 sm:w-56">
                    {d.reassign?.pending && d.reassign.product_exists && (
                      <div className="border border-sky-500/30 bg-sky-500/5 p-2 space-y-1.5"
                        data-testid={`incident-reassign-${d.id}`}>
                        <div className="text-[0.7rem] text-sky-200 flex items-center gap-1">
                          <ArrowRightLeft className="w-3.5 h-3.5" />
                          {t("admin.deliveries.incidents.reassignTitle", {
                            qty: d.reassign.quantity,
                            product: d.reassign.product_name || "—",
                          })}
                        </div>
                        <select
                          data-testid={`incident-reassign-store-${d.id}`}
                          value={picked[d.id] || ""}
                          onChange={(e) => setPicked((p) => ({ ...p, [d.id]: e.target.value }))}
                          className="w-full bg-black/40 border border-white/10 text-xs text-neutral-200 px-2 py-1.5 rounded-none">
                          <option value="">{t("admin.deliveries.incidents.reassignPick")}</option>
                          {(d.reassign.stores || []).map((s) => (
                            <option key={s.id} value={s.id}>{s.name}</option>
                          ))}
                        </select>
                        <Button
                          onClick={() => reassign(d.id)} disabled={busy === d.id || !picked[d.id]}
                          data-testid={`incident-reassign-btn-${d.id}`}
                          className="rounded-none gap-2 w-full bg-sky-600 hover:bg-sky-500 h-8 text-xs">
                          <ArrowRightLeft className="w-3.5 h-3.5" />
                          {t("admin.deliveries.incidents.reassignBtn")}
                        </Button>
                      </div>
                    )}
                    {d.reassign?.pending && !d.reassign.product_exists && (
                      <div className="text-[0.7rem] text-amber-300/80 border border-amber-500/20 bg-amber-500/5 p-2"
                        data-testid={`incident-reassign-blocked-${d.id}`}>
                        {t("admin.deliveries.incidents.reassignBlocked")}
                      </div>
                    )}
                    <Button
                      onClick={() => resolve(d.id)} disabled={busy === d.id}
                      data-testid={`delivery-incident-resolve-${d.id}`}
                      variant="outline"
                      className="rounded-none gap-2 border-white/10">
                      <CheckCircle2 className="w-4 h-4" />
                      {busy === d.id ? "…" : t("admin.deliveries.incidents.resolve")}
                    </Button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
