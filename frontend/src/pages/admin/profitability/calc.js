// Pure profitability math (mirrors the operator's Excel "Calculadora USDT→CUP").
// Percentages are percent numbers (26 = 26%).
// Modo 2 — combined cash cycle: sell currency for cash, sell cash → transfer
// at sellPct, buy cash back with transfer at buyPct. All results in cash units.
export function computeUnit({ sell, buy, buyPct, sellPct }) {
  const s = Number(sell) || 0;
  const b = Number(buy) || 0;
  const bp = (Number(buyPct) || 0) / 100;
  const sp = (Number(sellPct) || 0) / 100;
  const resultFx = s - b;
  const transferValue = s * (1 + sp);
  const recoveredCash = transferValue / (1 + bp);
  const conversionGain = recoveredCash - s;
  const netGain = recoveredCash - b;
  return {
    resultFx,
    transferValue,
    recoveredCash,
    conversionGain,
    netGain,
    marginOnSell: s ? netGain / s : 0,
    marginOnBuy: b ? netGain / b : 0,
    maxBuyPrice: recoveredCash,
    minSellPrice: (b * (1 + bp)) / (1 + sp),
    cushion: recoveredCash - b,
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
