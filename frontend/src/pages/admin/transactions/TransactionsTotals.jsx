import { ArrowDown, ArrowUp } from "lucide-react";

export function TransactionsTotals({ totalsByCurrency }) {
  const rows = Object.entries(totalsByCurrency)
    .map(([code, v]) => ({ code, ...v, net: (v.in || 0) - (v.out || 0) }))
    .sort((a, b) => Math.abs(b.net) - Math.abs(a.net));

  if (rows.length === 0) return null;

  return (
    <div
      className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3"
      data-testid="transactions-totals"
    >
      {rows.slice(0, 6).map((row) => (
        <div key={row.code} className="tactile-card p-4">
          <div className="micro-label text-neutral-500 mb-1">{row.code}</div>
          <div className="space-y-1 text-sm">
            <div className="flex justify-between">
              <span className="text-neutral-400 flex items-center gap-1">
                <ArrowDown className="w-3 h-3 text-[#22C55E]" /> Entradas
              </span>
              <span className="font-mono text-[#22C55E]">+{row.in.toLocaleString()}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-neutral-400 flex items-center gap-1">
                <ArrowUp className="w-3 h-3 text-[#EF4444]" /> Salidas
              </span>
              <span className="font-mono text-[#EF4444]">-{row.out.toLocaleString()}</span>
            </div>
            <div className="flex justify-between border-t border-white/5 pt-1 mt-1">
              <span className="text-neutral-300 text-xs">Neto</span>
              <span
                className={`font-mono font-bold ${row.net >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"}`}
              >
                {row.net >= 0 ? "+" : ""}{row.net.toLocaleString()}
              </span>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
