import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import {
  Wallet, FileDown, History, ArrowDownToLine, ArrowUpFromLine, ArrowRightLeft, Lock,
} from "lucide-react";

import { VipBalancesGrid } from "./vip/VipBalancesGrid";
import { VipWithdrawalForm } from "./vip/VipWithdrawalForm";
import { VipLedgerDialog } from "./vip/VipLedgerDialog";
import { DepositForm } from "./vip/DepositForm";
import { AccountHistoryDialog } from "./vip/AccountHistoryDialog";
import { MethodPicker } from "./vip/MethodPicker";
import { FlashNumber } from "@/components/FlashNumber";
import BalanceConverterCard from "@/components/BalanceConverterCard";
import VerificationGateBanner from "@/components/VerificationGateBanner";
import QuickDateRange from "@/components/QuickDateRange";
import { useLiveEvent } from "@/hooks/useLiveStream";

/**
 * iter115 — "Depósitos y Retiros" redesigned as an exchange-style hub:
 * three big action buttons (Depositar / Retirar / Convertir) that toggle
 * their panel, plus a small History button opening a dialog with separate
 * tabs for deposits, withdrawals and conversions.
 */
export default function VipView() {
  const { refresh } = useAuth();
  const { t } = useTranslation();
  const [withdrawals, setWithdrawals] = useState([]);
  const [balances, setBalances] = useState({ balances: [], total_usdt: 0 });
  const [ledger, setLedger] = useState({ by_currency: {}, total_orders: 0 });
  const [ledgerOpen, setLedgerOpen] = useState(false);
  const [ledgerCurrency, setLedgerCurrency] = useState("");
  const [closingSince, setClosingSince] = useState("");
  const [closingUntil, setClosingUntil] = useState("");
  const [downloading, setDownloading] = useState(false);
  const [action, setAction] = useState(null); // null | deposit | withdraw | convert
  const [method, setMethod] = useState(null); // null | crypto | transfer | cash
  const [historyOpen, setHistoryOpen] = useState(false);

  const downloadClosing = async () => {
    setDownloading(true);
    try {
      const res = await axios.get(`${API}/vip/daily-closing`, {
        params: {
          since: closingSince || undefined,
          until: closingUntil || undefined,
        },
        responseType: "blob",
        withCredentials: true,
      });
      const url = window.URL.createObjectURL(new Blob([res.data], { type: "application/pdf" }));
      const a = document.createElement("a");
      a.href = url;
      const slug = closingSince && closingUntil
        ? `${closingSince}_${closingUntil}`
        : (closingSince || closingUntil || "historico");
      a.download = `cierre_${slug}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      toast.success(t("vipView.closingDownloaded"));
    } catch (_) {
      toast.error(t("vipView.closingError"));
    } finally {
      setDownloading(false);
    }
  };

  const load = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/vip/withdrawals/mine`, { withCredentials: true });
      setWithdrawals(r.data);
    } catch (_) { setWithdrawals([]); }
    try {
      const b = await axios.get(`${API}/vip/balances`, { withCredentials: true });
      setBalances(b.data);
    } catch (_) { setBalances({ balances: [], total_usdt: 0 }); }
    try {
      const l = await axios.get(`${API}/vip/balance-ledger`, { withCredentials: true });
      setLedger(l.data);
    } catch (_) { setLedger({ by_currency: {}, total_orders: 0 }); }
  }, []);
  useEffect(() => { load(); }, [load]);

  useLiveEvent("balance_updated", load);
  useLiveEvent("withdrawal_status_changed", load);
  useLiveEvent("order_status_changed", load);

  const handleDrillDown = (currency) => {
    setLedgerCurrency(currency);
    setLedgerOpen(true);
  };

  const handleSubmitted = async () => {
    await load();
    await refresh();
  };

  const toggleAction = (key) => {
    setMethod(null);
    setAction((cur) => (cur === key ? null : key));
  };

  const ACTIONS = [
    { key: "deposit",  icon: ArrowDownToLine, label: t("vipView.actions.deposit"),  accent: "text-emerald-400", ring: "border-emerald-500/60 bg-emerald-500/10" },
    { key: "withdraw", icon: ArrowUpFromLine, label: t("vipView.actions.withdraw"), accent: "text-[#A78BFA]",   ring: "border-[#8B5CF6]/70 bg-[#8B5CF6]/10" },
    { key: "convert",  icon: ArrowRightLeft,  label: t("vipView.actions.convert"),  accent: "text-sky-400",     ring: "border-sky-500/60 bg-sky-500/10" },
  ];

  return (
    <div className="space-y-8" data-testid="vip-view">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="micro-label text-[#8B5CF6] mb-2">{t("vipView.eyebrow")}</div>
          <h1 className="font-display text-3xl">{t("vipView.title")}</h1>
        </div>
        <button
          type="button"
          onClick={() => setHistoryOpen(true)}
          data-testid="account-history-btn"
          className="flex items-center gap-2 border border-white/15 hover:border-[#8B5CF6]/60 hover:bg-white/5 text-neutral-400 hover:text-white px-3 h-9 text-[0.65rem] uppercase tracking-widest font-mono transition-colors shrink-0"
          title={t("vipView.actions.history")}
        >
          <History className="w-4 h-4" />
          <span className="hidden sm:inline">{t("vipView.actions.history")}</span>
        </button>
      </div>

      <div className="relative overflow-hidden bg-gradient-to-b from-[#181628] to-[#1A1730] border border-white/[0.08] rounded-2xl p-8 shadow-2xl shadow-black/50 hover:border-violet-500/20 transition-colors duration-500">
        <div className="absolute -top-24 -right-24 w-64 h-64 bg-violet-500/20 blur-[100px] rounded-full pointer-events-none" />
        <Wallet className="w-8 h-8 text-violet-400 mb-3 relative" />
        <div className="text-xs font-semibold tracking-[0.22em] text-violet-300/70 uppercase mb-3 block relative">
          {t("vipView.totalValue")}
        </div>
        <div className="text-5xl sm:text-6xl font-mono tabular-nums tracking-tight font-semibold text-white drop-shadow-[0_2px_10px_rgba(0,0,0,0.5)] relative">
          <FlashNumber value={balances.total_usdt} testid="vip-total-usdt-flash">
            {balances.total_usdt?.toLocaleString(undefined, { maximumFractionDigits: 2 }) || "0.00"}
          </FlashNumber>{" "}
          <span className="text-2xl text-neutral-400">USDT</span>
        </div>
        <div className="text-sm text-neutral-500 mt-2 relative">
          {t("vipView.consolidatedNote")}
        </div>
        {Number(balances.frozen_total_usdt) > 0 && (
          <div className="flex items-center gap-2 text-sm text-amber-400/90 mt-3 relative" data-testid="frozen-total-note">
            <Lock className="w-4 h-4" />
            {t("vipView.frozenNote", {
              amount: Number(balances.frozen_total_usdt).toLocaleString(undefined, { maximumFractionDigits: 2 }),
            })}
          </div>
        )}
      </div>

      {/* iter115 — exchange-style action buttons */}
      <div className="grid grid-cols-3 gap-3" data-testid="vip-action-buttons">
        {ACTIONS.map(({ key, icon: Icon, label, accent, ring }) => {
          const active = action === key;
          return (
            <button
              key={key}
              type="button"
              onClick={() => toggleAction(key)}
              data-testid={`action-${key}-btn`}
              aria-pressed={active}
              className={`tactile-card p-4 sm:p-5 flex flex-col items-center gap-2.5 transition-colors ${
                active ? ring : "hover:border-white/25"
              }`}
            >
              <span className={`w-11 h-11 rounded-full border border-white/10 bg-black/40 flex items-center justify-center ${accent}`}>
                <Icon className="w-5 h-5" />
              </span>
              <span className={`text-xs sm:text-sm font-semibold uppercase tracking-widest ${active ? "text-white" : "text-neutral-300"}`}>
                {label}
              </span>
            </button>
          );
        })}
      </div>

      {action === "deposit" && (
        <div data-testid="panel-deposit" className="animate-in fade-in slide-in-from-top-2 duration-300">
          {!method ? (
            <MethodPicker mode="deposit" onSelect={setMethod} />
          ) : (
            <DepositForm
              method={method}
              onBack={() => setMethod(null)}
              onSubmitted={handleSubmitted}
              showHistory={false}
            />
          )}
        </div>
      )}
      {action === "withdraw" && (
        <div data-testid="panel-withdraw" className="animate-in fade-in slide-in-from-top-2 duration-300">
          <VerificationGateBanner blocking action="withdraw">
            {!method ? (
              <MethodPicker mode="withdraw" onSelect={setMethod} />
            ) : (
              <VipWithdrawalForm
                balances={balances}
                method={method}
                onBack={() => setMethod(null)}
                onSubmitted={handleSubmitted}
              />
            )}
          </VerificationGateBanner>
        </div>
      )}
      {action === "convert" && (
        <div data-testid="panel-convert" className="animate-in fade-in slide-in-from-top-2 duration-300">
          <BalanceConverterCard onConverted={load} />
        </div>
      )}

      <VipBalancesGrid
        balances={balances}
        ledger={ledger}
        onDrillDown={handleDrillDown}
      />

      <div className="tactile-card p-6">
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div>
              <h2 className="font-display text-xl flex items-center gap-2">
                <FileDown className="w-5 h-5 text-[#8B5CF6]" /> {t("vipView.dailyClosing")}
              </h2>
              <p className="text-sm text-neutral-400 mt-1">
                {t("vipView.dailyClosingSub")}
              </p>
            </div>
            <div className="flex items-end gap-3 flex-wrap">
              <div className="flex flex-col">
                <label className="micro-label text-neutral-500 mb-1">{t("myTransactions.filters.since")}</label>
                <Input
                  data-testid="closing-since-input"
                  type="date"
                  value={closingSince}
                  onChange={(e) => setClosingSince(e.target.value)}
                  className="rounded-none bg-[#0a0a0a] border-white/10 h-11 font-mono w-40"
                />
              </div>
              <div className="flex flex-col">
                <label className="micro-label text-neutral-500 mb-1">{t("myTransactions.filters.until")}</label>
                <Input
                  data-testid="closing-until-input"
                  type="date"
                  value={closingUntil}
                  onChange={(e) => setClosingUntil(e.target.value)}
                  className="rounded-none bg-[#0a0a0a] border-white/10 h-11 font-mono w-40"
                />
              </div>
              <Button
                data-testid="download-closing-btn"
                onClick={downloadClosing}
                disabled={downloading}
                className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-semibold rounded-none h-11"
              >
                <FileDown className="w-4 h-4 mr-2" />
                {downloading ? t("vipView.generating") : t("vipView.downloadPdf")}
              </Button>
            </div>
          </div>
          <QuickDateRange
            since={closingSince}
            until={closingUntil}
            onRangeChange={({ since: s, until: u }) => { setClosingSince(s); setClosingUntil(u); }}
            testIdPrefix="closing-quick"
          />
        </div>
      </div>

      <AccountHistoryDialog
        open={historyOpen}
        onOpenChange={setHistoryOpen}
        withdrawals={withdrawals}
        onChanged={handleSubmitted}
      />

      <VipLedgerDialog
        open={ledgerOpen}
        onOpenChange={setLedgerOpen}
        currency={ledgerCurrency}
        bucket={ledger.by_currency?.[ledgerCurrency]}
      />
    </div>
  );
}
