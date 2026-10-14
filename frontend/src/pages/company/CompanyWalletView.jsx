import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Wallet, ArrowDownToLine, ArrowUpFromLine, ArrowRightLeft } from "lucide-react";
import CurrencyIcon from "@/components/CurrencyIcon";
import { FlashNumber } from "@/components/FlashNumber";
import BalanceConverterCard from "@/components/BalanceConverterCard";
import VerificationGateBanner from "@/components/VerificationGateBanner";
import { MethodPicker } from "@/pages/dashboard/vip/MethodPicker";
import { DepositForm } from "@/pages/dashboard/vip/DepositForm";
import { VipWithdrawalForm } from "@/pages/dashboard/vip/VipWithdrawalForm";
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
  const [balances, setBalances] = useState({ balances: [], total_usdt: 0 });
  const [action, setAction] = useState(null);
  const [method, setMethod] = useState(null);

  const load = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/vip/balances`, { withCredentials: true });
      setBalances(r.data);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { load(); }, [load]);
  useLiveEvent("balance_updated", load);
  useLiveEvent("order_status_changed", load);
  useLiveEvent("withdrawal_status_changed", load);

  const toggleAction = (key) => {
    setAction((cur) => (cur === key ? null : key));
    setMethod(null);
  };

  const handleSubmitted = () => {
    setAction(null); setMethod(null);
    load(); refresh?.();
  };

  return (
    <div className="space-y-6" data-testid="company-wallet-view">
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

      <div className="relative overflow-hidden bg-gradient-to-b from-[#181628] to-[#1A1730] border border-white/[0.08] rounded-2xl p-8 shadow-2xl shadow-black/50">
        <div className="absolute -top-24 -right-24 w-64 h-64 bg-violet-500/20 blur-[100px] rounded-full pointer-events-none" />
        <Wallet className="w-8 h-8 text-violet-400 mb-3 relative" />
        <div className="text-xs font-semibold tracking-[0.22em] text-violet-300/70 uppercase mb-3 block relative">Saldo total</div>
        <div className="text-5xl sm:text-6xl font-mono tabular-nums tracking-tight font-semibold text-white relative" data-testid="company-wallet-total">
          <FlashNumber value={balances.total_usdt || 0} testid="company-wallet-total-flash">
            {Number(balances.total_usdt || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
          </FlashNumber>{" "}
          <span className="text-2xl text-neutral-400">USDT</span>
        </div>
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

      <section>
        <div className="micro-label text-neutral-500 mb-3">Saldo por moneda</div>
        {balances.balances.length === 0 ? (
          <div className="text-sm text-neutral-500 py-10 text-center border border-white/5 bg-black/20" data-testid="company-wallet-empty">
            Aún no tienes saldo. Las ventas del marketplace y tus depósitos aparecerán aquí.
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {balances.balances.map((b) => (
              <div key={b.currency} className="tactile-card p-5" data-testid={`company-wallet-${b.currency}`}>
                <div className="flex items-center gap-3 mb-2">
                  <CurrencyIcon code={b.currency} size="lg" />
                  <div className="micro-label text-neutral-500">{b.currency}</div>
                </div>
                <div className="font-mono text-2xl text-white mt-1">
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
        )}
      </section>
    </div>
  );
}
