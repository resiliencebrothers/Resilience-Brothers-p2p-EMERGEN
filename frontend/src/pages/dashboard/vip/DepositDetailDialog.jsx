import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Clock, CheckCircle2, XCircle, Bike } from "lucide-react";
import CopyableText from "@/components/CopyableText";
import ExplorerLink from "@/components/ExplorerLink";
import CurrencyIcon from "@/components/CurrencyIcon";
import DeliveryTrackDialog from "@/components/DeliveryTrackDialog";

const STATUS_BIG = {
  pending: { cls: "bg-amber-500/10 text-amber-400 border-amber-500/30", Icon: Clock },
  confirmed: { cls: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30", Icon: CheckCircle2 },
  rejected: { cls: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30", Icon: XCircle },
};

const fmtDateTime = (v) => (v ? new Date(v).toLocaleString() : "");

function InfoRow({ label, children, testid }) {
  return (
    <div className="flex items-start justify-between gap-4 text-sm py-1.5" data-testid={testid}>
      <span className="text-neutral-500 shrink-0">{label}</span>
      <span className="text-white text-right break-all min-w-0">{children}</span>
    </div>
  );
}

/**
 * iter153 — Exchange-style deposit detail (mirrors the BingX "Detalles del
 * depósito" view): amount, big status pill, method, network, TxID with
 * copy + block-explorer link, timestamps and staff notes.
 */
export function DepositDetailDialog({ d, onClose }) {
  const { t } = useTranslation();
  const [trackingOpen, setTrackingOpen] = useState(false);
  if (!d) return null;
  const st = STATUS_BIG[d.status] || STATUS_BIG.pending;
  const StIcon = st.Icon;

  return (
    <Dialog open={!!d} onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        data-testid="deposit-detail-dialog"
        className="bg-[#0c0c0c] border border-emerald-500/30 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="text-center">{t("deposits.detail.title")}</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col items-center text-center gap-2 py-1">
          <CurrencyIcon code={d.currency} size="lg" />
          <div className="text-xs text-neutral-500 uppercase tracking-widest">
            {t("deposits.detail.amountLabel", { currency: d.currency })}
          </div>
          <div className="font-mono text-4xl tracking-tight text-emerald-400" data-testid="deposit-detail-amount">
            +{Number(d.amount).toLocaleString(undefined, { maximumFractionDigits: 4 })}
          </div>
          <span className={`inline-flex items-center gap-1.5 text-xs uppercase tracking-widest px-3 py-1.5 border font-mono ${st.cls}`} data-testid="deposit-detail-status">
            <StIcon className="w-3.5 h-3.5" />
            {t(`deposits.detail.statusBig.${d.status}`, d.status)}
          </span>
        </div>

        <div className="border-t border-white/10 pt-3 space-y-0.5">
          <InfoRow label={t("deposits.detail.methodLabel")}>
            {t(`methodPicker.options.${d.method}.label`, d.method)}
            {d.cash_mode ? ` · ${t(`deposits.cashMode.${d.cash_mode}`, d.cash_mode)}` : ""}
          </InfoRow>
          {d.network && (
            <InfoRow label={t("deposits.detail.networkLabel")} testid={`deposit-detail-network-${d.id}`}>
              {d.network}
            </InfoRow>
          )}
          {d.tx_hash && (
            <InfoRow label={t("deposits.detail.txidLabel")} testid={`deposit-detail-hash-${d.id}`}>
              <span className="font-mono text-xs text-[#22C55E]">
                <CopyableText
                  value={d.tx_hash}
                  label={d.tx_hash}
                  toastMessage={t("withdraw.detail.txidCopied")}
                  testid={`deposit-hash-copy-${d.id}`}
                />
              </span>
            </InfoRow>
          )}
          {d.account_holder && (
            <InfoRow label={t("deposits.detail.holderLabel")}>{d.account_holder}</InfoRow>
          )}
          <InfoRow label={t("deposits.detail.timeLabel")}>
            <span className="text-xs">{fmtDateTime(d.created_at)}</span>
          </InfoRow>
          {d.reviewed_at && (
            <InfoRow label={t("deposits.detail.reviewedLabel")}>
              <span className="text-xs">{fmtDateTime(d.reviewed_at)}</span>
            </InfoRow>
          )}
          {d.note && (
            <InfoRow label={t("deposits.detail.noteLabel")}>
              <span className="text-xs">{d.note}</span>
            </InfoRow>
          )}
          {d.admin_note && (
            <InfoRow label={t("deposits.detail.staffNote")}>
              <span className="text-xs italic text-neutral-300">{d.admin_note}</span>
            </InfoRow>
          )}
        </div>

        {(d.tx_hash || d.proof_url) && (
          <div className="flex flex-wrap items-center gap-2">
            {d.tx_hash && d.network && (
              <ExplorerLink
                network={d.network}
                txHash={d.tx_hash}
                testid={`deposit-explorer-${d.id}`}
              />
            )}
            {d.proof_url && (
              <a
                href={d.proof_url}
                target="_blank"
                rel="noreferrer"
                className="text-xs text-[#8B5CF6] underline underline-offset-4"
                data-testid={`deposit-proof-link-${d.id}`}
              >
                {t("deposits.detail.proofLink")}
              </a>
            )}
          </div>
        )}

        {/* iter208 — botón "Seguir recogida" para depósitos cash-courier */}
        {d.method === "cash" && d.cash_mode === "courier"
          && d.status === "pending" && (
          <Button
            data-testid={`open-tracking-${d.id}`}
            onClick={() => setTrackingOpen(true)}
            className="w-full rounded-none bg-[#8B5CF6]/10 hover:bg-[#8B5CF6]/20 border border-[#8B5CF6]/40 text-[#A78BFA] h-11"
          >
            <Bike className="w-4 h-4 mr-2" /> {t("tracker.openBtn")}
          </Button>
        )}

        <DeliveryTrackDialog
          refId={d.id}
          open={trackingOpen}
          onClose={() => setTrackingOpen(false)}
        />
      </DialogContent>
    </Dialog>
  );
}
