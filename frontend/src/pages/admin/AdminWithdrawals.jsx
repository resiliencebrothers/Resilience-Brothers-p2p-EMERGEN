import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";

export default function AdminWithdrawals() {
  const [items, setItems] = useState([]);
  const [redemptions, setRedemptions] = useState([]);
  const [open, setOpen] = useState(null);
  const [note, setNote] = useState("");

  const load = async () => {
    const [w, r] = await Promise.all([
      axios.get(`${API}/admin/withdrawals`, { withCredentials: true }),
      axios.get(`${API}/admin/redemptions`, { withCredentials: true }),
    ]);
    setItems(w.data); setRedemptions(r.data);
  };
  useEffect(() => { load(); }, []);

  const updateW = async (status) => {
    await axios.put(`${API}/admin/withdrawals/${open.id}/status`, { status, admin_note: note }, { withCredentials: true });
    toast.success(`Retiro ${status}`);
    setOpen(null); setNote(""); load();
  };

  const updateR = async (id, status) => {
    await axios.put(`${API}/admin/redemptions/${id}/status`, { status }, { withCredentials: true });
    toast.success("Actualizado"); load();
  };

  return (
    <div data-testid="admin-withdrawals" className="space-y-8">
      <div>
        <div className="micro-label text-[#EAB308] mb-2">/ Retiros VIP</div>
        <h1 className="font-display text-3xl">Retiros & Canjes</h1>
      </div>

      <div>
        <h2 className="font-display text-xl mb-3">Retiros</h2>
        <div className="tactile-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="border-b border-white/10 bg-[#0a0a0a]">
              <tr className="text-left">
                <th className="px-3 py-3 micro-label text-neutral-500">Usuario</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Monto</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Método</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Detalles</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Estado</th>
                <th className="px-3 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && <tr><td colSpan="6" className="text-center text-neutral-500 py-6">Sin retiros</td></tr>}
              {items.map(w => (
                <tr key={w.id} className="border-b border-white/5">
                  <td className="px-3 py-3">{w.user_name}</td>
                  <td className="px-3 py-3 font-mono text-[#EAB308]">${w.amount_usd}</td>
                  <td className="px-3 py-3">{w.method}</td>
                  <td className="px-3 py-3 text-xs max-w-xs truncate">{w.details}</td>
                  <td className="px-3 py-3 text-xs uppercase">{w.status}</td>
                  <td className="px-3 py-3"><Button size="sm" onClick={() => { setOpen(w); setNote(w.admin_note || ""); }} className="bg-[#EAB308] hover:bg-[#FACC15] text-black rounded-none h-8">Gestionar</Button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <h2 className="font-display text-xl mb-3">Canjes de Mercancía</h2>
        <div className="tactile-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="border-b border-white/10 bg-[#0a0a0a]">
              <tr className="text-left">
                <th className="px-3 py-3 micro-label text-neutral-500">Usuario</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Producto</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Cant.</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Total</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Dirección</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Estado</th>
                <th className="px-3 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {redemptions.length === 0 && <tr><td colSpan="7" className="text-center text-neutral-500 py-6">Sin canjes</td></tr>}
              {redemptions.map(r => (
                <tr key={r.id} className="border-b border-white/5">
                  <td className="px-3 py-3">{r.user_name}</td>
                  <td className="px-3 py-3">{r.product_name}</td>
                  <td className="px-3 py-3 font-mono">{r.quantity}</td>
                  <td className="px-3 py-3 font-mono text-[#EAB308]">${r.total_usd}</td>
                  <td className="px-3 py-3 text-xs max-w-xs truncate">{r.delivery_address}</td>
                  <td className="px-3 py-3 text-xs uppercase">{r.status}</td>
                  <td className="px-3 py-3">
                    <div className="flex gap-1">
                      <Button size="sm" onClick={() => updateR(r.id, "approved")} className="bg-[#22C55E] text-black rounded-none h-7 text-xs">✓</Button>
                      <Button size="sm" onClick={() => updateR(r.id, "delivered")} className="bg-[#EAB308] text-black rounded-none h-7 text-xs">⇪</Button>
                      <Button size="sm" onClick={() => updateR(r.id, "rejected")} className="bg-[#EF4444] text-white rounded-none h-7 text-xs">✕</Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <Dialog open={!!open} onOpenChange={() => setOpen(null)}>
        <DialogContent className="bg-[#141414] border-white/10 text-white rounded-none">
          <DialogHeader><DialogTitle className="font-display">Retiro #{open?.id?.slice(0,8)}</DialogTitle></DialogHeader>
          {open && (
            <div className="space-y-3">
              <div className="font-mono text-sm space-y-1">
                <div><span className="text-neutral-500">Cliente:</span> {open.user_name}</div>
                <div><span className="text-neutral-500">Monto:</span> ${open.amount_usd}</div>
                <div><span className="text-neutral-500">Método:</span> {open.method}</div>
                <div><span className="text-neutral-500">Detalles:</span> {open.details}</div>
              </div>
              <Textarea value={note} onChange={e => setNote(e.target.value)} placeholder="Nota..." rows={2} className="rounded-none bg-[#0a0a0a] border-white/10" />
              <div className="grid grid-cols-3 gap-2">
                <Button onClick={() => updateW("approved")} className="bg-[#22C55E] text-black rounded-none">Aprobar</Button>
                <Button onClick={() => updateW("paid")} className="bg-[#EAB308] text-black rounded-none">Pagado</Button>
                <Button onClick={() => updateW("rejected")} className="bg-[#EF4444] text-white rounded-none">Rechazar</Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
