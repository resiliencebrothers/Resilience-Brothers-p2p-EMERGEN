import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { Layers, HandCoins } from "lucide-react";
import { API } from "@/App";
import AdminPageHeader from "@/components/AdminPageHeader";
import { useLiveRefresh } from "@/hooks/useLiveStream";
import AdminVipBatchItems from "./vip/AdminVipBatchItems";
import { AdminSettlements } from "./vip/AdminVipLedgerOps";

/**
 * iter110 — Admin hub for the VIP ledger workflows.
 * iter163 — client deposits + capital deposits moved to the dedicated
 * "Depósitos y Retiros" hub (/admin/withdrawals), gated by `withdrawals`.
 * iter171 — badge refresh is debounced (useLiveRefresh) so a burst of new
 * batches / settlements does not spawn dozens of concurrent /pending-count
 * fetches.
 */
const SUBTABS = [
  { id: "items",    labelKey: "adminVipHub.tabs.items",    icon: Layers,    countKey: "items_pending",       Component: AdminVipBatchItems },
  { id: "settle",   labelKey: "adminVipHub.tabs.settle",   icon: HandCoins, countKey: "settlements_pending", Component: AdminSettlements },
];

const BADGE_EVENTS = ["new_vip_batch", "settlement_request", "vip_batch_item_decision"];

export default function AdminVipBatches() {
  const { t } = useTranslation();
  const [active, setActive] = useState("items");
  const [counts, setCounts] = useState(null);

  const loadCounts = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/admin/vip-batches/pending-count`, {
        withCredentials: true,
        timeout: 20000,
      });
      setCounts(r.data);
    } catch { /* badge is best-effort */ }
  }, []);

  useEffect(() => { loadCounts(); }, [loadCounts]);
  useLiveRefresh(loadCounts, BADGE_EVENTS);

  const Meta = SUBTABS.find((s) => s.id === active) || SUBTABS[0];
  const ActiveComponent = Meta.Component;

  return (
    <div className="space-y-4" data-testid="admin-vip-hub">
      <AdminPageHeader
        eyebrow={t("adminVipHub.eyebrow")}
        title={t("adminVipHub.title")}
        testid="admin-vip-hub-header"
      />

      <nav className="flex items-center gap-1 border-b border-white/5 overflow-x-auto" data-testid="admin-vip-hub-tabs">
        {SUBTABS.map((tt) => {
          const Icon = tt.icon;
          const isActive = active === tt.id;
          const count = counts?.[tt.countKey] || 0;
          return (
            <button
              key={tt.id}
              type="button"
              onClick={() => setActive(tt.id)}
              data-testid={`admin-vip-hub-tab-${tt.id}`}
              className={`inline-flex items-center gap-2 px-4 py-2.5 text-xs uppercase tracking-widest font-mono border-b-2 transition-colors whitespace-nowrap ${
                isActive
                  ? "text-[#8B5CF6] border-[#8B5CF6]"
                  : "text-neutral-500 border-transparent hover:text-neutral-300"
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {t(tt.labelKey)}
              {count > 0 && (
                <span
                  data-testid={`admin-vip-hub-count-${tt.id}`}
                  className="inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1 text-[0.6rem] font-bold border border-amber-500/50 bg-amber-500/10 text-amber-400"
                >
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      <ActiveComponent onChanged={loadCounts} />
    </div>
  );
}
