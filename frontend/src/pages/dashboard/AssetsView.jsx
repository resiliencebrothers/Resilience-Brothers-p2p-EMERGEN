import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { Wallet, ArrowRightLeft, Calculator } from "lucide-react";
import CurrencyIcon from "@/components/CurrencyIcon";
import BalanceConverterCard from "@/components/BalanceConverterCard";
import ProfitCalculatorSection from "./ProfitCalculatorSection";
import { useAuth } from "@/context/AuthContext";
import { useLiveEvent } from "@/hooks/useLiveStream";

/**
 * iter113 — "Activos" section (all clients: VIP + normal).
 * Per-currency account balances with USDT equivalents. Batch credits,
 * confirmed deposits and accumulated orders all land here.
 * Jun 2026 — hosts the "Convertir Saldos" converter (moved from Overview).
 */
export default function AssetsView() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const isVip = user?.role === "vip";
  const [data, setData] = useState({ balances: [], total_usdt: 0 });
  const [loading, setLoading] = useState(true);
  const [showConverter, setShowConverter] = useState(false);
  const [showCalculator, setShowCalculator] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/vip/balances`, { withCredentials: true });
      setData(r.data);
    } catch { setData({ balances: [], total_usdt: 0 }); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);
  useLiveEvent("balance_updated", load);
  useLiveEvent("order_status_changed", load);
  useLiveEvent("withdrawal_status_changed", load);

  return (
    <div className="space-y-8" data-testid="assets-view">
      <div>
        <div className="micro-label text-[#8B5CF6] mb-2">{t("assetsView.eyebrow")}</div>
        <h1 className="font-display text-3xl">{t("assetsView.title")}</h1>
        <p className="text-sm text-neutral-400 mt-2 max-w-xl">{t("assetsView.subtitle")}</p>
      </div>

      <div className="relative overflow-hidden bg-gradient-to-b from-[#181628] to-[#1A1730] border border-white/[0.08] rounded-2xl p-8 shadow-2xl shadow-black/50">
        <div className="absolute -top-24 -right-24 w-64 h-64 bg-violet-500/20 blur-[100px] rounded-full pointer-events-none" />
        <Wallet className="w-8 h-8 text-violet-400 mb-3 relative" />
        <div className="text-xs font-semibold tracking-[0.22em] text-violet-300/70 uppercase mb-3 block relative">
          {t("assetsView.total")}
        </div>
        <div
          className="text-5xl sm:text-6xl font-mono tabular-nums tracking-tight font-semibold text-white relative"
          data-testid="assets-total-usdt"
        >
          {Number(data.total_usdt || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}{" "}
          <span className="text-2xl text-neutral-400">USDT</span>
        </div>
        <div className="text-sm text-neutral-500 mt-2 relative">{t("assetsView.approxNote")}</div>
        <button
          type="button"
          data-testid="assets-convert-btn"
          onClick={() => setShowConverter((v) => !v)}
          className="relative mt-6 inline-flex items-center gap-2 bg-[#8B5CF6] hover:bg-[#7C3AED] text-white px-5 py-2.5 font-mono text-xs uppercase tracking-wider transition-colors"
        >
          <ArrowRightLeft className="w-4 h-4" />
          {showConverter ? t("assetsView.hideConverter") : t("assetsView.convertBtn")}
        </button>
        {isVip && (
          <button
            type="button"
            data-testid="assets-calc-btn"
            onClick={() => setShowCalculator((v) => !v)}
            className="relative mt-6 ml-3 inline-flex items-center gap-2 border border-[#8B5CF6]/50 text-[#A78BFA] hover:bg-[#8B5CF6]/10 px-5 py-2.5 font-mono text-xs uppercase tracking-wider transition-colors"
          >
            <Calculator className="w-4 h-4" />
            {showCalculator ? t("assetsView.hideCalc") : t("assetsView.calcBtn")}
          </button>
        )}
      </div>

      {isVip && showCalculator && <ProfitCalculatorSection />}

      {showConverter && (
        <div data-testid="assets-converter-wrap">
          <BalanceConverterCard onConverted={load} />
        </div>
      )}

      <section>
        <div className="micro-label text-neutral-500 mb-3">{t("assetsView.perCurrency")}</div>
        {loading && (
          <div className="text-sm text-neutral-500 py-8 text-center">{t("admin.common.loadingEllipsis")}</div>
        )}
        {!loading && data.balances.length === 0 && (
          <div className="text-sm text-neutral-500 py-10 text-center border border-white/5 bg-black/20" data-testid="assets-empty">
            {t("assetsView.empty")}
          </div>
        )}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {data.balances.map((b) => (
            <div key={b.currency} className="tactile-card p-5" data-testid={`asset-${b.currency}`}>
              <div className="flex items-center gap-3 mb-2">
                <CurrencyIcon code={b.currency} size="lg" />
                <div className="micro-label text-neutral-500">{b.currency}</div>
              </div>
              <div className="font-mono text-2xl text-white mt-1" data-testid={`asset-amount-${b.currency}`}>
                {Number(b.amount).toLocaleString(undefined, { maximumFractionDigits: 4 })}
              </div>
              {b.usdt_equivalent != null && (
                <div className="text-[0.7rem] text-neutral-500 font-mono mt-1">
                  ≈ {Number(b.usdt_equivalent).toLocaleString(undefined, { maximumFractionDigits: 2 })} USDT
                </div>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
