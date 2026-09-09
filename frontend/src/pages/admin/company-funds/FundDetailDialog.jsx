/**
 * iter268 — FundDetailDialog
 *
 * Dashboard por moneda del Fondo de Empresa. Se abre al tocar la tarjeta
 * (bloque dinámico de entradas/salidas o el pasivo de clientes) y muestra:
 *  - KPIs: disponible, balance bruto, custodia de clientes
 *  - Entradas y salidas desglosadas con totales
 *  - Rentabilidad total
 *  - Desglose por CLIENTE del saldo por pagar (a quién se le debe y cuánto)
 */
import { useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { API } from "@/App";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import {
  ArrowDownLeft, ArrowUpRight, AlertTriangle, LayoutDashboard,
  TrendingUp, TrendingDown, UserRound,
} from "lucide-react";

const fmt = (n) =>
  Number(n || 0).toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });

function Kpi({ label, value, tone, testId }) {
  const cls = { pos: "text-[#22C55E]", neg: "text-[#EF4444]", warn: "text-[#F59E0B]", neutral: "text-neutral-200" }[tone];
  return (
    <div className="border border-white/10 bg-white/[0.02] px-3 py-2 min-w-0" data-testid={testId}>
      <div className="text-[0.55rem] uppercase tracking-widest text-neutral-500 truncate">{label}</div>
      <div className={`font-display text-xl mt-0.5 tabular-nums ${cls}`}>{fmt(value)}</div>
    </div>
  );
}

function DashRow({ label, value, tone }) {
  const zero = !Number(value);
  const cls = zero ? "text-neutral-600" : tone === "in" ? "text-[#22C55E]" : "text-[#F87171]";
  return (
    <div className="flex items-baseline justify-between gap-3 text-[0.75rem] font-mono py-1 border-b border-white/5 last:border-0">
      <span className={zero ? "text-neutral-600" : "text-neutral-400"}>{label}</span>
      <span className={`${cls} tabular-nums whitespace-nowrap`}>{fmt(value)}</span>
    </div>
  );
}

