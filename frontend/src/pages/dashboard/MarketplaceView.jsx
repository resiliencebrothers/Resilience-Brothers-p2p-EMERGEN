import { useEffect, useMemo, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
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
import { Boxes, Package, Search, Truck, Store, MapPin, QrCode, Tag, BadgeCheck, AlertTriangle } from "lucide-react";
import { QRCodeCanvas } from "qrcode.react";
import BalanceConverterCard from "@/components/BalanceConverterCard";
import VerificationGateBanner from "@/components/VerificationGateBanner";
import MunicipalDeliveryPicker from "@/components/MunicipalDeliveryPicker";
import OffersBanner from "@/components/OffersBanner";
import DeliveryCoverageDialog from "@/components/DeliveryCoverageDialog";
import { extractDetailMessage } from "@/utils/apiErrors";
import { fmtQty, unitAbbr, isFractionUnit, qtyStep, sanitizeQty } from "@/utils/units";

export default function MarketplaceView() {
  const { refresh } = useAuth();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [products, setProducts] = useState([]);
  const [open, setOpen] = useState(null);
  // iter285 — la cantidad vive como texto: el usuario puede borrar el «1»
  // inicial y escribir directamente el número (qtyNum = valor efectivo).
  const [qty, setQty] = useState("1");
  const qtyNum = Math.max(0, parseFloat(qty) || 0);
  // Cotización canónica de servidor (misma operación/redondeo que la compra):
  // el total a mostrar y reenviar como expected_total_usdt viene del backend,
  // así multiplicar el precio unitario USDT ya redondeado por la cantidad no
  // puede divergir del total agregado convertido (evita PRICE_CHANGED falso).
  const [quote, setQuote] = useState(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [quoteError, setQuoteError] = useState(false);
  const [quoteReload, setQuoteReload] = useState(0);
  const [addr, setAddr] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState([]);
  // iter198 — courier fee for the marketplace deliveries.
  const [deliveryCoords, setDeliveryCoords] = useState(null);
  const [courierQuote, setCourierQuote] = useState(null);
  // Prop. Tarifa-Municipio — municipio elegido (fuente principal del envío a
  // domicilio) y bandera de "sin cobertura" para ofrecer recoger/contactar.
  const [deliveryMunicipality, setDeliveryMunicipality] = useState(null);
  const [noCoverage, setNoCoverage] = useState(false);
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
  // iter326 — filtro "Ofertas": ver todas las liquidaciones juntas.
  const [onlyOffers, setOnlyOffers] = useState(false);
  const norm = (s) => (s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  const offerCount = useMemo(() => products.filter((p) => p.on_offer).length, [products]);
  const categories = useMemo(
    () => [...new Set(products.map((p) => (p.category || "").trim()).filter(Boolean))]
      .sort((a, b) => a.localeCompare(b)),
    [products],
  );
  const visibleProducts = products.filter((p) =>
    (!onlyOffers || p.on_offer) &&
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

  // Stock EN VIVO del producto abierto: se lee de la lista `products` (que se
  // refresca con el evento products_changed) sin reemplazar `open`, para no
  // perder la elección de entrega/tienda del comprador. availableQty es lo que
  // queda disponible según la modalidad (central para envío, estantería para
  // recogida); si otro cliente agota las existencias, el aviso aparece solo.
  const liveProduct = useMemo(
    () => (open ? (products.find((p) => p.id === open.id) || open) : null),
    [open, products],
  );
  const availableQty = useMemo(() => {
    const p = liveProduct;
    if (!p) return null;
    if (fulfillment === "pickup") {
      if (!storeId) return null;
      return Number((p.by_store || {})[storeId] || 0);
    }
    if (p.company_id) return Math.max(0, Number(p.stock || 0) - Number(p.distributed || 0));
    return Number(p.stock || 0);
  }, [liveProduct, fulfillment, storeId]);
  const stockBlocked = availableQty != null && qtyNum > 0 && qtyNum > availableQty;

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
    // Solo los vendedores LEGACY (owner_id sin company_id) no tienen recogida.
    // Los productos de Empresa (con company_id) SÍ pueden recogerse en sus
    // tiendas: se consultan sus sucursales con stock del producto.
    if (open.owner_id && !open.company_id) { setStores([]); return; }
    axios.get(`${API}/stores`, { params: { product_id: open.id }, withCredentials: true })
      .then((r) => {
        setStores(r.data);
        if (r.data.length === 1) setStoreId(r.data[0].id);
      })
      .catch(() => setStores([]));
  }, [open]);

  // Cotización de servidor: al abrir el diálogo o cambiar la cantidad, pide el
  // total canónico (con debounce para la escritura). R01 — la cotización
  // anterior se INVALIDA (quote=null) al cambiar producto/cantidad y si la
  // petición falla; el total local jamás se usa como importe autorizado, así
  // que un timeout/500 nunca habilita una compra con cálculo de cliente.
  useEffect(() => {
    if (!open || qtyNum <= 0) {
      setQuote(null); setQuoteLoading(false); setQuoteError(false); return;
    }
    let cancelled = false;
    setQuote(null); setQuoteError(false); setQuoteLoading(true);
    const id = setTimeout(() => {
      axios.get(`${API}/vip/redeem-quote`, {
        params: { product_id: open.id, quantity: qtyNum },
        withCredentials: true,
      })
        .then((r) => { if (!cancelled) { setQuote(r.data); setQuoteLoading(false); } })
        .catch(() => { if (!cancelled) { setQuote(null); setQuoteLoading(false); setQuoteError(true); } });
    }, 300);
    return () => { cancelled = true; clearTimeout(id); };
  }, [open, qtyNum, quoteReload]);

  // Cotización válida = existe, corresponde al producto abierto Y a la cantidad
  // actual (normalizada igual que el backend: enteros por unidad, 3 decimales en
  // fracción). La comparación por cantidad es un refuerzo: aunque el efecto ya
  // invalida la cotización al cambiar `qtyNum`, esto evita reenviar un total que
  // no corresponda a la cantidad mostrada. Mientras no la haya (cargando o
  // error), no se puede confirmar la compra.
  const normQty = isFractionUnit(open?.unit)
    ? Math.round(qtyNum * 1000) / 1000
    : Math.round(qtyNum);
  const validQuote =
    quote && open && quote.product_id === open.id
      && Math.abs(Number(quote.quantity) - normQty) < 1e-6
      ? quote : null;

  // Enlace directo desde los banners de ofertas (resumen o mercado):
  // ?product=<id> abre ese producto; ?offers=1 activa el filtro Ofertas.
  // Se revalida con el catálogo; si no está en la lista (p. ej. fuera de los
  // primeros N) se consulta el detalle por id; si no hay stock, se avisa.
  useEffect(() => {
    if (searchParams.get("offers") === "1") setOnlyOffers(true);
    const pid = searchParams.get("product");
    if (!pid || !products.length || open) return;
    const clearParam = () => {
      const next = new URLSearchParams(searchParams);
      next.delete("product");
      setSearchParams(next, { replace: true });
    };
    const isBuyable = (prod) => {
      if (!prod || prod.price_usdt == null) return false;
      const central = Number(prod.stock || 0) - Number(prod.distributed || 0);
      const pickup = prod.by_store && Object.values(prod.by_store).some((q) => Number(q) > 0);
      return central > 0 || pickup;
    };
    (async () => {
      let prod = products.find((p) => p.id === pid);
      if (!prod) {
        try {
          const r = await axios.get(`${API}/products/${pid}`, { withCredentials: true });
          prod = r.data;
        } catch { prod = null; }
      }
      if (isBuyable(prod)) setOpen(prod);
      else toast.info("Esta oferta ya no está disponible.");
      clearParam();
    })();
  }, [products, searchParams]); // eslint-disable-line react-hooks/exhaustive-deps

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
    if (qtyNum <= 0) return toast.error(t("marketplace.invalidQty"));
    if (stockBlocked) return toast.error(t("marketplace.stockBlockedToast"));
    // R01 — sin cotización de servidor válida para ESTE producto/cantidad no se
    // autoriza la compra (nunca se cobra con un total calculado en el cliente).
    if (!validQuote) return toast.error(t("marketplace.quoteRequired"));
    const pickup = fulfillment === "pickup";
    if (pickup && !storeId) return toast.error(t("marketplace.pickupStoreRequired"));
    if (pickup) {
      const sel = stores.find((s) => s.id === storeId);
      if (sel && sel.available_qty !== undefined && sel.available_qty !== null
          && Number(sel.available_qty) < qtyNum) {
        return toast.error(t("marketplace.pickupStoreInsufficient"));
      }
    }
    if (!pickup && !addr) return toast.error(t("marketplace.addressRequired"));
    // Prop. Tarifa-Municipio — entrega a domicilio exige municipio con tarifa.
    if (!pickup && noCoverage) return toast.error(t("marketplace.noCoverageToast"));
    if (!pickup && !deliveryMunicipality) return toast.error(t("marketplace.municipalityRequired"));
    setBusy(true);
    try {
      await axios.post(`${API}/vip/redeem`, {
        product_id: open.id,
        quantity: qtyNum,
        expected_total_usdt: validQuote.total_usdt,
        ...(pickup
          ? { fulfillment: "store_pickup", store_id: storeId }
          : {
            delivery_address: addr,
            ...(phone.trim() ? { receiver_phone: phone.trim() } : {}),
            ...(deliveryCoords
              ? { delivery_latitude: deliveryCoords.lat, delivery_longitude: deliveryCoords.lon }
              : {}),
            ...(deliveryMunicipality
              ? { courier_municipality: deliveryMunicipality.id, courier_province: deliveryMunicipality.province }
              : {}),
            ...(courierQuote && !courierQuote.free && Number(courierQuote.fee_usdt) > 0
              ? { expected_courier_fee_usdt: Number(courierQuote.fee_usdt) }
              : {}),
          }),
      }, { withCredentials: true });
      toast.success(t("marketplace.successPending"));
      setOpen(null); setQty("1"); setAddr(""); setPhone("");
      setDeliveryCoords(null); setCourierQuote(null);
      setDeliveryMunicipality(null); setNoCoverage(false);
      setFulfillment("delivery"); setStoreId("");
      await refresh();
      const p = await axios.get(`${API}/products`, { withCredentials: true }); setProducts(p.data);
      const h = await axios.get(`${API}/vip/redemptions/mine`, { withCredentials: true }); setHistory(h.data);
      await loadBalances();
    } catch (e) {
      const detail = e?.response?.data?.detail;
      // El precio cambió desde que se abrió el diálogo (p. ej. oferta vencida):
      // avisar y refrescar el producto para que confirme el nuevo precio.
      if (e?.response?.status === 409 && typeof detail === "string" && detail.startsWith("PRICE_CHANGED")) {
        toast.warning(detail.split("|")[1] || "El precio cambió. Revisa el nuevo precio.");
        try {
          const fresh = await axios.get(`${API}/products/${open.id}`, { withCredentials: true });
          setOpen(fresh.data);
          const all = await axios.get(`${API}/products`, { withCredentials: true }); setProducts(all.data);
        } catch { /* producto ya no disponible */ setOpen(null); }
      } else if (typeof detail === "string" && detail.startsWith("COURIER_FEE_CHANGED")) {
        toast.warning(detail.split("|")[1] || t("marketplace.courierFeeChanged"));
      } else if (typeof detail === "string" && detail.startsWith("COURIER_NO_COVERAGE")) {
        setNoCoverage(true);
        toast.error(detail.split("|")[1] || t("marketplace.noCoverageToast"));
      } else if (typeof detail === "string" && detail.startsWith("COURIER_MUNICIPALITY_REQUIRED")) {
        toast.error(detail.split("|")[1] || t("marketplace.municipalityRequired"));
      } else {
        toast.error(extractDetailMessage(e, "Error al canjear"));
      }
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
            {(() => {
              // iter254(R07) — el marketplace liquida en USDT: mostrar el
              // saldo USDT gastable, no el equivalente multi-moneda.
              const usdt = (balances.balances || []).find(
                (b) => (b.code || b.currency) === "USDT");
              return (usdt?.amount || 0).toLocaleString(undefined, {
                maximumFractionDigits: 2 });
            })()}
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
      <div className="flex items-center gap-2 flex-wrap">
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
        <DeliveryCoverageDialog />
      </div>

      {/* iter222 — chips de categoría · iter326 — chip de Ofertas */}
      {(categories.length > 1 || offerCount > 0) && (
        <div className="flex gap-2 flex-wrap" data-testid="marketplace-category-chips">
          {offerCount > 0 && (
            <button
              data-testid="category-chip-offers"
              onClick={() => setOnlyOffers((v) => !v)}
              className={`px-3 py-1.5 text-xs uppercase tracking-wider border rounded-full transition-colors flex items-center gap-1 ${
                onlyOffers
                  ? "border-red-500 text-white bg-red-500"
                  : "border-red-500/40 text-red-300 hover:bg-red-500/10"
              }`}
            >
              <Tag className="w-3 h-3" /> {t("marketplace.offersChip")} ({offerCount})
            </button>
          )}
          <button
            data-testid="category-chip-all"
            onClick={() => { setCategory(""); setOnlyOffers(false); }}
            className={`px-3 py-1.5 text-xs uppercase tracking-wider border rounded-full transition-colors ${
              !category && !onlyOffers
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


      {!onlyOffers && !query.trim() && <OffersBanner />}
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {products.length === 0 && <p className="text-neutral-500 col-span-full text-center py-12">{t("marketplace.empty")}</p>}
        {products.length > 0 && visibleProducts.length === 0 && (
          <p className="text-neutral-500 col-span-full text-center py-12" data-testid="marketplace-search-empty">{t("marketplace.searchEmpty")}</p>
        )}
        {visibleProducts.map(p => (
          <div key={p.id} className="tactile-card overflow-hidden flex flex-col">
            <div className="aspect-video bg-[#0a0a0a] overflow-hidden relative">
              {p.on_offer && p.offer_discount_pct > 0 && (
                <span className="absolute top-2 left-2 z-10 text-[0.65rem] font-bold uppercase tracking-wider px-2 py-1 bg-red-500 text-white shadow-lg" data-testid={`product-offer-badge-${p.id}`}>
                  {t("marketplace.offer")} −{p.offer_discount_pct}%
                </span>
              )}
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
                  <div className="flex flex-col items-end gap-1 shrink-0">
                    <span className="text-[0.6rem] uppercase tracking-wider px-1.5 py-0.5 bg-amber-500/10 text-amber-300 border border-amber-500/20" data-testid={`product-vendor-${p.id}`}>
                      {t("marketplace.soldBy")} {p.owner_name}
                    </span>
                    {p.owner_verified && (
                      <span
                        data-testid={`product-verified-company-${p.id}`}
                        title={t("marketplace.verifiedCompanyHint")}
                        className="inline-flex items-center gap-1 text-[0.6rem] uppercase tracking-wider px-1.5 py-0.5 bg-emerald-500/10 text-emerald-300 border border-emerald-500/30"
                      >
                        <BadgeCheck className="w-3 h-3" /> {t("marketplace.verifiedCompany")}
                      </span>
                    )}
                  </div>
                )}
              </div>
              <h3 className="font-display text-lg mb-2">{p.name}</h3>
              <p className="text-sm text-neutral-400 mb-4 line-clamp-2">{p.description}</p>
              <div className="mt-auto flex items-center justify-between">
                <div>
                  <div className="font-display text-xl text-[#8B5CF6]" data-testid={`product-price-${p.id}`}>
                    {p.price_usdt != null ? p.price_usdt : "—"} <span className="text-xs text-neutral-400">USDT{isFractionUnit(p.unit) ? `/${unitAbbr(p.unit)}` : ""}</span>
                    {p.on_offer && p.offer_original_price_usdt != null && (
                      <span className="ml-2 text-xs text-neutral-500 line-through font-normal" data-testid={`product-offer-old-${p.id}`}>
                        {p.offer_original_price_usdt} USDT
                      </span>
                    )}
                  </div>
                  {p.store_currency && p.price_store != null && (
                    <div className="text-[0.65rem] text-neutral-500 font-mono" data-testid={`product-store-equiv-${p.id}`}>
                      ≈ {Number(p.price_store).toLocaleString(undefined, { maximumFractionDigits: 2 })} {p.store_currency} {t("marketplace.cashSuffix")}
                      {p.on_offer && p.offer_original_price_store != null && (
                        <span className="ml-1 line-through text-neutral-600">
                          {Number(p.offer_original_price_store).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                        </span>
                      )}
                    </div>
                  )}
                  {!p.store_currency && usdtRates.length > 0 && (
                    <div className="text-[0.65rem] text-neutral-500 font-mono" data-testid={`product-equivalents-${p.id}`}>
                      ≈ {equivalents(p.price_usdt ?? p.price_usd)}
                    </div>
                  )}
                  <div className="text-xs text-neutral-500" data-testid={`product-stock-${p.id}`}>{t("marketplace.stock")} {fmtQty(p.stock, p.unit)}</div>
                </div>
                <Button data-testid={`redeem-${p.id}`} onClick={() => setOpen(p)} disabled={p.stock <= 0 || p.price_usdt == null} className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-semibold rounded-none">
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
                  <td className="px-4 py-3 font-mono">{fmtQty(h.quantity, h.unit)}</td>
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

      <Dialog open={!!open} onOpenChange={() => { setOpen(null); setDeliveryCoords(null); setCourierQuote(null); setDeliveryMunicipality(null); setNoCoverage(false); setFulfillment("delivery"); setStoreId(""); }}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-display">{t("marketplace.redeem")}: {open?.name}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label className="micro-label text-neutral-500">{t("marketplace.redeemQuantity")}{open && isFractionUnit(open.unit) ? ` (${unitAbbr(open.unit)})` : ""}</Label>
              <Input data-testid="redeem-qty" type="number" min="0" step={qtyStep(open?.unit)} value={qty} onChange={e => setQty(sanitizeQty(e.target.value, open?.unit))} className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12" />
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
                    onClick={() => { setFulfillment("pickup"); setDeliveryCoords(null); setCourierQuote(null); setDeliveryMunicipality(null); setNoCoverage(false); }}
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
                {stores.length === 0 && (
                  <p className="text-[0.7rem] text-amber-400" data-testid="pickup-no-stores">
                    {t("marketplace.pickupNoStores")}
                  </p>
                )}
                {stores.map((s) => {
                  const tracked = s.available_qty !== undefined && s.available_qty !== null;
                  const enough = !tracked || Number(s.available_qty) >= qtyNum;
                  return (
                  <button
                    key={s.id}
                    data-testid={`pickup-store-option-${s.id}`}
                    disabled={tracked && !enough}
                    onClick={() => enough && setStoreId(s.id)}
                    className={`block w-full text-left border p-3 transition-colors ${
                      !enough
                        ? "border-white/5 opacity-50 cursor-not-allowed"
                        : storeId === s.id
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
                    {tracked && (
                      <div
                        className={`text-[0.65rem] mt-1 font-mono ${enough ? "text-[#22C55E]" : "text-red-400"}`}
                        data-testid={`pickup-store-stock-${s.id}`}
                      >
                        {enough
                          ? t("marketplace.pickupStoreStock", { qty: s.available_qty })
                          : t("marketplace.pickupStoreNoStock")}
                      </div>
                    )}
                    {(s.hours || s.phone) && (
                      <div className="text-[0.65rem] text-neutral-500 mt-0.5 font-mono">
                        {[s.hours, s.phone].filter(Boolean).join(" · ")}
                      </div>
                    )}
                  </button>
                  );
                })}
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
                <div>
                  <Label className="micro-label text-neutral-500">{t("marketplace.redeemPhoneLabel")}</Label>
                  <Input data-testid="redeem-phone" inputMode="tel" value={phone} onChange={e => setPhone(e.target.value)} placeholder="+53 5xxxxxxx" className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-11" />
                </div>
                <MunicipalDeliveryPicker
                  currency="USDT"
                  amount={quote?.total_usdt != null ? quote.total_usdt : (open?.price_usdt || 0) * qtyNum}
                  onCoords={setDeliveryCoords}
                  onQuote={setCourierQuote}
                  onMunicipality={setDeliveryMunicipality}
                  onNoCoverage={setNoCoverage}
                  suppressNoCoverageNote
                />
                {noCoverage && (
                  <div className="space-y-2" data-testid="redeem-no-coverage-block">
                    <div className="flex items-start gap-2 text-xs text-amber-200 border border-amber-400/40 bg-amber-400/10 px-3 py-2.5" data-testid="redeem-no-coverage-warning">
                      <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5 text-amber-400" />
                      <span>
                        {stores.length > 0
                          ? t("marketplace.noCoverageWarnPickup")
                          : t("marketplace.noCoverageWarnNoPickup")}
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-2" data-testid="redeem-no-coverage-actions">
                      {stores.length > 0 && (
                        <Button
                          type="button"
                          variant="outline"
                          data-testid="no-coverage-pickup-btn"
                          onClick={() => { setFulfillment("pickup"); setDeliveryCoords(null); setCourierQuote(null); setNoCoverage(false); }}
                          className="rounded-none border-[#8B5CF6]/40 text-[#8B5CF6] hover:bg-[#8B5CF6]/10 h-9 text-xs"
                        >
                          <Store className="w-3.5 h-3.5 mr-1.5" /> {t("marketplace.switchToPickup")}
                        </Button>
                      )}
                      <Button
                        type="button"
                        variant="outline"
                        data-testid="no-coverage-contact-btn"
                        onClick={() => { setOpen(null); navigate("/dashboard/support"); }}
                        className="rounded-none border-amber-400/40 text-amber-300 hover:bg-amber-400/10 h-9 text-xs"
                      >
                        {t("marketplace.contactTeam")}
                      </Button>
                    </div>
                  </div>
                )}
              </>
            )}
            {stockBlocked && (
              <div data-testid="redeem-stock-blocked" className="flex items-start gap-2 text-xs text-red-300 border border-red-500/30 bg-red-500/10 px-3 py-2">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <span>
                  {availableQty <= 0
                    ? t("marketplace.stockGoneZero")
                    : t("marketplace.stockGoneSome", { qty: fmtQty(availableQty, open?.unit) })}
                </span>
              </div>
            )}
            {quoteError && !quoteLoading && (
              <div data-testid="redeem-quote-error" className="flex items-center justify-between gap-2 text-xs text-red-300 border border-red-500/30 bg-red-500/10 px-3 py-2">
                <span>{t("marketplace.quoteError")}</span>
                <button
                  data-testid="redeem-quote-retry"
                  onClick={() => setQuoteReload((n) => n + 1)}
                  className="shrink-0 underline font-semibold hover:text-red-200"
                >
                  {t("marketplace.retry")}
                </button>
              </div>
            )}
            <div className="border border-white/10 p-3 font-mono text-sm space-y-1">
              <div className="flex justify-between">
                <span className="text-neutral-500">{t("marketplace.columnTotal")}:</span>
                <span className="text-[#8B5CF6]" data-testid="redeem-total-usdt">
                  {(quote?.total_usdt != null ? quote.total_usdt : (open?.price_usdt || 0) * qtyNum).toFixed(2)} USDT
                </span>
              </div>
              {open?.store_currency && open?.price_store != null && (
                <div className="text-[0.65rem] text-neutral-500" data-testid="redeem-store-equiv">
                  ≈ {(quote?.store_total != null ? quote.store_total : open.price_store * qtyNum).toLocaleString(undefined, { maximumFractionDigits: 2 })} {open.store_currency} {t("marketplace.cashSuffix")}
                </div>
              )}
              {!open?.store_currency && usdtRates.length > 0 && open && (
                <div className="text-[0.65rem] text-neutral-500" data-testid="redeem-total-equivalents">
                  ≈ {equivalents(quote?.total_usdt != null ? quote.total_usdt : (open.price_usdt ?? open.price_usd) * qtyNum)}
                </div>
              )}
              {quote?.on_offer && quote.original_total_usdt != null && Number(quote.original_total_usdt) > Number(quote.total_usdt) && (
                <div className="flex justify-between items-baseline text-xs pt-1 border-t border-white/5 mt-1" data-testid="redeem-savings-line">
                  <span className="text-neutral-500 line-through" data-testid="redeem-original-total">
                    {Number(quote.original_total_usdt).toFixed(2)} USDT
                  </span>
                  <span className="text-[#22C55E] font-semibold" data-testid="redeem-savings-amount">
                    {t("marketplace.youSave")} {(Number(quote.original_total_usdt) - Number(quote.total_usdt)).toFixed(2)} USDT ({Math.round((1 - Number(quote.total_usdt) / Number(quote.original_total_usdt)) * 100)}%)
                  </span>
                </div>
              )}
              {courierQuote && fulfillment !== "pickup" && !courierQuote.free && !courierQuote.requires_manual_review && Number(courierQuote.fee_usdt) > 0 && (
                <div className="flex justify-between text-xs" data-testid="redeem-courier-fee-line">
                  <span className="text-neutral-500">{t("marketplace.courierFeeLine")}:</span>
                  <span className="text-amber-300">+{Number(courierQuote.fee_usdt).toFixed(2)} USDT</span>
                </div>
              )}
              {(() => {
                const feeUsd = (fulfillment !== "pickup" && courierQuote && !courierQuote.free && !courierQuote.requires_manual_review)
                  ? Number(courierQuote.fee_usdt || 0) : 0;
                if (feeUsd <= 0) return null;
                const productTotal = quote?.total_usdt != null ? quote.total_usdt : (open?.price_usdt || 0) * qtyNum;
                return (
                  <div className="flex justify-between text-sm font-bold pt-1 border-t border-white/10 mt-1" data-testid="redeem-grand-total-line">
                    <span>{t("marketplace.grandTotal")}:</span>
                    <span className="text-[#8B5CF6]" data-testid="redeem-grand-total">{(productTotal + feeUsd).toFixed(2)} USDT</span>
                  </div>
                );
              })()}
              {courierQuote?.requires_manual_review && fulfillment !== "pickup" && (
                <p className="text-[0.65rem] text-amber-400 font-sans" data-testid="redeem-courier-manual-note">
                  {t("marketplace.courierManualNote")}
                </p>
              )}
            </div>
            <Button data-testid="confirm-redeem" onClick={redeem} disabled={busy || quoteLoading || stockBlocked || !validQuote || (fulfillment !== "pickup" && (noCoverage || !deliveryMunicipality || !(courierQuote && (courierQuote.free || Number(courierQuote.fee_usdt) > 0 || courierQuote.enabled === false))))} className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-12 disabled:opacity-50">
              {busy ? t("marketplace.processing") : stockBlocked ? t("marketplace.stockBlockedBtn") : quoteLoading ? t("marketplace.calculating") : quoteError ? t("marketplace.quoteUnavailable") : t("marketplace.confirmRedeem")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={!!qrItem} onOpenChange={() => setQrItem(null)}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-w-sm max-h-[85vh] overflow-y-auto">
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
                {fmtQty(qrItem.quantity, qrItem.unit)}{isFractionUnit(qrItem.unit) ? " · " : "× "}{qrItem.product_name}{qrItem.store_name ? ` — ${qrItem.store_name}` : ""}
              </p>
              <p className="text-[0.65rem] text-neutral-500">{t("marketplace.qrHint")}</p>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
