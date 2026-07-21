import { HandCoins } from "lucide-react";
import { fmtDate, fmtNum } from "./userStatsMeta";

export default function CapitalDebtsSection({ capital }) {
  return (
    <div className="tactile-card p-5" data-testid="user-stats-capital-section">
      <h2 className="font-display text-xl mb-4 flex items-center gap-2">
        <HandCoins className="w-5 h-5 text-[#8B5CF6]" /> Solicitudes de capital activas
      </h2>
      {capital.active_requests.length === 0 ? (
        <div className="text-sm text-neutral-500">
          Este cliente no tiene deudas de capital operativo pendientes.
        </div>
      ) : (
        <>
          <div className="text-sm text-neutral-400 mb-4">
            Total pendiente:{" "}
            <span className="text-red-400 tabular-nums">
              {fmtNum(capital.total_debt_usdt, 2)} USDT
            </span>
          </div>
          <div className="space-y-3">
            {capital.active_requests.map((cr) => (
              <CapitalDebtRow key={cr.id} cr={cr} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function CapitalDebtRow({ cr }) {
  const paidPct = cr.debt_original
    ? Math.round(((cr.debt_original - cr.debt_remaining) / cr.debt_original) * 100)
    : 0;
  return (
    <div className="border border-white/10 p-4" data-testid={`user-stats-capital-${cr.id}`}>
      <div className="flex items-start justify-between flex-wrap gap-2">
        <div>
          <div className="font-mono text-sm">
            {fmtNum(cr.debt_remaining, 2)} / {fmtNum(cr.debt_original, 2)} {cr.currency_code}
          </div>
          <div className="text-xs text-neutral-500 mt-1">
            {cr.reason} · Desembolsado {fmtDate(cr.disbursed_at)}
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs text-neutral-500">Descuento por orden</div>
          <div className="font-mono text-[#8B5CF6]">{cr.discount_pct}%</div>
        </div>
      </div>
      <div className="mt-3 h-1.5 bg-white/5">
        <div className="h-full bg-emerald-500 transition-all" style={{ width: `${paidPct}%` }} />
      </div>
      <div className="text-[0.65rem] text-neutral-500 mt-1 uppercase tracking-widest">
        {paidPct}% devuelto
      </div>
    </div>
  );
}
