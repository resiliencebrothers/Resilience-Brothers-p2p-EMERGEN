/**
 * iter55.36i — Universal fee/min preview. Refactored from iter55.29's
 * "only-when-destination-is-USDT" variant to reflect the new business rule:
 * every allowed conversion costs a flat 0.10 USDT (translated to the
 * destination currency), and the source must be worth ≥ 1.00 USDT.
 *
 * Props:
 *  - fromCode / toCode
 *  - previewRate: number or null
 *  - previewGross: number or null
 *  - previewNet: number or null (previewGross - feeInToCode)
 *  - feeInToCode: number or null — the 0.10 USDT fee translated to the
 *      destination currency using the same rate table the backend uses. Null
 *      when we can't determine the USDT↔to_code path client-side.
 *  - feeUsdt: constant (0.10) — surface it to the user so they know the
 *      canonical fee is denominated in USDT even for fiat destinations.
 *  - belowMinSource: boolean — true when previewSourceUsdt < minSourceUsdt.
 *  - minSourceUsdt: constant (1.0).
 *  - previewSourceUsdt: number or null — for the warning body only.
 */
export function ConvertPreview({
  fromCode, toCode,
  previewRate, previewGross, previewNet,
  feeInToCode, feeUsdt,
  belowMinSource, minSourceUsdt, previewSourceUsdt,
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
          {previewGross !== null && (
            <div className="flex justify-between items-baseline mt-1">
              <span className="text-xs text-neutral-500">
                Comisión ({feeUsdt.toFixed(2)} USDT):
              </span>
              <span
                className="font-mono text-sm text-[#EF4444]"
                data-testid="converter-preview-fee"
              >
                -{feeInToCode === null
                  ? `${feeUsdt.toFixed(2)} USDT`
                  : `${Number(feeInToCode.toFixed(4)).toLocaleString(undefined, { maximumFractionDigits: 4 })} ${toCode}`}
              </span>
            </div>
          )}
          <div className="flex justify-between items-baseline border-t border-white/10 pt-1.5 mt-1.5">
            <span className="text-xs text-neutral-400">Recibirás:</span>
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
            Tasa: 1 {fromCode} = {previewRate.toFixed(6)} {toCode}
          </div>
          {belowMinSource && (
            <div
              className="text-[0.7rem] text-[#EF4444] mt-2 leading-relaxed"
              data-testid="converter-below-min"
            >
              Mínimo por conversión: equivalente a {minSourceUsdt.toFixed(2)} USDT.
              {previewSourceUsdt !== null && (
                <> Tu monto equivale a {previewSourceUsdt.toFixed(4)} USDT.</>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
