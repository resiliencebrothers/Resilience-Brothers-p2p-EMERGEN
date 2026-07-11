import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { useSearchParams } from "react-router-dom";
import { API } from "@/App";
import { Badge } from "@/components/ui/badge";
import CopyableText from "@/components/CopyableText";
import ExplorerLink from "@/components/ExplorerLink";
import { extractCryptoNetwork } from "@/services/delivery_validators";
import { ORDER_FILTER_STATUSES } from "@/constants/orderStatus";

const STATUS_STYLES = {
  pending: "bg-[#8B5CF6]/10 text-[#8B5CF6] border-[#8B5CF6]/30",
  approved: "bg-[#F59E0B]/10 text-[#F59E0B] border-[#F59E0B]/30",
  completed: "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  rejected: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30",
};

const STATUS_LABELS = {
  pending: "Pendiente",
  approved: "Confirmado",
  completed: "Completado",
  rejected: "Rechazado",
  requires_double_approval: "Doble aprobación",
};

export default function OrdersView() {
  const [orders, setOrders] = useState([]);
  const [selected, setSelected] = useState(null);
  // iter55.25b — allow deep-linking from the dashboard StatCards so a click on
  // "Pendientes" jumps here already scoped to `filter=pending` (mirrors the
  // owner's mental model that the counter and the table should be in lock-step).
  const [searchParams, setSearchParams] = useSearchParams();
  const initialFilter = searchParams.get("filter") || "all";
  const [filter, setFilter] = useState(initialFilter);

  useEffect(() => {
    axios.get(`${API}/orders/mine`, { withCredentials: true }).then(r => setOrders(r.data));
  }, []);

  const filteredOrders = useMemo(() => {
    const statuses = ORDER_FILTER_STATUSES[filter];
    if (!statuses) return orders;
    return orders.filter((o) => statuses.includes(o.status));
  }, [orders, filter]);

  const applyFilter = (next) => {
    setFilter(next);
    if (next === "all") {
      searchParams.delete("filter");
    } else {
      searchParams.set("filter", next);
    }
    setSearchParams(searchParams, { replace: true });
  };

  const FILTER_PILLS = [
    { key: "all", label: "Todas" },
    { key: "pending", label: "Pendientes" },
    { key: "completed", label: "Completadas" },
    { key: "rejected", label: "Rechazadas" },
  ];

  return (
    <div data-testid="orders-view">
      <div className="mb-6">
        <div className="micro-label text-[#8B5CF6] mb-2">/ Historial</div>
        <h1 className="font-display text-3xl">Mis Órdenes</h1>
      </div>

      {/* Filter pills — deep-link aware */}
      <div className="flex gap-2 mb-4 flex-wrap" data-testid="orders-filter-pills">
        {FILTER_PILLS.map((p) => (
          <button
            key={p.key}
            type="button"
            onClick={() => applyFilter(p.key)}
            data-testid={`orders-filter-${p.key}`}
            aria-pressed={filter === p.key}
            className={
              "text-xs uppercase tracking-wider border px-3 py-1.5 rounded-none transition-colors " +
              (filter === p.key
                ? "bg-[#8B5CF6] text-white border-[#8B5CF6]"
                : "border-white/15 text-neutral-400 hover:border-[#8B5CF6]/60 hover:text-white")
            }
          >
            {p.label}
          </button>
        ))}
      </div>

      <div className="tactile-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="border-b border-white/10 bg-[#0a0a0a]">
              <tr className="text-left">
                <th className="px-4 py-3 micro-label text-neutral-500">ID</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Par</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Envías</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Recibes</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Estado</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Fecha</th>
              </tr>
            </thead>
            <tbody>
              {filteredOrders.length === 0 && (
                <tr><td colSpan="6" className="text-center text-neutral-500 py-12">
                  {filter === "all" ? "Sin órdenes aún." : "Ninguna orden en este filtro."}
                </td></tr>
              )}
              {filteredOrders.map(o => (
                <tr key={o.id} onClick={() => setSelected(o)} className="border-b border-white/5 hover:bg-white/5 cursor-pointer transition-colors">
                  <td className="px-4 py-4 font-mono text-xs">{o.id.slice(0, 8)}</td>
                  <td className="px-4 py-4 font-mono text-sm">{o.from_code} → {o.to_code}</td>
                  <td className="px-4 py-4 font-mono text-sm">{o.amount_from}</td>
                  <td className="px-4 py-4 font-mono text-sm text-[#8B5CF6]">{o.amount_to}</td>
                  <td className="px-4 py-4">
                    <span className={`text-xs uppercase tracking-wider border px-2 py-1 ${STATUS_STYLES[o.status]}`}>{STATUS_LABELS[o.status] || o.status}</span>
                  </td>
                  <td className="px-4 py-4 text-xs text-neutral-400">{new Date(o.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur" onClick={() => setSelected(null)}>
          <div className="bg-[#141322] border border-white/10 max-w-lg w-full p-6 max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-display text-xl">Orden #{selected.id.slice(0,8)}</h3>
              <button onClick={() => setSelected(null)} className="text-neutral-500 hover:text-white">✕</button>
            </div>
            <div className="space-y-2 font-mono text-sm">
              <Row label="Par" value={`${selected.from_code} → ${selected.to_code}`} />
              <Row label="Envías" value={`${selected.amount_from} ${selected.from_code}`} />
              <Row label="Recibes" value={`${selected.amount_to} ${selected.to_code}`} />
              <Row label="Tasa" value={selected.rate_applied} />
              {selected.commission_percent > 0 && (
                <Row label="Comisión" value={`${selected.commission_percent}%`} />
              )}
              <Row label="Entrega" value={selected.delivery_method} />
              <Row label="Detalles" value={selected.delivery_details || "—"} />
              <Row label="Titular" value={selected.sender_name} />
              <Row label="Estado" value={STATUS_LABELS[selected.status] || selected.status} />
              {selected.admin_note && <Row label="Nota admin" value={selected.admin_note} />}
            </div>
            {selected.proof_image && (
              <div className="mt-4">
                <div className="micro-label text-neutral-500 mb-2">Tu comprobante de pago</div>
                <img src={selected.proof_image} alt="proof" className="w-full border border-white/10" />
              </div>
            )}
            {/* Payout evidence — uploaded by staff once they've paid the client.
                Visible only when the order is completed for full transparency. */}
            {selected.status === "completed" && (selected.payout_proof_image || selected.payout_tx_hash) && (
              <div className="mt-4 border-t border-white/5 pt-4">
                <div className="micro-label text-[#22C55E] mb-2">
                  ✓ Comprobante del pago realizado a ti
                </div>
                {selected.payout_tx_hash && (
                  <div className="text-xs bg-[#0a0a0a] border border-white/10 p-2 mb-2 flex items-start gap-2 flex-wrap">
                    <span className="text-neutral-500 flex-shrink-0">Hash:</span>
                    <span className="text-[#22C55E]" data-testid="my-order-payout-hash">
                      <CopyableText
                        value={selected.payout_tx_hash}
                        label="Copiar hash"
                        toastMessage="Hash copiado"
                        testid="my-order-payout-hash-copy"
                      />
                    </span>
                    <ExplorerLink
                      network={extractCryptoNetwork(selected.delivery_details, selected.delivery_method)}
                      txHash={selected.payout_tx_hash}
                      testid="my-order-explorer-link"
                    />
                  </div>
                )}
                {selected.payout_proof_image && (
                  <a
                    href={selected.payout_proof_image}
                    target="_blank"
                    rel="noreferrer"
                    data-testid="my-order-payout-proof"
                    className="block"
                  >
                    <img
                      src={selected.payout_proof_image}
                      alt="Captura del pago al cliente"
                      className="w-full border border-[#22C55E]/40"
                    />
                  </a>
                )}
                <p className="text-[0.7rem] text-neutral-500 mt-2">
                  Esta es la evidencia del pago realizado por Resilience Brothers a tu cuenta/wallet.
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex justify-between border-b border-white/5 py-2">
      <span className="text-neutral-500">{label}:</span>
      <span className="text-right max-w-xs break-words">{value}</span>
    </div>
  );
}
