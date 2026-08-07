import { useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Check, X, Ban, Clock } from "lucide-react";
import CopyableText from "@/components/CopyableText";
import ExplorerLink from "@/components/ExplorerLink";
import CurrencyIcon from "@/components/CurrencyIcon";

const STATUS_RANK = { pending: 1, approved: 2, paid: 3 };

const fmtDateTime = (v) => (v ? new Date(v).toLocaleString() : "");

function StepDot({ state }) {
  if (state === "done") {
    return (
      <span className="w-5 h-5 rounded-full bg-[#8B5CF6] flex items-center justify-center shrink-0">
        <Check className="w-3 h-3 text-white" />
      </span>
    );
  }
  if (state === "current") {
    return (
      <span className="w-5 h-5 rounded-full border-2 border-[#8B5CF6] flex items-center justify-center shrink-0">
        <span className="w-2 h-2 rounded-full bg-[#8B5CF6] animate-pulse" />
      </span>
    );
  }
  if (state === "bad") {
    return (
      <span className="w-5 h-5 rounded-full bg-[#EF4444] flex items-center justify-center shrink-0">
        <X className="w-3 h-3 text-white" />
      </span>
    );
  }
  return <span className="w-5 h-5 rounded-full border border-white/20 shrink-0" />;
}

function InfoRow({ label, children, testid }) {
  return (
    <div className="flex items-start justify-between gap-4 text-sm py-1.5" data-testid={testid}>
      <span className="text-neutral-500 shrink-0">{label}</span>
      <span className="text-white text-right break-all min-w-0">{children}</span>
    </div>
  );
}

/**
 * iter153 — Exchange-style withdrawal detail: BingX-like progress timeline
 * (Solicitud enviada → Bajo revisión → Retirando → Retiro exitoso), full
 * payout info (address, network, TxID + explorer, proof) and self-service
 * cancellation while the request is still pending.
 */
