import { useTranslation } from "react-i18next";
import { Boxes } from "lucide-react";

export function RevenueMarketplaceTable({ marketplace, fmt }) {
  const { t } = useTranslation();
  return (
    <div className="tactile-card overflow-hidden" data-testid="revenue-marketplace">
      <div className="px-6 py-4 border-b border-white/10 flex items-center justify-between flex-wrap gap-2">
        <div>
          <h2 className="font-display text-lg flex items-center gap-2">
            <Boxes className="w-5 h-5 text-[#8B5CF6]" /> {t("admin.revenue.mpTitle")}
          </h2>
          <p className="text-xs text-neutral-500 mt-1">
            {t("admin.revenue.mpSubtitle")}
          </p>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right">
            <div className="micro-label text-neutral-500">{t("admin.revenue.mpRevenue")}</div>
            <div className="font-mono font-semibold">${fmt(marketplace.total_revenue_usd)}</div>
          </div>
          <div className="text-right">
            <div className="micro-label text-neutral-500">{t("admin.revenue.mpCost")}</div>
            <div className="font-mono">${fmt(marketplace.total_cost_usd)}</div>
          </div>
          <div className="text-right">
            <div className="micro-label text-[#22C55E]">{t("admin.revenue.mpNetProfit")}</div>
            <div className="font-mono text-[#22C55E] font-bold">
              ${fmt(marketplace.total_profit_usd)}
            </div>
          </div>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.revenue.colProduct")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.revenue.colUnits")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.revenue.colRedemptions")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.revenue.mpRevenue")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.revenue.mpCost")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.revenue.colProfit")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.revenue.colMargin")}</th>
            </tr>
          </thead>
          <tbody>
            {marketplace.items.length === 0 && (
              <tr>
                <td colSpan="7" className="text-center text-neutral-500 py-8">
                  {t("admin.revenue.mpEmpty")}
                </td>
              </tr>
            )}
            {marketplace.items.map(p => (
              <tr key={p.product} className="border-b border-white/5">
                <td className="px-4 py-3">{p.product}</td>
                <td className="px-4 py-3 font-mono">{p.units}</td>
                <td className="px-4 py-3 font-mono">{p.redemptions}</td>
                <td className="px-4 py-3 font-mono">${fmt(p.revenue_usd)}</td>
                <td className="px-4 py-3 font-mono text-neutral-400">${fmt(p.cost_usd)}</td>
                <td className="px-4 py-3 font-mono text-[#22C55E]">${fmt(p.profit_usd)}</td>
                <td className="px-4 py-3 font-mono text-[#22C55E]">{p.margin_pct}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
