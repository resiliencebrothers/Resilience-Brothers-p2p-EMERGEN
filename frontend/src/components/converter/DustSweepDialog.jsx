/**
 * iter79 — Dust sweep dialog.
 *
 * Preview & confirm modal for the "clean small balances" action. Fetches
 * `GET /api/vip/dust` on open, lists the currencies that will be swept
 * with their USDT equivalents, and calls `POST /api/vip/convert-dust`
 * on confirm.
 *
 * A single flat 0.01 USDT fee applies to the whole batch — the frontend
 * mirrors the backend's behaviour so the user sees exactly what they
 * will get.
 */
import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { extractDetailMessage } from "@/utils/apiErrors";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { Sparkles, Wallet, ArrowRightLeft } from "lucide-react";
import CurrencyIcon from "@/components/CurrencyIcon";

export default function DustSweepDialog({ open, onOpenChange, onConverted }) {
  const { t } = useTranslation();
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) {
      setPreview(null);
      return;
    }
    setLoading(true);
    axios.get(`${API}/vip/dust`, { withCredentials: true })
      .then((r) => setPreview(r.data))
      .catch(() => toast.error(t("dustSweep.previewError")))
      .finally(() => setLoading(false));
  }, [open, t]);

  const submit = async () => {
    setBusy(true);
    try {
      const r = await axios.post(
        `${API}/vip/convert-dust`, {}, { withCredentials: true },
      );
      toast.success(
        t("dustSweep.doneToast", {
          count: r.data.items.length,
          usdt: (r.data.credited_usdt || 0).toFixed(4),
        }),
      );
      onOpenChange(false);
      if (onConverted) await onConverted();
    } catch (e) {
      toast.error(extractDetailMessage(e, t("dustSweep.error")));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="dust-sweep-dialog"
        className="bg-[#0c0c0c] border border-[#8B5CF6]/30 text-white max-w-lg rounded-none"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-[#8B5CF6]" />
            {t("dustSweep.title")}
          </DialogTitle>
          <DialogDescription className="text-neutral-500 text-xs">
            {t("dustSweep.subtitle", { threshold: preview?.threshold_usdt ?? 5 })}
          </DialogDescription>
        </DialogHeader>

        {loading && (
          <div className="text-center text-neutral-500 py-8" data-testid="dust-sweep-loading">
            {t("dustSweep.loading")}
          </div>
        )}

        {!loading && preview && preview.items.length === 0 && (
          <div
            className="text-center py-8 border border-dashed border-white/10"
            data-testid="dust-sweep-empty"
          >
            <Wallet className="w-8 h-8 text-neutral-600 mx-auto mb-2" />
            <div className="text-sm text-neutral-400">{t("dustSweep.emptyTitle")}</div>
            <div className="text-xs text-neutral-600 mt-1">
              {t("dustSweep.emptySubtitle", { threshold: preview.threshold_usdt })}
            </div>
          </div>
        )}

        {!loading && preview && preview.items.length > 0 && (
          <div className="space-y-3" data-testid="dust-sweep-preview">
            <div className="max-h-[240px] overflow-y-auto border border-white/5 divide-y divide-white/5">
              {preview.items.map((it) => (
                <div
                  key={it.currency}
                  className="flex items-center justify-between p-3 hover:bg-white/[0.02]"
                  data-testid={`dust-sweep-item-${it.currency}`}
                >
                  <div className="flex items-center gap-2">
                    <CurrencyIcon code={it.currency} size="md" />
                    <div>
                      <div className="font-mono text-sm text-neutral-200">
                        {Number(it.amount).toLocaleString(undefined, { maximumFractionDigits: 6 })}
                        <span className="text-neutral-500 ml-1">{it.currency}</span>
                      </div>
                      <div className="text-[0.6rem] text-neutral-600 font-mono">
                        1 {it.currency} ≈ {Number(it.rate).toFixed(6)} USDT
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <ArrowRightLeft className="w-3.5 h-3.5 text-[#8B5CF6]" />
                    <div className="font-mono text-sm text-[#22C55E]">
                      +{Number(it.usdt_equivalent).toFixed(4)}
                      <span className="text-neutral-500 ml-1">USDT</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div className="grid grid-cols-2 gap-3 text-sm bg-[#0a0a0a] border border-white/5 p-3">
              <div>
                <div className="micro-label text-neutral-500 mb-1">
                  {t("dustSweep.totalLabel")}
                </div>
                <div
                  className="font-mono text-[#22C55E]"
                  data-testid="dust-sweep-total"
                >
                  +{Number(preview.total_usdt || 0).toFixed(4)} USDT
                </div>
              </div>
              <div>
                <div className="micro-label text-neutral-500 mb-1">
                  {t("dustSweep.feeLabel")}
                </div>
                <div className="font-mono text-[#EF4444]">
                  −{Number(preview.fee_usdt || 0).toFixed(2)} USDT
                </div>
              </div>
              <div className="col-span-2 pt-2 border-t border-white/5">
                <div className="micro-label text-[#8B5CF6] mb-1">
                  {t("dustSweep.netLabel")}
                </div>
                <div
                  className="font-mono text-lg text-[#8B5CF6]"
                  data-testid="dust-sweep-net"
                >
                  +{Number(preview.net_usdt || 0).toFixed(4)} USDT
                </div>
              </div>
            </div>

            {!preview.can_convert && preview.reason === "usdt_fee_required" && (
              <div
                className="text-xs text-[#F59E0B] border border-[#F59E0B]/30 bg-[#F59E0B]/5 p-2"
                data-testid="dust-sweep-warn-fee"
              >
                {t("dustSweep.feeGuard", {
                  fee: preview.fee_usdt,
                  balance: preview.usdt_balance,
                })}
              </div>
            )}

            <div className="flex justify-end gap-2 pt-1">
              <Button
                type="button"
                variant="ghost"
                onClick={() => onOpenChange(false)}
                className="rounded-none text-neutral-400 hover:text-white hover:bg-white/5"
                data-testid="dust-sweep-cancel"
              >
                {t("common.cancel")}
              </Button>
              <Button
                type="button"
                disabled={busy || !preview.can_convert}
                onClick={submit}
                className="rounded-none bg-[#8B5CF6] hover:bg-[#8B5CF6]/90 text-white font-mono text-xs uppercase tracking-wider"
                data-testid="dust-sweep-confirm"
              >
                <Sparkles className="w-3.5 h-3.5 mr-2" />
                {busy ? t("dustSweep.working") : t("dustSweep.confirm")}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
