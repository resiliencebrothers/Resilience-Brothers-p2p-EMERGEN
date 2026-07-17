import { useTranslation } from "react-i18next";

export function RevenueByPairTable({ byPair, profitMarginPct, ordersTotal, fmt }) {
  const { t } = useTranslation();
  return (
    <div className="tactile-card overflow-hidden">
      <div className="px-6 py-4 border-b border-white/10">
        <h2 className="font-display text-lg">{t("admin.revenue.byPairTitle")}</h2>
        <p className="text-xs text-neutral-500 mt-1">
          {t("admin.revenue.byPairSubtitle", { pct: profitMarginPct, n: ordersTotal })}
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.revenue.colPair")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.revenue.colOrders")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.revenue.colVolumeIn")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.revenue.colVolumeOut")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.revenue.colRatesNVR")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.revenue.colProfit")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.revenue.colMargin")}</th>
            </tr>
          </thead>
          <tbody>
            {byPair.length === 0 && (
              <tr>
                <td colSpan="7" className="text-center text-neutral-500 py-8">
                  {t("admin.revenue.byPairEmpty")}
                </td>
              </tr>
            )}
            {byPair.map(p => (
              <tr key={p.pair} className="border-b border-white/5">
                <td className="px-4 py-3 font-mono font-semibold">{p.pair}</td>
                <td className="px-4 py-3 font-mono">{p.orders}</td>
                <td className="px-4 py-3 font-mono">{fmt(p.volume_from)} {p.from_code}</td>
                <td className="px-4 py-3 font-mono">{fmt(p.volume_to)} {p.to_code}</td>
                <td className="px-4 py-3 font-mono text-xs">
                  <div>
                    {p.rate_normal} /{" "}
                    <span className="text-[#8B5CF6]">{p.rate_vip}</span> /{" "}
                    <span className="text-[#22C55E]">{p.real_rate}</span>
                  </div>
                </td>
                <td className="px-4 py-3 font-mono">
                  <div className="text-[#22C55E]">{fmt(p.profit_to)} {p.to_code}</div>
                  <div className="text-xs text-neutral-500">≈ {fmt(p.profit_usdt)} USDT</div>
                </td>
                <td className="px-4 py-3 font-mono text-[#22C55E]">{p.avg_profit_pct}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
