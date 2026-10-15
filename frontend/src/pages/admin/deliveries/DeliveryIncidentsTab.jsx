import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { AlertTriangle, CheckCircle2 } from "lucide-react";

// Incidencias de mensajería: entregas con movimiento físico cuyo origen quedó
// rechazado/cancelado (origin_conflict). Gestión manual + marcar resuelta.
export default function DeliveryIncidentsTab() {
  const { t } = useTranslation();
  const [rows, setRows] = useState([]);
  const [busy, setBusy] = useState("");

  const load = () =>
    axios.get(`${API}/admin/delivery-incidents`, { withCredentials: true })
      .then((r) => setRows(r.data || []))
      .catch(() => toast.error(t("admin.deliveries.incidents.loadError")));

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const resolve = async (did) => {
    const note = window.prompt(t("admin.deliveries.incidents.resolvePrompt")) ?? "";
    setBusy(did);
    try {
      await axios.post(`${API}/admin/delivery-incidents/${did}/resolve`,
        { note }, { withCredentials: true });
      toast.success(t("admin.deliveries.incidents.resolved"));
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    } finally { setBusy(""); }
  };

  return (
    <div className="space-y-4" data-testid="delivery-incidents-tab">
      <div className="flex items-center gap-2">
        <AlertTriangle className="w-5 h-5 text-amber-400" />
        <h2 className="text-lg font-semibold">{t("admin.deliveries.incidents.title")}</h2>
      </div>
      <p className="text-sm text-neutral-400">{t("admin.deliveries.incidents.desc")}</p>

      {rows.length === 0 ? (
        <div className="border border-white/10 bg-[#0d0d0d] p-8 text-center text-neutral-500"
          data-testid="delivery-incidents-empty">
          <CheckCircle2 className="w-6 h-6 mx-auto mb-2 text-emerald-400" />
          {t("admin.deliveries.incidents.empty")}
        </div>
      ) : (
        <div className="space-y-3">
          {rows.map((d) => {
            const oc = d.origin_conflict || {};
            return (
              <div key={d.id} data-testid={`delivery-incident-${d.id}`}
                className="border border-amber-500/30 bg-amber-500/5 p-4 flex flex-col sm:flex-row sm:items-center gap-3 justify-between">
                <div className="space-y-1 min-w-0">
                  <div className="text-sm font-semibold flex items-center gap-2">
                    <span className="font-mono text-amber-300">{(d.id || "").slice(0, 8)}</span>
                    <span className="text-neutral-400">· {d.client_name || d.receiver_name || "—"}</span>
                  </div>
                  <div className="text-xs text-neutral-400">
                    {t("admin.deliveries.incidents.row", {
                      kind: oc.kind || d.kind || "—",
                      status: d.status || "—",
                    })}
                  </div>
                  {oc.note && <div className="text-[0.7rem] text-amber-200/80 break-words">{oc.note}</div>}
                  {oc.at && <div className="text-[0.65rem] text-neutral-500 font-mono">{new Date(oc.at).toLocaleString("es")}</div>}
                </div>
                <Button
                  onClick={() => resolve(d.id)} disabled={busy === d.id}
                  data-testid={`delivery-incident-resolve-${d.id}`}
                  className="rounded-none gap-2 shrink-0">
                  <CheckCircle2 className="w-4 h-4" />
                  {busy === d.id ? "…" : t("admin.deliveries.incidents.resolve")}
                </Button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
