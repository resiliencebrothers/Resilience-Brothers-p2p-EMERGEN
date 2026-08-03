// iter113 — pure profitability math (mirrors the operator's Excel panel).
// Percentages are percent numbers (26 = 26%).
// Modo 2 — combined flow: FX result + transfer differential.
export function computeUnit({ sell, buy, buyPct, sellPct }) {
  const s = Number(sell) || 0;
  const b = Number(buy) || 0;
  const bp = (Number(buyPct) || 0) / 100;
  const sp = (Number(sellPct) || 0) / 100;
  const resultFx = s - b;
  const transferCost = s * (1 + bp);
  const transferValue = s * (1 + sp);
  const conversionGain = transferValue - transferCost;
  const netGain = resultFx + conversionGain;
  return {
    resultFx,
    transferCost,
    transferValue,
    conversionGain,
    netGain,
    marginOnSell: s ? netGain / s : 0,
    marginOnBuy: b ? netGain / b : 0,
    maxBuyPrice: s + s * (sp - bp),
    cushion: s + s * (sp - bp) - b,
  };
}

// Modo 1 — direct transfer sale: buy the currency in cash, sell it in
// transfer. buyPct = transfer cost %. Break-even is a MINIMUM sell price.
export function computeDirect({ sell, buy, buyPct }) {
  const s = Number(sell) || 0;
  const b = Number(buy) || 0;
  const bp = (Number(buyPct) || 0) / 100;
  const realCost = b * (1 + bp);
  const netGain = s - realCost;
  return {
    realCost,
    netGain,
    marginOnSell: s ? netGain / s : 0,
    marginOnCost: realCost ? netGain / realCost : 0,
    minSellPrice: realCost,
    cushion: s - realCost,
  };
}

export const fmt = (n, d = 2) =>
  Number(n ?? 0).toLocaleString("es-ES", { maximumFractionDigits: d });

export const fmtPct = (fraction, d = 2) =>
  `${((Number(fraction) || 0) * 100).toLocaleString("es-ES", { maximumFractionDigits: d })}%`;
