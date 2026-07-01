import { ArrowDownCircle, ArrowUpCircle } from "lucide-react";

const METHOD_LABELS = {
  transfer: "Transferencia",
  cash: "Efectivo",
  crypto: "Cripto",
};

function fmt(dateStr) {
  if (!dateStr) return "—";
  try {
    return new Date(dateStr).toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return dateStr;
  }
}

export default function AdjustmentsTable({ items }) {
  if (!items || items.length === 0) {
    return (
      <div
        data-testid="adjustments-empty"
        className="tactile-card p-6 text-center text-neutral-500 text-sm"
      >
        Sin ajustes manuales registrados. Usa el botón &quot;Ajuste manual&quot; para
        registrar aportes propios de la empresa o salidas de capital.
      </div>
    );
  }
  return (
    <div className="tactile-card overflow-hidden" data-testid="adjustments-table">
      <table className="w-full text-sm">
        <thead className="bg-[#0a0a0a] border-b border-white/10">
          <tr className="text-left">
            <th className="px-4 py-3 micro-label text-neutral-500">Fecha</th>
            <th className="px-4 py-3 micro-label text-neutral-500">Tipo</th>
            <th className="px-4 py-3 micro-label text-neutral-500">Moneda</th>
            <th className="px-4 py-3 micro-label text-neutral-500">Monto</th>
            <th className="px-4 py-3 micro-label text-neutral-500">Método</th>
            <th className="px-4 py-3 micro-label text-neutral-500">Fuente</th>
            <th className="px-4 py-3 micro-label text-neutral-500">Autorizado por</th>
            <th className="px-4 py-3 micro-label text-neutral-500">Nota</th>
          </tr>
        </thead>
        <tbody>
          {items.map((a) => {
            const isIn = a.adjustment_type === "inflow";
            return (
              <tr
                key={a.id}
                className="border-b border-white/5"
                data-testid={`adjustment-row-${a.id}`}
              >
                <td className="px-4 py-3 text-xs text-neutral-400 whitespace-nowrap">
                  {fmt(a.created_at)}
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`inline-flex items-center gap-1 text-xs uppercase border px-2 py-1 ${
                      isIn
                        ? "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30"
                        : "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30"
                    }`}
                  >
                    {isIn ? (
                      <ArrowDownCircle className="w-3 h-3" />
                    ) : (
                      <ArrowUpCircle className="w-3 h-3" />
                    )}
                    {isIn ? "Entrada" : "Salida"}
                  </span>
                </td>
                <td className="px-4 py-3 font-mono">{a.currency}</td>
                <td
                  className={`px-4 py-3 font-mono ${
                    isIn ? "text-[#22C55E]" : "text-[#EF4444]"
                  }`}
                >
                  {isIn ? "+" : "−"}
                  {Number(a.amount).toLocaleString(undefined, {
                    maximumFractionDigits: 2,
                  })}
                </td>
                <td className="px-4 py-3 text-xs">
                  {METHOD_LABELS[a.method] || a.method}
                </td>
                <td className="px-4 py-3 text-xs max-w-[220px]">
                  <div className="truncate" title={a.source_name}>
                    {a.source_name}
                  </div>
                  {a.source_account && (
                    <div
                      className="truncate text-neutral-500 font-mono text-[0.65rem]"
                      title={a.source_account}
                    >
                      {a.source_account}
                    </div>
                  )}
                </td>
                <td className="px-4 py-3 text-xs">{a.actor_name || a.actor_email}</td>
                <td className="px-4 py-3 text-xs text-neutral-400 max-w-[220px] truncate">
                  {a.note || "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
