import { useTranslation } from "react-i18next";
import AdminPageHeader from "@/components/AdminPageHeader";
import AdminVipBatchItems from "./vip/AdminVipBatchItems";

/**
 * iter110 — Admin hub for the VIP ledger workflows.
 * iter163 — client deposits + capital deposits moved to the dedicated
 * "Depósitos y Retiros" hub (/admin/withdrawals), gated by `withdrawals`.
 * iter189 — "Cobros y Pagos" (settlements) tab removed: that flow is fully
 * covered by the Depósitos y Retiros hub, so this page is now just the
 * VIP orders queue.
 */
export default function AdminVipBatches() {
  const { t } = useTranslation();
  return (
    <div className="space-y-4" data-testid="admin-vip-hub">
      <AdminPageHeader
        eyebrow={t("adminVipHub.eyebrow")}
        title={t("adminVipHub.title")}
        testid="admin-vip-hub-header"
      />
      <AdminVipBatchItems />
    </div>
  );
}
