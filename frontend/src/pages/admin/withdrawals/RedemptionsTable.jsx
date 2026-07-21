import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";

export default function RedemptionsTable({ redemptions, onUpdateStatus }) {
  const { t } = useTranslation();
  return (
    <div className="tactile-card overflow-hidden">
      <table className="w-full text-sm">
        <thead className="border-b border-white/10 bg-[#0a0a0a]">
          <tr className="text-left">
            <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colUser")}</th>
            <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colProduct")}</th>
            <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colQty")}</th>
            <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colTotal")}</th>
            <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colAddress")}</th>
            <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colStatus")}</th>
            <th className="px-3 py-3"></th>
          </tr>
        </thead>
        <tbody>
          {redemptions.length === 0 && (
            <tr>
              <td colSpan="7" className="text-center text-neutral-500 py-6">{t("admin.withdrawals.emptyRedemptions")}</td>
            </tr>
          )}
          {redemptions.map((r) => (
            <tr key={r.id} className="border-b border-white/5">
              <td className="px-3 py-3">{r.user_name}</td>
              <td className="px-3 py-3">{r.product_name}</td>
              <td className="px-3 py-3 font-mono">{r.quantity}</td>
              <td className="px-3 py-3 font-mono text-[#8B5CF6]">${r.total_usd}</td>
              <td className="px-3 py-3 text-xs max-w-xs truncate">{r.delivery_address}</td>
              <td className="px-3 py-3 text-xs uppercase">{r.status}</td>
              <td className="px-3 py-3">
                <div className="flex gap-1">
                  <Button size="sm" onClick={() => onUpdateStatus(r.id, "approved")} className="bg-[#22C55E] text-black rounded-none h-7 text-xs">✓</Button>
                  <Button size="sm" onClick={() => onUpdateStatus(r.id, "delivered")} className="bg-[#8B5CF6] text-white rounded-none h-7 text-xs">⇪</Button>
                  <Button size="sm" onClick={() => onUpdateStatus(r.id, "rejected")} className="bg-[#EF4444] text-white rounded-none h-7 text-xs">✕</Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
