import { useTranslation } from "react-i18next";

/**
 * Live quote preview: shown when a rate has been resolved and the user has
 * typed a positive amount. Renders rate, gross, commission, residue credit
 * (for cash-fiat) and the final deliverable amount.
 */
export default function QuotePreview({
  fromCode, toCode, rate, amount,
  gross, finalAmount, finalAmountRaw,
  commission, residueCredited, isCashFiatDelivery,
}) {
  const { t } = useTranslation();
  if (!rate || amount <= 0) return null;
  return (
    <div className="border border-[#8B5CF6]/30 bg-[#8B5CF6]/5 p-5 space-y-2 font-mono text-sm">
      <div className="flex justify-between">
        <span className="text-neutral-400">{t("exchange.rateApplied")}</span>
        <span>{rate} {toCode}/{fromCode}</span>
      </div>
      <div className="flex justify-between">
        <span className="text-neutral-400">{t("exchange.gross")}</span>
        <span>{gross.toFixed(4)} {toCode}</span>
      </div>
      {commission > 0 && (
        <div className="flex justify-between">
          <span className="text-neutral-400">{t("exchange.commission", { pct: commission })}</span>
          <span className="text-[#EF4444]">-{(gross - finalAmountRaw).toFixed(4)}</span>
        </div>
      )}
      {isCashFiatDelivery && residueCredited > 0 && (
        <div className="flex justify-between text-[#8B5CF6]" data-testid="cash-fiat-residue-credit">
          <span>{t("exchange.residueCredit")}</span>
          <span>+{residueCredited.toFixed(4)} {toCode}</span>
        </div>
      )}
      <div className="border-t border-white/10 pt-2 mt-2 flex justify-between text-base">
        <span className="text-white">
          {isCashFiatDelivery ? t("exchange.receiveInCash") : t("exchange.receiveIn", { code: toCode })}
        </span>
        <span className="text-[#8B5CF6] font-bold" data-testid="final-amount-display">
          {isCashFiatDelivery ? finalAmount.toFixed(0) : finalAmount.toFixed(4)} {toCode}
        </span>
      </div>
    </div>
  );
}
