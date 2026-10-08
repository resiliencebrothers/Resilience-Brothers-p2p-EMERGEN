import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import {
  AlertTriangle, CheckCircle2, Inbox, CornerDownRight, Loader2, Hash,
} from "lucide-react";

const qty = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 3 });
const money = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
const when = (s) => (s ? new Date(s).toLocaleString() : "—");

// iter354 — Bandeja de Revisión: agrupa los movimientos con orden/valoración
// INCIERTA y permite re-sellar su secuencia efectiva en un solo lugar.
export default function InventoryReviewTab() {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [target, setTarget] = useState(null);     // movimiento en diálogo
  const [timeline, setTimeline] = useState(null);
  const [tlLoading, setTlLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const typeLabel = (ty) => t(`inventory.review.types.${ty}`, ty);

  const load = useCallback(() => {
    setLoading(true);
    axios.get(`${API}/admin/inventory/uncertain`, { withCredentials: true })
      .then((r) => setData(r.data))
      .catch((e) => toast.error(e.response?.data?.detail || t("inventory.review.loadError")))
      .finally(() => setLoading(false));
  }, [t]);
  useEffect(() => { load(); }, [load]);

  const openResolve = (mv) => {
    setTarget(mv);
    setTimeline(null);
    setTlLoading(true);
    axios.get(`${API}/admin/inventory/uncertain/${mv.id}/timeline`, { withCredentials: true })
      .then((r) => setTimeline(r.data))
      .catch((e) => {
        toast.error(e.response?.data?.detail || t("inventory.review.loadError"));
        setTarget(null);
      })
      .finally(() => setTlLoading(false));
  };

  const resolve = async (afterId) => {
    if (!target) return;
    setSaving(true);
    try {
      await axios.post(`${API}/admin/inventory/uncertain/${target.id}/resolve`,
        { after_movement_id: afterId },
        { withCredentials: true });
      toast.success(t("inventory.review.resolved"));
      setTarget(null);
      setTimeline(null);
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("inventory.review.resolveError"));
    } finally {
      setSaving(false);
    }
  };

  const total = data?.total || 0;

  return (
    <div className="space-y-6" data-testid="inventory-review-view">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <Inbox className="w-5 h-5 text-[#8B5CF6]" />
          <h3 className="text-sm uppercase tracking-wider text-white">
            {t("inventory.review.title")}
          </h3>
        </div>
        <span className={`text-[0.65rem] px-2 py-0.5 border ${total > 0
          ? "border-rose-500/40 text-rose-300" : "border-emerald-500/30 text-emerald-300"}`}
          data-testid="review-count-badge">
          {total}
        </span>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}
          data-testid="review-refresh-btn"
          className="ml-auto rounded-none border-white/10 text-xs">
          {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : t("inventory.review.refresh")}
        </Button>
      </div>

      <p className="text-[0.7rem] text-neutral-400 max-w-2xl">
        {t("inventory.review.intro")}
      </p>

      {!loading && total === 0 && (
        <div className="flex flex-col items-center justify-center gap-3 py-16 border border-white/5 bg-white/[0.02]"
          data-testid="review-empty">
          <CheckCircle2 className="w-10 h-10 text-emerald-400" />
          <p className="text-sm text-neutral-300">{t("inventory.review.empty")}</p>
        </div>
      )}

      <div className="space-y-5">
        {(data?.products || []).map((g) => (
          <div key={g.product_id} className="border border-white/10 bg-white/[0.02]"
            data-testid={`review-group-${g.product_id}`}>
            <div className="flex items-center gap-2 px-4 py-2.5 border-b border-white/10">
              <AlertTriangle className="w-4 h-4 text-rose-400" />
              <span className="text-sm text-white font-medium">{g.product_name}</span>
              <span className="text-[0.6rem] text-neutral-500 ml-auto">
                {g.movements.length} {t("inventory.review.items")}
              </span>
            </div>
            <div className="divide-y divide-white/5">
              {g.movements.map((mv) => (
                <div key={mv.id} className="flex items-center gap-3 px-4 py-3 flex-wrap"
                  data-testid={`review-item-${mv.id}`}>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-sm text-neutral-200">
                      <span className="uppercase text-[0.6rem] px-1.5 py-0.5 border border-white/15 text-neutral-300">
                        {typeLabel(mv.type)}
                      </span>
                      <span>{qty(mv.quantity)} {mv.unit}</span>
                      {mv.unit_cost > 0 && (
                        <span className="text-neutral-500">· {money(mv.unit_cost)} CUP</span>
                      )}
                    </div>
                    <div className="text-[0.65rem] text-neutral-500 mt-0.5">
                      {mv.note || "—"} · {when(mv.created_at)}
                    </div>
                  </div>
                  <Button size="sm" onClick={() => openResolve(mv)}
                    data-testid={`review-resolve-btn-${mv.id}`}
                    className="bg-[#8B5CF6] hover:bg-[#7c4df0] text-white rounded-none text-xs">
                    {t("inventory.review.resolve")}
                  </Button>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Diálogo de resolución: elegir dónde reinsertar el movimiento */}
      <Dialog open={!!target} onOpenChange={(o) => { if (!o && !saving) { setTarget(null); setTimeline(null); } }}>
        <DialogContent className="bg-[#0d0d12] border-white/10 max-w-xl max-h-[85vh] overflow-y-auto"
          data-testid="review-resolve-dialog">
          <DialogHeader>
            <DialogTitle className="text-white">{t("inventory.review.dialogTitle")}</DialogTitle>
            <DialogDescription className="text-neutral-400 text-xs">
              {t("inventory.review.dialogDesc")}
            </DialogDescription>
          </DialogHeader>

          {tlLoading && (
            <div className="flex justify-center py-10">
              <Loader2 className="w-6 h-6 animate-spin text-[#8B5CF6]" />
            </div>
          )}

          {timeline && (
            <div className="space-y-1 max-h-[55vh] overflow-y-auto pr-1">
              {/* Insertar al inicio */}
              <button type="button" disabled={saving} onClick={() => resolve(null)}
                data-testid="review-insert-start"
                className="w-full flex items-center gap-2 text-[0.65rem] uppercase tracking-wider text-[#8B5CF6] hover:text-white hover:bg-[#8B5CF6]/10 border border-dashed border-[#8B5CF6]/30 px-3 py-1.5 transition-colors">
                <CornerDownRight className="w-3 h-3" /> {t("inventory.review.insertStart")}
              </button>

              {timeline.timeline.map((r) => (
                <div key={r.id}>
                  <div className={`flex items-center gap-2 px-3 py-2 text-sm border ${r.is_target
                    ? "border-rose-500/40 bg-rose-500/5 text-rose-200"
                    : "border-white/10 bg-white/[0.02] text-neutral-200"}`}
                    data-testid={`timeline-row-${r.id}`}>
                    <Hash className="w-3 h-3 text-neutral-500 shrink-0" />
                    <span className="text-[0.6rem] text-neutral-500 w-10">
                      {r.effect_seq != null ? r.effect_seq : "—"}
                    </span>
                    <span className="uppercase text-[0.6rem] px-1.5 py-0.5 border border-white/15 text-neutral-300">
                      {typeLabel(r.type)}
                    </span>
                    <span>{qty(r.quantity)} {r.unit}</span>
                    {r.is_target && (
                      <span className="ml-auto text-[0.55rem] uppercase px-1.5 py-0.5 border border-rose-500/40 text-rose-300">
                        {t("inventory.review.thisOne")}
                      </span>
                    )}
                  </div>
                  {r.anchor_eligible && (
                    <button type="button" disabled={saving} onClick={() => resolve(r.id)}
                      data-testid={`review-insert-after-${r.id}`}
                      className="w-full flex items-center gap-2 text-[0.65rem] uppercase tracking-wider text-[#8B5CF6] hover:text-white hover:bg-[#8B5CF6]/10 border border-dashed border-[#8B5CF6]/30 px-3 py-1.5 my-1 transition-colors">
                      <CornerDownRight className="w-3 h-3" /> {t("inventory.review.insertAfter")}
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
