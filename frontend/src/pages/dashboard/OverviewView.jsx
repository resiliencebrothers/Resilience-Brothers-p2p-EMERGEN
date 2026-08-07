import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { useTranslation } from "react-i18next";
import { Activity, TrendingUp, Wallet, ArrowUpRight, CheckCircle, Clock, Boxes } from "lucide-react";
import { Link } from "react-router-dom";
import CurrencyPairIcon from "@/components/CurrencyPairIcon";
import { FlashNumber } from "@/components/FlashNumber";
import { useLiveEvent } from "@/hooks/useLiveStream";
import {
  ORDER_IN_FLIGHT,
  ORDER_COMPLETED,
  WITHDRAWAL_IN_FLIGHT,
  WITHDRAWAL_COMPLETED,
} from "@/constants/orderStatus";

export default function OverviewView() {
  const { user } = useAuth();
  const { t } = useTranslation();
  const [rates, setRates] = useState([]);
  const [orders, setOrders] = useState([]);
  const [withdrawals, setWithdrawals] = useState([]);
  const [balances, setBalances] = useState(null);
  const [batchStats, setBatchStats] = useState(null);
  const [productCount, setProductCount] = useState(null);

  // iter114 — VIP batch orders count toward the dashboard summary cards.
  const isVipRole = user?.role === "vip";
  const refreshBatchStats = useCallback(() => {
    if (!isVipRole) return;
    axios.get(`${API}/vip/batch-stats`, { withCredentials: true })
      .then(r => setBatchStats(r.data))
      .catch(() => {});
  }, [isVipRole]);

  useEffect(() => {
    axios.get(`${API}/rates`).then(r => setRates(r.data)).catch(() => {});
    axios.get(`${API}/orders/mine`, { withCredentials: true }).then(r => setOrders(r.data)).catch(() => {});
    axios.get(`${API}/vip/balances`, { withCredentials: true }).then(r => setBalances(r.data)).catch(() => {});
    axios.get(`${API}/products`).then(r => setProductCount(r.data.length)).catch(() => {});
    // iter55.22 — include VIP withdrawals so a "cash approved / En progreso" retiro
    // counts as pending until it's actually delivered/paid.
    axios.get(`${API}/vip/withdrawals/mine`, { withCredentials: true })
      .then(r => setWithdrawals(r.data))
      .catch(() => {});
    refreshBatchStats();
  }, [refreshBatchStats]);

  // iter97 — live SSE refresh so operators don't have to reload the tab
  // after an admin updates a rate, or after their own order/withdrawal
  // moves to a new status.
  const refreshRates = useCallback(() => {
    axios.get(`${API}/rates`).then(r => setRates(r.data)).catch(() => {});
  }, []);
  const refreshOrdersAndBalances = useCallback(() => {
    axios.get(`${API}/orders/mine`, { withCredentials: true }).then(r => setOrders(r.data)).catch(() => {});
    axios.get(`${API}/vip/balances`, { withCredentials: true }).then(r => setBalances(r.data)).catch(() => {});
    axios.get(`${API}/vip/withdrawals/mine`, { withCredentials: true }).then(r => setWithdrawals(r.data)).catch(() => {});
    refreshBatchStats();
  }, [refreshBatchStats]);
  useLiveEvent("rates_updated", refreshRates);
  useLiveEvent("order_status_changed", refreshOrdersAndBalances);
  useLiveEvent("withdrawal_status_changed", refreshOrdersAndBalances);
  useLiveEvent("balance_updated", refreshOrdersAndBalances);

  const isVip = user?.role === "vip" || user?.role === "admin";
  const isStaff = user?.role === "admin" || user?.role === "employee";
  const isClient = user && !isStaff;

  const pendingOrders = orders.filter(o => ORDER_IN_FLIGHT.has(o.status)).length;
  const pendingWithdrawals = withdrawals.filter(w => WITHDRAWAL_IN_FLIGHT.has(w.status)).length;
  const pending = pendingOrders + pendingWithdrawals + (batchStats?.items_pending || 0);

  const completedOrders = orders.filter(o => ORDER_COMPLETED.has(o.status)).length;
  const completedWithdrawals = withdrawals.filter(w => WITHDRAWAL_COMPLETED.has(w.status)).length;
  const approved = completedOrders + completedWithdrawals + (batchStats?.items_approved || 0);

  return (
    <div className="space-y-8" data-testid="overview-view">
      <div>
        <div className="micro-label text-[#8B5CF6] mb-2">{t("dashboard.breadcrumb")}</div>
        <h1 className="font-display text-3xl lg:text-4xl">
          {t("dashboard.greeting", { name: user?.name?.split(" ")[0] || "" })}
        </h1>
        <p className="text-neutral-400 mt-2">
          {isVip ? t("dashboard.accountVip") : t("dashboard.accountStandard")}
        </p>
      </div>

      {/* Summary cards — every card is now a quick-action button that keeps
          showing its info (owner request, Jun 2026). */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={Wallet}
          label={t("dashboard.stats.totalBalance")}
          value={(
            <FlashNumber value={balances?.total_usdt || 0} testid="overview-total-flash">
              {(balances?.total_usdt || 0).toFixed(2)}
            </FlashNumber>
          )}
          sub={t("dashboard.stats.totalBalanceSub")}
          to={isClient ? "/dashboard/assets" : undefined}
          testid="stat-saldo-total"
        />
        {isClient ? (
          <StatCard
            icon={Boxes}
            label={t("dashboard.stats.marketplace")}
            value={productCount ?? "—"}
            sub={t("dashboard.stats.marketplaceSub")}
            to="/dashboard/marketplace"
            testid="stat-marketplace"
          />
        ) : (
          <StatCard
            icon={Clock}
            label={t("dashboard.stats.pending")}
            value={pending}
            sub={t("dashboard.stats.pendingSub")}
            to="/dashboard/orders?filter=pending"
            testid="stat-pendientes"
          />
        )}
        <StatCard
          icon={CheckCircle}
          label={t("dashboard.stats.completed")}
          value={approved}
          sub={t("dashboard.stats.completedSub")}
          to="/dashboard/orders?filter=completed"
          testid="stat-completadas"
        />
        <StatCard
          icon={Activity}
          label={t("dashboard.stats.statusLabel")}
          value={user?.role?.toUpperCase()}
          sub={t("dashboard.stats.statusSub")}
          to="/dashboard/profile"
          testid="stat-estatus"
        />
      </div>

      <div className="tactile-card p-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="font-display text-xl flex items-center gap-2"><TrendingUp className="w-5 h-5 text-[#8B5CF6]" /> {t("dashboard.currentRates")}</h2>
          <Link to="/dashboard/exchange" className="micro-label text-[#8B5CF6] hover:underline">{t("dashboard.operate")}</Link>
        </div>
        <div
          className="space-y-2 max-h-[420px] overflow-y-auto pr-2"
          data-testid="dashboard-current-rates-scroll"
        >
          {rates.length === 0 && <p className="text-neutral-500 text-sm">{t("dashboard.noRatesYet")}</p>}
          {rates.map(r => (
            <div key={r.id || `${r.from_code}-${r.to_code}`} className="flex items-center justify-between border-b border-white/5 py-3 last:border-0">
              <div>
                <CurrencyPairIcon from={r.from_code} to={r.to_code} size="md" showLabel />
              </div>
              <div className="text-right">
                <div className="font-mono text-sm">
                  {isVip ? (
                    <span className="text-[#22C55E]">{r.rate_vip}</span>
                  ) : (
                    <span>{r.rate_normal}</span>
                  )}
                </div>
                <div className="micro-label text-neutral-500 text-[0.6rem]">
                  {isVip ? t("dashboard.vipRateLabel") : `VIP: ${r.rate_vip}`}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function StatCard({ icon: Icon, label, value, sub, to, testid }) {
  const body = (
    <>
      <div className="flex items-start justify-between mb-3">
        <Icon className="w-5 h-5 text-[#8B5CF6]" />
        {to && <ArrowUpRight className="w-4 h-4 text-neutral-600 group-hover:text-[#8B5CF6] transition-colors" />}
      </div>
      <div className="micro-label text-neutral-500">{label}</div>
      <div className="font-display text-2xl mt-1">{value}</div>
      <div className="text-xs text-neutral-500 mt-1">{sub}</div>
    </>
  );
  if (to) {
    return (
      <Link
        to={to}
        data-testid={testid}
        className="tactile-card p-5 block group hover:border-[#8B5CF6]/50 hover:bg-white/[0.02] transition-colors focus:outline-none focus:ring-2 focus:ring-[#8B5CF6]/60"
      >
        {body}
      </Link>
    );
  }
  return (
    <div className="tactile-card p-5" data-testid={testid}>
      {body}
    </div>
  );
}
