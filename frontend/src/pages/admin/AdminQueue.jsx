import { useEffect, useState } from "react";
import axios from "axios";
import { Link } from "react-router-dom";
import { API } from "@/App";
import { ListChecks, ArrowDownToLine, ChevronRight } from "lucide-react";
import { toast } from "sonner";
import DefensiveModePanel from "@/components/DefensiveModePanel";

const ORDER_STATUS = {
  pending: "Pendiente",
  requires_double_approval: "Doble aprobación",
};

export default function AdminQueue() {
  const [data, setData] = useState({ orders: [], withdrawals: [], counts: { orders: 0, withdrawals: 0 } });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const r = await axios.get(`${API}/admin/queue`, { withCredentials: true });
        setData(r.data);
      } catch (e) {
        toast.error("Error al cargar cola");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  if (loading) return <div className="text-neutral-500 micro-label">Cargando cola...</div>;

  const empty = data.counts.orders === 0 && data.counts.withdrawals === 0;

  return (
    <div data-testid="admin-queue" className="space-y-8">
      <div>
        <div className="micro-label text-[#EAB308] mb-2">/ Mi Cola</div>
        <h1 className="font-display text-3xl">Pendientes en tu scope</h1>
        <p className="text-neutral-500 text-sm mt-2">
          Sólo los ítems pendientes dentro de tus monedas autorizadas. Los admins ven todo.
        </p>
      </div>

      <DefensiveModePanel />

      {empty && (
        <div className="tactile-card p-12 text-center">
          <div className="micro-label text-[#22C55E] mb-2">/ todo al día</div>
          <p className="text-neutral-400">No hay órdenes ni retiros pendientes en tu scope.</p>
        </div>
      )}

      {data.counts.orders > 0 && (
        <section data-testid="queue-orders">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-display text-xl flex items-center gap-2">
              <ListChecks className="w-5 h-5 text-[#EAB308]" /> Órdenes pendientes
              <span className="text-xs text-neutral-500 font-mono">({data.counts.orders})</span>
            </h2>
            <Link to="/admin/orders" className="micro-label text-[#EAB308] hover:underline">
              Ir a Órdenes →
            </Link>
          </div>
          <div className="tactile-card overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-[#0a0a0a] border-b border-white/10">
                <tr className="text-left">
                  <th className="px-4 py-3 micro-label text-neutral-500">Usuario</th>
                  <th className="px-4 py-3 micro-label text-neutral-500">Par</th>
                  <th className="px-4 py-3 micro-label text-neutral-500">Monto</th>
                  <th className="px-4 py-3 micro-label text-neutral-500">Método</th>
                  <th className="px-4 py-3 micro-label text-neutral-500">Estado</th>
                  <th className="px-4 py-3 micro-label text-neutral-500">Creada</th>
                </tr>
              </thead>
              <tbody>
                {data.orders.slice(0, 50).map(o => (
                  <tr key={o.id} className="border-b border-white/5" data-testid={`queue-order-${o.id}`}>
                    <td className="px-4 py-3">{o.user_name}</td>
                    <td className="px-4 py-3 font-mono">{o.from_code} → {o.to_code}</td>
                    <td className="px-4 py-3 font-mono text-[#EAB308]">{o.amount_from} {o.from_code}</td>
                    <td className="px-4 py-3 text-xs">{o.delivery_method}</td>
                    <td className="px-4 py-3 text-xs uppercase">{ORDER_STATUS[o.status] || o.status}</td>
                    <td className="px-4 py-3 text-xs text-neutral-500">{new Date(o.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.orders.length > 50 && (
              <div className="px-4 py-2 text-xs text-neutral-500 border-t border-white/10">
                Mostrando 50 de {data.orders.length} — ver el resto en /admin/orders
              </div>
            )}
          </div>
        </section>
      )}

      {data.counts.withdrawals > 0 && (
        <section data-testid="queue-withdrawals">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-display text-xl flex items-center gap-2">
              <ArrowDownToLine className="w-5 h-5 text-[#EAB308]" /> Retiros pendientes
              <span className="text-xs text-neutral-500 font-mono">({data.counts.withdrawals})</span>
            </h2>
            <Link to="/admin/withdrawals" className="micro-label text-[#EAB308] hover:underline">
              Ir a Retiros →
            </Link>
          </div>
          <div className="tactile-card overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-[#0a0a0a] border-b border-white/10">
                <tr className="text-left">
                  <th className="px-4 py-3 micro-label text-neutral-500">Usuario</th>
                  <th className="px-4 py-3 micro-label text-neutral-500">Monto</th>
                  <th className="px-4 py-3 micro-label text-neutral-500">Moneda</th>
                  <th className="px-4 py-3 micro-label text-neutral-500">Método</th>
                  <th className="px-4 py-3 micro-label text-neutral-500">Solicitado</th>
                </tr>
              </thead>
              <tbody>
                {data.withdrawals.slice(0, 50).map(w => (
                  <tr key={w.id} className="border-b border-white/5" data-testid={`queue-withdrawal-${w.id}`}>
                    <td className="px-4 py-3">{w.user_name}</td>
                    <td className="px-4 py-3 font-mono text-[#EAB308]">{w.amount_usd}</td>
                    <td className="px-4 py-3 font-mono">{w.currency || "USD"}</td>
                    <td className="px-4 py-3 text-xs">
                      {w.method}
                      {w.method === "crypto" && w.crypto_network && (
                        <span className="ml-1.5 inline-flex items-center px-1.5 py-0.5 text-[0.55rem] uppercase tracking-wider bg-[#EAB308]/10 text-[#EAB308] border border-[#EAB308]/30 font-mono">
                          {w.crypto_network}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-neutral-500">{new Date(w.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
