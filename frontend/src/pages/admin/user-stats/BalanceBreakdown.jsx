import { Wallet } from "lucide-react";
import { fmtNum } from "./userStatsMeta";

export default function BalanceBreakdown({ balances }) {
  const entries = Object.entries(balances || {});
  return (
    <div className="tactile-card p-5">
      <h2 className="font-display text-xl mb-4 flex items-center gap-2">
        <Wallet className="w-5 h-5 text-[#8B5CF6]" /> Saldo por moneda
      </h2>
      {entries.length === 0 ? (
        <div className="text-sm text-neutral-500">Sin saldo acumulado en ninguna moneda.</div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="user-stats-balances-grid">
          {entries.map(([code, amount]) => (
            <div key={code} className="border border-white/10 p-3" data-testid={`user-stats-balance-${code}`}>
              <div className="micro-label text-neutral-500">{code}</div>
              <div className="font-display text-2xl tabular-nums mt-1">{fmtNum(amount, 4)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
