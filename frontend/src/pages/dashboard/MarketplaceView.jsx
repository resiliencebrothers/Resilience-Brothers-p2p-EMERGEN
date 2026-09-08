import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { useTranslation } from "react-i18next";
import { useLiveEvent } from "@/hooks/useLiveStream";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { Boxes, Package, Search, Truck, Store, MapPin, QrCode } from "lucide-react";
import { QRCodeCanvas } from "qrcode.react";
import BalanceConverterCard from "@/components/BalanceConverterCard";
import VerificationGateBanner from "@/components/VerificationGateBanner";
import CourierQuotePicker from "@/components/CourierQuotePicker";
import { extractDetailMessage } from "@/utils/apiErrors";

export default function MarketplaceView() {
  const { refresh } = useAuth();
  const { t } = useTranslation();
  const [products, setProducts] = useState([]);
  const [open, setOpen] = useState(null);
  const [qty, setQty] = useState(1);
  const [addr, setAddr] = useState("");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState([]);
  // iter198 — courier fee for the marketplace deliveries.
  const [deliveryCoords, setDeliveryCoords] = useState(null);
  const [courierQuote, setCourierQuote] = useState(null);
  // iter236 — recogida en tienda física.
  const [fulfillment, setFulfillment] = useState("delivery");
  const [stores, setStores] = useState([]);
  const [storeId, setStoreId] = useState("");
  // iter239 — QR del código de recogida.
  const [qrItem, setQrItem] = useState(null);
  // iter50 — multi-currency VIP balance moved into the shared
  // <BalanceConverterCard /> component which fetches its own state.
  const [balances, setBalances] = useState({ balances: [], total_usdt: 0 });
  // iter217 — tasas USDT→X del día para mostrar equivalencias bajo el precio.
  const [rates, setRates] = useState([]);
  // iter221 — buscador instantáneo (sin acentos ni mayúsculas).
  const [query, setQuery] = useState("");
  // iter222 — chips de categoría para navegar la tienda más rápido.
  const [category, setCategory] = useState("");
  const norm = (s) => (s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  const categories = useMemo(
    () => [...new Set(products.map((p) => (p.category || "").trim()).filter(Boolean))]
      .sort((a, b) => a.localeCompare(b)),
    [products],
  );
  const visibleProducts = products.filter((p) =>
    (!category || (p.category || "").trim() === category) &&
    (!query.trim() || norm(p.name).includes(norm(query)) ||
      norm(p.category).includes(norm(query)) || norm(p.owner_name).includes(norm(query))));

  const usdtRates = useMemo(
    () => rates.filter((r) => r.from_code === "USDT" && r.to_code !== "USDT"
      && Number(r.rate_convert ?? r.rate_vip) > 0).slice(0, 3),
    [rates],
  );

  const equivalents = (priceUsdt) =>
    usdtRates
      .map((r) => `${(priceUsdt * Number(r.rate_convert ?? r.rate_vip)).toLocaleString(undefined, { maximumFractionDigits: 2 })} ${r.to_code}`)
      .join(" · ");

  const loadBalances = () =>
    axios.get(`${API}/vip/balances`, { withCredentials: true })
      .then((r) => setBalances(r.data))
      .catch(() => {});

  useEffect(() => {
    axios.get(`${API}/products`, { withCredentials: true }).then(r => setProducts(r.data));
    axios.get(`${API}/rates`, { withCredentials: true }).then(r => setRates(r.data)).catch(() => {});
    axios.get(`${API}/vip/redemptions/mine`, { withCredentials: true }).then(r => setHistory(r.data)).catch(() => {});
    loadBalances();
  }, []);

  // iter217 — refresco en vivo cuando vendedores/staff cambian productos.
  useLiveEvent("products_changed", () => {
    axios.get(`${API}/products`, { withCredentials: true }).then(r => setProducts(r.data)).catch(() => {});
  });

  // iter236 — sucursales donde se puede recoger el producto abierto.
  useEffect(() => {
    if (!open) return;
    setFulfillment("delivery"); setStoreId("");
    if (open.owner_id) { setStores([]); return; }
    axios.get(`${API}/stores`, { params: { product_id: open.id }, withCredentials: true })
      .then((r) => {
        setStores(r.data);
        if (r.data.length === 1) setStoreId(r.data[0].id);
      })
      .catch(() => setStores([]));
  }, [open]);

  // iter237 — el cliente avisa que va en camino a recoger.
  const onMyWay = async (id) => {
    try {
      await axios.post(`${API}/vip/redemptions/${id}/on-my-way`, {}, { withCredentials: true });
      toast.success(t("marketplace.toastOnMyWay"));
      const h = await axios.get(`${API}/vip/redemptions/mine`, { withCredentials: true }); setHistory(h.data);
    } catch (e) {
      toast.error(extractDetailMessage(e) || "Error");
    }
  };

  const redeem = async () => {
    if (!open) return;
    if (qty < 1) return toast.error(t("marketplace.invalidQty"));
    const pickup = fulfillment === "pickup";
    if (pickup && !storeId) return toast.error(t("marketplace.pickupStoreRequired"));
    if (!pickup && !addr) return toast.error(t("marketplace.addressRequired"));
    setBusy(true);
    try {
      await axios.post(`${API}/vip/redeem`, {
        product_id: open.id,
        quantity: qty,
        ...(pickup
          ? { fulfillment: "store_pickup", store_id: storeId }
          : {
            delivery_address: addr,
            ...(deliveryCoords
              ? { delivery_latitude: deliveryCoords.lat, delivery_longitude: deliveryCoords.lon }
              : {}),
            ...(courierQuote?.municipality
              ? { courier_municipality: courierQuote.municipality }
              : {}),
          }),
      }, { withCredentials: true });
      toast.success(t("marketplace.successPending"));
      setOpen(null); setQty(1); setAddr("");
      setDeliveryCoords(null); setCourierQuote(null);
      setFulfillment("delivery"); setStoreId("");
      await refresh();
      const p = await axios.get(`${API}/products`, { withCredentials: true }); setProducts(p.data);
      const h = await axios.get(`${API}/vip/redemptions/mine`, { withCredentials: true }); setHistory(h.data);
      await loadBalances();
    } catch (e) {
      toast.error(extractDetailMessage(e, "Error al canjear"));
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-8" data-testid="marketplace-view">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="micro-label text-[#8B5CF6] mb-2">{t("marketplace.eyebrow")}</div>
          <h1 className="font-display text-3xl flex items-center gap-3"><Boxes className="w-8 h-8 text-[#8B5CF6]" /> {t("marketplace.titleFull")}</h1>
        </div>
        <div className="tactile-card px-5 py-3 min-w-full sm:min-w-[180px]" data-testid="marketplace-balance-widget">
          <div className="micro-label text-neutral-500">{t("marketplace.balanceLabel")}</div>
          <div
            className="font-display text-2xl text-[#8B5CF6]"
            data-testid="marketplace-balance-usdt"
          >
            {(balances.total_usdt || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
            <span className="text-sm text-neutral-400 ml-1">USDT</span>
          </div>
        </div>
      </div>

      {/* iter55.36o — full-verification gate applies to both the converter
          widget above and the redeem grid below. Rendered inline so the
          balance summary at the top remains visible even when locked. */}
      <VerificationGateBanner action="redeemAndConvert" />

      {/* iter50 — shared converter widget (also rendered on the main Dashboard) */}
      <BalanceConverterCard onConverted={loadBalances} />

      {/* iter221 — buscador instantáneo de productos */}
      <div className="relative w-full sm:w-[340px]">
        <Search className="w-4 h-4 text-neutral-500 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
        <Input
          data-testid="marketplace-search-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("marketplace.searchPlaceholder")}
          className="rounded-none pl-9 bg-[#0a0a0a] border-white/10 h-10"
        />
      </div>

      {/* iter222 — chips de categoría */}
      {categories.length > 1 && (
        <div className="flex gap-2 flex-wrap" data-testid="marketplace-category-chips">
          <button
            data-testid="category-chip-all"
            onClick={() => setCategory("")}
            className={`px-3 py-1.5 text-xs uppercase tracking-wider border rounded-full transition-colors ${
              !category
                ? "border-[#8B5CF6] text-[#8B5CF6] bg-[#8B5CF6]/10"
                : "border-white/10 text-neutral-400 hover:text-white"
            }`}
          >
            {t("marketplace.categoryAll")}
          </button>
          {categories.map((c) => (
            <button
              key={c}
              data-testid={`category-chip-${c}`}
              onClick={() => setCategory(category === c ? "" : c)}
              className={`px-3 py-1.5 text-xs uppercase tracking-wider border rounded-full transition-colors ${
                category === c
                  ? "border-[#8B5CF6] text-[#8B5CF6] bg-[#8B5CF6]/10"
                  : "border-white/10 text-neutral-400 hover:text-white"
              }`}
            >
              {c}
            </button>
          ))}
        </div>
      )}

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {products.length === 0 && <p className="text-neutral-500 col-span-full text-center py-12">{t("marketplace.empty")}</p>}
        {products.length > 0 && visibleProducts.length === 0 && (
          <p className="text-neutral-500 col-span-full text-center py-12" data-testid="marketplace-search-empty">{t("marketplace.searchEmpty")}</p>
        )}
        {visibleProducts.map(p => (
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
              <div className="flex items-center justify-between gap-2 mb-1">
                <div className="micro-label text-neutral-500">{p.category}</div>
                {p.owner_name && (
                  <span className="text-[0.6rem] uppercase tracking-wider px-1.5 py-0.5 bg-amber-500/10 text-amber-300 border border-amber-500/20" data-testid={`product-vendor-${p.id}`}>
                    {t("marketplace.soldBy")} {p.owner_name}
                  </span>
                )}
              </div>
              <h3 className="font-display text-lg mb-2">{p.name}</h3>
              <p className="text-sm text-neutral-400 mb-4 line-clamp-2">{p.description}</p>
              <div className="mt-auto flex items-center justify-between">
                <div>
                  <div className="font-display text-xl text-[#8B5CF6]" data-testid={`product-price-${p.id}`}>
                    {p.price_usdt != null ? p.price_usdt : "—"} <span className="text-xs text-neutral-400">USDT</span>
                  </div>
                  {p.store_currency && p.price_store != null && (
                    <div className="text-[0.65rem] text-neutral-500 font-mono" data-testid={`product-store-equiv-${p.id}`}>
                      ≈ {Number(p.price_store).toLocaleString(undefined, { maximumFractionDigits: 2 })} {p.store_currency} {t("marketplace.cashSuffix")}
                    </div>
                  )}
                  {!p.store_currency && usdtRates.length > 0 && (
                    <div className="text-[0.65rem] text-neutral-500 font-mono" data-testid={`product-equivalents-${p.id}`}>
                      ≈ {equivalents(p.price_usdt ?? p.price_usd)}
                    </div>
                  )}
                  <div className="text-xs text-neutral-500">{t("marketplace.stock")} {p.stock}</div>
                </div>
                <Button data-testid={`redeem-${p.id}`} onClick={() => setOpen(p)} disabled={p.stock === 0 || p.price_usdt == null} className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-semibold rounded-none">
                  {t("marketplace.redeem")}
                </Button>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div>
        <h2 className="font-display text-xl mb-4">{t("marketplace.myRedemptions")}</h2>
        <div className="tactile-card overflow-x-auto">
          <table className="w-full text-sm min-w-[640px]">
            <thead className="border-b border-white/10 bg-[#0a0a0a]">
              <tr className="text-left">
                <th className="px-4 py-3 micro-label text-neutral-500">{t("marketplace.columnProduct")}</th>
                <th className="px-4 py-3 micro-label text-neutral-500">{t("marketplace.columnQty")}</th>
                <th className="px-4 py-3 micro-label text-neutral-500">{t("marketplace.columnTotal")}</th>
                <th className="px-4 py-3 micro-label text-neutral-500">{t("marketplace.colCourier")}</th>
                <th className="px-4 py-3 micro-label text-neutral-500">{t("marketplace.columnStatus")}</th>
                <th className="px-4 py-3 micro-label text-neutral-500">{t("marketplace.columnDate")}</th>
              </tr>
            </thead>
            <tbody>
              {history.length === 0 && <tr><td colSpan="6" className="text-center text-neutral-500 py-8">Sin canjes.</td></tr>}
              {history.map(h => (
                <tr key={h.id} className="border-b border-white/5">
                  <td className="px-4 py-3">{h.product_name}</td>
                  <td className="px-4 py-3 font-mono">{h.quantity}</td>
                  <td className="px-4 py-3 font-mono text-[#8B5CF6]">${h.total_usd}</td>
                  <td className="px-4 py-3 text-xs" data-testid={`redemption-courier-${h.id}`}>
                    {h.fulfillment === "store_pickup" ? (
                      <span className="text-[#8B5CF6]" data-testid={`redemption-pickup-${h.id}`}>
                        {t("marketplace.pickupShort")}{h.store_name ? ` · ${h.store_name}` : ""}
                        {h.pickup_code && (
                          <span className="block font-mono text-white mt-0.5" data-testid={`pickup-code-${h.id}`}>
                            {t("marketplace.pickupCodeLabel")}: {h.pickup_code.slice(0, 3)}-{h.pickup_code.slice(3)}
                            {h.status !== "delivered" && h.status !== "rejected" && (
                              <button
                                data-testid={`pickup-qr-btn-${h.id}`}
                                onClick={() => setQrItem(h)}
                                className="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 text-[0.6rem] uppercase tracking-wider border border-[#8B5CF6]/50 text-[#8B5CF6] hover:bg-[#8B5CF6]/10 transition-colors align-middle"
                              >
                                <QrCode className="w-3 h-3" /> {t("marketplace.showQrBtn")}
                              </button>
                            )}
                          </span>
                        )}
                      </span>
                    ) : h.courier_fee_status === "free" ? (
                      <span className="text-[#22C55E]">{t("marketplace.courierFree")}</span>
                    ) : Number(h.courier_fee_usd) > 0 ? (
                      <span className="font-mono text-amber-300">-${h.courier_fee_usd}</span>
                    ) : h.courier_fee_status === "manual_review" ? (
                      <span className="text-neutral-500">{t("marketplace.courierPending")}</span>
                    ) : (
                      <span className="text-neutral-600">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-xs uppercase tracking-wider">{h.status}</span>
                    {h.pickup_ready_at && (
                      <div className="text-[0.6rem] text-[#22C55E]" data-testid={`redemption-pickup-ready-${h.id}`}>
                        {t("marketplace.pickupReadyBadge")}
                      </div>
                    )}
                    {h.pickup_ready_at && h.status === "approved" && !h.on_my_way_at && (
                      <button
                        data-testid={`on-my-way-btn-${h.id}`}
                        onClick={() => onMyWay(h.id)}
                        className="mt-1 px-2 py-1 text-[0.6rem] uppercase tracking-wider border border-amber-500/50 text-amber-400 hover:bg-amber-500/10 transition-colors"
                      >
                        {t("marketplace.onMyWayBtn")}
                      </button>
                    )}
                    {h.on_my_way_at && (
                      <div className="text-[0.6rem] text-amber-400 mt-0.5" data-testid={`on-my-way-done-${h.id}`}>
                        {t("marketplace.onMyWayDone")}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-neutral-500">{new Date(h.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <Dialog open={!!open} onOpenChange={() => { setOpen(null); setDeliveryCoords(null); setCourierQuote(null); setFulfillment("delivery"); setStoreId(""); }}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-display">{t("marketplace.redeem")}: {open?.name}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label className="micro-label text-neutral-500">{t("marketplace.redeemQuantity")}</Label>
              <Input data-testid="redeem-qty" type="number" min="1" value={qty} onChange={e => setQty(parseInt(e.target.value) || 1)} className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12" />
            </div>
            {stores.length > 0 && (
              <div>
                <Label className="micro-label text-neutral-500">{t("marketplace.fulfillmentLabel")}</Label>
                <div className="grid grid-cols-2 gap-2 mt-2">
                  <button
                    data-testid="fulfillment-delivery-btn"
                    onClick={() => setFulfillment("delivery")}
                    className={`flex items-center justify-center gap-2 px-3 py-2.5 text-xs uppercase tracking-wider border transition-colors ${
                      fulfillment === "delivery"
                        ? "border-[#8B5CF6] text-[#8B5CF6] bg-[#8B5CF6]/10"
                        : "border-white/10 text-neutral-400 hover:text-white"
                    }`}
                  >
                    <Truck className="w-4 h-4" /> {t("marketplace.fulfillmentDelivery")}
                  </button>
                  <button
                    data-testid="fulfillment-pickup-btn"
                    onClick={() => { setFulfillment("pickup"); setDeliveryCoords(null); setCourierQuote(null); }}
                    className={`flex items-center justify-center gap-2 px-3 py-2.5 text-xs uppercase tracking-wider border transition-colors ${
                      fulfillment === "pickup"
                        ? "border-[#8B5CF6] text-[#8B5CF6] bg-[#8B5CF6]/10"
                        : "border-white/10 text-neutral-400 hover:text-white"
                    }`}
                  >
                    <Store className="w-4 h-4" /> {t("marketplace.fulfillmentPickup")}
                  </button>
                </div>
              </div>
            )}
            {fulfillment === "pickup" ? (
              <div className="space-y-2" data-testid="pickup-store-picker">
                <Label className="micro-label text-neutral-500">{t("marketplace.pickupSelectStore")}</Label>
                {stores.map((s) => (
                  <button
                    key={s.id}
                    data-testid={`pickup-store-option-${s.id}`}
                    onClick={() => setStoreId(s.id)}
                    className={`block w-full text-left border p-3 transition-colors ${
                      storeId === s.id
                        ? "border-[#8B5CF6] bg-[#8B5CF6]/10"
                        : "border-white/10 hover:border-white/30"
                    }`}
                  >
                    <div className="text-sm font-semibold flex items-center gap-2">
                      <MapPin className="w-3.5 h-3.5 text-[#8B5CF6]" /> {s.name}
                    </div>
                    <div className="text-xs text-neutral-400 mt-1">
                      {s.address}{[s.municipality, s.province].filter(Boolean).length > 0 ? ` — ${[s.municipality, s.province].filter(Boolean).join(", ")}` : ""}
                    </div>
                    {(s.hours || s.phone) && (
                      <div className="text-[0.65rem] text-neutral-500 mt-0.5 font-mono">
                        {[s.hours, s.phone].filter(Boolean).join(" · ")}
                      </div>
                    )}
                  </button>
                ))}
                <p className="text-[0.65rem] text-[#22C55E]" data-testid="redeem-pickup-free-line">
                  {t("marketplace.pickupFreeLine")}
                </p>
              </div>
            ) : (
              <>
                <div>
                  <Label className="micro-label text-neutral-500">{t("marketplace.redeemAddressLabel")}</Label>
                  <Textarea data-testid="redeem-addr" value={addr} onChange={e => setAddr(e.target.value)} rows={3} className="rounded-none mt-2 bg-[#0a0a0a] border-white/10" />
                </div>
                <CourierQuotePicker
                  currency="USD"
                  amount={(open?.price_usdt || 0) * qty}
                  addressText={addr}
                  onCoords={setDeliveryCoords}
                  onQuote={setCourierQuote}
                />
              </>
            )}
            <div className="border border-white/10 p-3 font-mono text-sm space-y-1">
              <div className="flex justify-between">
                <span className="text-neutral-500">{t("marketplace.columnTotal")}:</span>
                <span className="text-[#8B5CF6]">{((open?.price_usdt || 0) * qty).toFixed(2)} USDT</span>
              </div>
              {open?.store_currency && open?.price_store != null && (
                <div className="text-[0.65rem] text-neutral-500" data-testid="redeem-store-equiv">
                  ≈ {(open.price_store * qty).toLocaleString(undefined, { maximumFractionDigits: 2 })} {open.store_currency} {t("marketplace.cashSuffix")}
                </div>
              )}
              {!open?.store_currency && usdtRates.length > 0 && open && (
                <div className="text-[0.65rem] text-neutral-500" data-testid="redeem-total-equivalents">
                  ≈ {equivalents((open.price_usdt ?? open.price_usd) * qty)}
                </div>
              )}
              {courierQuote && fulfillment !== "pickup" && !courierQuote.free && !courierQuote.requires_manual_review && Number(courierQuote.fee_currency_amount) > 0 && (
                <div className="flex justify-between text-xs" data-testid="redeem-courier-fee-line">
                  <span className="text-neutral-500">{t("marketplace.courierFeeLine")}:</span>
                  <span className="text-amber-300">+${Number(courierQuote.fee_currency_amount).toFixed(2)}</span>
                </div>
              )}
              {courierQuote?.requires_manual_review && fulfillment !== "pickup" && (
                <p className="text-[0.65rem] text-amber-400 font-sans" data-testid="redeem-courier-manual-note">
                  {t("marketplace.courierManualNote")}
                </p>
              )}
            </div>
            <Button data-testid="confirm-redeem" onClick={redeem} disabled={busy} className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-12">
              {busy ? t("marketplace.processing") : t("marketplace.confirmRedeem")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={!!qrItem} onOpenChange={() => setQrItem(null)}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-w-sm">
          <DialogHeader>
            <DialogTitle className="font-display">{t("marketplace.qrTitle")}</DialogTitle>
          </DialogHeader>
          {qrItem && (
            <div className="space-y-4 text-center" data-testid="pickup-qr-dialog">
              <div className="bg-white p-4 inline-block mx-auto">
                <QRCodeCanvas value={qrItem.pickup_code} size={220} level="M" marginSize={1} />
              </div>
              <p className="font-mono text-2xl tracking-[0.3em]" data-testid="pickup-qr-code-text">
                {qrItem.pickup_code.slice(0, 3)}-{qrItem.pickup_code.slice(3)}
              </p>
              <p className="text-xs text-neutral-400">
                {qrItem.quantity}× {qrItem.product_name}{qrItem.store_name ? ` — ${qrItem.store_name}` : ""}
              </p>
              <p className="text-[0.65rem] text-neutral-500">{t("marketplace.qrHint")}</p>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
