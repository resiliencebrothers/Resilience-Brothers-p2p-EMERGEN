import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";

const STATUS_STYLES = {
  paid: "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  approved: "bg-[#8B5CF6]/10 text-[#8B5CF6] border-[#8B5CF6]/30",
  rejected: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30",
  pending: "bg-neutral-700/20 text-neutral-400 border-neutral-700/40",
};

export default function WithdrawalsTable({ items, statusLabel, onManage }) {
  const { t } = useTranslation();
  return (
    <div className="tactile-card overflow-hidden">
      <table className="w-full text-sm">
        <thead className="border-b border-white/10 bg-[#0a0a0a]">
          <tr className="text-left">
            <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colUser")}</th>
            <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colAmount")}</th>
            <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colCurrency")}</th>
            <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colMethod")}</th>
            <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colDetails")}</th>
            <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colStatus")}</th>
            <th className="px-3 py-3"></th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 && (
            <tr>
              <td colSpan="7" className="text-center text-neutral-500 py-6">{t("admin.withdrawals.empty")}</td>
            </tr>
          )}
          {items.map((w) => (
            <tr key={w.id} className="border-b border-white/5">
              <td className="px-3 py-3">{w.user_name}</td>
              <td className="px-3 py-3 font-mono text-[#8B5CF6]">{w.amount_usd}</td>
              <td className="px-3 py-3 font-mono">{w.currency || "USD"}</td>
              <td className="px-3 py-3">
                <span>{w.method}</span>
                {w.method === "crypto" && w.crypto_network && (
                  <span
                    data-testid={`withdrawal-network-${w.id}`}
                    className="ml-2 inline-flex items-center px-1.5 py-0.5 text-[0.6rem] uppercase tracking-wider bg-[#8B5CF6]/10 text-[#8B5CF6] border border-[#8B5CF6]/30 font-mono"
                  >
                    {w.crypto_network}
                  </span>
                )}
              </td>
              <td className="px-3 py-3 text-xs max-w-xs truncate">{w.details}</td>
              <td className="px-3 py-3">
                <span className={`text-xs uppercase tracking-wider border px-2 py-1 ${STATUS_STYLES[w.status] || STATUS_STYLES.pending}`}>
                  {statusLabel(w.status, w.method)}
                </span>
              </td>
              <td className="px-3 py-3">
                <Button
                  size="sm"
                  onClick={() => onManage(w)}
                  className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none h-8"
                  data-testid={`manage-withdrawal-${w.id}`}
                >
                  {t("admin.withdrawals.manage")}
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
