import { useTranslation } from "react-i18next";
import { Eye } from "lucide-react";
import { extractCryptoNetwork, NETWORK_META } from "@/services/delivery_validators";
import CurrencyPairIcon from "@/components/CurrencyPairIcon";

const STATUS_STYLES = {
  pending: "bg-[#8B5CF6]/10 text-[#8B5CF6] border-[#8B5CF6]/30",
  requires_double_approval: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/40",
  approved: "bg-[#F59E0B]/10 text-[#F59E0B] border-[#F59E0B]/30",
  completed: "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  rejected: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30",
};

const STATUS_KEYS = {
  pending: "admin.orders.statusPending",
  requires_double_approval: "admin.orders.statusDoubleApproval",
  approved: "admin.orders.statusApproved",
  completed: "admin.orders.statusCompleted",
  rejected: "admin.orders.statusRejected",
};

/**
 * Paged table listing pending/approved/completed/rejected orders.
 * Emits `onOpenOrder(order)` when the operator clicks the eye icon.
 */
export default function OrdersTable({ orders, loading, onOpenOrder }) {
  const { t } = useTranslation();
  return (
    <div className="tactile-card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="border-b border-white/10 bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.orders.colId")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.orders.colClient")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.orders.colRole")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.orders.colPair")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.orders.colAmount")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.orders.colReceives")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.orders.colDelivery")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.orders.colStatus")}</th>
              <th className="px-3 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan="9" className="text-center text-neutral-500 py-8">
                  {t("admin.common.loadingEllipsis")}
                </td>
              </tr>
            )}
            {!loading && orders.length === 0 && (
              <tr>
                <td colSpan="9" className="text-center text-neutral-500 py-8">
                  {t("admin.orders.empty")}
                </td>
              </tr>
            )}
            {orders.map((o) => (
              <OrdersTableRow key={o.id} order={o} onOpen={() => onOpenOrder(o)} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function OrdersTableRow({ order: o, onOpen }) {
  const { t } = useTranslation();
  let networkBadge = null;
  if (o.delivery_method === "crypto") {
    const net = extractCryptoNetwork(o.delivery_details, "crypto");
    const meta = net ? NETWORK_META[net] : null;
    if (meta) {
      networkBadge = (
        <span
          data-testid={`row-network-${net}`}
          className="inline-flex items-center px-1.5 py-0.5 font-mono text-[0.6rem] font-bold tracking-wider w-fit"
          style={{ background: meta.bg, color: meta.fg }}
        >
          {net}
        </span>
      );
    }
  }
  return (
    <tr className="border-b border-white/5 hover:bg-white/5">
      <td className="px-3 py-3 font-mono text-xs">{o.id.slice(0, 6)}</td>
      <td className="px-3 py-3">{o.user_name}</td>
      <td className="px-3 py-3"><span className="text-xs uppercase">{o.user_role}</span></td>
      <td className="px-3 py-3"><CurrencyPairIcon from={o.from_code} to={o.to_code} size="sm" showLabel /></td>
      <td className="px-3 py-3 font-mono">{o.amount_from}</td>
      <td className="px-3 py-3 font-mono text-[#8B5CF6]">{o.amount_to}</td>
      <td className="px-3 py-3 text-xs">
        <div className="flex flex-col gap-1">
          <span>{o.delivery_method}</span>
          {networkBadge}
        </div>
      </td>
      <td className="px-3 py-3">
        <span className={`text-xs uppercase border px-2 py-0.5 ${STATUS_STYLES[o.status]}`}>
          {t(STATUS_KEYS[o.status] || o.status)}
        </span>
      </td>
      <td className="px-3 py-3">
        <button
          onClick={onOpen}
          data-testid={`view-order-${o.id}`}
          className="text-neutral-400 hover:text-[#8B5CF6]"
        >
          <Eye className="w-4 h-4" />
        </button>
      </td>
    </tr>
  );
}