export function WithdrawalDetailDialog({ w, onClose, onChanged }) {
  const { t } = useTranslation();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  if (!w) return null;

  const rank = STATUS_RANK[w.status] || 0;
  const terminalBad = w.status === "rejected" || w.status === "cancelled";

  const cancelWithdrawal = async () => {
    setBusy(true);
    try {
      await axios.post(`${API}/vip/withdrawals/${w.id}/cancel`, {}, { withCredentials: true });
      toast.success(t("withdraw.detail.cancelledToast"));
      onChanged?.();
      onClose();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("withdraw.detail.cancelError"));
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  };

  const steps = terminalBad
    ? [
      { key: "sent", label: t("withdraw.detail.steps.sent"), sub: fmtDateTime(w.created_at), state: "done" },
      {
        key: "terminal",
        label: w.status === "rejected" ? t("withdraw.detail.rejectedTitle") : t("withdraw.detail.cancelledTitle"),
        sub: t("withdraw.detail.refundNote"),
        state: "bad",
      },
    ]
    : [
      { key: "sent", label: t("withdraw.detail.steps.sent"), sub: fmtDateTime(w.created_at), state: "done" },
      {
        key: "review",
        label: t("withdraw.detail.steps.review"),
        sub: rank >= 2 ? t("withdraw.detail.steps.reviewOk") : t("withdraw.detail.steps.reviewWait"),
        state: rank >= 2 ? "done" : "current",
      },
      {
        key: "processing",
        label: t("withdraw.detail.steps.processing"),
        sub: rank === 2 ? t("withdraw.detail.steps.processingSub") : "",
        state: rank >= 3 ? "done" : rank === 2 ? "current" : "todo",
      },
      {
        key: "done",
        label: t("withdraw.detail.steps.done"),
        sub: rank >= 3 ? fmtDateTime(w.paid_at) : "",
        state: rank >= 3 ? "done" : "todo",
      },
    ];

  const isCrypto = w.method === "crypto";

  return (
    <Dialog open={!!w} onOpenChange={(o) => !o && !busy && onClose()}>
      <DialogContent
        data-testid="withdrawal-detail-dialog"
        className="bg-[#0c0c0c] border border-[#8B5CF6]/30 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="text-center">{t("withdraw.detail.title")}</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col items-center text-center gap-2 py-1">
          <CurrencyIcon code={w.currency || "USD"} size="lg" />
          <div className="text-xs text-neutral-500 uppercase tracking-widest">
            {t("withdraw.detail.amountArrival", { currency: w.currency || "USD" })}
          </div>
          <div className="font-mono text-4xl tracking-tight" data-testid="withdrawal-detail-amount">
            -{Number(w.amount_usd).toLocaleString(undefined, { maximumFractionDigits: 4 })}
          </div>
          {w.status === "approved" && (
            <div className="text-xs text-amber-400 bg-amber-500/10 border border-amber-500/30 px-3 py-1.5 flex items-center gap-1.5" data-testid="withdrawal-inprogress-note">
              <Clock className="w-3.5 h-3.5" />
              {t("withdraw.detail.inProgressNote")}
            </div>
          )}
        </div>

        <ol className="mt-2" data-testid="withdrawal-timeline">
          {steps.map((s, i) => (
            <li key={s.key} className="flex gap-3" data-testid={`timeline-step-${s.key}`}>
              <div className="flex flex-col items-center">
                <StepDot state={s.state} />
                {i < steps.length - 1 && (
                  <div className={`w-px flex-1 min-h-[20px] ${s.state === "done" ? "bg-[#8B5CF6]/60" : "bg-white/10"}`} />
                )}
              </div>
              <div className="pb-4">
                <div className={`text-sm font-semibold leading-5 ${
                  s.state === "bad" ? "text-[#EF4444]" : s.state === "todo" ? "text-neutral-600" : "text-white"
                }`}>
                  {s.label}
                </div>
                {s.sub && <div className="text-xs text-neutral-500 mt-0.5">{s.sub}</div>}
              </div>
            </li>
          ))}
        </ol>

        <div className="border-t border-white/10 pt-3 space-y-0.5">
          <InfoRow label={t("withdraw.detail.methodLabel")}>
            {t(`methodPicker.options.${w.method}.label`, w.method)}
          </InfoRow>
          {w.crypto_network && (
            <InfoRow label={t("withdraw.detail.networkLabel")} testid={`withdrawal-detail-network-${w.id}`}>
              {w.crypto_network}
            </InfoRow>
          )}
          <InfoRow label={isCrypto ? t("withdraw.detail.addressLabel") : t("withdraw.detail.detailsLabel")}>
            {isCrypto ? (
              <span className="font-mono text-xs">
                <CopyableText
                  value={w.details}
                  label={w.details}
                  toastMessage={t("withdraw.detail.addressCopied")}
                  testid={`withdrawal-detail-address-${w.id}`}
                />
              </span>
            ) : (
              <span className="text-xs whitespace-pre-wrap">{w.details}</span>
            )}
          </InfoRow>
          {w.beneficiary_name && (
            <InfoRow label={t("withdraw.detail.beneficiaryLabel")}>{w.beneficiary_name}</InfoRow>
          )}
          {w.payout_tx_hash && (
            <InfoRow label={t("withdraw.detail.txidLabel")} testid={`payout-hash-${w.id}`}>
              <span className="font-mono text-xs text-[#22C55E]">
                <CopyableText
                  value={w.payout_tx_hash}
                  label={w.payout_tx_hash}
                  toastMessage={t("withdraw.detail.txidCopied")}
                  testid={`payout-hash-copy-${w.id}`}
                />
              </span>
            </InfoRow>
          )}
          <InfoRow label={t("withdraw.detail.requestedAt")}>
            <span className="text-xs">{fmtDateTime(w.created_at)}</span>
          </InfoRow>
          {w.status === "paid" && w.paid_at && (
            <InfoRow label={t("withdraw.detail.paidAt")}>
              <span className="text-xs">{fmtDateTime(w.paid_at)}</span>
            </InfoRow>
          )}
          {w.admin_note && (
            <InfoRow label={t("withdraw.detail.staffNote")}>
              <span className="text-xs italic text-neutral-300">{w.admin_note}</span>
            </InfoRow>
          )}
        </div>

        {(w.payout_tx_hash || w.payout_proof_image) && (
          <div className="flex flex-wrap items-center gap-2">
            {w.payout_tx_hash && (
              <ExplorerLink
                network={w.crypto_network}
                txHash={w.payout_tx_hash}
                testid={`payout-explorer-${w.id}`}
              />
            )}
            {w.payout_proof_image && (
              <a
                href={w.payout_proof_image}
                target="_blank"
                rel="noreferrer"
                className="text-xs text-[#8B5CF6] underline underline-offset-4"
                data-testid={`payout-proof-${w.id}`}
              >
                {t("withdraw.detail.proofLink")}
              </a>
            )}
          </div>
        )}

        {w.status === "pending" && (
          confirming ? (
            <div className="border border-[#EF4444]/40 bg-[#EF4444]/5 p-3 space-y-2" data-testid="cancel-confirm-box">
              <div className="text-sm font-semibold">{t("withdraw.detail.cancelConfirmTitle")}</div>
              <div className="text-xs text-neutral-400">{t("withdraw.detail.cancelConfirmBody")}</div>
              <div className="flex gap-2">
                <Button
                  data-testid="cancel-withdrawal-yes"
                  disabled={busy}
                  onClick={cancelWithdrawal}
                  className="flex-1 rounded-none bg-[#EF4444] hover:bg-[#DC2626] text-white h-10"
                >
                  {busy ? "…" : t("withdraw.detail.cancelYes")}
                </Button>
                <Button
                  data-testid="cancel-withdrawal-no"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => setConfirming(false)}
                  className="flex-1 rounded-none border border-white/10 text-neutral-300 h-10"
                >
                  {t("withdraw.detail.cancelNo")}
                </Button>
              </div>
            </div>
          ) : (
            <Button
              data-testid="cancel-withdrawal-btn"
              variant="ghost"
              onClick={() => setConfirming(true)}
              className="w-full rounded-none border border-[#EF4444]/40 text-[#EF4444] hover:bg-[#EF4444]/10 hover:text-[#EF4444] h-11"
            >
              <Ban className="w-4 h-4 mr-2" /> {t("withdraw.detail.cancelBtn")}
            </Button>
          )
        )}
      </DialogContent>
    </Dialog>
  );
}
