import { ArrowDown, ArrowUp } from "lucide-react";

export function TransactionsTable({ items, loading, onRowClick }) {
  return (
    <div className="tactile-card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="border-b border-white/10 bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-3 py-3 micro-label text-neutral-500">Fecha</th>
              <th className="px-3 py-3 micro-label text-neutral-500">Tipo</th>
              <th className="px-3 py-3 micro-label text-neutral-500">Moneda</th>
              <th className="px-3 py-3 micro-label text-neutral-500 text-right">Monto</th>
              <th className="px-3 py-3 micro-label text-neutral-500">Titular de cuenta</th>
              <th className="px-3 py-3 micro-label text-neutral-500">Cliente</th>
              <th className="px-3 py-3 micro-label text-neutral-500">Método</th>
              <th className="px-3 py-3 micro-label text-neutral-500">Estado</th>
              <th className="px-3 py-3 micro-label text-neutral-500">Ref</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan="9" className="text-center text-neutral-500 py-8">
                  Cargando...
                </td>
              </tr>
            )}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan="9" className="text-center text-neutral-500 py-8">
                  Sin transacciones que mostrar
                </td>
              </tr>
            )}
            {items.map((it) => (
              <tr
                key={`${it.ref_type}-${it.ref_id}`}
                data-testid={`tx-row-${it.ref_id}`}
                onClick={() => onRowClick(it)}
                className="border-b border-white/5 hover:bg-[#8B5CF6]/5 cursor-pointer transition-colors"
              >
                <td className="px-3 py-2 font-mono text-xs text-neutral-400">
                  {new Date(it.created_at).toLocaleString()}
                </td>
                <td className="px-3 py-2">
                  {it.direction === "in" ? (
                    <span className="inline-flex items-center gap-1 text-[#22C55E] text-xs font-bold uppercase">
                      <ArrowDown className="w-3 h-3" /> Entrada
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-[#EF4444] text-xs font-bold uppercase">
                      <ArrowUp className="w-3 h-3" /> Salida
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 font-mono text-[#8B5CF6]">{it.currency}</td>
                <td className="px-3 py-2 font-mono text-right">{it.amount.toLocaleString()}</td>
                <td className="px-3 py-2">
                  {it.holder_name || <span className="text-neutral-600">—</span>}
                </td>
                <td className="px-3 py-2 text-neutral-400">{it.client_name}</td>
                <td className="px-3 py-2 text-xs uppercase text-neutral-500">{it.method}</td>
                <td className="px-3 py-2 text-xs uppercase text-neutral-500">{it.status}</td>
                <td className="px-3 py-2 font-mono text-xs text-neutral-600">
                  {it.ref_id?.slice(0, 6)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
