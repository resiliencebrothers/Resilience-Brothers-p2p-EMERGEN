import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Warehouse, Store, ArrowRightLeft, PackagePlus, Undo2, History, SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";

// Inventario por ubicación: almacén central (= total − distribuido) + tiendas.
const MOVE_LABEL = { receive: "Recibido en central", distribute: "Distribuido a tienda", return: "Devuelto al central", dispatch: "Despachado (envío)", dispatch_return: "Devuelto (envío cancelado)", adjust: "Ajuste de total", release: "Devuelto por cierre de tienda" };

export default function CompanyInventoryView() {
  const [rows, setRows] = useState([]);
  const [stores, setStores] = useState([]);
  const [moves, setMoves] = useState([]);
  const [dialog, setDialog] = useState(null); // {mode, product, storeId?}
  const [qty, setQty] = useState("");
  const [storeId, setStoreId] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    axios.get(`${API}/company/inventory`, { withCredentials: true }).then((r) => setRows(r.data)).catch(() => {});
    axios.get(`${API}/company/inventory/moves`, { withCredentials: true }).then((r) => setMoves(r.data)).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    axios.get(`${API}/company/stores`, { withCredentials: true }).then((r) => setStores(r.data)).catch(() => {});
  }, [load]);

  const openDialog = (mode, product, preStore = "") => {
    setDialog({ mode, product });
    setQty(mode === "adjust" ? String(product.total) : "");
    setStoreId(preStore);
  };

  const submit = async () => {
    const n = parseFloat(qty);
    const { mode, product } = dialog;
    if (mode === "adjust") {
      if (isNaN(n) || n < 0) return toast.error("Total inválido");
    } else if (!n || n <= 0) {
      return toast.error("Cantidad inválida");
    }
    if ((mode === "distribute" || mode === "return") && !storeId) return toast.error("Elige una tienda");
    setBusy(true);
    // F2-02 — clave estable de operación: se genera UNA vez y se conserva en el
    // reintento por pérdida de respuesta, para que el servidor deduplique.
    const opId = (window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`);
    let body;
    if (mode === "receive") body = { product_id: product.product_id, qty: n, op_id: opId };
    else if (mode === "adjust") body = { product_id: product.product_id, new_total: n, expected_total: product.total, op_id: opId };
    else body = { product_id: product.product_id, store_id: storeId, qty: n, op_id: opId };
    const okMsg = mode === "receive" ? "Mercancía recibida" : mode === "distribute" ? "Distribuido a la tienda" : mode === "return" ? "Devuelto al central" : "Stock ajustado";
    const doPost = () => axios.post(`${API}/company/inventory/${mode}`, body, { withCredentials: true });
    try {
      try {
        await doPost();
      } catch (e1) {
        // Sin respuesta del servidor (red) → reintenta UNA vez con la MISMA clave.
        if (!e1.response) { await doPost(); } else { throw e1; }
      }
      toast.success(okMsg);
      setDialog(null); load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "No se pudo completar la operación");
    } finally { setBusy(false); }
  };

  const title = dialog?.mode === "receive" ? "Recibir en almacén central"
    : dialog?.mode === "distribute" ? "Distribuir a una tienda"
    : dialog?.mode === "adjust" ? "Ajustar total (inventario físico)"
    : "Devolver al almacén central";

  return (
    <div className="space-y-6" data-testid="company-inventory-view">
      <div>
        <div className="micro-label text-[#8B5CF6] mb-2">Empresa</div>
        <h2 className="font-display text-2xl flex items-center gap-3">
          <Warehouse className="w-6 h-6 text-[#8B5CF6]" /> Inventario por ubicación
        </h2>
        <p className="text-sm text-neutral-500 mt-1">El almacén central es lo distribuible (total − distribuido). Reparte existencias a tus tiendas.</p>
      </div>

      {rows.length === 0 && (
        <p className="text-neutral-500 text-center py-12 tactile-card" data-testid="company-inventory-empty">
          No tienes productos todavía. Crea un producto para gestionar su inventario.
        </p>
      )}

      <div className="space-y-4">
        {rows.map((p) => (
          <div key={p.product_id} className="tactile-card p-4" data-testid={`company-inv-${p.product_id}`}>
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div>
                <h3 className="font-display text-lg">{p.name}</h3>
                <div className="flex items-center gap-4 mt-2 text-sm">
                  <span className="text-neutral-400">Total: <span className="text-white font-mono" data-testid={`company-inv-total-${p.product_id}`}>{p.total}</span></span>
                  <span className="flex items-center gap-1 text-[#8B5CF6]">
                    <Warehouse className="w-4 h-4" /> Central: <span className="font-mono" data-testid={`company-inv-central-${p.product_id}`}>{p.central}</span>
                  </span>
                  {p.over_distributed && <span className="text-amber-400 text-xs">(sobre-distribuido)</span>}
                  {p.low && (
                    <span className="flex items-center gap-1 text-amber-300 text-xs border border-amber-500/30 bg-amber-500/10 px-2 py-0.5" data-testid={`company-inv-low-${p.product_id}`}>
                      Stock bajo (mín. {p.min_stock})
                    </span>
                  )}
                </div>
              </div>
              <div className="flex gap-2">
                <Button data-testid={`company-inv-receive-${p.product_id}`} size="sm" variant="outline"
                  onClick={() => openDialog("receive", p)}
                  className="rounded-none border-white/15 hover:border-[#8B5CF6] text-white">
                  <PackagePlus className="w-4 h-4 mr-1" /> Recibir
                </Button>
                <Button data-testid={`company-inv-distribute-${p.product_id}`} size="sm"
                  onClick={() => openDialog("distribute", p)}
                  className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white">
                  <ArrowRightLeft className="w-4 h-4 mr-1" /> Distribuir
                </Button>
                <Button data-testid={`company-inv-adjust-${p.product_id}`} size="sm" variant="outline"
                  onClick={() => openDialog("adjust", p)}
                  className="rounded-none border-white/15 hover:border-amber-400 text-white">
                  <SlidersHorizontal className="w-4 h-4 mr-1" /> Ajustar
                </Button>
              </div>
            </div>
            {p.stores.length > 0 && (
              <div className="mt-3 pt-3 border-t border-white/5 flex flex-wrap gap-2">
                {p.stores.map((s) => (
                  <div key={s.store_id} className="flex items-center gap-2 bg-[#0a0a0a] border border-white/10 px-3 py-1.5 text-sm" data-testid={`company-inv-store-${p.product_id}-${s.store_id}`}>
                    <Store className="w-3.5 h-3.5 text-neutral-500" />
                    <span className="text-neutral-300">{s.store_name}</span>
                    <span className="font-mono text-white">{s.qty}</span>
                    <button data-testid={`company-inv-return-${p.product_id}-${s.store_id}`}
                      onClick={() => openDialog("return", p, s.store_id)}
                      className="text-neutral-500 hover:text-[#8B5CF6]" title="Devolver al central">
                      <Undo2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {moves.length > 0 && (
        <div className="tactile-card p-4" data-testid="company-inventory-moves">
          <h3 className="font-display text-base flex items-center gap-2 mb-3"><History className="w-4 h-4 text-[#8B5CF6]" /> Movimientos recientes</h3>
          <div className="space-y-1 max-h-64 overflow-y-auto">
            {moves.map((m) => (
              <div key={m.id} className="flex items-center justify-between text-xs text-neutral-400 border-b border-white/5 py-1.5">
                <span>{MOVE_LABEL[m.type] || m.type}{m.store_name ? ` · ${m.store_name}` : ""}</span>
                <span className="flex items-center gap-3">
                  <span className="font-mono text-white">{m.qty}</span>
                  <span className="text-neutral-600">{new Date(m.created_at).toLocaleString("es")}</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <Dialog open={!!dialog} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
          <DialogHeader><DialogTitle className="font-display">{title}</DialogTitle></DialogHeader>
          {dialog && (
            <div className="space-y-3">
              {dialog.mode === "adjust" ? (
                <p className="text-sm text-neutral-400">{dialog.product.name} · total actual: <span className="font-mono text-white">{dialog.product.total}</span> · distribuido: <span className="font-mono text-white">{dialog.product.distributed}</span></p>
              ) : (
                <p className="text-sm text-neutral-400">{dialog.product.name} · central disponible: <span className="font-mono text-white">{dialog.product.central}</span></p>
              )}
              {(dialog.mode === "distribute" || dialog.mode === "return") && (
                <div>
                  <Label className="micro-label text-neutral-500">Tienda</Label>
                  {dialog.mode === "return" ? (
                    <Input disabled value={dialog.product.stores.find((s) => s.store_id === storeId)?.store_name || ""} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
                  ) : (
                    <Select value={storeId} onValueChange={setStoreId}>
                      <SelectTrigger data-testid="company-inv-store-select" className="rounded-none mt-1 bg-[#0a0a0a] border-white/10">
                        <SelectValue placeholder="Selecciona una tienda" />
                      </SelectTrigger>
                      <SelectContent className="bg-[#1A1730] border-white/10 text-white">
                        {stores.map((s) => (
                          <SelectItem key={s.id} value={s.id} data-testid={`company-inv-store-opt-${s.id}`}>{s.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                </div>
              )}
              <div>
                <Label className="micro-label text-neutral-500">{dialog.mode === "adjust" ? "Nuevo total" : "Cantidad"}</Label>
                <Input data-testid="company-inv-qty" type="number" step="any" min="0" value={qty}
                  onChange={(e) => setQty(e.target.value)} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" autoFocus />
                {dialog.mode === "adjust" && (
                  <p className="text-xs text-neutral-500 mt-1">No puede ser menor que lo distribuido ({dialog.product.distributed}). Se registra como un ajuste auditado.</p>
                )}
              </div>
              <Button data-testid="company-inv-submit" onClick={submit} disabled={busy}
                className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-11">
                {busy ? "…" : "Confirmar"}
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
