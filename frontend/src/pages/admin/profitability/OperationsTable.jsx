// iter113 — logged client operations table with totals and delete.
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Trash2 } from "lucide-react";
import { fmt, fmtPct } from "./calc";

const FILTERS = ["all", "profitable", "loss"];

export default function OperationsTable({ items, totals, onDelete }) {
  const { t } = useTranslation();
  const [filter, setFilter] = useState("all");
  const filtered = filter === "all" ? items : items.filter((i) => i.status === filter);

  return (
    <div className="tactile-card p-5 space-y-4" data-testid="profit-ops">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="font-display text-lg">{t("profitability.ops.title")}</h3>
          <p className="text-xs text-neutral-500">{t("profitability.ops.subtitle")}</p>
        </div>
        <div className="flex gap-1">
          {FILTERS.map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              data-testid={`ops-filter-${f}`}
              className={`px-3 py-1 rounded-full text-xs border transition-colors ${filter === f
                ? "border-[#8B5CF6]/60 text-[#A78BFA] bg-[#8B5CF6]/10"
                : "border-white/10 text-neutral-500 hover:text-neutral-300"}`}
            >
              {t(`profitability.ops.filter_${f}`)}
            </button>
          ))}
        </div>
      </div>

      {totals && (
        <div className="flex flex-wrap gap-2 text-xs" data-testid="ops-totals">
          <Chip label={`${totals.count} ${t("profitability.ops.totalOps")}`} />
          <Chip label={`${totals.profitable} ${t("profitability.ops.profitableCount")}`} color="green" />
          <Chip label={`${totals.loss} ${t("profitability.ops.lossCount")}`} color="red" />
          {Object.entries(totals.net_by_currency || {}).map(([code, net]) => (
            <Chip key={code} label={`${t("profitability.ops.netTotal")} ${code}: ${fmt(net)}`} color={net >= 0 ? "green" : "red"} />
          ))}
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-sm" data-testid="profit-ops-table">
          <thead>
            <tr className="text-left text-neutral-500 text-xs border-b border-white/10">
              <th className="py-2 pr-3">{t("profitability.ops.date")}</th>
              <th className="py-2 pr-3">{t("profitability.ops.client")}</th>
              <th className="py-2 pr-3">{t("profitability.ops.mode")}</th>
              <th className="py-2 pr-3">{t("profitability.ops.pair")}</th>
              <th className="py-2 pr-3 text-right">{t("profitability.ops.qty")}</th>
              <th className="py-2 pr-3 text-right">{t("profitability.ops.sell")}</th>
              <th className="py-2 pr-3 text-right">{t("profitability.ops.buy")}</th>
              <th className="py-2 pr-3 text-right">{t("profitability.ops.convGain")}</th>
              <th className="py-2 pr-3 text-right">{t("profitability.ops.netGain")}</th>
              <th className="py-2 pr-3 text-right">{t("profitability.ops.margin")}</th>
              <th className="py-2 pr-3">{t("profitability.ops.status")}</th>
              <th className="py-2"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={12} className="py-6 text-center text-neutral-500 text-xs">{t("profitability.ops.empty")}</td></tr>
            )}
            {filtered.map((op) => (
              <tr key={op.id} className="border-b border-white/5" data-testid={`op-row-${op.id}`}>
                <td className="py-2 pr-3 font-mono text-xs text-neutral-400 whitespace-nowrap">{op.op_date}</td>
                <td className="py-2 pr-3 text-neutral-200">{op.client_name}</td>
                <td className="py-2 pr-3">
                  <span className={`text-[0.6rem] px-1.5 py-0.5 rounded border whitespace-nowrap ${op.mode === "direct"
                    ? "border-[#38BDF8]/40 text-[#38BDF8] bg-[#38BDF8]/10"
                    : "border-[#A78BFA]/40 text-[#A78BFA] bg-[#A78BFA]/10"}`}>
                    {op.mode === "direct" ? t("profitability.ops.mode1Short") : t("profitability.ops.mode2Short")}
                  </span>
                </td>
                <td className="py-2 pr-3 font-mono text-xs text-neutral-300 whitespace-nowrap">{op.currency} → {op.payment_currency}</td>
                <td className="py-2 pr-3 text-right font-mono text-neutral-400">{fmt(op.quantity, 4)}</td>
                <td className="py-2 pr-3 text-right font-mono text-neutral-400">{fmt(op.sell_price)}</td>
                <td className="py-2 pr-3 text-right font-mono text-neutral-400">{fmt(op.buy_price)}</td>
                <td className={`py-2 pr-3 text-right font-mono ${op.conversion_gain >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"}`}>{fmt(op.conversion_gain)}</td>
                <td className={`py-2 pr-3 text-right font-mono font-semibold ${op.net_gain >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"}`}>{fmt(op.net_gain)}</td>
                <td className="py-2 pr-3 text-right font-mono text-neutral-400">{fmtPct((op.profitability_pct || 0) / 100)}</td>
                <td className="py-2 pr-3">
                  <span className={`text-[0.65rem] px-2 py-0.5 rounded-full border ${op.status === "profitable"
                    ? "border-[#22C55E]/40 text-[#22C55E] bg-[#22C55E]/10"
                    : "border-[#EF4444]/40 text-[#EF4444] bg-[#EF4444]/10"}`}>
                    {op.status === "profitable" ? t("profitability.pairs.profitable") : t("profitability.pairs.loss")}
                  </span>
                </td>
                <td className="py-2 text-right">
                  <button
                    type="button"
                    onClick={() => { if (window.confirm(t("profitability.ops.confirmDelete"))) onDelete(op.id); }}
                    className="p-1.5 rounded-md text-neutral-500 hover:text-[#EF4444] hover:bg-white/5 transition-colors"
                    data-testid={`op-delete-${op.id}`}
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Chip({ label, color }) {
  const cls = color === "green"
    ? "border-[#22C55E]/40 text-[#22C55E] bg-[#22C55E]/10"
    : color === "red"
      ? "border-[#EF4444]/40 text-[#EF4444] bg-[#EF4444]/10"
      : "border-white/10 text-neutral-400 bg-white/[0.03]";
  return <span className={`px-2.5 py-1 rounded-full border font-mono ${cls}`}>{label}</span>;
}
