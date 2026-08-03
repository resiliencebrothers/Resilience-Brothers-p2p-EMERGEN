// iter115 — volume projections, mode-aware (Modo 1 direct / Modo 2 combined).
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { computeUnit, computeDirect, fmt, fmtPct } from "./calc";

export default function ProjectionsTable({ calc, setCalc }) {
  const { t } = useTranslation();
  const isDirect = calc.mode === "direct";
  const u = isDirect ? computeDirect(calc) : computeUnit(calc);
  const qty = Number(calc.qty) || 0;
  const opsDay = Number(calc.opsPerDay) || 0;
  const daysMonth = Number(calc.daysPerMonth) || 0;
  const unit = calc.toCode || "";
  const sellGross = Number(calc.sell) || 0;

  const rows = [
    { key: "perOp", units: qty },
    { key: "daily", units: qty * opsDay },
    { key: "weekly", units: qty * opsDay * 7 },
    { key: "monthly", units: qty * opsDay * daysMonth },
  ];

  return (
    <div className="tactile-card p-5 space-y-4" data-testid="profit-projections">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h3 className="font-display text-lg">{t("profitability.proj.title")}</h3>
        <div className="flex gap-3">
          <div className="space-y-1">
            <Label className="text-xs text-neutral-400">{t("profitability.proj.opsPerDay")}</Label>
            <Input type="number" min="0" className="w-28" value={calc.opsPerDay}
              onChange={(e) => setCalc((p) => ({ ...p, opsPerDay: e.target.value }))}
              data-testid="profit-proj-opsday-input" />
          </div>
          <div className="space-y-1">
            <Label className="text-xs text-neutral-400">{t("profitability.proj.daysPerMonth")}</Label>
            <Input type="number" min="0" className="w-28" value={calc.daysPerMonth}
              onChange={(e) => setCalc((p) => ({ ...p, daysPerMonth: e.target.value }))}
              data-testid="profit-proj-daysmonth-input" />
          </div>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm" data-testid="profit-projections-table">
          <thead>
            <tr className="text-left text-neutral-500 text-xs border-b border-white/10">
              <th className="py-2 pr-3">{t("profitability.proj.period")}</th>
              <th className="py-2 pr-3 text-right">{t("profitability.proj.units")}</th>
              {isDirect ? (
                <>
                  <th className="py-2 pr-3 text-right">{t("profitability.proj.netGain")}</th>
                  <th className="py-2 pr-3 text-right">{t("profitability.proj.profitability")}</th>
                  <th className="py-2 pr-3 text-right">{t("profitability.proj.sellTotal")}</th>
                  <th className="py-2 text-right">{t("profitability.proj.costTotal")}</th>
                </>
              ) : (
                <>
                  <th className="py-2 pr-3 text-right">{t("profitability.proj.fxGain")}</th>
                  <th className="py-2 pr-3 text-right">{t("profitability.proj.convGain")}</th>
                  <th className="py-2 pr-3 text-right">{t("profitability.proj.netGain")}</th>
                  <th className="py-2 text-right">{t("profitability.proj.profitability")}</th>
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const net = u.netGain * r.units;
              const rentPct = fmtPct(sellGross && r.units ? net / (sellGross * r.units) : 0);
              return (
                <tr key={r.key} className="border-b border-white/5" data-testid={`profit-proj-row-${r.key}`}>
                  <td className="py-2 pr-3 text-neutral-300">{t(`profitability.proj.${r.key}`)}</td>
                  <td className="py-2 pr-3 text-right font-mono text-neutral-400">{fmt(r.units, 4)}</td>
                  {isDirect ? (
                    <>
                      <td className={`py-2 pr-3 text-right font-mono font-semibold ${net >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"}`}>{fmt(net)} {unit}</td>
                      <td className="py-2 pr-3 text-right font-mono text-neutral-400">{rentPct}</td>
                      <td className="py-2 pr-3 text-right font-mono text-neutral-400">{fmt(sellGross * r.units)}</td>
                      <td className="py-2 text-right font-mono text-neutral-400">{fmt(u.realCost * r.units)}</td>
                    </>
                  ) : (
                    <>
                      <td className={`py-2 pr-3 text-right font-mono ${u.resultFx >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"}`}>{fmt(u.resultFx * r.units)}</td>
                      <td className={`py-2 pr-3 text-right font-mono ${u.conversionGain >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"}`}>{fmt(u.conversionGain * r.units)}</td>
                      <td className={`py-2 pr-3 text-right font-mono font-semibold ${net >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"}`}>{fmt(net)} {unit}</td>
                      <td className="py-2 text-right font-mono text-neutral-400">{rentPct}</td>
                    </>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
