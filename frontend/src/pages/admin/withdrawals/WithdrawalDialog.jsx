import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Banknote } from "lucide-react";
import CopyableText from "@/components/CopyableText";
import CashDetailsTable, { parseCashDetails } from "@/components/CashDetailsTable";
import ExplorerLink from "@/components/ExplorerLink";
import FundAccountSelect from "@/components/FundAccountSelect";
import { validateCryptoHash, findNetwork } from "@/services/cryptoValidators";

export default function WithdrawalDialog({
  open, onClose,
  note, onNoteChange,
  payoutProof, onPayoutProofChange,
  payoutHash, onPayoutHashChange,
  paidFromAccount, onPaidFromAccountChange,
  statusLabel,
  onProofUpload,
  onAskChange,
  courierKm, onCourierKmChange, courierMuni, onCourierMuniChange,
  onApplyCourier, onCreateDelivery,
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
            {open.method === "cash" ? (
              <>
                <CourierFeeBlock
                  w={open}
                  courierKm={courierKm}
                  onCourierKmChange={onCourierKmChange}
                  courierMuni={courierMuni}
                  onCourierMuniChange={onCourierMuniChange}
                  onApplyCourier={onApplyCourier}
                  onCreateDelivery={onCreateDelivery ? () => onCreateDelivery("withdrawal", open.id) : null}
                />
                <div
                  className="text-[0.7rem] text-neutral-400 flex items-center gap-1.5 border border-white/10 bg-white/[0.02] px-2.5 py-2"
                  data-testid="withdrawal-cashbox-note"
                >
                  <Banknote className="w-3.5 h-3.5 text-[#22C55E] flex-shrink-0" />
                  <span>{t("admin.withdrawals.cashBoxNote")}</span>
                </div>
              </>
            ) : (
              <FundAccountSelect
                currency={open.currency || "USD"}
                value={paidFromAccount}
                onChange={onPaidFromAccountChange}
                label={t("admin.withdrawals.paidFromAccount")}
                unassignedLabel={t("admin.companyFunds.unassigned")}
                testId="withdrawal-paid-from-account"
                autoMode
              />
            )}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              <Button data-testid="withdrawal-approve" onClick={() => onAskChange("approved")} className="bg-[#22C55E] text-black rounded-none">
                {open.method === "cash" ? t("admin.withdrawals.approveInProgress") : t("admin.withdrawals.approveConfirm")}
              </Button>
              <PayButton w={open} onAskChange={onAskChange} />
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

// iter208 — Bloquea el botón "Entregado" en retiros CASH hasta que la
// mensajería esté finalizada por el mensajero. El backend también valida
// esta condición (routes/admin_withdrawals.py::_assert_cash_courier_ready)
// pero deshabilitarlo visualmente evita clics innecesarios y mejora UX.
function PayButton({ w, onAskChange }) {
  const { t } = useTranslation();
  const isCash = w.method === "cash";
  const isOfficePickup = (w.cash_delivery_mode || "courier") === "office_pickup";
  const deliveryStatus = w.courier_delivery_status;
  const courierAssigned = !!w.courier_delivery_assigned;
  const courierName = w.courier_delivery_courier_name || "";

  let blocked = false;
  let reasonKey = null;
  let reasonVars = {};

  if (isCash && !isOfficePickup && w.status !== "paid") {
    if (!deliveryStatus) {
      blocked = true;
      reasonKey = "admin.withdrawals.payLock.noJob";
    } else if (!courierAssigned) {
      blocked = true;
      reasonKey = "admin.withdrawals.payLock.noCourier";
    } else if (!["delivered", "confirmed"].includes(deliveryStatus)) {
      blocked = true;
      reasonKey = "admin.withdrawals.payLock.notDelivered";
      reasonVars = { courier: courierName || t("admin.withdrawals.payLock.courierFallback") };
    }
  }

  const label = isCash ? t("admin.withdrawals.payDelivered") : t("admin.withdrawals.payPaid");
  return (
    <div className="flex flex-col gap-1">
      <Button
        data-testid="withdrawal-pay"
        onClick={() => onAskChange("paid")}
        disabled={blocked}
        className="bg-[#8B5CF6] text-white rounded-none disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {label}
      </Button>
      {blocked && (
        <div
          data-testid="withdrawal-pay-lock-hint"
          className="text-[0.65rem] text-amber-400 leading-tight"
        >
          {t(reasonKey, reasonVars)}
        </div>
      )}
    </div>
  );
}


function CourierFeeBlock({ w, courierKm, onCourierKmChange, courierMuni, onCourierMuniChange, onApplyCourier }) {
  const { t } = useTranslation();
  const [quote, setQuote] = useState(null);
  const [munis, setMunis] = useState([]);

  useEffect(() => {
    if (!w?.id) return;
    axios.get(`${API}/vip/courier-fee-quote`, {
      params: { currency: w.currency || "USD", amount: w.amount_usd || 0 },
      withCredentials: true,
    }).then((r) => setQuote(r.data)).catch(() => setQuote(null));
    // iter211 — tarifas fijas por municipio para cobro sin km.
    axios.get(`${API}/courier/municipality-rates`, { withCredentials: true })
      .then((r) => setMunis(r.data || [])).catch(() => setMunis([]));
  }, [w?.id, w?.currency, w?.amount_usd]);

  if (!quote) return null;
  const muniRow = munis.find((m) => m.municipality === courierMuni);
  const km = parseFloat(courierKm || "0") || 0;
  const rawFee = courierMuni && muniRow
    ? Number(muniRow.price_usdt || 0)
    : km > 0
      ? Math.max(Number(quote.min_fee_usdt || 0), km * (quote.rate_usdt_per_km || 0))
      : 0;
  const feeUsdt = Math.round(rawFee * 100) / 100;
  const feeCur = quote.currency_per_usdt != null
    ? Math.round(feeUsdt * quote.currency_per_usdt * 100) / 100
    : null;
  const charged = Number(w.courier_fee_usdt || 0) > 0;

  return (
    <div className="border border-white/10 p-3 space-y-2 bg-[#0a0a0a]/50" data-testid="courier-fee-block">
      <div className="micro-label text-[#8B5CF6]">{t("admin.withdrawals.courier.title")}</div>
      {quote.free ? (
        <p className="text-[0.7rem] text-[#22C55E]" data-testid="courier-free-note">
          {t("admin.withdrawals.courier.freeNote", { min: quote.free_min_usdt, eq: quote.usdt_equivalent })}
        </p>
      ) : !quote.enabled ? (
        <p className="text-[0.7rem] text-amber-400" data-testid="courier-not-configured">
          {t("admin.withdrawals.courier.notConfigured")}
        </p>
      ) : (
        <>
          {Number(w.courier_quote_km || 0) > 0 && (
            <p className="text-[0.65rem] text-neutral-500" data-testid="courier-auto-km-hint">
              {t("admin.withdrawals.courier.autoKmHint", { km: w.courier_quote_km })}
            </p>
          )}
          {charged && (
            <p className="text-[0.7rem] text-neutral-300" data-testid="courier-charged-note">
              {w.courier_municipality
                ? t("admin.withdrawals.courier.chargedMuni", {
                    muni: w.courier_municipality,
                    fee: w.courier_fee_usdt,
                    feeCurrency: w.courier_fee_currency_amount,
                    currency: w.courier_fee_currency || w.currency,
                  })
                : t("admin.withdrawals.courier.charged", {
                    km: w.courier_km,
                    fee: w.courier_fee_usdt,
                    feeCurrency: w.courier_fee_currency_amount,
                    currency: w.courier_fee_currency || w.currency,
                  })}
            </p>
          )}
          {/* iter211 — cobro por tarifa fija de municipio (mapa falló) */}
          <div>
            <label className="micro-label text-neutral-500">{t("admin.withdrawals.courier.muniLabel")}</label>
            <Select
              value={courierMuni || "__km__"}
              onValueChange={(v) => onCourierMuniChange(v === "__km__" ? "" : v)}
            >
              <SelectTrigger
                className="h-10 mt-1 rounded-none bg-[#0a0a0a] border-white/10 text-xs"
                data-testid="courier-muni-select"
              >
                <SelectValue placeholder={t("admin.withdrawals.courier.muniByKm")} />
              </SelectTrigger>
              <SelectContent className="bg-[#1A1730] border-white/10 text-white max-h-64">
                <SelectItem value="__km__">{t("admin.withdrawals.courier.muniByKm")}</SelectItem>
                {munis.map((m) => (
                  <SelectItem key={m.id} value={m.municipality}>
                    {m.municipality} — {m.price_usdt} USDT
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex items-end gap-2">
            <div className="flex-1">
              <label className="micro-label text-neutral-500">{t("admin.withdrawals.courier.kmLabel")}</label>
              <Input
                data-testid="courier-km-input"
                type="number"
                min="0"
                step="0.1"
                value={courierKm}
                disabled={!!courierMuni}
                onChange={(e) => onCourierKmChange(e.target.value)}
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10 font-mono disabled:opacity-40"
              />
            </div>
            <Button
              data-testid="courier-apply-btn"
              onClick={onApplyCourier}
              className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none h-10"
            >
              {charged ? t("admin.withdrawals.courier.update") : t("admin.withdrawals.courier.apply")}
            </Button>
          </div>
          {courierMuni && muniRow && (
            <p className="text-[0.7rem] text-neutral-400 font-mono" data-testid="courier-muni-fee-preview">
              {courierMuni}: {feeUsdt} USDT
              {feeCur != null ? ` ≈ ${feeCur} ${quote.currency}` : ""}
            </p>
          )}
          {!courierMuni && km > 0 && (
            <p className="text-[0.7rem] text-neutral-400 font-mono" data-testid="courier-fee-preview">
              MAX({quote.min_fee_usdt} USDT, {km} km × {quote.rate_usdt_per_km} USDT/km) = {feeUsdt} USDT
              {feeCur != null ? ` ≈ ${feeCur} ${quote.currency}` : ""}
            </p>
          )}
          {charged && (
            <p className="text-[0.65rem] text-neutral-500">{t("admin.withdrawals.courier.zeroHint")}</p>
          )}
        </>
      )}
    </div>
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
