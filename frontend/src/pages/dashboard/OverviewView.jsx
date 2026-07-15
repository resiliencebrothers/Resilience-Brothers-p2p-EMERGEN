import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { useTranslation } from "react-i18next";
import { Activity, TrendingUp, Wallet, ArrowUpRight, CheckCircle, Clock } from "lucide-react";
import { Link } from "react-router-dom";
import BalanceConverterCard from "@/components/BalanceConverterCard";
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

  useEffect(() => {
    axios.get(`${API}/rates`).then(r => setRates(r.data)).catch(() => {});
    axios.get(`${API}/orders/mine`, { withCredentials: true }).then(r => setOrders(r.data)).catch(() => {});
    axios.get(`${API}/vip/balances`, { withCredentials: true }).then(r => setBalances(r.data)).catch(() => {});
    // iter55.22 — include VIP withdrawals so a "cash approved / En progreso" retiro
    // counts as pending until it's actually delivered/paid.
    axios.get(`${API}/vip/withdrawals/mine`, { withCredentials: true })
      .then(r => setWithdrawals(r.data))
      .catch(() => {});
  }, []);

  const isVip = user?.role === "vip" || user?.role === "admin";
  const isStaff = user?.role === "admin" || user?.role === "employee";
  const isClient = user && !isStaff;

  // iter55.22 / .25 — status semantics are the single source of truth in
  // src/constants/orderStatus.js so the dashboard counter and the
  // /orders filter pills can't drift again (that drift caused the bug fixed
  // in iter55.25 — "Pendientes: 2" showing when the table had 1 row).
  const pendingOrders = orders.filter(o => ORDER_IN_FLIGHT.has(o.status)).length;
  const pendingWithdrawals = withdrawals.filter(w => WITHDRAWAL_IN_FLIGHT.has(w.status)).length;
  const pending = pendingOrders + pendingWithdrawals;

  const completedOrders = orders.filter(o => ORDER_COMPLETED.has(o.status)).length;
  const completedWithdrawals = withdrawals.filter(w => WITHDRAWAL_COMPLETED.has(w.status)).length;
  const approved = completedOrders + completedWithdrawals;

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

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={Wallet}
          label={t("dashboard.stats.totalBalance")}
          value={`${(balances?.total_usdt || 0).toFixed(2)}`}
          sub={t("dashboard.stats.totalBalanceSub")}
        />
        <StatCard
          icon={Clock}
          label={t("dashboard.stats.pending")}
          value={pending}
          sub={t("dashboard.stats.pendingSub")}
          to="/dashboard/orders?filter=pending"
          testid="stat-pendientes"
        />
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
        />
      </div>

      {/* iter50 — Converter widget visible to normal + vip clients */}
      {isClient && (
        <BalanceConverterCard
          onConverted={() =>
            axios.get(`${API}/vip/balances`, { withCredentials: true })
              .then((r) => setBalances(r.data))
              .catch(() => {})
          }
        />
      )}

      <div className="grid lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 tactile-card p-6">
          <div className="flex items-center justify-between mb-6">
            <h2 className="font-display text-xl flex items-center gap-2"><TrendingUp className="w-5 h-5 text-[#8B5CF6]" /> {t("dashboard.currentRates")}</h2>
            <Link to="/dashboard/exchange" className="micro-label text-[#8B5CF6] hover:underline">{t("dashboard.operate")}</Link>
          </div>
          <div className="space-y-2">
            {rates.length === 0 && <p className="text-neutral-500 text-sm">{t("dashboard.noRatesYet")}</p>}
            {rates.map(r => (
              <div key={r.id} className="flex items-center justify-between border-b border-white/5 py-3 last:border-0">
                <div>
                  <span className="font-mono text-sm">{r.from_code} → {r.to_code}</span>
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
        <div className="tactile-card p-6">
          <h2 className="font-display text-xl mb-4">{t("dashboard.quickActions")}</h2>
          <div className="space-y-2">
            <Link to="/dashboard/exchange" data-testid="quick-exchange" className="block border border-white/10 hover:border-[#8B5CF6] p-4 transition-colors group">
              <div className="flex items-center justify-between">
                <span className="font-medium">{t("dashboard.newExchange")}</span>
                <ArrowUpRight className="w-4 h-4 text-neutral-500 group-hover:text-[#8B5CF6]" />
              </div>
              <div className="micro-label text-neutral-500 mt-1">{t("dashboard.newExchangeSub")}</div>
            </Link>
            <Link to="/dashboard/orders" data-testid="quick-orders" className="block border border-white/10 hover:border-[#8B5CF6] p-4 transition-colors group">
              <div className="flex items-center justify-between">
                <span className="font-medium">{t("dashboard.viewOrders")}</span>
                <ArrowUpRight className="w-4 h-4 text-neutral-500 group-hover:text-[#8B5CF6]" />
              </div>
              <div className="micro-label text-neutral-500 mt-1">{t("dashboard.viewOrdersSub")}</div>
            </Link>
            {isClient && (
              <Link to="/dashboard/marketplace" data-testid="quick-marketplace" className="block border border-white/10 hover:border-[#8B5CF6] p-4 transition-colors group">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{t("dashboard.marketplaceLink")}</span>
                  <ArrowUpRight className="w-4 h-4 text-neutral-500 group-hover:text-[#8B5CF6]" />
                </div>
                <div className="micro-label text-neutral-500 mt-1">{t("dashboard.marketplaceLinkSub")}</div>
              </Link>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function StatCard({ icon: Icon, label, value, sub, to, testid }) {
  const body = (
    <>
      <Icon className="w-5 h-5 text-[#8B5CF6] mb-3" />
      <div className="micro-label text-neutral-500">{label}</div>
      <div className="font-display text-2xl mt-1">{value}</div>
      <div className="text-xs text-neutral-500 mt-1">{sub}</div>
    </>
  );
  // iter55.25b — when the card represents a filtered list (Pendientes,
  // Completadas), wrap it in a Link so the user can jump straight to the
  // matching filtered view. Static cards (Saldo, Estatus) render as plain divs.
  if (to) {
    return (
      <Link
        to={to}
        data-testid={testid}
        className="tactile-card p-5 block hover:border-[#8B5CF6]/50 hover:bg-white/[0.02] transition-colors focus:outline-none focus:ring-2 focus:ring-[#8B5CF6]/60"
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
