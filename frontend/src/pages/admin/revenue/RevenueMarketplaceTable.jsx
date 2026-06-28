import { Boxes } from "lucide-react";

export function RevenueMarketplaceTable({ marketplace, fmt }) {
  return (
    <div className="tactile-card overflow-hidden" data-testid="revenue-marketplace">
      <div className="px-6 py-4 border-b border-white/10 flex items-center justify-between flex-wrap gap-2">
        <div>
          <h2 className="font-display text-lg flex items-center gap-2">
            <Boxes className="w-5 h-5 text-[#EAB308]" /> Ganancia del Marketplace
          </h2>
          <p className="text-xs text-neutral-500 mt-1">
            Solo redenciones entregadas (status=delivered).
            Configura el campo «Costo» en cada producto.
          </p>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right">
            <div className="micro-label text-neutral-500">Ingreso</div>
            <div className="font-mono font-semibold">${fmt(marketplace.total_revenue_usd)}</div>
          </div>
          <div className="text-right">
            <div className="micro-label text-neutral-500">Costo</div>
            <div className="font-mono">${fmt(marketplace.total_cost_usd)}</div>
          </div>
          <div className="text-right">
            <div className="micro-label text-[#22C55E]">Ganancia neta</div>
            <div className="font-mono text-[#22C55E] font-bold">
              ${fmt(marketplace.total_profit_usd)}
            </div>
          </div>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">Producto</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Unidades</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Canjes</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Ingreso</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Costo</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Ganancia</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Margen</th>
            </tr>
          </thead>
          <tbody>
            {marketplace.items.length === 0 && (
              <tr>
                <td colSpan="7" className="text-center text-neutral-500 py-8">
                  Sin canjes entregados aún en este período.
                </td>
              </tr>
            )}
            {marketplace.items.map(p => (
              <tr key={p.product} className="border-b border-white/5">
                <td className="px-4 py-3">{p.product}</td>
                <td className="px-4 py-3 font-mono">{p.units}</td>
                <td className="px-4 py-3 font-mono">{p.redemptions}</td>
                <td className="px-4 py-3 font-mono">${fmt(p.revenue_usd)}</td>
                <td className="px-4 py-3 font-mono text-neutral-400">${fmt(p.cost_usd)}</td>
                <td className="px-4 py-3 font-mono text-[#22C55E]">${fmt(p.profit_usd)}</td>
                <td className="px-4 py-3 font-mono text-[#22C55E]">{p.margin_pct}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
