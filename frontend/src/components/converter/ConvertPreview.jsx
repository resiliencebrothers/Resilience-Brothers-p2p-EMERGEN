/**
 * iter55.29 — Extracted from BalanceConverterCard as part of the high-complexity
 * refactor. Pure presentational component that renders the live rate preview,
 * the 0.01 USDT fee row, and the "below-minimum-net" warning.
 *
 * Props:
 *  - fromCode / toCode
 *  - previewRate: number or null
 *  - previewGross: number or null
 *  - previewNet: number or null
 *  - isToUsdt: boolean — whether destination is USDT (fee applies)
 *  - belowMinNet: boolean
 *  - usdtFee / usdtMinNet: constants (kept as props so the parent stays the
 *    single source of truth mirroring the backend).
 */
export function ConvertPreview({
  fromCode, toCode,
  previewRate, previewGross, previewNet,
  isToUsdt, belowMinNet,
  usdtFee, usdtMinNet,
}) {
  return (
    <div
      className="border border-white/10 p-3 bg-[#0a0a0a]"
      data-testid="converter-preview"
    >
      {previewRate === null && toCode && fromCode && toCode !== fromCode && (
        <div className="text-xs text-red-400" data-testid="converter-preview-no-rate">
          No hay tasa cotizada para {fromCode} → {toCode}.
        </div>
      )}
      {previewRate !== null && (
        <>
          <div className="flex justify-between items-baseline">
            <span className="text-xs text-neutral-500">Bruto:</span>
            <span
              className="font-mono text-sm text-neutral-300"
              data-testid="converter-preview-gross"
            >
              {previewGross === null
                ? `~ ${toCode}`
                : `${Number(previewGross.toFixed(4)).toLocaleString(undefined, { maximumFractionDigits: 4 })} ${toCode}`}
            </span>
          </div>
          {isToUsdt && previewGross !== null && (
            <div className="flex justify-between items-baseline mt-1">
              <span className="text-xs text-neutral-500">Comisión:</span>
              <span
                className="font-mono text-sm text-[#EF4444]"
                data-testid="converter-preview-fee"
              >
                -{usdtFee.toFixed(2)} USDT
              </span>
            </div>
          )}
          <div className="flex justify-between items-baseline border-t border-white/10 pt-1.5 mt-1.5">
            <span className="text-xs text-neutral-400">Recibirás:</span>
            <span
              className={"font-mono text-lg " + (belowMinNet ? "text-[#EF4444]" : "text-[#8B5CF6]")}
              data-testid="converter-preview-amount"
            >
              {previewNet === null
                ? `~ ${toCode}`
                : `${Number(previewNet.toFixed(4)).toLocaleString(undefined, { maximumFractionDigits: 4 })} ${toCode}`}
            </span>
          </div>
          <div className="text-[0.65rem] text-neutral-600 font-mono mt-1">
            Tasa: 1 {fromCode} = {previewRate.toFixed(6)} {toCode}
          </div>
          {belowMinNet && (
            <div
              className="text-[0.7rem] text-[#EF4444] mt-2 leading-relaxed"
              data-testid="converter-below-min"
            >
              Mínimo neto {usdtMinNet.toFixed(2)} USDT tras la comisión —
              acumula más saldo antes de convertir.
            </div>
          )}
        </>
      )}
    </div>
  );
}
