import { useTranslation } from "react-i18next";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Calendar } from "lucide-react";

export function RevenueDailyTable({ daily, dailyRange, setDailyRange, fmt }) {
  const { t } = useTranslation();
  return (
    <div className="tactile-card overflow-hidden" data-testid="revenue-daily-card">
      <div className="px-6 py-4 border-b border-white/10 flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="font-display text-lg flex items-center gap-2">
            <Calendar className="w-5 h-5 text-[#8B5CF6]" /> {t("admin.revenue.dailyTitle")}
          </h2>
          <p className="text-xs text-neutral-500 mt-1">
            {t("admin.revenue.dailySubtitle")}
          </p>
        </div>
        <Select value={dailyRange} onValueChange={setDailyRange}>
          <SelectTrigger
            data-testid="daily-range"
            className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-36"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
            <SelectItem value="7">{t("admin.revenue.dailyRange7")}</SelectItem>
            <SelectItem value="14">{t("admin.revenue.dailyRange14")}</SelectItem>
            <SelectItem value="30">{t("admin.revenue.dailyRange30")}</SelectItem>
            <SelectItem value="60">{t("admin.revenue.dailyRange60")}</SelectItem>
            <SelectItem value="90">{t("admin.revenue.dailyRange90")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.revenue.colDate")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.revenue.colOrders")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.revenue.colVolume")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.revenue.colP2P")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.revenue.colMarketplace")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.revenue.colUsdtFees")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.revenue.colTotal")}</th>
            </tr>
          </thead>
          <tbody data-testid="daily-rows">
            {daily.length === 0 && (
              <tr>
                <td colSpan="7" className="text-center text-neutral-500 py-8">
                  {t("admin.revenue.emptyRange")}
                </td>
              </tr>
            )}
            {daily.map(d => (
              <tr key={d.bucket} className="border-b border-white/5">
                <td className="px-4 py-3 font-mono">{d.bucket}</td>
                <td className="px-4 py-3 font-mono">{d.orders}</td>
                <td className="px-4 py-3 font-mono text-neutral-400">{fmt(d.volume_usdt)} USDT</td>
                <td className="px-4 py-3 font-mono">{fmt(d.p2p_profit_usdt)} USDT</td>
                <td className="px-4 py-3 font-mono">{fmt(d.marketplace_profit_usdt)} USDT</td>
                <td className="px-4 py-3 font-mono text-neutral-300">
                  {fmt(d.conversion_fees_usdt || 0)} USDT
                  {d.conversions > 0 && (
                    <span className="text-neutral-500 text-xs"> · {d.conversions}</span>
                  )}
                </td>
                <td className="px-4 py-3 font-mono text-[#22C55E] font-bold">
                  {fmt(d.total_profit_usdt)} USDT
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
