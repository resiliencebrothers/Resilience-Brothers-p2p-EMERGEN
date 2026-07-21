import { useRef } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import CopyableText from "@/components/CopyableText";
import CashDetailsTable, { parseCashDetails } from "@/components/CashDetailsTable";
import ExplorerLink from "@/components/ExplorerLink";
import { validateCryptoHash, findNetwork } from "@/services/cryptoValidators";

export default function WithdrawalDialog({
  open, onClose,
  note, onNoteChange,
  payoutProof, onPayoutProofChange,
  payoutHash, onPayoutHashChange,
  statusLabel,
  onProofUpload,
  onAskChange,
}) {
  const { t } = useTranslation();
  const fileRef = useRef(null);

  return (
    <Dialog open={!!open} onOpenChange={onClose}>
      <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-w-lg max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-display">{t("admin.withdrawals.dialogTitle", { id: open?.id?.slice(0, 8) })}</DialogTitle>
          <DialogDescription className="text-neutral-500 text-xs">
            {t("admin.withdrawals.dialogDesc")}
          </DialogDescription>
        </DialogHeader>
        {open && (
          <div className="space-y-4">
            <WithdrawalInfoBlock w={open} statusLabel={statusLabel} />
            <Textarea
              value={note}
              onChange={(e) => onNoteChange(e.target.value)}
              placeholder={t("admin.withdrawals.notePlaceholder")}
              rows={2}
              className="rounded-none bg-[#0a0a0a] border-white/10"
            />
            <PayoutEvidenceBlock
              w={open}
              payoutProof={payoutProof}
              payoutHash={payoutHash}
              onPayoutHashChange={onPayoutHashChange}
              onPayoutProofChange={onPayoutProofChange}
              onProofUpload={onProofUpload}
              fileRef={fileRef}
            />
            <div className="grid grid-cols-3 gap-2">
              <Button data-testid="withdrawal-approve" onClick={() => onAskChange("approved")} className="bg-[#22C55E] text-black rounded-none">
                {open.method === "cash" ? t("admin.withdrawals.approveInProgress") : t("admin.withdrawals.approveConfirm")}
              </Button>
              <Button data-testid="withdrawal-pay" onClick={() => onAskChange("paid")} className="bg-[#8B5CF6] text-white rounded-none">
                {open.method === "cash" ? t("admin.withdrawals.payDelivered") : t("admin.withdrawals.payPaid")}
              </Button>
              <Button data-testid="withdrawal-reject" onClick={() => onAskChange("rejected")} className="bg-[#EF4444] text-white rounded-none">
                {t("admin.withdrawals.reject")}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function WithdrawalInfoBlock({ w, statusLabel }) {
  const { t } = useTranslation();
  return (
    <div className="font-mono text-sm space-y-1">
      <div><span className="text-neutral-500">{t("admin.withdrawals.fClient")}</span> {w.user_name}</div>
      <div><span className="text-neutral-500">{t("admin.withdrawals.fAmount")}</span> {w.amount_usd} {w.currency || "USD"}</div>
      <div><span className="text-neutral-500">{t("admin.withdrawals.fMethod")}</span> {w.method}</div>
      {w.method === "crypto" && w.crypto_network && (
        <div data-testid="withdrawal-modal-network">
          <span className="text-neutral-500">{t("admin.withdrawals.fNetwork")}</span>{" "}
          <span className="inline-flex items-center px-1.5 py-0.5 text-[0.7rem] uppercase tracking-wider bg-[#8B5CF6]/10 text-[#8B5CF6] border border-[#8B5CF6]/30 font-mono ml-1">
            {w.crypto_network}
          </span>
        </div>
      )}
      <div className="flex items-start gap-2 flex-wrap">
        <span className="text-neutral-500 flex-shrink-0">
          {w.method === "crypto" ? t("admin.withdrawals.fWallet") : t("admin.withdrawals.fDetails")}
        </span>
        {w.method === "cash" && parseCashDetails(w.details) ? (
          <div className="flex-1 min-w-0 space-y-2">
            <CashDetailsTable details={w.details} />
            <CopyableText
              value={w.details}
              label={t("admin.withdrawals.copyFullBlock")}
              toastMessage={t("admin.withdrawals.copyDetailsToast")}
              testid="withdrawal-copy-details"
            />
          </div>
        ) : (
          <CopyableText
            value={w.details}
            label={w.method === "crypto" ? t("admin.withdrawals.copyWallet") : t("admin.withdrawals.copyDetails")}
            toastMessage={w.method === "crypto" ? t("admin.withdrawals.copyWalletToast") : t("admin.withdrawals.copyDetailsToast")}
            testid="withdrawal-copy-details"
          />
        )}
      </div>
      <div className="flex items-start gap-2 flex-wrap">
        <span className="text-neutral-500 flex-shrink-0">{t("admin.withdrawals.fBeneficiary")}</span>
        {w.beneficiary_name ? (
          <CopyableText
            value={w.beneficiary_name}
            label={t("admin.withdrawals.copyBeneficiary")}
            toastMessage={t("admin.withdrawals.copyBeneficiaryToast")}
            testid="withdrawal-copy-beneficiary"
            monospace={false}
          />
        ) : (
          <span>—</span>
        )}
      </div>
      <div>
        <span className="text-neutral-500">{t("admin.withdrawals.fStatus")}</span>{" "}
        <span className="uppercase tracking-wider">{statusLabel(w.status, w.method)}</span>
      </div>
    </div>
  );
}

function PayoutEvidenceBlock({ w, payoutProof, payoutHash, onPayoutHashChange, onProofUpload, fileRef }) {
  const { t } = useTranslation();
  return (
    <div className="border border-white/10 p-3 space-y-3 bg-[#0a0a0a]/50">
      <div className="micro-label text-[#8B5CF6]">
        {w.method === "crypto" ? t("admin.withdrawals.payoutTxHash") : t("admin.withdrawals.payoutEvidence")}
      </div>
      {w.method === "crypto" ? (
        <CryptoHashInput w={w} payoutHash={payoutHash} onPayoutHashChange={onPayoutHashChange} />
      ) : (
        <TransferProofInput w={w} payoutProof={payoutProof} onProofUpload={onProofUpload} fileRef={fileRef} />
      )}
    </div>
  );
}

function CryptoHashInput({ w, payoutHash, onPayoutHashChange }) {
  const { t } = useTranslation();
  return (
    <div>
      <Input
        data-testid="payout-tx-hash"
        value={payoutHash}
        onChange={(e) => onPayoutHashChange(e.target.value)}
        placeholder={
          w.crypto_network
            ? findNetwork(w.crypto_network).hashPlaceholder
            : t("admin.withdrawals.hashPlaceholder")
        }
        className="rounded-none bg-[#0a0a0a] border-white/10 h-11 font-mono text-xs"
      />
      {payoutHash && w.crypto_network && (
        validateCryptoHash(payoutHash, w.crypto_network) ? (
          <p
            data-testid="payout-hash-match-ok"
            className="text-[0.7rem] text-[#22C55E] mt-1.5 flex items-center gap-1.5"
          >
            <span aria-hidden>✓</span>
            <span>{t("withdraw.networkMatchOk")} <strong>{findNetwork(w.crypto_network).label}</strong></span>
          </p>
        ) : (
          <p
            data-testid="payout-hash-mismatch"
            className="text-[0.7rem] text-[#EF4444] mt-1.5 flex items-start gap-1.5 leading-relaxed"
          >
            <span aria-hidden className="mt-0.5">⚠</span>
            <span>
              <strong>{t("withdraw.networkMismatch")} {findNetwork(w.crypto_network).label}</strong>. {t("withdraw.networkMismatchHint")}
            </span>
          </p>
        )
      )}
      {w.payout_tx_hash && (
        <div className="mt-2 flex items-center flex-wrap gap-2">
          <ExplorerLink
            network={w.crypto_network}
            txHash={w.payout_tx_hash}
            testid="admin-withdrawal-explorer-link"
          />
          <span className="text-[0.65rem] text-neutral-500">
            {t("admin.withdrawals.explorerHint")}
          </span>
        </div>
      )}
      <p className="text-[0.65rem] text-neutral-500 mt-2 leading-relaxed">
        {t("admin.withdrawals.hashHelper")}
      </p>
    </div>
  );
}

function TransferProofInput({ payoutProof, onProofUpload, fileRef }) {
  const { t } = useTranslation();
  return (
    <div>
      <label className="micro-label text-neutral-500">
        {t("admin.withdrawals.captureLabel")}
      </label>
      <input
        ref={fileRef}
        data-testid="payout-proof-input"
        type="file"
        accept="image/*"
        onChange={onProofUpload}
        className="block mt-1 text-xs text-neutral-400"
      />
      {payoutProof && (
        <div className="mt-2">
          <img src={payoutProof} alt="proof" className="max-h-40 border border-white/10" data-testid="payout-proof-preview" />
        </div>
      )}
    </div>
  );
}
