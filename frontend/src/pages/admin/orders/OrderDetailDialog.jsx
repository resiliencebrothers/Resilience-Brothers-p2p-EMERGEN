import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Upload } from "lucide-react";
import { getDeliveryBadge, extractCryptoNetwork, NETWORK_META } from "@/services/delivery_validators";
import CopyBtn from "./CopyBtn";
import CurrencyPairIcon from "@/components/CurrencyPairIcon";

const STATUS_KEYS = {
  pending: "admin.orders.statusPending",
  requires_double_approval: "admin.orders.statusDoubleApproval",
  approved: "admin.orders.statusApproved",
  completed: "admin.orders.statusCompleted",
  rejected: "admin.orders.statusRejected",
};

/**
 * Order-detail modal with client info, delivery block, payout evidence
 * and the approve/complete/reject action buttons.
 * Fully controlled by the parent (AdminOrders).
 */
export default function OrderDetailDialog({
  open,
  isAdmin,
  note, onNoteChange,
  payoutProof, onPayoutProofChange,
  payoutHash, onPayoutHashChange,
  onClose,
  onUpdateStatus,
  onPayoutUpload,
}) {
  const { t } = useTranslation();

  return (
    <Dialog open={!!open} onOpenChange={onClose}>
      <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-display">
            {t("admin.orders.dialogTitle", { id: open?.id?.slice(0, 8) })}
          </DialogTitle>
          <DialogDescription className="text-neutral-500 text-xs">
            {t("admin.orders.dialogDesc")}
          </DialogDescription>
        </DialogHeader>
        {open && (
          <div className="space-y-4">
            <OrderClientGrid order={open} />

            {open.delivery_details && (
              <DeliveryBlock order={open} />
            )}

            {open.proof_image && (
              <div>
                <div className="micro-label text-neutral-500 mb-2">{t("admin.orders.clientProof")}</div>
                <img src={open.proof_image} alt="proof" className="w-full max-h-96 object-contain border border-white/10" />
              </div>
            )}

            <PayoutEvidence
              order={open}
              payoutProof={payoutProof}
              payoutHash={payoutHash}
              onPayoutHashChange={onPayoutHashChange}
              onPayoutProofChange={onPayoutProofChange}
              onPayoutUpload={onPayoutUpload}
            />

            <Textarea
              value={note}
              onChange={(e) => onNoteChange(e.target.value)}
              placeholder={t("admin.orders.adminNotePlaceholder")}
              rows={2}
              className="rounded-none bg-[#0a0a0a] border-white/10"
            />

            <ActionButtons order={open} isAdmin={isAdmin} onUpdateStatus={onUpdateStatus} />

            {!isAdmin && (open?.status === "approved" || open?.status === "completed") && (
              <p className="text-[0.65rem] text-neutral-500 italic">
                {t("admin.orders.alreadyDone", { status: t(STATUS_KEYS[open.status]) })}
              </p>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function OrderClientGrid({ order: o }) {
  const { t } = useTranslation();
  return (
    <div className="grid grid-cols-2 gap-2 font-mono text-sm">
      <div><span className="text-neutral-500">{t("admin.orders.fClient")}</span> {o.user_name}</div>
      <div><span className="text-neutral-500">{t("admin.orders.fEmail")}</span> {o.user_email}</div>
      <div><span className="text-neutral-500">{t("admin.orders.fRole")}</span> {o.user_role}</div>
      <div className="flex items-center gap-2"><span className="text-neutral-500">{t("admin.orders.fPair")}</span> <CurrencyPairIcon from={o.from_code} to={o.to_code} size="sm" showLabel /></div>
      <div><span className="text-neutral-500">{t("admin.orders.fSends")}</span> {o.amount_from} {o.from_code}</div>
      <div><span className="text-neutral-500">{t("admin.orders.fReceives")}</span> {o.amount_to} {o.to_code}</div>
      <div><span className="text-neutral-500">{t("admin.orders.fRate")}</span> {o.rate_applied}</div>
      {o.commission_percent > 0 && (
        <div><span className="text-neutral-500">{t("admin.orders.fCommission")}</span> {o.commission_percent}%</div>
      )}
      <div className="col-span-2"><span className="text-neutral-500">{t("admin.orders.fHolder")}</span> {o.sender_name}</div>
    </div>
  );
}

function DeliveryBlock({ order: o }) {
  const { t } = useTranslation();
  const net = o.delivery_method === "crypto" ? extractCryptoNetwork(o.delivery_details, "crypto") : null;
  const meta = net ? NETWORK_META[net] : null;
  const badge = getDeliveryBadge(o.to_code, o.delivery_method, o.delivery_details);

  return (
    <div className="border border-white/10 bg-[#0a0a0a] p-3" data-testid="delivery-block">
      {meta && (
        <div
          data-testid={`admin-network-badge-${net}`}
          className="mb-3 flex items-center gap-3 border-l-4 pl-3 py-2"
          style={{ borderColor: meta.bg, background: `${meta.bg}12` }}
        >
          <span
            className="inline-flex items-center px-3 py-1.5 font-mono text-xs font-bold tracking-wider uppercase"
            style={{ background: meta.bg, color: meta.fg }}
          >
            {meta.label}
          </span>
          <span className="text-[0.7rem] text-neutral-400 leading-tight">
            {net === "AMBIGUOUS_0X"
              ? t("admin.orders.networkClientNotDeclared")
              : t("admin.orders.networkSendOn", { net })}
          </span>
        </div>
      )}

      <div className="micro-label text-neutral-500 mb-2 flex items-center justify-between">
        <span>{t("admin.orders.deliveryBlock", { method: o.delivery_method })}</span>
        {badge && (
          <span
            data-testid={badge.ok ? "delivery-badge-ok" : "delivery-badge-warn"}
            className={`text-[0.65rem] normal-case tracking-normal ${
              badge.ok ? "text-[#22C55E]" : "text-[#EF4444]"
            }`}
          >
            {badge.feedback}
          </span>
        )}
      </div>

      <div className="whitespace-pre-wrap font-mono text-sm text-neutral-200 break-words">
        {o.delivery_details}
      </div>

      <DeliveryCopyButtons order={o} />
    </div>
  );
}

function DeliveryCopyButtons({ order: o }) {
  const { t } = useTranslation();
  const digitsOnly = (o.delivery_details.match(/\d/g) || []).join("");
  const upperTo = (o.to_code || "").toUpperCase();
  const isCubanBank =
    o.delivery_method === "transfer" &&
    ["CUP", "CUPT", "CUPE"].includes(upperTo) &&
    digitsOnly.length === 16;
  const isClabe =
    o.delivery_method === "transfer" &&
    upperTo === "MXN" &&
    digitsOnly.length === 18;

  let extra = null;
  if (isCubanBank || isClabe) {
    extra = (
      <>
        <CopyBtn
          testid="copy-delivery-account-digits"
          label={t("admin.orders.copyAccountDigits", { n: digitsOnly.length })}
          value={digitsOnly}
        />
        <CopyBtn
          testid="copy-delivery-account-formatted"
          label={t("admin.orders.copyFormatted")}
          value={digitsOnly.match(/.{1,4}/g).join(" ")}
        />
      </>
    );
  } else if (o.delivery_method === "crypto") {
    const wallet = o.delivery_details.match(
      /(T[1-9A-HJ-NP-Za-km-z]{33}|0x[a-fA-F0-9]{40}|bc1[a-z0-9]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})/,
    );
    if (wallet) {
      extra = (
        <CopyBtn
          testid="copy-delivery-wallet"
          label={t("admin.orders.copyWallet", { short: `${wallet[0].slice(0, 6)}…${wallet[0].slice(-4)}` })}
          value={wallet[0]}
        />
      );
    }
  }

  return (
    <div className="flex flex-wrap gap-2 mt-3">
      <CopyBtn
        testid="copy-delivery-full"
        label={t("admin.orders.copyAll")}
        value={o.delivery_details}
      />
      {extra}
    </div>
  );
}

function PayoutEvidence({ order: o, payoutProof, payoutHash, onPayoutHashChange, onPayoutProofChange, onPayoutUpload }) {
  const { t } = useTranslation();
  if (o.delivery_method === "cash" || o.delivery_method === "accumulate") return null;

  return (
    <div className="border-t border-white/5 pt-4">
      <div className="micro-label text-[#8B5CF6] mb-2">
        {o.delivery_method === "crypto"
          ? t("admin.orders.payoutTxHash")
          : t("admin.orders.payoutTransfer")}
      </div>
      <p className="text-[0.7rem] text-neutral-500 mb-3 leading-relaxed">
        {o.delivery_method === "transfer"
          ? t("admin.orders.payoutHelperTransfer", { code: o.to_code })
          : t("admin.orders.payoutHelperCrypto")}
      </p>
      <div className="space-y-2">
        {o.delivery_method === "crypto" && (
          <Input
            data-testid="order-payout-tx-hash"
            value={payoutHash}
            onChange={(e) => onPayoutHashChange(e.target.value)}
            placeholder={t("admin.orders.payoutTxHash")}
            className="rounded-none bg-[#0a0a0a] border-white/10 h-11 font-mono text-xs"
          />
        )}
        {o.delivery_method === "transfer" && (
          <>
            <div className="flex items-center gap-2">
              <label className="flex-1 flex items-center gap-2 cursor-pointer bg-[#0a0a0a] border border-white/10 hover:border-[#8B5CF6]/40 px-3 py-2 text-xs text-neutral-300">
                <Upload className="w-3.5 h-3.5 text-[#8B5CF6]" />
                <span>{payoutProof ? t("admin.orders.changeScreenshot") : t("admin.orders.uploadScreenshot")}</span>
                <input
                  type="file"
                  accept="image/*"
                  onChange={onPayoutUpload}
                  data-testid="order-payout-proof-upload"
                  className="hidden"
                />
              </label>
              {payoutProof && (
                <button
                  type="button"
                  data-testid="order-payout-proof-clear"
                  onClick={() => onPayoutProofChange("")}
                  className="text-[0.7rem] text-neutral-500 hover:text-[#EF4444] underline underline-offset-4"
                >
                  {t("admin.orders.removeUpload")}
                </button>
              )}
            </div>
            {payoutProof && (
              <img
                src={payoutProof}
                alt={t("admin.orders.screenshotAlt")}
                data-testid="order-payout-proof-preview"
                className="w-full max-h-72 object-contain border border-[#8B5CF6]/30"
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}

function ActionButtons({ order: o, isAdmin, onUpdateStatus }) {
  const { t } = useTranslation();
  const lockedFromApprove = !isAdmin && (o?.status === "approved" || o?.status === "completed" || o?.status === "rejected");
  const lockedFromComplete = !isAdmin && (o?.status === "completed" || o?.status === "rejected");
  const lockedFromReject = lockedFromApprove;
  return (
    <div className="grid grid-cols-3 gap-2">
      <Button
        data-testid="approve-order"
        onClick={() => onUpdateStatus("approved")}
        disabled={lockedFromApprove}
        className="bg-[#22C55E] hover:bg-[#16A34A] text-black rounded-none disabled:opacity-40"
      >
        {t("admin.orders.confirmBtn")}
      </Button>
      <Button
        data-testid="complete-order"
        onClick={() => onUpdateStatus("completed")}
        disabled={lockedFromComplete}
        className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none disabled:opacity-40"
      >
        {t("admin.orders.completeBtn")}
      </Button>
      <Button
        data-testid="reject-order"
        onClick={() => onUpdateStatus("rejected")}
        disabled={lockedFromReject}
        className="bg-[#EF4444] hover:bg-[#DC2626] text-white rounded-none disabled:opacity-40"
      >
        {t("admin.orders.rejectBtn")}
      </Button>
    </div>
  );
}
