import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { Boxes, Package, ChevronDown, ArrowRightLeft } from "lucide-react";

export default function MarketplaceView() {
  const { user, refresh } = useAuth();
  const [products, setProducts] = useState([]);
  const [open, setOpen] = useState(null);
  const [qty, setQty] = useState(1);
  const [addr, setAddr] = useState("");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState([]);
  // iter47 — multi-currency VIP balance (no longer just legacy USD)
  const [balances, setBalances] = useState({ balances: [], total_usdt: 0 });
  const [showBreakdown, setShowBreakdown] = useState(false);
  // iter48 — instant self-conversion dialog state
  const [convertOpen, setConvertOpen] = useState(false);
  const [convertFromCode, setConvertFromCode] = useState("");
  const [convertToCode, setConvertToCode] = useState("USDT");
  const [convertAmount, setConvertAmount] = useState("");
  const [convertBusy, setConvertBusy] = useState(false);
  // iter49 — rate cache for live preview (mirrors backend inverse-fallback logic)
  const [rates, setRates] = useState([]);
  const [currencies, setCurrencies] = useState([]);

  const loadBalances = () =>
    axios.get(`${API}/vip/balances`, { withCredentials: true })
      .then((r) => setBalances(r.data))
      .catch(() => {});

  useEffect(() => {
    axios.get(`${API}/products`).then(r => setProducts(r.data));
    axios.get(`${API}/vip/redemptions/mine`, { withCredentials: true }).then(r => setHistory(r.data)).catch(() => {});
    axios.get(`${API}/rates`).then(r => setRates(r.data)).catch(() => {});
    axios.get(`${API}/currencies`).then(r => setCurrencies(r.data.filter(c => c.is_active))).catch(() => {});
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

  const openConvertDialog = (fromCode) => {
    setConvertFromCode(fromCode);
    // Default destination: USDT if user is NOT already converting from USDT,
    // otherwise the first other active currency.
    const defaultTo = fromCode === "USDT"
      ? (currencies.find(c => c.code !== "USDT")?.code || "USD")
      : "USDT";
    setConvertToCode(defaultTo);
    setConvertAmount("");
    setConvertOpen(true);
  };

  // iter49 — mirror of `services/balances.py::_convert_direct` (inverse-first)
  // so the preview value matches what the backend will return exactly.
  const computeRate = (fromCode, toCode) => {
    if (!fromCode || !toCode || fromCode === toCode) return null;
    const isVip = user?.role === "vip" || user?.role === "admin";
    const pickRate = (r) => Number(isVip ? (r.rate_vip || r.rate_normal) : r.rate_normal);
    const direct = rates.find(r => r.from_code === fromCode && r.to_code === toCode);
    if (direct) {
      const v = pickRate(direct);
      if (v > 0) return v;
    }
    const inverse = rates.find(r => r.from_code === toCode && r.to_code === fromCode);
    if (inverse) {
      const inv = pickRate(inverse);
      if (inv > 0) return 1 / inv;
    }
    return null;
  };

  const previewRate = computeRate(convertFromCode, convertToCode);
  const previewAmount = previewRate && convertAmount
    ? Number(parseFloat(convertAmount) * previewRate).toFixed(4)
    : null;

  const submitConvert = async () => {
    const amt = parseFloat(convertAmount);
    if (!amt || amt <= 0) return toast.error("Cantidad inválida");
    if (!convertToCode || convertToCode === convertFromCode) {
      return toast.error("Selecciona una moneda destino diferente");
    }
    const available = positiveBalances.find(b => b.currency === convertFromCode);
    if (!available || Number(available.amount) < amt) {
      return toast.error(`No tienes ${amt} ${convertFromCode} disponible.`);
    }
    setConvertBusy(true);
    try {
      const r = await axios.post(
        `${API}/vip/convert`,
        { from_code: convertFromCode, to_code: convertToCode, amount_from: amt },
        { withCredentials: true },
      );
      toast.success(
        `Convertiste ${amt} ${convertFromCode} en ${r.data.amount_to} ${convertToCode}.`,
      );
      setConvertOpen(false);
      await loadBalances();
      await refresh();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error en la conversión");
    } finally { setConvertBusy(false); }
  };

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
                      className="flex items-center justify-between text-xs gap-2"
                      data-testid={`marketplace-balance-${b.currency}`}
                    >
                      <span className="text-neutral-400 font-mono">{b.currency}</span>
                      <div className="flex items-center gap-2">
                        <span className="text-neutral-200 font-mono">
                          {Number(b.amount).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                        </span>
                        <button
                          onClick={() => openConvertDialog(b.currency)}
                          className="text-[#EAB308] hover:text-[#FACC15] transition-colors p-0.5"
                          title={`Convertir ${b.currency} a otra moneda`}
                          data-testid={`marketplace-convert-${b.currency}`}
                        >
                          <ArrowRightLeft className="w-3 h-3" />
                        </button>
                      </div>
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

      {/* iter48 — Instant self-conversion dialog */}
      <Dialog open={convertOpen} onOpenChange={setConvertOpen}>
        <DialogContent className="bg-[#111] border-white/10 text-white rounded-none">
          <DialogHeader>
            <DialogTitle data-testid="convert-dialog-title" className="flex items-center gap-2">
              Convertir {convertFromCode}
              <ArrowRightLeft className="w-4 h-4 text-[#EAB308]" />
              {convertToCode}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 pt-4">
            <div className="text-xs text-neutral-400">
              Mueve fondos entre tus propias monedas al tipo de cambio VIP. No
              requiere aprobación del staff.
            </div>
            {/* Destination dropdown */}
            <div>
              <Label className="micro-label text-neutral-500">Moneda destino</Label>
              <Select value={convertToCode} onValueChange={setConvertToCode}>
                <SelectTrigger
                  data-testid="convert-to-code"
                  className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12"
                >
                  <SelectValue placeholder="Selecciona destino" />
                </SelectTrigger>
                <SelectContent className="bg-[#111] border-white/10 text-white">
                  {currencies
                    .filter(c => c.code !== convertFromCode)
                    .map(c => (
                      <SelectItem
                        key={c.code}
                        value={c.code}
                        data-testid={`convert-to-option-${c.code}`}
                      >
                        {c.code} · {c.name}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
            {/* Amount input */}
            <div>
              <Label className="micro-label text-neutral-500">
                Cantidad de {convertFromCode}
              </Label>
              <div className="flex items-center gap-2 mt-2">
                <Input
                  data-testid="convert-amount"
                  type="number"
                  min="0"
                  step="any"
                  value={convertAmount}
                  onChange={(e) => setConvertAmount(e.target.value)}
                  className="rounded-none bg-[#0a0a0a] border-white/10 h-12 font-mono"
                />
                <Button
                  variant="ghost"
                  className="text-xs text-[#EAB308] h-12 rounded-none px-3 hover:bg-[#EAB308]/10"
                  onClick={() => {
                    const b = positiveBalances.find(x => x.currency === convertFromCode);
                    if (b) setConvertAmount(String(b.amount));
                  }}
                  data-testid="convert-max"
                >MÁX</Button>
              </div>
              {convertFromCode && (
                <div className="text-[0.65rem] text-neutral-500 mt-1 font-mono">
                  Saldo: {(positiveBalances.find(x => x.currency === convertFromCode)?.amount || 0).toLocaleString(undefined, { maximumFractionDigits: 4 })} {convertFromCode}
                </div>
              )}
            </div>
            {/* Live preview (iter49) */}
            <div
              className="border border-white/10 p-3 bg-[#0a0a0a]"
              data-testid="convert-preview"
            >
              {previewRate === null && convertToCode && convertFromCode && convertToCode !== convertFromCode && (
                <div className="text-xs text-red-400" data-testid="convert-preview-no-rate">
                  No hay tasa cotizada para {convertFromCode} → {convertToCode}.
                </div>
              )}
              {previewRate !== null && (
                <>
                  <div className="flex justify-between items-baseline">
                    <span className="text-xs text-neutral-500">Recibirás:</span>
                    <span
                      className="font-mono text-lg text-[#EAB308]"
                      data-testid="convert-preview-amount"
                    >
                      {previewAmount === null
                        ? `~ ${convertToCode}`
                        : `${Number(previewAmount).toLocaleString(undefined, { maximumFractionDigits: 4 })} ${convertToCode}`}
                    </span>
                  </div>
                  <div className="text-[0.65rem] text-neutral-600 font-mono mt-1">
                    Tasa: 1 {convertFromCode} = {previewRate.toFixed(6)} {convertToCode}
                  </div>
                </>
              )}
            </div>
            <Button
              data-testid="confirm-convert"
              onClick={submitConvert}
              disabled={convertBusy || !convertAmount || previewRate === null}
              className="w-full bg-[#EAB308] hover:bg-[#FACC15] text-black font-bold rounded-none h-12 flex items-center justify-center gap-2"
            >
              <ArrowRightLeft className="w-4 h-4" />
              {convertBusy ? "Convirtiendo..." : "Confirmar conversión"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
