import { useTranslation } from "react-i18next";

/**
 * iter76 — Preview panel for the balance converter.
 *
 * The commission is ALWAYS denominated in USDT and NEVER shown as an
 * equivalent in the destination currency. This mirrors the backend rule
 * introduced in iter76 (`routes/orders.py::vip_convert`) where the fee is
 * deducted from the *source-side USDT equivalent* before the conversion.
 *
 * Numeric outcome is identical to the previous "translate fee to
 * destination" model; only the presentation changes.
 *
 * Props:
 *  - fromCode / toCode
 *  - previewRate:        number | null
 *  - previewNet:         number | null — amount_to (fee already deducted at the USDT layer)
 *  - feeUsdt:            constant 0.01 — surfaced to the client so they know
 *                        the fee is exactly this many USDT no matter what.
 *  - belowMinSource:     boolean — true when source is worth < minSourceUsdt.
 *  - minSourceUsdt:      constant 1.0.
 *  - previewSourceUsdt:  number | null — the source's USDT value (for the
 *                        min-warning body only).
 */
export function ConvertPreview({
  fromCode, toCode,
  previewRate, previewNet,
  feeUsdt,
  belowMinSource, minSourceUsdt, previewSourceUsdt,
}) {
  const { t } = useTranslation();
  return (
    <div
      className="border border-white/10 p-3 bg-[#0a0a0a]"
      data-testid="converter-preview"
    >
      {previewRate === null && toCode && fromCode && toCode !== fromCode && (
        <div className="text-xs text-red-400" data-testid="converter-preview-no-rate">
          {t("balanceConverter.noRateForPair", { from: fromCode, to: toCode })}
        </div>
      )}
      {previewRate !== null && (
        <>
          <div className="flex justify-between items-baseline">
            <span className="text-xs text-neutral-500">{t("balanceConverter.commissionLabel")}</span>
            <span
              className="font-mono text-sm text-[#EF4444]"
              data-testid="converter-preview-fee"
            >
              −{feeUsdt.toFixed(2)} USDT
            </span>
          </div>
          <div className="flex justify-between items-baseline border-t border-white/10 pt-1.5 mt-1.5">
            <span className="text-xs text-neutral-400">{t("balanceConverter.youReceive")}</span>
            <span
              className={"font-mono text-lg " + (belowMinSource ? "text-[#EF4444]" : "text-[#8B5CF6]")}
              data-testid="converter-preview-amount"
            >
              {previewNet === null
                ? `~ ${toCode}`
                : `${Number(previewNet.toFixed(4)).toLocaleString(undefined, { maximumFractionDigits: 4 })} ${toCode}`}
            </span>
          </div>
          <div className="text-[0.65rem] text-neutral-600 font-mono mt-1">
            {t("balanceConverter.rateSummary", { from: fromCode, rate: previewRate.toFixed(6), to: toCode })}
          </div>
          {belowMinSource && (
            <div
              className="text-[0.7rem] text-[#EF4444] mt-2 leading-relaxed"
              data-testid="converter-below-min"
            >
              {t("balanceConverter.minSource", { min: minSourceUsdt.toFixed(2) })}
              {previewSourceUsdt !== null && (
                <>{" "}{t("balanceConverter.yourAmountEquiv", { value: previewSourceUsdt.toFixed(4) })}</>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
