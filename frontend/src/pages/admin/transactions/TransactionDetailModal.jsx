import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import CopyableText from "@/components/CopyableText";
import ExplorerLink from "@/components/ExplorerLink";
import { extractCryptoNetwork } from "@/services/delivery_validators";
import { ArrowDown, ArrowUp, Download, Receipt, X, ExternalLink, Landmark, Wallet, AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { OriginBadge } from "./OriginBadge";
import { originOf } from "./originMeta";

// Cuenta de cobro de la empresa (entradas) + a qué se acreditó (depósitos).
function AccountAndCreditBlock({ selected, t }) {
  const isDeposit = selected.ref_type === "deposit";
  const showsAccount = selected.direction === "in" && (isDeposit || selected.ref_type === "order");
  if (!showsAccount) return null;
  const needsAccount = isDeposit ? selected.method !== "cash" : true;
  return (
    <div className="border border-white/5 p-4 bg-[#0a0a0a] space-y-3" data-testid="tx-account-block">
      <div>
        <div className="micro-label text-neutral-500 mb-1 flex items-center gap-1.5">
          <Landmark className="w-3 h-3" /> {t("admin.transactions.accountLabel")}
        </div>
        {selected.payment_account_label ? (
          <div data-testid="tx-account-value">
            <div className="text-emerald-400 font-medium">{selected.payment_account_label}</div>
            {selected.payment_account_details && (
              <pre className="text-xs text-neutral-400 whitespace-pre-wrap font-mono mt-1">{selected.payment_account_details}</pre>
            )}
          </div>
        ) : needsAccount ? (
          <div className="text-xs text-amber-400 flex items-start gap-1.5" data-testid="tx-account-missing">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span>
              {t("admin.transactions.accountMissing")}
              {isDeposit && ` ${t("admin.transactions.accountMissingDepositHint")}`}
            </span>
          </div>
        ) : (
          <div className="text-xs text-neutral-500">{t("admin.transactions.accountCashNA")}</div>
        )}
      </div>
      {isDeposit && (
        <div data-testid="tx-credited-block">
          <div className="micro-label text-neutral-500 mb-1 flex items-center gap-1.5">
            <Wallet className="w-3 h-3" /> {t("admin.transactions.creditedTo")}
          </div>
          <div className="text-sm text-neutral-200">
            {t("admin.transactions.creditedToValue", { currency: selected.currency, client: selected.client_name || "—" })}
          </div>
          <div className="text-xs text-neutral-500 mt-1">{t("admin.transactions.noMarginHint")}</div>
        </div>
      )}
    </div>
  );
}

export function TransactionDetailModal({ selected, onClose, onNavigate }) {
  const { t } = useTranslation();
  if (!selected) {
    // Keep the Dialog mounted but with no selected data → closed.
    return (
      <Dialog open={false} onOpenChange={onClose}>
        <DialogContent className="hidden" />
      </Dialog>
    );
  }
  const origin = originOf(selected.ref_type);

  return (
    <Dialog open={!!selected} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        data-testid="tx-detail-modal"
        className="bg-[#0c0c0c] border border-white/10 text-white max-w-2xl rounded-none max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-white flex-wrap">
            <Receipt className="w-5 h-5 text-[#8B5CF6]" />
            {t("admin.transactions.detailTitle")}
            {selected.direction === "in" ? (
              <span className="ml-2 text-[#22C55E] text-xs font-bold uppercase flex items-center gap-1">
                <ArrowDown className="w-3 h-3" /> {t("admin.transactions.in")}
              </span>
            ) : (
              <span className="ml-2 text-[#EF4444] text-xs font-bold uppercase flex items-center gap-1">
                <ArrowUp className="w-3 h-3" /> {t("admin.transactions.out")}
              </span>
            )}
            <OriginBadge refType={selected.ref_type} testid="tx-modal-origin" />
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 text-sm">
          <div className="text-xs text-neutral-400 border-l-2 border-[#8B5CF6]/60 pl-3" data-testid="tx-origin-explainer">
            {t(`admin.transactions.originExplainer.${selected.ref_type}`, t("admin.transactions.originExplainer.default"))}
          </div>
          <div className="grid grid-cols-2 gap-3 border border-white/5 p-4 bg-[#0a0a0a]">
            <div>
              <div className="micro-label text-neutral-500 mb-1">{t("admin.transactions.colCurrency")}</div>
              <div className="font-mono text-[#8B5CF6] text-lg">{selected.currency}</div>
            </div>
            <div>
              <div className="micro-label text-neutral-500 mb-1">{t("admin.transactions.colAmount")}</div>
              <div className="font-mono text-xl">{selected.amount.toLocaleString()}</div>
            </div>
            <div>
              <div className="micro-label text-neutral-500 mb-1">{t("admin.transactions.colHolder")}</div>
              <div className="font-medium" data-testid="tx-modal-holder">
                {selected.holder_name || "—"}
              </div>
            </div>
            <div>
              <div className="micro-label text-neutral-500 mb-1">{t("admin.transactions.colClient")}</div>
              <div className="text-neutral-300">{selected.client_name}</div>
              <div className="text-xs text-neutral-500">{selected.client_email}</div>
            </div>
            <div>
              <div className="micro-label text-neutral-500 mb-1">{t("admin.transactions.colMethod")}</div>
              <div className="uppercase text-xs">
                {selected.method}
                {selected.method === "crypto" && selected.crypto_network && (
                  <span
                    data-testid="tx-detail-crypto-network"
                    className="ml-2 inline-flex items-center px-1.5 py-0.5 text-[0.6rem] uppercase tracking-wider bg-[#8B5CF6]/10 text-[#8B5CF6] border border-[#8B5CF6]/30 font-mono"
                  >
                    {selected.crypto_network}
                  </span>
                )}
              </div>
            </div>
            <div>
              <div className="micro-label text-neutral-500 mb-1">{t("admin.transactions.colStatus")}</div>
              <div className="uppercase text-xs text-[#22C55E]">{selected.status}</div>
            </div>
            <div className="col-span-2">
              <div className="micro-label text-neutral-500 mb-1">{t("admin.transactions.colDate")}</div>
              <div className="font-mono text-xs">
                {new Date(selected.created_at).toLocaleString()}
              </div>
            </div>
            <div className="col-span-2">
              <div className="micro-label text-neutral-500 mb-1">
                {t(`admin.transactions.idLabel.${origin.idKey}`)}
              </div>
              <div className="font-mono text-xs text-neutral-400" data-testid="tx-modal-ref-id">{selected.ref_id}</div>
            </div>
          </div>

          <AccountAndCreditBlock selected={selected} t={t} />

          {selected.delivery_details && (
            <div className="border border-white/5 p-4 bg-[#0a0a0a]">
              <div className="micro-label text-neutral-500 mb-2 flex items-center justify-between gap-2">
                <span>
                  {selected.direction === "in" ? t("admin.transactions.sendData") : t("admin.transactions.beneficiaryData")}
                </span>
              </div>
              <div className="text-sm text-neutral-300">
                <CopyableText
                  value={selected.delivery_details}
                  label={t("admin.transactions.copy")}
                  toastMessage={
                    selected.method === "crypto" ? t("admin.transactions.walletCopied") : t("admin.transactions.dataCopied")
                  }
                  testid="tx-copy-delivery-details"
                  className="whitespace-pre-wrap"
                />
              </div>
            </div>
          )}

          {selected.admin_note && (
            <div className="border border-[#8B5CF6]/30 p-4 bg-[#8B5CF6]/5">
              <div className="micro-label text-[#8B5CF6] mb-2">{t("admin.transactions.adminNote")}</div>
              <div className="text-sm text-neutral-300">{selected.admin_note}</div>
            </div>
          )}

          {/* iter55.19f — on-chain payout hash + explorer link. Only visible
              for crypto salidas that have a hash recorded. Works for both
              withdrawals (crypto_network stored) and orders (network inferred
              from delivery_details). */}
          {selected.method === "crypto" && selected.payout_tx_hash && (
            <div className="border border-[#22C55E]/30 p-4 bg-[#22C55E]/5">
              <div className="micro-label text-[#22C55E] mb-2">
                {t("admin.transactions.payoutHash")}
              </div>
              <div className="text-xs flex items-start flex-wrap gap-2">
                <span className="text-[#22C55E]">
                  <CopyableText
                    value={selected.payout_tx_hash}
                    label={t("admin.transactions.copyHash")}
                    toastMessage={t("admin.transactions.hashCopied")}
                    testid="tx-payout-hash-copy"
                  />
                </span>
                <ExplorerLink
                  network={
                    selected.crypto_network
                    || extractCryptoNetwork(selected.delivery_details, selected.method)
                  }
                  txHash={selected.payout_tx_hash}
                  testid="tx-payout-explorer-link"
                />
              </div>
            </div>
          )}

          {selected.ref_type === "deposit" && selected.method === "crypto" && selected.tx_hash && (
            <div className="border border-[#22C55E]/30 p-4 bg-[#22C55E]/5" data-testid="tx-deposit-hash-block">
              <div className="micro-label text-[#22C55E] mb-2">
                {t("admin.transactions.depositHash")}
              </div>
              <div className="text-xs flex items-start flex-wrap gap-2">
                <span className="text-[#22C55E]">
                  <CopyableText
                    value={selected.tx_hash}
                    label={t("admin.transactions.copyHash")}
                    toastMessage={t("admin.transactions.hashCopied")}
                    testid="tx-deposit-hash-copy"
                  />
                </span>
                <ExplorerLink
                  network={selected.crypto_network}
                  txHash={selected.tx_hash}
                  testid="tx-deposit-explorer-link"
                />
              </div>
            </div>
          )}

          {(selected.direction === "in" || selected.ref_type === "order_payout") && (
            <div>
              <div className="micro-label text-neutral-500 mb-2 flex items-center justify-between">
                <span>
                  {selected.ref_type === "order_payout"
                    ? t("admin.transactions.proofPayout")
                    : t("admin.transactions.proofTransfer")}
                </span>
                {selected.proof_image && (
                  <a
                    href={selected.proof_image}
                    download={`comprobante_${selected.ref_id?.slice(0, 8)}.png`}
                    data-testid="tx-proof-download"
                    className="text-[#8B5CF6] hover:underline normal-case tracking-normal flex items-center gap-1"
                  >
                    <Download className="w-3 h-3" /> {t("admin.transactions.download")}
                  </a>
                )}
              </div>
              {selected.proof_image ? (
                <a
                  href={selected.proof_image}
                  target="_blank"
                  rel="noreferrer"
                  data-testid="tx-proof-open"
                  className="block border border-white/10 bg-[#0a0a0a] p-2"
                >
                  <img
                    src={selected.proof_image}
                    alt="Comprobante"
                    className="w-full max-h-96 object-contain bg-black"
                    onError={(e) => { e.currentTarget.style.display = "none"; }}
                  />
                </a>
              ) : (
                <div className="border border-dashed border-white/10 p-6 text-center text-neutral-600 text-xs">
                  {t("admin.transactions.noProof")}
                </div>
              )}
            </div>
          )}

          {selected.direction === "out" && selected.ref_type !== "order_payout" && (
            <div className="border border-dashed border-white/10 p-4 text-center text-xs text-neutral-500">
              <X className="w-4 h-4 inline mr-1" />
              {t("admin.transactions.outNoProof")}
            </div>
          )}

          <div className="pt-2 flex justify-end">
            <Button
              data-testid="tx-modal-goto-source"
              onClick={() => onNavigate(selected)}
              className="rounded-none bg-[#8B5CF6] hover:bg-[#8B5CF6]/90 text-white font-bold h-10 px-4 text-xs uppercase tracking-wider"
            >
              <ExternalLink className="w-3.5 h-3.5 mr-2" />
              {t(`admin.transactions.goTo.${origin.go}`)}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
