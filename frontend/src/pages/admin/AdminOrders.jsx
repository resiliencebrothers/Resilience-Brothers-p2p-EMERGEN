import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Eye } from "lucide-react";
import { toast } from "sonner";

const STATUS_STYLES = {
  pending: "bg-[#EAB308]/10 text-[#EAB308] border-[#EAB308]/30",
  approved: "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  completed: "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  rejected: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30",
};

export default function AdminOrders() {
  const [orders, setOrders] = useState([]);
  const [filter, setFilter] = useState("all");
  const [open, setOpen] = useState(null);
  const [note, setNote] = useState("");

  const load = async () => {
    const r = await axios.get(`${API}/admin/orders`, { withCredentials: true });
    setOrders(r.data);
  };
  useEffect(() => { load(); }, []);

  const updateStatus = async (status) => {
    if (!open) return;
    await axios.put(`${API}/admin/orders/${open.id}/status`, { status, admin_note: note }, { withCredentials: true });
    toast.success(`Orden ${status}`);
    setOpen(null); setNote(""); load();
  };

  const filtered = filter === "all" ? orders : orders.filter(o => o.status === filter);

  return (
    <div data-testid="admin-orders">
      <div className="mb-6">
        <div className="micro-label text-[#EAB308] mb-2">/ Órdenes</div>
        <h1 className="font-display text-3xl">Cola de Operaciones P2P</h1>
      </div>
      <div className="flex gap-2 mb-4">
        {["all", "pending", "approved", "rejected", "completed"].map(f => (
          <button key={f} onClick={() => setFilter(f)} className={`micro-label px-3 py-1.5 border transition-colors ${filter === f ? "bg-[#EAB308] text-black border-[#EAB308]" : "border-white/10 text-neutral-400 hover:text-white"}`}>
            {f}
          </button>
        ))}
      </div>
      <div className="tactile-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-white/10 bg-[#0a0a0a]">
              <tr className="text-left">
                <th className="px-3 py-3 micro-label text-neutral-500">ID</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Cliente</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Rol</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Par</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Monto</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Recibe</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Entrega</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Estado</th>
                <th className="px-3 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 && <tr><td colSpan="9" className="text-center text-neutral-500 py-8">Sin órdenes</td></tr>}
              {filtered.map(o => (
                <tr key={o.id} className="border-b border-white/5 hover:bg-white/5">
                  <td className="px-3 py-3 font-mono text-xs">{o.id.slice(0,6)}</td>
                  <td className="px-3 py-3">{o.user_name}</td>
                  <td className="px-3 py-3"><span className="text-xs uppercase">{o.user_role}</span></td>
                  <td className="px-3 py-3 font-mono">{o.from_code}→{o.to_code}</td>
                  <td className="px-3 py-3 font-mono">{o.amount_from}</td>
                  <td className="px-3 py-3 font-mono text-[#EAB308]">{o.amount_to}</td>
                  <td className="px-3 py-3 text-xs">{o.delivery_method}</td>
                  <td className="px-3 py-3"><span className={`text-xs uppercase border px-2 py-0.5 ${STATUS_STYLES[o.status]}`}>{o.status}</span></td>
                  <td className="px-3 py-3"><button onClick={() => { setOpen(o); setNote(o.admin_note || ""); }} data-testid={`view-order-${o.id}`} className="text-neutral-400 hover:text-[#EAB308]"><Eye className="w-4 h-4" /></button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <Dialog open={!!open} onOpenChange={() => setOpen(null)}>
        <DialogContent className="bg-[#141414] border-white/10 text-white rounded-none max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-display">Orden #{open?.id?.slice(0,8)}</DialogTitle></DialogHeader>
          {open && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-2 font-mono text-sm">
                <div><span className="text-neutral-500">Cliente:</span> {open.user_name}</div>
                <div><span className="text-neutral-500">Email:</span> {open.user_email}</div>
                <div><span className="text-neutral-500">Rol:</span> {open.user_role}</div>
                <div><span className="text-neutral-500">Par:</span> {open.from_code}→{open.to_code}</div>
                <div><span className="text-neutral-500">Envía:</span> {open.amount_from} {open.from_code}</div>
                <div><span className="text-neutral-500">Recibe:</span> {open.amount_to} {open.to_code}</div>
                <div><span className="text-neutral-500">Tasa:</span> {open.rate_applied}</div>
                <div><span className="text-neutral-500">Comisión:</span> {open.commission_percent}%</div>
                <div className="col-span-2"><span className="text-neutral-500">Titular pago:</span> {open.sender_name}</div>
                <div className="col-span-2"><span className="text-neutral-500">Entrega ({open.delivery_method}):</span> {open.delivery_details || "—"}</div>
              </div>
              {open.proof_image && (
                <div>
                  <div className="micro-label text-neutral-500 mb-2">Comprobante</div>
                  <img src={open.proof_image} alt="proof" className="w-full max-h-96 object-contain border border-white/10" />
                </div>
              )}
              <Textarea value={note} onChange={e => setNote(e.target.value)} placeholder="Nota administrativa..." rows={2} className="rounded-none bg-[#0a0a0a] border-white/10" />
              <div className="grid grid-cols-3 gap-2">
                <Button data-testid="approve-order" onClick={() => updateStatus("approved")} className="bg-[#22C55E] hover:bg-[#16A34A] text-black rounded-none">Aprobar</Button>
                <Button data-testid="complete-order" onClick={() => updateStatus("completed")} className="bg-[#EAB308] hover:bg-[#FACC15] text-black rounded-none">Completar</Button>
                <Button data-testid="reject-order" onClick={() => updateStatus("rejected")} className="bg-[#EF4444] hover:bg-[#DC2626] text-white rounded-none">Rechazar</Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
