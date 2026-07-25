import { useEffect, useState, useRef, useCallback } from "react";
import axios from "axios";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { ListChecks, ArrowDownToLine, Radio } from "lucide-react";
import { toast } from "sonner";
import DefensiveModePanel from "@/components/DefensiveModePanel";
import CurrencyPairIcon from "@/components/CurrencyPairIcon";
import { useLiveEvent, useLiveStatus } from "@/hooks/useLiveStream";

const PENDING_ORDER_STATUSES = new Set(["pending", "requires_double_approval"]);
const PENDING_WITHDRAWAL_STATUSES = new Set(["pending", "approved"]);
const FLASH_MS = 4000;

export default function AdminQueue() {
  const { t } = useTranslation();
  const [data, setData] = useState({ orders: [], withdrawals: [], counts: { orders: 0, withdrawals: 0 } });
  const [loading, setLoading] = useState(true);
  // iter98 — track newly-arrived rows (via SSE) so we can flash them briefly.
  const [flashIds, setFlashIds] = useState(new Set());
  const connected = useLiveStatus();
  const flashTimeoutsRef = useRef({});

  useEffect(() => {
    const load = async () => {
      try {
        const r = await axios.get(`${API}/admin/queue`, { withCredentials: true });
        setData(r.data);
      } catch (e) {
        toast.error(t("adminQueue.loadError"));
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [t]);

  const flashRow = useCallback((id) => {
    setFlashIds((prev) => {
      const next = new Set(prev);
      next.add(id);
      return next;
    });
    // Clear any previous timer for the same id so re-flashing works.
    if (flashTimeoutsRef.current[id]) clearTimeout(flashTimeoutsRef.current[id]);
    flashTimeoutsRef.current[id] = setTimeout(() => {
      setFlashIds((prev) => {
        if (!prev.has(id)) return prev;
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      delete flashTimeoutsRef.current[id];
    }, FLASH_MS);
  }, []);

  useEffect(() => {
    // Cleanup any pending flash timeouts on unmount.
    const timeouts = flashTimeoutsRef.current;
    return () => {
      Object.values(timeouts).forEach(clearTimeout);
    };
  }, []);

  // Prepend new order when it lands.
  useLiveEvent("order_created", (o) => {
    if (!o?.id) return;
    setData((prev) => {
      // Avoid duplicates if the initial GET also lists it.
      if (prev.orders.some((x) => x.id === o.id)) return prev;
      const orders = [o, ...prev.orders];
      return { ...prev, orders, counts: { ...prev.counts, orders: orders.length } };
    });
    flashRow(o.id);
  });

  // Prepend new withdrawal when it lands.
  useLiveEvent("withdrawal_created", (w) => {
    if (!w?.id) return;
    setData((prev) => {
      if (prev.withdrawals.some((x) => x.id === w.id)) return prev;
      const withdrawals = [w, ...prev.withdrawals];
      return { ...prev, withdrawals, counts: { ...prev.counts, withdrawals: withdrawals.length } };
    });
    flashRow(w.id);
  });

  // Remove order from queue when it leaves pending status.
  useLiveEvent("order_status_changed", (payload) => {
    if (!payload?.order_id) return;
    setData((prev) => {
      const stillPending = PENDING_ORDER_STATUSES.has(payload.status);
      const filtered = stillPending
        ? prev.orders
        : prev.orders.filter((o) => o.id !== payload.order_id);
      if (filtered.length === prev.orders.length && stillPending) return prev;
      return { ...prev, orders: filtered, counts: { ...prev.counts, orders: filtered.length } };
    });
  });

  useLiveEvent("withdrawal_status_changed", (payload) => {
    if (!payload?.withdrawal_id) return;
    setData((prev) => {
      const stillPending = PENDING_WITHDRAWAL_STATUSES.has(payload.status);
      const filtered = stillPending
        ? prev.withdrawals
        : prev.withdrawals.filter((w) => w.id !== payload.withdrawal_id);
      if (filtered.length === prev.withdrawals.length && stillPending) return prev;
      return { ...prev, withdrawals: filtered, counts: { ...prev.counts, withdrawals: filtered.length } };
    });
  });

  const ORDER_STATUS = {
    pending: t("adminQueue.orders.statusPending"),
    requires_double_approval: t("adminQueue.orders.statusDoubleApproval"),
  };

  if (loading) return <div className="text-neutral-500 micro-label">{t("adminQueue.loading")}</div>;

  const empty = data.counts.orders === 0 && data.counts.withdrawals === 0;
  const flashClass = "queue-row-flash";

  return (
    <div data-testid="admin-queue" className="space-y-8">
      <style>{`
        @keyframes queueFlash {
          0%   { background-color: rgba(139, 92, 246, 0.28); }
          40%  { background-color: rgba(139, 92, 246, 0.18); }
          100% { background-color: transparent; }
        }
        .queue-row-flash {
          animation: queueFlash ${FLASH_MS}ms ease-out;
        }
      `}</style>

      <div>
        <div className="micro-label text-[#8B5CF6] mb-2 flex items-center gap-2">
          {t("adminQueue.eyebrow")}
          <span
            data-testid="admin-queue-live-indicator"
            className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[0.55rem] uppercase tracking-wider font-mono border ${
              connected
                ? "text-[#22C55E] border-[#22C55E]/40 bg-[#22C55E]/10"
                : "text-neutral-500 border-neutral-500/40 bg-neutral-500/10"
            }`}
            title={connected ? t("adminQueue.liveOn") : t("adminQueue.liveOff")}
          >
            <Radio className="w-2.5 h-2.5" /> {connected ? t("adminQueue.liveOn") : t("adminQueue.liveOff")}
          </span>
        </div>
        <h1 className="font-display text-3xl">{t("adminQueue.title")}</h1>
        <p className="text-neutral-500 text-sm mt-2">
          {t("adminQueue.subtitle")}
        </p>
      </div>

      <DefensiveModePanel />

      {empty && (
        <div className="tactile-card p-12 text-center">
          <div className="micro-label text-[#22C55E] mb-2">{t("adminQueue.allClear")}</div>
          <p className="text-neutral-400">{t("adminQueue.emptyBody")}</p>
        </div>
      )}

      {data.counts.orders > 0 && (
        <section data-testid="queue-orders">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-display text-xl flex items-center gap-2">
              <ListChecks className="w-5 h-5 text-[#8B5CF6]" /> {t("adminQueue.orders.sectionTitle")}
              <span className="text-xs text-neutral-500 font-mono">({data.counts.orders})</span>
            </h2>
            <Link to="/admin/orders" className="micro-label text-[#8B5CF6] hover:underline">
              {t("adminQueue.orders.goto")}
            </Link>
          </div>
          <div className="tactile-card overflow-x-auto">
            <table className="w-full text-sm min-w-[720px]">
              <thead className="bg-[#0a0a0a] border-b border-white/10">
                <tr className="text-left">
                  <th className="px-4 py-3 micro-label text-neutral-500">{t("adminQueue.orders.colUser")}</th>
                  <th className="px-4 py-3 micro-label text-neutral-500">{t("adminQueue.orders.colPair")}</th>
                  <th className="px-4 py-3 micro-label text-neutral-500">{t("adminQueue.orders.colAmount")}</th>
                  <th className="px-4 py-3 micro-label text-neutral-500">{t("adminQueue.orders.colMethod")}</th>
                  <th className="px-4 py-3 micro-label text-neutral-500">{t("adminQueue.orders.colStatus")}</th>
                  <th className="px-4 py-3 micro-label text-neutral-500">{t("adminQueue.orders.colCreated")}</th>
                </tr>
              </thead>
              <tbody>
                {data.orders.slice(0, 50).map(o => (
                  <tr
                    key={o.id}
                    className={`border-b border-white/5 ${flashIds.has(o.id) ? flashClass : ""}`}
                    data-testid={`queue-order-${o.id}`}
                  >
                    <td className="px-4 py-3">{o.user_name}</td>
                    <td className="px-4 py-3"><CurrencyPairIcon from={o.from_code} to={o.to_code} size="md" showLabel /></td>
                    <td className="px-4 py-3 font-mono text-[#8B5CF6]">{o.amount_from} {o.from_code}</td>
                    <td className="px-4 py-3 text-xs">{o.delivery_method}</td>
                    <td className="px-4 py-3 text-xs uppercase">{ORDER_STATUS[o.status] || o.status}</td>
                    <td className="px-4 py-3 text-xs text-neutral-500">{new Date(o.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.orders.length > 50 && (
              <div className="px-4 py-2 text-xs text-neutral-500 border-t border-white/10">
                {t("adminQueue.orders.showingOf", { count: data.orders.length })}
              </div>
            )}
          </div>
        </section>
      )}

      {data.counts.withdrawals > 0 && (
        <section data-testid="queue-withdrawals">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-display text-xl flex items-center gap-2">
              <ArrowDownToLine className="w-5 h-5 text-[#8B5CF6]" /> {t("adminQueue.withdrawals.sectionTitle")}
              <span className="text-xs text-neutral-500 font-mono">({data.counts.withdrawals})</span>
            </h2>
            <Link to="/admin/withdrawals" className="micro-label text-[#8B5CF6] hover:underline">
              {t("adminQueue.withdrawals.goto")}
            </Link>
          </div>
          <div className="tactile-card overflow-x-auto">
            <table className="w-full text-sm min-w-[720px]">
              <thead className="bg-[#0a0a0a] border-b border-white/10">
                <tr className="text-left">
                  <th className="px-4 py-3 micro-label text-neutral-500">{t("adminQueue.withdrawals.colUser")}</th>
                  <th className="px-4 py-3 micro-label text-neutral-500">{t("adminQueue.withdrawals.colAmount")}</th>
                  <th className="px-4 py-3 micro-label text-neutral-500">{t("adminQueue.withdrawals.colCurrency")}</th>
                  <th className="px-4 py-3 micro-label text-neutral-500">{t("adminQueue.withdrawals.colMethod")}</th>
                  <th className="px-4 py-3 micro-label text-neutral-500">{t("adminQueue.withdrawals.colRequested")}</th>
                </tr>
              </thead>
              <tbody>
                {data.withdrawals.slice(0, 50).map(w => (
                  <tr
                    key={w.id}
                    className={`border-b border-white/5 ${flashIds.has(w.id) ? flashClass : ""}`}
                    data-testid={`queue-withdrawal-${w.id}`}
                  >
                    <td className="px-4 py-3">{w.user_name}</td>
                    <td className="px-4 py-3 font-mono text-[#8B5CF6]">{w.amount_usd}</td>
                    <td className="px-4 py-3 font-mono">{w.currency || "USD"}</td>
                    <td className="px-4 py-3 text-xs">
                      {w.method}
                      {w.method === "crypto" && w.crypto_network && (
                        <span className="ml-1.5 inline-flex items-center px-1.5 py-0.5 text-[0.55rem] uppercase tracking-wider bg-[#8B5CF6]/10 text-[#8B5CF6] border border-[#8B5CF6]/30 font-mono">
                          {w.crypto_network}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-neutral-500">{new Date(w.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
