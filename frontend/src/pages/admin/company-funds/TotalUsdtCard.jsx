/**
 * iter152 — TotalUsdtCard
 *
 * Prominent treasury summary card at the top of "Fondo Empresa". Sums the
 * per-currency balances into a single USDT figure so the admin sees, at
 * a glance, how much the company is worth right now. Uses the same rate
 * lookup as the VIP threshold + user portfolio views for consistency.
 *
 * Backend: GET /admin/company-funds/total-usdt
 */
import { useEffect, useState } from "react";
import axios from "axios";
import { FlashNumber } from "@/components/FlashNumber";
import { useTranslation } from "react-i18next";
import { Wallet, TrendingUp, ArrowDownLeft, ArrowUpRight, AlertTriangle, RefreshCw } from "lucide-react";
import { API } from "@/App";

const fmt2 = (n) =>
  Number(n || 0).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

export default function TotalUsdtCard() {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    try {
      const r = await axios.get(`${API}/admin/company-funds/total-usdt`, {
        withCredentials: true,
      });
      setData(r.data);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => { load(); }, []);

  if (loading) {
    return (
      <div className="tactile-card p-5 animate-pulse" data-testid="total-usdt-card-skeleton">
        <div className="h-4 w-40 bg-white/5 mb-3" />
        <div className="h-10 w-64 bg-white/10" />
      </div>
    );
  }
  if (!data) return null;

  const missing = data.missing_rate_currencies || [];
  const profitTone = (data.total_profit_usdt || 0) >= 0 ? "text-[#22C55E]" : "text-[#F87171]";

  return (
    <div
      className="tactile-card p-5 relative overflow-hidden"
      data-testid="total-usdt-card"
    >
      {/* Ambient violet glow to differentiate this card from the per-currency ones */}
      <div className="pointer-events-none absolute -top-24 -right-16 w-64 h-64 bg-[#8B5CF6]/20 blur-3xl rounded-full" />
      <div className="relative">
        <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
          <div className="flex items-center gap-2">
            <Wallet className="w-4 h-4 text-[#8B5CF6]" />
            <span className="micro-label text-neutral-500">
              {t("admin.companyFunds.totalUsdt.eyebrow")}
            </span>
          </div>
          <button
            type="button"
            onClick={() => { setRefreshing(true); load(); }}
            data-testid="total-usdt-refresh"
            className="flex items-center gap-1 text-[0.65rem] uppercase tracking-widest text-neutral-500 hover:text-white transition-colors"
          >
            <RefreshCw className={`w-3 h-3 ${refreshing ? "animate-spin" : ""}`} />
            {t("admin.companyFunds.totalUsdt.refresh")}
          </button>
        </div>

        <div className="flex items-end justify-between flex-wrap gap-6">
          <div>
            <div className="text-xs text-neutral-400 mb-1">
              {t("admin.companyFunds.totalUsdt.availableLabel")}
            </div>
            <div className="flex items-baseline gap-2">
              <div
                className="font-mono text-4xl sm:text-5xl font-semibold text-white leading-none"
                data-testid="total-usdt-available"
              >
                <FlashNumber value={data.total_available_usdt} testid="total-usdt-flash">
                  {fmt2(data.total_available_usdt)}
                </FlashNumber>
              </div>
              <div className="micro-label text-[#8B5CF6] text-xs">USDT</div>
            </div>
            <div className="text-[0.7rem] text-neutral-500 mt-2 flex items-center gap-4 flex-wrap">
              <span>
                {t("admin.companyFunds.totalUsdt.grossLabel")}:
                <span className="text-neutral-300 font-mono ml-1" data-testid="total-usdt-gross">
                  {fmt2(data.total_balance_usdt)}
                </span>
              </span>
              <span>
                {t("admin.companyFunds.totalUsdt.custodyLabel")}:
                <span className="text-amber-400 font-mono ml-1" data-testid="total-usdt-custody">
                  {fmt2(data.total_liabilities_usdt)}
                </span>
              </span>
            </div>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 min-w-0">
            <MiniStat
              icon={ArrowDownLeft}
              iconClass="text-[#22C55E]"
              label={t("admin.companyFunds.totalUsdt.inflow")}
              value={fmt2(data.total_inflow_usdt)}
              testid="total-usdt-inflow"
            />
            <MiniStat
              icon={ArrowUpRight}
              iconClass="text-[#F87171]"
              label={t("admin.companyFunds.totalUsdt.outflow")}
              value={fmt2(data.total_outflow_usdt)}
              testid="total-usdt-outflow"
            />
            <MiniStat
              icon={TrendingUp}
              iconClass={profitTone}
              label={t("admin.companyFunds.totalUsdt.profit")}
              value={fmt2(data.total_profit_usdt)}
              valueClass={profitTone}
              testid="total-usdt-profit"
            />
          </div>
        </div>

        {missing.length > 0 && (
          <div
            className="mt-4 flex items-start gap-2 border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[0.7rem] text-amber-300"
            data-testid="total-usdt-missing"
          >
            <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <div>
              {t("admin.companyFunds.totalUsdt.missingRates", {
                list: missing.join(", "),
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function MiniStat({ icon: Icon, iconClass, label, value, valueClass, testid }) {
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-1.5 micro-label text-neutral-500">
        <Icon className={`w-3.5 h-3.5 ${iconClass}`} />
        {label}
      </div>
      <div
        className={`font-mono text-lg mt-0.5 truncate ${valueClass || "text-white"}`}
        data-testid={testid}
      >
        {value}
      </div>
    </div>
  );
}