export default function FundDetailDialog({ fund, onClose }) {
  const { t } = useTranslation();
  const [clients, setClients] = useState(null);
  const [loadingClients, setLoadingClients] = useState(false);
  const f = fund;

  useEffect(() => {
    if (!f) { setClients(null); return undefined; }
    let ignore = false;
    setLoadingClients(true);
    axios.get(`${API}/admin/company-funds/client-balances/${encodeURIComponent(f.currency)}`, {
      withCredentials: true,
    })
      .then((r) => { if (!ignore) setClients(r.data); })
      .catch(() => { if (!ignore) toast.error(t("admin.companyFunds.clientBreakdownLoadError")); })
      .finally(() => { if (!ignore) setLoadingClients(false); });
    return () => { ignore = true; };
  }, [f, t]);

  if (!f) {
    return <Dialog open={false} onOpenChange={() => onClose?.()} />;
  }

  const inTotal = (f.inflow || 0) + (f.inflow_vip_batches || 0) + (f.inflow_deposits || 0) + (f.manual_inflow || 0);
  const outTotal = (f.outflow_orders || 0) + (f.outflow_clients || 0) + (f.outflow_company || 0) + (f.manual_outflow || 0);
  const profit = Number(f.profit_total || 0);
  const profitPos = profit >= 0;
  const ProfitIcon = profitPos ? TrendingUp : TrendingDown;

  return (
    <Dialog open={!!fund} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent
        data-testid="fund-dashboard-dialog"
        className="bg-[#0c0c0c] border border-[#8B5CF6]/30 text-white rounded-none max-w-2xl max-h-[85vh] overflow-y-auto tx-body-scroll"
      >
        <DialogHeader>
          <DialogTitle className="font-mono flex items-center gap-2">
            <LayoutDashboard className="w-4 h-4 text-[#8B5CF6]" />
            {t("admin.companyFunds.fundDashTitle", { currency: f.currency })}
          </DialogTitle>
          <DialogDescription className="text-xs text-neutral-500">
            {t("admin.companyFunds.fundDashSub")}
          </DialogDescription>
        </DialogHeader>

        {/* KPIs */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          <Kpi label={t("admin.companyFunds.availableBalance")}
            value={f.balance_available ?? f.balance}
            tone={(f.balance_available ?? f.balance) >= 0 ? "pos" : "neg"}
            testId="fund-dash-available" />
          <Kpi label={t("admin.companyFunds.grossBalance")} value={f.balance}
            tone="neutral" testId="fund-dash-gross" />
          <Kpi label={t("admin.companyFunds.clientBalancesOwed")}
            value={f.client_balances} tone="warn" testId="fund-dash-custody" />
        </div>

        {/* Entradas / Salidas */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-1">
          <div className="border border-[#22C55E]/20 bg-[#22C55E]/[0.04] p-3" data-testid="fund-dash-inflows">
            <div className="flex items-center justify-between gap-2 pb-2 border-b border-white/10">
              <div className="flex items-center gap-1.5 text-[0.6rem] uppercase tracking-widest text-neutral-400">
                <ArrowDownLeft className="w-3 h-3 text-[#22C55E]" />
                <span>{t("admin.companyFunds.inflows")}</span>
              </div>
              <span className="font-mono text-[0.8rem] text-[#22C55E] tabular-nums" data-testid="fund-dash-in-total">
                {fmt(inTotal)}
              </span>
            </div>
            <div className="mt-1">
              <DashRow label={t("admin.companyFunds.orders")} value={f.inflow} tone="in" />
              <DashRow label={t("admin.companyFunds.vipBatchesIn")} value={f.inflow_vip_batches} tone="in" />
              <DashRow label={t("admin.companyFunds.depositsIn")} value={f.inflow_deposits} tone="in" />
              <DashRow label={t("admin.companyFunds.ownContribution")} value={f.manual_inflow} tone="in" />
            </div>
          </div>
          <div className="border border-[#EF4444]/20 bg-[#EF4444]/[0.04] p-3" data-testid="fund-dash-outflows">
            <div className="flex items-center justify-between gap-2 pb-2 border-b border-white/10">
              <div className="flex items-center gap-1.5 text-[0.6rem] uppercase tracking-widest text-neutral-400">
                <ArrowUpRight className="w-3 h-3 text-[#EF4444]" />
                <span>{t("admin.companyFunds.outflows")}</span>
              </div>
              <span className="font-mono text-[0.8rem] text-[#F87171] tabular-nums" data-testid="fund-dash-out-total">
                {fmt(outTotal)}
              </span>
            </div>
            <div className="mt-1">
              <DashRow label={t("admin.companyFunds.deliveredToClients")} value={f.outflow_orders} tone="out" />
              <DashRow label={t("admin.companyFunds.vipWithdrawals")} value={f.outflow_clients_vip} tone="out" />
              <DashRow label={t("admin.companyFunds.normalWithdrawals")} value={f.outflow_clients_normal} tone="out" />
              <DashRow label={t("admin.companyFunds.companyOutflow")} value={f.outflow_company} tone="out" />
              <DashRow label={t("admin.companyFunds.ownOutflow")} value={f.manual_outflow} tone="out" />
            </div>
          </div>
        </div>

        {/* Rentabilidad */}
        <div className={`flex items-center justify-between gap-2 border px-3 py-2 ${profitPos ? "border-[#22C55E]/25 bg-[#22C55E]/5" : "border-[#EF4444]/25 bg-[#EF4444]/5"}`}>
          <div className="flex items-center gap-1.5 text-[0.6rem] uppercase tracking-widest text-neutral-400">
            <ProfitIcon className={`w-3 h-3 ${profitPos ? "text-[#22C55E]" : "text-[#EF4444]"}`} />
            <span>{t("admin.companyFunds.profitTotal")}</span>
          </div>
          <span className={`font-mono text-[0.85rem] tabular-nums ${profitPos ? "text-[#22C55E]" : "text-[#EF4444]"}`}>
            {profitPos ? "+" : ""}{fmt(profit)}
            <span className="text-[0.65rem] text-neutral-500 ml-2">
              {profitPos ? "+" : ""}{Number(f.profit_pct || 0).toFixed(2)}%
            </span>
          </span>
        </div>

        {/* Desglose por cliente del saldo por pagar */}
        <div className="border border-[#F59E0B]/25 bg-[#F59E0B]/[0.04] p-3" data-testid="fund-dash-clients">
          <div className="flex items-center justify-between gap-2 pb-2 border-b border-white/10">
            <div className="flex items-center gap-1.5 text-[0.6rem] uppercase tracking-widest text-[#F59E0B]">
              <AlertTriangle className="w-3 h-3" />
              <span>{t("admin.companyFunds.clientBreakdownTitle")}</span>
            </div>
            <span className="font-mono text-[0.8rem] text-[#F59E0B] tabular-nums" data-testid="fund-dash-clients-total">
              {fmt(clients?.total ?? f.client_balances)}
            </span>
          </div>
          <p className="text-[0.6rem] text-neutral-500 mt-1.5">
            {t("admin.companyFunds.clientBreakdownSub")}
          </p>
          {loadingClients && (
            <div className="text-xs text-neutral-500 py-4 text-center">
              {t("admin.common.loadingEllipsis")}
            </div>
          )}
          {!loadingClients && clients && clients.clients.length === 0 && (
            <div className="text-xs text-neutral-500 py-4 text-center" data-testid="fund-dash-clients-empty">
              {t("admin.companyFunds.clientBreakdownEmpty")}
            </div>
          )}
          {!loadingClients && clients && clients.clients.length > 0 && (
            <div className="mt-2 max-h-56 overflow-y-auto tx-body-scroll divide-y divide-white/5">
              {clients.clients.map((cl) => (
                <div key={cl.user_id}
                  className="flex items-center justify-between gap-3 py-1.5"
                  data-testid={`fund-dash-client-row-${cl.user_id}`}>
                  <div className="flex items-center gap-2 min-w-0">
                    <UserRound className={`w-3.5 h-3.5 shrink-0 ${cl.role === "vip" ? "text-[#A78BFA]" : "text-neutral-500"}`} />
                    <div className="min-w-0">
                      <div className="text-[0.75rem] text-neutral-200 truncate">{cl.name || cl.email}</div>
                      <div className="text-[0.6rem] text-neutral-500 font-mono truncate">{cl.email}</div>
                    </div>
                  </div>
                  <span className="font-mono text-[0.75rem] text-[#F59E0B] tabular-nums whitespace-nowrap">
                    {fmt(cl.amount)} {f.currency}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
