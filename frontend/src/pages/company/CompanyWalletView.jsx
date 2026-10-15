import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { Wallet, ArrowDownToLine, ArrowUpFromLine, ArrowRightLeft, History, Lock, FileDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import QuickDateRange from "@/components/QuickDateRange";
import { FlashNumber } from "@/components/FlashNumber";
import BalanceConverterCard from "@/components/BalanceConverterCard";
import VerificationGateBanner from "@/components/VerificationGateBanner";
import { MethodPicker } from "@/pages/dashboard/vip/MethodPicker";
import { DepositForm } from "@/pages/dashboard/vip/DepositForm";
import { VipWithdrawalForm } from "@/pages/dashboard/vip/VipWithdrawalForm";
import { VipBalancesGrid } from "@/pages/dashboard/vip/VipBalancesGrid";
import { AccountHistoryDialog } from "@/pages/dashboard/vip/AccountHistoryDialog";
import { VipLedgerDialog } from "@/pages/dashboard/vip/VipLedgerDialog";
import { useLiveEvent } from "@/hooks/useLiveStream";

// Sub-saldo de la Empresa — misma infraestructura que VIP y clientes normales
// (/vip/balances, /deposits, /vip/withdraw). Las ventas del marketplace se
// acreditan aquí netas de comisión; los retiros SON la liquidación con Resilience.
const ACTIONS = [
  { key: "deposit", icon: ArrowDownToLine, label: "Depositar", accent: "text-emerald-400", ring: "border-emerald-500/50" },
  { key: "withdraw", icon: ArrowUpFromLine, label: "Retirar / Liquidar", accent: "text-amber-400", ring: "border-amber-500/50" },
  { key: "convert", icon: ArrowRightLeft, label: "Convertir", accent: "text-[#8B5CF6]", ring: "border-[#8B5CF6]/50" },
];

export default function CompanyWalletView() {
  const { refresh } = useAuth();
  const [balances, setBalances] = useState({ balances: [], total_usdt: 0, frozen_total_usdt: 0 });
  const [withdrawals, setWithdrawals] = useState([]);
  const [ledger, setLedger] = useState({ by_currency: {}, total_orders: 0 });
  const [action, setAction] = useState(null);
  const [method, setMethod] = useState(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [ledgerOpen, setLedgerOpen] = useState(false);
  const [ledgerCurrency, setLedgerCurrency] = useState("");
  const [closingSince, setClosingSince] = useState("");
  const [closingUntil, setClosingUntil] = useState("");
  const [downloading, setDownloading] = useState(false);

  const downloadClosing = async () => {
    setDownloading(true);
    try {
      const res = await axios.get(`${API}/vip/daily-closing`, {
        params: { since: closingSince || undefined, until: closingUntil || undefined },
        responseType: "blob", withCredentials: true,
      });
      const url = window.URL.createObjectURL(new Blob([res.data], { type: "application/pdf" }));
      const a = document.createElement("a");
      a.href = url;
      const slug = closingSince && closingUntil
        ? `${closingSince}_${closingUntil}`
        : (closingSince || closingUntil || "historico");
      a.download = `cierre_empresa_${slug}.pdf`;
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
      toast.success("Cierre contable descargado");
    } catch {
      toast.error("No se pudo generar el cierre contable");
    } finally { setDownloading(false); }
  };

  const load = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/vip/balances`, { withCredentials: true });
      setBalances(r.data);
    } catch { /* ignore */ }
    try {
      const w = await axios.get(`${API}/vip/withdrawals/mine`, { withCredentials: true });
      setWithdrawals(w.data);
    } catch { setWithdrawals([]); }
    try {
      const l = await axios.get(`${API}/vip/balance-ledger`, { withCredentials: true });
      setLedger(l.data);
    } catch { setLedger({ by_currency: {}, total_orders: 0 }); }
  }, []);

  useEffect(() => { load(); }, [load]);
  useLiveEvent("balance_updated", load);
  useLiveEvent("order_status_changed", load);
  useLiveEvent("withdrawal_status_changed", load);

  const toggleAction = (key) => {
    setAction((cur) => (cur === key ? null : key));
    setMethod(null);
  };

  const handleDrillDown = (currency) => {
    setLedgerCurrency(currency);
    setLedgerOpen(true);
  };

  const handleSubmitted = () => {
    setAction(null); setMethod(null);
    load(); refresh?.();
  };

  return (
    <div className="space-y-6" data-testid="company-wallet-view">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="micro-label text-[#8B5CF6] mb-2">Empresa</div>
          <h2 className="font-display text-2xl flex items-center gap-3">
            <Wallet className="w-6 h-6 text-[#8B5CF6]" /> Saldo y liquidación
          </h2>
          <p className="text-sm text-neutral-500 mt-1 max-w-2xl">
            Tu sub-saldo. Las ventas del marketplace se acreditan aquí netas de la
            comisión de Resilience. Deposita, convierte y retira (la retirada es la
            liquidación con Resilience).
          </p>
        </div>
        <button type="button" onClick={() => setHistoryOpen(true)}
          data-testid="company-wallet-history-btn"
          className="flex items-center gap-2 border border-white/15 hover:border-[#8B5CF6]/60 hover:bg-white/5 text-neutral-400 hover:text-white px-3 h-9 text-[0.65rem] uppercase tracking-widest font-mono transition-colors shrink-0"
          title="Historial de depósitos y retiros">
          <History className="w-4 h-4" />
          <span className="hidden sm:inline">Historial</span>
        </button>
      </div>

      <div className="relative overflow-hidden bg-gradient-to-b from-[#181628] to-[#1A1730] border border-white/[0.08] rounded-2xl p-8 shadow-2xl shadow-black/50">
        <div className="absolute -top-24 -right-24 w-64 h-64 bg-violet-500/20 blur-[100px] rounded-full pointer-events-none" />
        <Wallet className="w-8 h-8 text-violet-400 mb-3 relative" />
        <div className="text-xs font-semibold tracking-[0.22em] text-violet-300/70 uppercase mb-3 block relative">Saldo disponible</div>
        <div className="text-5xl sm:text-6xl font-mono tabular-nums tracking-tight font-semibold text-white relative" data-testid="company-wallet-total">
          <FlashNumber value={balances.total_usdt || 0} testid="company-wallet-total-flash">
            {Number(balances.total_usdt || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
          </FlashNumber>{" "}
          <span className="text-2xl text-neutral-400">USDT</span>
        </div>
        {Number(balances.frozen_total_usdt) > 0 && (
          <div className="flex items-center gap-2 text-sm text-amber-400/90 mt-3 relative" data-testid="company-wallet-frozen-total">
            <Lock className="w-4 h-4" />
            Retenido en retiros pendientes: ≈ {Number(balances.frozen_total_usdt).toLocaleString(undefined, { maximumFractionDigits: 2 })} USDT
          </div>
        )}
      </div>

      <div className="grid grid-cols-3 gap-3" data-testid="company-wallet-actions">
        {ACTIONS.map(({ key, icon: Icon, label, accent, ring }) => {
          const active = action === key;
          return (
            <button key={key} type="button" onClick={() => toggleAction(key)}
              data-testid={`company-wallet-action-${key}`} aria-pressed={active}
              className={`tactile-card p-4 sm:p-5 flex flex-col items-center gap-2.5 transition-colors ${active ? ring : "hover:border-white/25"}`}>
              <span className={`w-11 h-11 rounded-full border border-white/10 bg-black/40 flex items-center justify-center ${accent}`}>
                <Icon className="w-5 h-5" />
              </span>
              <span className={`text-xs sm:text-sm font-semibold uppercase tracking-widest ${active ? "text-white" : "text-neutral-300"}`}>{label}</span>
            </button>
          );
        })}
      </div>

      {action === "deposit" && (
        <div data-testid="company-wallet-deposit">
          {!method
            ? <MethodPicker mode="deposit" onSelect={setMethod} />
            : <DepositForm method={method} onBack={() => setMethod(null)} onSubmitted={handleSubmitted} showHistory={false} />}
        </div>
      )}
      {action === "withdraw" && (
        <div data-testid="company-wallet-withdraw">
          <VerificationGateBanner blocking action="withdraw">
            {!method
              ? <MethodPicker mode="withdraw" onSelect={setMethod} />
              : <VipWithdrawalForm balances={balances} method={method} onBack={() => setMethod(null)} onSubmitted={handleSubmitted} />}
          </VerificationGateBanner>
        </div>
      )}
      {action === "convert" && (
        <div data-testid="company-wallet-convert"><BalanceConverterCard onConverted={load} /></div>
      )}

      <section data-testid="company-wallet-balances">
        <div className="micro-label text-neutral-500 mb-3">Saldo por moneda</div>
        <VipBalancesGrid balances={balances} ledger={ledger} onDrillDown={handleDrillDown} />
        <p className="text-xs text-neutral-500 mt-3">
          El saldo mostrado es el <strong>disponible</strong>. Lo retenido por
          retiros pendientes aparece marcado en cada moneda y vuelve a estar
          disponible si el retiro se rechaza o cancela.
        </p>
      </section>

      <section className="tactile-card p-6" data-testid="company-wallet-closing">
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div>
              <h2 className="font-display text-xl flex items-center gap-2">
                <FileDown className="w-5 h-5 text-[#8B5CF6]" /> Cierre contable
              </h2>
              <p className="text-sm text-neutral-400 mt-1 max-w-xl">
                Descarga un PDF con tus movimientos (depósitos, retiros, ventas y
                conversiones) y el saldo por rango de fechas. Sin fechas: histórico completo.
              </p>
            </div>
            <div className="flex items-end gap-3 flex-wrap">
              <div className="flex flex-col">
                <label className="micro-label text-neutral-500 mb-1">Desde</label>
                <Input data-testid="company-closing-since-input" type="date"
                  value={closingSince} onChange={(e) => setClosingSince(e.target.value)}
                  className="rounded-none bg-[#0a0a0a] border-white/10 h-11 font-mono w-40" />
              </div>
              <div className="flex flex-col">
                <label className="micro-label text-neutral-500 mb-1">Hasta</label>
                <Input data-testid="company-closing-until-input" type="date"
                  value={closingUntil} onChange={(e) => setClosingUntil(e.target.value)}
                  className="rounded-none bg-[#0a0a0a] border-white/10 h-11 font-mono w-40" />
              </div>
              <Button data-testid="company-closing-download-btn" onClick={downloadClosing}
                disabled={downloading}
                className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-semibold rounded-none h-11">
                <FileDown className="w-4 h-4 mr-2" />
                {downloading ? "Generando…" : "Descargar PDF"}
              </Button>
            </div>
          </div>
          <QuickDateRange since={closingSince} until={closingUntil}
            onRangeChange={({ since: s, until: u }) => { setClosingSince(s); setClosingUntil(u); }}
            testIdPrefix="company-closing-quick" />
        </div>
      </section>

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
