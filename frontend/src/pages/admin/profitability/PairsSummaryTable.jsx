// iter113 — profitability summary for every registered pair. Prices and
// transfer % are editable in-row to simulate; a row can be sent to the
// calculator on top for the full breakdown.
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ArrowUpLeft } from "lucide-react";
import { computeUnit, fmt, fmtPct } from "./calc";

export default function PairsSummaryTable({ rates, pctFor, onLoadToCalc }) {
  const { t } = useTranslation();
  const [overrides, setOverrides] = useState({});

  const rowState = (r) => {
    const ov = overrides[r.id] || {};
    const pct = pctFor(r.to_code);
    return {
      // real_rate = operator's sell price; rate_normal = operator's buy cost.
      sell: ov.sell !== undefined ? ov.sell : (r.real_rate ?? ""),
      buy: ov.buy !== undefined ? ov.buy : (r.rate_normal ?? ""),
      buyPct: ov.buyPct !== undefined ? ov.buyPct : (pct.buy_pct ?? 0),
      sellPct: ov.sellPct !== undefined ? ov.sellPct : (pct.sell_pct ?? 0),
    };
  };

  const setOv = (id, key) => (e) =>
    setOverrides((p) => ({ ...p, [id]: { ...(p[id] || {}), [key]: e.target.value } }));

  return (
    <div className="tactile-card p-5 space-y-4" data-testid="profit-pairs">
      <div>
        <h3 className="font-display text-lg">{t("profitability.pairs.title")}</h3>
        <p className="text-xs text-neutral-500">{t("profitability.pairs.subtitle")}</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm" data-testid="profit-pairs-table">
          <thead>
            <tr className="text-left text-neutral-500 text-xs border-b border-white/10">
              <th className="py-2 pr-3">{t("profitability.pairs.pair")}</th>
              <th className="py-2 pr-3">{t("profitability.pairs.sell")}</th>
              <th className="py-2 pr-3">{t("profitability.pairs.buy")}</th>
              <th className="py-2 pr-3">{t("profitability.pairs.buyPctShort")}</th>
              <th className="py-2 pr-3">{t("profitability.pairs.sellPctShort")}</th>
              <th className="py-2 pr-3 text-right">{t("profitability.pairs.netUnit")}</th>
              <th className="py-2 pr-3 text-right">{t("profitability.pairs.margin")}</th>
              <th className="py-2 pr-3 text-right">{t("profitability.pairs.maxBuy")}</th>
              <th className="py-2 pr-3">{t("profitability.pairs.status")}</th>
              <th className="py-2"></th>
            </tr>
          </thead>
          <tbody>
            {rates.length === 0 && (
              <tr><td colSpan={10} className="py-6 text-center text-neutral-500 text-xs">{t("profitability.pairs.empty")}</td></tr>
            )}
            {rates.map((r) => {
              const st = rowState(r);
              const hasData = st.sell !== "" && st.sell !== null && st.buy !== "" && st.buy !== null;
              const u = computeUnit(st);
              return (
                <tr key={r.id} className="border-b border-white/5" data-testid={`pair-row-${r.from_code}-${r.to_code}`}>
                  <td className="py-2 pr-3 font-mono text-neutral-200 whitespace-nowrap">{r.from_code} → {r.to_code}</td>
                  <CellInput value={st.sell} onChange={setOv(r.id, "sell")} testid={`pair-sell-${r.from_code}-${r.to_code}`} />
                  <CellInput value={st.buy} onChange={setOv(r.id, "buy")} testid={`pair-buy-${r.from_code}-${r.to_code}`} />
                  <CellInput value={st.buyPct} onChange={setOv(r.id, "buyPct")} narrow testid={`pair-buypct-${r.from_code}-${r.to_code}`} />
                  <CellInput value={st.sellPct} onChange={setOv(r.id, "sellPct")} narrow testid={`pair-sellpct-${r.from_code}-${r.to_code}`} />
                  <td className={`py-2 pr-3 text-right font-mono font-semibold ${!hasData ? "text-neutral-600" : u.netGain >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"}`}>
                    {hasData ? fmt(u.netGain) : "—"}
                  </td>
                  <td className="py-2 pr-3 text-right font-mono text-neutral-400">{hasData ? fmtPct(u.marginOnSell) : "—"}</td>
                  <td className="py-2 pr-3 text-right font-mono text-[#A78BFA]">{st.sell !== "" && st.sell !== null ? fmt(u.maxBuyPrice) : "—"}</td>
                  <td className="py-2 pr-3">
                    {hasData ? (
                      <span className={`text-[0.65rem] px-2 py-0.5 rounded-full border ${u.netGain >= 0
                        ? "border-[#22C55E]/40 text-[#22C55E] bg-[#22C55E]/10"
                        : "border-[#EF4444]/40 text-[#EF4444] bg-[#EF4444]/10"}`}>
                        {u.netGain >= 0 ? t("profitability.pairs.profitable") : t("profitability.pairs.loss")}
                      </span>
                    ) : <span className="text-neutral-600 text-xs">—</span>}
                  </td>
                  <td className="py-2 text-right">
                    <button
                      type="button"
                      title={t("profitability.pairs.toCalc")}
                      onClick={() => onLoadToCalc({
                        pairId: r.id, fromCode: r.from_code, toCode: r.to_code,
                        sell: st.sell, buy: st.buy, buyPct: st.buyPct, sellPct: st.sellPct,
                      })}
                      className="p-1.5 rounded-md text-neutral-400 hover:text-[#A78BFA] hover:bg-white/5 transition-colors"
                      data-testid={`pair-tocalc-${r.from_code}-${r.to_code}`}
                    >
                      <ArrowUpLeft className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CellInput({ value, onChange, narrow, testid }) {
  return (
    <td className="py-2 pr-3">
      <input
        type="number"
        step="any"
        min="0"
        value={value}
        onChange={onChange}
        data-testid={testid}
        className={`${narrow ? "w-16" : "w-24"} bg-white/[0.04] border border-white/10 rounded-md px-2 py-1 text-xs font-mono text-neutral-200 focus:outline-none focus:border-[#8B5CF6]/60`}
      />
    </td>
  );
}
