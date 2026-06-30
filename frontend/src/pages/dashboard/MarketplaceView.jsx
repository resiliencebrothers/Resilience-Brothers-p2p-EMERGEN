import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { Boxes, Package, ChevronDown } from "lucide-react";

export default function MarketplaceView() {
  const { refresh } = useAuth();
  const [products, setProducts] = useState([]);
  const [open, setOpen] = useState(null);
  const [qty, setQty] = useState(1);
  const [addr, setAddr] = useState("");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState([]);
  // iter47 — multi-currency VIP balance (no longer just legacy USD)
  const [balances, setBalances] = useState({ balances: [], total_usdt: 0 });
  const [showBreakdown, setShowBreakdown] = useState(false);

  const loadBalances = () =>
    axios.get(`${API}/vip/balances`, { withCredentials: true })
      .then((r) => setBalances(r.data))
      .catch(() => {});

  useEffect(() => {
    axios.get(`${API}/products`).then(r => setProducts(r.data));
    axios.get(`${API}/vip/redemptions/mine`, { withCredentials: true }).then(r => setHistory(r.data)).catch(() => {});
    loadBalances();
  }, []);

  const redeem = async () => {
    if (!open) return;
    if (qty < 1) return toast.error("Cantidad inválida");
    if (!addr) return toast.error("Dirección requerida");
    setBusy(true);
    try {
      await axios.post(`${API}/vip/redeem`, { product_id: open.id, quantity: qty, delivery_address: addr }, { withCredentials: true });
      toast.success("Canje solicitado. Pendiente de aprobación.");
      setOpen(null); setQty(1); setAddr("");
      await refresh();
      const p = await axios.get(`${API}/products`); setProducts(p.data);
      const h = await axios.get(`${API}/vip/redemptions/mine`, { withCredentials: true }); setHistory(h.data);
      await loadBalances();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    } finally { setBusy(false); }
  };

  const positiveBalances = (balances.balances || []).filter(b => Number(b.amount) > 0);
  const hasMulti = positiveBalances.length > 0;

  return (
    <div className="space-y-8" data-testid="marketplace-view">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="micro-label text-[#EAB308] mb-2">/ Marketplace</div>
          <h1 className="font-display text-3xl flex items-center gap-3"><Boxes className="w-8 h-8 text-[#EAB308]" /> Canjea por Mercancía</h1>
        </div>
        <div className="tactile-card px-5 py-3 min-w-[180px]" data-testid="marketplace-balance-widget">
          <div className="micro-label text-neutral-500">Saldo total</div>
          <div
            className="font-display text-2xl text-[#EAB308]"
            data-testid="marketplace-balance-usdt"
          >
            {(balances.total_usdt || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
            <span className="text-sm text-neutral-400 ml-1">USDT</span>
          </div>
          {hasMulti && (
            <>
              <button
                onClick={() => setShowBreakdown(!showBreakdown)}
                className="text-xs text-neutral-400 hover:text-[#EAB308] mt-1 flex items-center gap-1 transition-colors"
                data-testid="marketplace-balance-toggle"
              >
                {showBreakdown ? "Ocultar" : `${positiveBalances.length} ${positiveBalances.length === 1 ? "moneda" : "monedas"}`}
                <ChevronDown
                  className={`w-3 h-3 transition-transform ${showBreakdown ? "rotate-180" : ""}`}
                />
              </button>
              {showBreakdown && (
                <div
                  className="mt-2 pt-2 border-t border-white/5 space-y-1"
                  data-testid="marketplace-balance-breakdown"
                >
                  {positiveBalances.map((b) => (
                    <div
                      key={b.currency}
                      className="flex items-center justify-between text-xs"
                      data-testid={`marketplace-balance-${b.currency}`}
                    >
                      <span className="text-neutral-400 font-mono">{b.currency}</span>
                      <span className="text-neutral-200 font-mono">
                        {Number(b.amount).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {products.length === 0 && <p className="text-neutral-500 col-span-full text-center py-12">No hay productos disponibles.</p>}
        {products.map(p => (
          <div key={p.id} className="tactile-card overflow-hidden flex flex-col">
            <div className="aspect-video bg-[#0a0a0a] overflow-hidden">
              {p.image_url ? (
                <img src={p.image_url} alt={p.name} className="w-full h-full object-cover" />
              ) : (
                <div className="w-full h-full flex items-center justify-center">
                  <Package className="w-12 h-12 text-neutral-700" />
                </div>
              )}
            </div>
            <div className="p-5 flex-1 flex flex-col">
              <div className="micro-label text-neutral-500 mb-1">{p.category}</div>
              <h3 className="font-display text-lg mb-2">{p.name}</h3>
              <p className="text-sm text-neutral-400 mb-4 line-clamp-2">{p.description}</p>
              <div className="mt-auto flex items-center justify-between">
                <div>
                  <div className="font-display text-xl text-[#EAB308]">${p.price_usd}</div>
                  <div className="text-xs text-neutral-500">Stock: {p.stock}</div>
                </div>
                <Button data-testid={`redeem-${p.id}`} onClick={() => setOpen(p)} disabled={p.stock === 0} className="bg-[#EAB308] hover:bg-[#FACC15] text-black font-semibold rounded-none">
                  Canjear
                </Button>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div>
        <h2 className="font-display text-xl mb-4">Mis Canjes</h2>
        <div className="tactile-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="border-b border-white/10 bg-[#0a0a0a]">
              <tr className="text-left">
                <th className="px-4 py-3 micro-label text-neutral-500">Producto</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Cant.</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Total</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Estado</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Fecha</th>
              </tr>
            </thead>
            <tbody>
              {history.length === 0 && <tr><td colSpan="5" className="text-center text-neutral-500 py-8">Sin canjes.</td></tr>}
              {history.map(h => (
                <tr key={h.id} className="border-b border-white/5">
                  <td className="px-4 py-3">{h.product_name}</td>
                  <td className="px-4 py-3 font-mono">{h.quantity}</td>
                  <td className="px-4 py-3 font-mono text-[#EAB308]">${h.total_usd}</td>
                  <td className="px-4 py-3"><span className="text-xs uppercase tracking-wider">{h.status}</span></td>
                  <td className="px-4 py-3 text-xs text-neutral-500">{new Date(h.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <Dialog open={!!open} onOpenChange={() => setOpen(null)}>
        <DialogContent className="bg-[#141414] border-white/10 text-white rounded-none">
          <DialogHeader>
            <DialogTitle className="font-display">Canjear: {open?.name}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label className="micro-label text-neutral-500">Cantidad</Label>
              <Input data-testid="redeem-qty" type="number" min="1" value={qty} onChange={e => setQty(parseInt(e.target.value) || 1)} className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">Dirección de entrega</Label>
              <Textarea data-testid="redeem-addr" value={addr} onChange={e => setAddr(e.target.value)} rows={3} className="rounded-none mt-2 bg-[#0a0a0a] border-white/10" />
            </div>
            <div className="border border-white/10 p-3 font-mono text-sm flex justify-between">
              <span className="text-neutral-500">Total:</span>
              <span className="text-[#EAB308]">${(open?.price_usd * qty || 0).toFixed(2)}</span>
            </div>
            <Button data-testid="confirm-redeem" onClick={redeem} disabled={busy} className="w-full bg-[#EAB308] hover:bg-[#FACC15] text-black font-bold rounded-none h-12">
              {busy ? "Procesando..." : "Confirmar Canje"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
