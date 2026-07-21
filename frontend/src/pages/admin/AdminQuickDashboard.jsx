/**
 * iter45 — Mobile-first quick admin dashboard at `/admin/quick`.
 *
 * One screen, 4 stacked cards. Optimised for staff who pull out their phone
 * during the day to answer one question: "is there anything I need to handle
 * right now?".
 *
 *  1. Pendientes urgentes (orders + withdrawals counts + 5 most recent)
 *  2. Fondos totales de la empresa (working capital, USDT-equivalent)
 *  3. Saldos acumulados VIP (USDT-equivalent — what we owe to clients)
 *  4. Acción rápida: link grande a /admin/orders?status=pending
 *
 *  Reuses existing backend endpoints — no new server-side surface.
 */
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import axios from "axios";
import * as Sentry from "@sentry/react";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import {
  ArrowDownToLine, Coins, ListChecks, Zap, Wallet, ChevronRight,
} from "lucide-react";
import CurrencyPairIcon from "@/components/CurrencyPairIcon";

const MAIN_CURRENCIES = ["USDT", "USD", "CUP"];

export default function AdminQuickDashboard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    axios.get(`${API}/admin/quick-summary`, { withCredentials: true })
      .then((r) => { if (!cancelled) setData(r.data); })
      .catch((e) => Sentry.captureException(e))
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <div className="text-neutral-400 micro-label" data-testid="quick-loading">
        {t("admin.quickDashboard.loading")}
      </div>
    );
  }

  const pending = data?.pending || {};
  const funds = data?.company_funds || {};
  const vip = data?.vip_holdings || {};
  const ordersPending = pending.orders_count || 0;
  const withdrawalsPending = pending.withdrawals_count || 0;
  const recentOrders = pending.recent_orders || [];

  const fundsTotalUsdt = funds.total_usdt || 0;
  const fundsByCurrency = (funds.items || []).reduce((acc, it) => {
    acc[it.currency] = it;
    return acc;
  }, {});

  const vipTotalUsdt = vip.total_usdt || 0;
  const liquidityNet = fundsTotalUsdt - vipTotalUsdt;

  return (
    <div className="space-y-4 max-w-2xl mx-auto" data-testid="admin-quick-dashboard">
      {/* Header */}
      <div className="flex items-center gap-3 mb-2">
        <Zap className="w-5 h-5 text-[#8B5CF6]" />
        <div>
          <div className="micro-label text-[#8B5CF6]">{t("admin.quickDashboard.eyebrow")}</div>
          <h1 className="font-display text-2xl">{t("admin.quickDashboard.title")}</h1>
        </div>
      </div>

      <section
        className="tactile-card p-5 border-l-2 border-l-[#8B5CF6]"
        data-testid="quick-pending-card"
      >
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <ListChecks className="w-5 h-5 text-[#8B5CF6]" />
            <h2 className="font-display text-lg">{t("admin.quickDashboard.pending")}</h2>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 mb-4">
          <PendingStat
            label={t("admin.quickDashboard.orders")} value={ordersPending}
            testId="quick-orders-pending"
          />
          <PendingStat
            icon={ArrowDownToLine} label={t("admin.quickDashboard.withdrawalsShort")} value={withdrawalsPending}
            testId="quick-withdrawals-pending"
          />
        </div>
        {recentOrders.length > 0 && (
          <div className="border-t border-white/5 pt-3 space-y-2">
            <div className="micro-label text-neutral-500 text-[0.6rem] mb-1">
              {t("admin.quickDashboard.lastFive")}
            </div>
            {recentOrders.map((o) => (
              <button
                key={o.id}
                onClick={() => navigate("/admin/orders")}
                className="w-full flex items-center justify-between text-left py-1.5 px-1 hover:bg-white/5 transition-colors"
                data-testid={`quick-recent-order-${o.id}`}
              >
                <CurrencyPairIcon from={o.from_code} to={o.to_code} size="sm" showLabel />
                <span className="font-mono text-xs text-neutral-500">
                  {(o.amount_from || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </span>
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="tactile-card p-5" data-testid="quick-funds-card">
        <div className="flex items-center gap-2 mb-3">
          <Wallet className="w-5 h-5 text-[#8B5CF6]" />
          <h2 className="font-display text-lg">{t("admin.quickDashboard.companyFunds")}</h2>
        </div>
        <BigUsdtValue value={fundsTotalUsdt} testId="quick-funds-total" t={t} />
        <div className="grid grid-cols-3 gap-2 mt-4">
          {MAIN_CURRENCIES.map((code) => (
            <CurrencyChip
              key={code}
              code={code}
              item={fundsByCurrency[code]}
              testId={`quick-funds-${code.toLowerCase()}`}
            />
          ))}
        </div>
      </section>

      <section className="tactile-card p-5" data-testid="quick-vip-card">
        <div className="flex items-center gap-2 mb-3">
          <Coins className="w-5 h-5 text-[#8B5CF6]" />
          <h2 className="font-display text-lg">{t("admin.quickDashboard.vipHoldings")}</h2>
          <span className="text-xs text-neutral-500 ml-auto">
            {t("admin.quickDashboard.vipWeOwe")}
          </span>
        </div>
        <BigUsdtValue value={vipTotalUsdt} testId="quick-vip-total" t={t} />
        <div
          className="mt-3 pt-3 border-t border-white/5 flex items-center justify-between"
          data-testid="quick-liquidity-net"
        >
          <span className="text-xs text-neutral-500">{t("admin.quickDashboard.netLiquidity")}</span>
          <span
            className={`font-mono text-sm font-semibold ${
              liquidityNet >= 0 ? "text-emerald-400" : "text-red-400"
            }`}
          >
            {liquidityNet >= 0 ? "+" : ""}
            {liquidityNet.toLocaleString(undefined, { maximumFractionDigits: 2 })} USDT
          </span>
        </div>
      </section>

      <Link
        to="/admin/orders"
        className="block"
        data-testid="quick-action-cta"
      >
        <Button
          className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none font-semibold py-6 text-base"
        >
          {t("admin.quickDashboard.viewAllPending")}
          <ChevronRight className="w-5 h-5 ml-1" />
        </Button>
      </Link>
    </div>
  );
}

function PendingStat({ icon: Icon, label, value, testId }) {
  const isActive = value > 0;
  return (
    <div
      className={`p-3 ${isActive ? "bg-[#8B5CF6]/10 border border-[#8B5CF6]/30" : "bg-white/5 border border-white/5"}`}
      data-testid={testId}
    >
      {Icon && <Icon className="w-4 h-4 text-neutral-400 mb-1" />}
      <div className="micro-label text-neutral-500 text-[0.6rem]">{label}</div>
      <div className={`font-display text-3xl mt-1 ${isActive ? "text-[#8B5CF6]" : "text-neutral-400"}`}>
        {value}
      </div>
    </div>
  );
}

function BigUsdtValue({ value, testId, t }) {
  return (
    <div data-testid={testId}>
      <div className="micro-label text-neutral-500 text-[0.6rem]">{t("admin.quickDashboard.totalPrefix")}</div>
      <div className="font-display text-3xl text-[#8B5CF6] mt-1">
        {(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
        <span className="text-sm text-neutral-400 ml-1">USDT</span>
      </div>
    </div>
  );
}

function CurrencyChip({ code, item, testId }) {
  return (
    <div
      className="bg-black/40 border border-white/5 p-2 text-center"
      data-testid={testId}
    >
      <div className="micro-label text-neutral-500 text-[0.55rem]">{code}</div>
      <div className="font-mono text-xs text-neutral-200 mt-0.5">
        {item ? (item.balance || 0).toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—"}
      </div>
    </div>
  );
}
