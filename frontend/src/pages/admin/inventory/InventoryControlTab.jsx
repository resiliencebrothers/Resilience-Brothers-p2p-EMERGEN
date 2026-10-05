import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/context/AuthContext";
import { useLiveEvent } from "@/hooks/useLiveStream";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import TotpPromptDialog from "@/components/TotpPromptDialog";
import { BellRing, Search, Plus, Eye, EyeOff, Trash2, Check, X, Wrench } from "lucide-react";
import { toast } from "sonner";

const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });

const STATUS_STYLES = {
  ok: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  bajo: "bg-amber-500/10 text-amber-300 border-amber-500/30",
  agotado: "bg-red-500/10 text-red-400 border-red-500/30",
};

// iter221 — búsqueda instantánea sin distinguir acentos ni mayúsculas.
const norm = (s) => (s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");

export default function InventoryControlTab() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  // iter223 — alta de productos directo desde el control de inventario.
  const emptyProduct = { name: "", category: "mercadito", price_usd: "", cost_usd: "", stock: 0, min_stock: "", target_stock: "", image_url: "", is_active: true };
  // iter226 — modo doble: crear producto nuevo o reponer uno existente.
  const emptyRestock = { product_id: "", quantity: 1, unit_cost: "", sale_price: "", note: "" };
  const [addOpen, setAddOpen] = useState(false);
  const [addBusy, setAddBusy] = useState(false);
  const [prod, setProd] = useState(emptyProduct);
  const [mode, setMode] = useState("new");
  const [restock, setRestock] = useState(emptyRestock);
  // iter218 — umbral configurable de "stock bajo" (alerta a admins).
  const [threshold, setThreshold] = useState("");
  // iter229 — moneda de la tienda física (los precios del inventario).
  const [storeCurrency, setStoreCurrency] = useState("");
  const [currencies, setCurrencies] = useState([]);
  const [totpOpen, setTotpOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  // iter320 (IPV) — conteo físico inline + ajuste autorizado (admin).
  const [countDraft, setCountDraft] = useState({});
  const [minDraft, setMinDraft] = useState({});
  const [targetDraft, setTargetDraft] = useState({});
  const [adjust, setAdjust] = useState(null);
  const [adjustBusy, setAdjustBusy] = useState(false);

  const load = useCallback(() => {
    axios.get(`${API}/admin/inventory/control`, { withCredentials: true })
      .then((r) => setRows(r.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    axios.get(`${API}/admin/settings`, { withCredentials: true })
      .then((r) => {
        setThreshold(String(r.data.low_stock_threshold ?? 5));
        setStoreCurrency(r.data.store_currency_code || "");
      })
      .catch(() => {});
    axios.get(`${API}/currencies`)
      .then((r) => setCurrencies(r.data.filter((c) => c.type === "fiat")))
      .catch(() => {});
  }, []);
  useLiveEvent("products_changed", load);

  const saveThreshold = async (totpCode) => {
    setBusy(true);
    try {
      await axios.put(`${API}/admin/settings`, {
        low_stock_threshold: parseInt(threshold) || 0,
        store_currency_code: storeCurrency || null,
        totp_code: totpCode,
      }, { withCredentials: true });
      toast.success(t("inventory.control.thresholdSaved"));
      setTotpOpen(false);
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
    finally { setBusy(false); }
  };

  const statusLabel = { ok: t("inventory.control.statusOk"), bajo: t("inventory.control.statusLow"), agotado: t("inventory.control.statusOut") };

  // iter320 (IPV) — estado del conteo físico por producto.
  const COUNT_STATUS = {
    sin_conteo: { label: t("inventory.control.cstSinConteo"), cls: "text-neutral-500 border-white/10" },
    cuadra: { label: t("inventory.control.cstCuadra"), cls: "text-emerald-400 border-emerald-500/30" },
    faltante: { label: t("inventory.control.cstFaltante"), cls: "text-red-400 border-red-500/30" },
    sobrante: { label: t("inventory.control.cstSobrante"), cls: "text-amber-300 border-amber-500/30" },
    ajustado: { label: t("inventory.control.cstAjustado"), cls: "text-sky-300 border-sky-500/30" },
  };

  const saveMinStock = async (r) => {
    const raw = minDraft[r.product_id];
    const n = parseInt(raw);
    const val = (raw === "" || raw === undefined || isNaN(n)) ? null : Math.max(0, n);
    try {
      await axios.patch(`${API}/admin/inventory/products/${r.product_id}/min-stock`,
        { min_stock: val }, { withCredentials: true });
      toast.success(t("inventory.control.minSaved"));
      setMinDraft((d) => { const nd = { ...d }; delete nd[r.product_id]; return nd; });
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
  };

  const saveTargetStock = async (r) => {
    const raw = targetDraft[r.product_id];
    const n = parseInt(raw);
    const val = (raw === "" || raw === undefined || isNaN(n)) ? null : Math.max(0, n);
    try {
      await axios.patch(`${API}/admin/inventory/products/${r.product_id}/target-stock`,
        { target_stock: val }, { withCredentials: true });
      toast.success(t("inventory.control.targetSaved"));
      setTargetDraft((d) => { const nd = { ...d }; delete nd[r.product_id]; return nd; });
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
  };

  const saveCount = async (r) => {
    const raw = countDraft[r.product_id] !== undefined ? countDraft[r.product_id] : r.counted_qty;
    if (raw === "" || raw === null || raw === undefined) return;
    const qty = parseInt(raw);
    if (isNaN(qty) || qty < 0) return toast.error(t("inventory.control.countPlaceholder"));
    try {
      await axios.post(`${API}/admin/inventory/counts`, { product_id: r.product_id, counted_qty: qty, note: "" }, { withCredentials: true });
      toast.success(t("inventory.control.countSaved"));
      setCountDraft((d) => { const n = { ...d }; delete n[r.product_id]; return n; });
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
  };

  const clearCount = async (r) => {
    try {
      await axios.delete(`${API}/admin/inventory/counts/${r.product_id}`, { withCredentials: true });
      toast.success(t("inventory.control.countCleared"));
      setCountDraft((d) => { const n = { ...d }; delete n[r.product_id]; return n; });
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
  };

  const doAdjust = async () => {
    if (!adjust?.row?.count_id) return;
    if (!adjust.document || adjust.document.trim().length < 2) return toast.error(t("inventory.control.adjustDocHint"));
    setAdjustBusy(true);
    try {
      await axios.post(`${API}/admin/inventory/counts/${adjust.row.count_id}/adjust`, { document: adjust.document.trim(), note: adjust.note || "" }, { withCredentials: true });
      toast.success(t("inventory.control.adjustDone"));
      setAdjust(null);
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
    finally { setAdjustBusy(false); }
  };

  const onProductPhoto = (file) => {
    if (!file) return;
    if (file.size > 4 * 1024 * 1024) return toast.error(t("inventory.control.photoTooBig"));
    const reader = new FileReader();
    reader.onload = () => setProd((f) => ({ ...f, image_url: reader.result }));
    reader.readAsDataURL(file);
  };

  const dupMatch = mode === "new" && prod.name.trim().length >= 2
    ? rows.find((r) => norm(r.name) === norm(prod.name)) : null;

  const createProduct = async () => {
    if (!prod.name || prod.name.trim().length < 2) return toast.error(t("inventory.control.nameRequired"));
    if (dupMatch) return toast.error(t("inventory.control.duplicateWarning", { name: dupMatch.name }));
    const price = parseFloat(prod.price_usd);
    if (!price || price <= 0) return toast.error(t("inventory.control.priceRequired"));
    setAddBusy(true);
    try {
      await axios.post(`${API}/admin/products`, {
        name: prod.name.trim(),
        description: "",
        image_url: prod.image_url,
        price_usd: price,
        cost_usd: parseFloat(prod.cost_usd) || 0,
        stock: parseInt(prod.stock) || 0,
        category: prod.category.trim() || "mercadito",
        is_active: prod.is_active,
        min_stock: prod.min_stock === "" ? null : (parseInt(prod.min_stock) >= 0 ? parseInt(prod.min_stock) : null),
        target_stock: prod.target_stock === "" ? null : (parseInt(prod.target_stock) >= 0 ? parseInt(prod.target_stock) : null),
      }, { withCredentials: true });
      toast.success(t("inventory.control.productCreated"));
      setAddOpen(false); setProd(emptyProduct);
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
    finally { setAddBusy(false); }
  };

  const saveRestock = async () => {
    if (!restock.product_id) return toast.error(t("inventory.control.restockProductRequired"));
    const qty = parseInt(restock.quantity);
    if (!qty || qty <= 0) return toast.error(t("inventory.control.restockQtyRequired"));
    setAddBusy(true);
    try {
      const payload = { product_id: restock.product_id, type: "entrada", quantity: qty, note: restock.note };
      if (restock.unit_cost !== "") payload.unit_cost = parseFloat(restock.unit_cost);
      if (restock.sale_price !== "") payload.sale_price = parseFloat(restock.sale_price);
      await axios.post(`${API}/admin/inventory/movements`, payload, { withCredentials: true });
      toast.success(t("inventory.control.restockSaved"));
      setAddOpen(false); setRestock(emptyRestock); setMode("new"); setProd(emptyProduct);
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
    finally { setAddBusy(false); }
  };

  const toggleActive = async (r) => {
    try {
      await axios.post(`${API}/admin/products/${r.product_id}/toggle-active`, {}, { withCredentials: true });
      toast.success(r.is_active ? t("inventory.control.hiddenToast") : t("inventory.control.publishedToast"));
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
  };

  const removeProduct = async (r) => {
    if (!window.confirm(t("inventory.control.confirmDelete", { name: r.name }))) return;
    try {
      await axios.delete(`${API}/admin/products/${r.product_id}`, { withCredentials: true });
      toast.success(t("inventory.control.productDeleted"));
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
  };

  const visible = rows.filter((r) => !query.trim() || norm(r.name).includes(norm(query)) || norm(r.category).includes(norm(query)));

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div className="relative w-full sm:w-[320px]">
          <Search className="w-4 h-4 text-neutral-500 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
          <Input
            data-testid="inventory-search-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("inventory.control.searchPlaceholder")}
            className="rounded-none pl-9 bg-[#0a0a0a] border-white/10 h-10"
          />
        </div>
        <div className="flex items-center gap-3">
          {query.trim() && (
            <span className="text-xs text-neutral-500" data-testid="inventory-search-count">
              {t("inventory.control.searchCount", { count: visible.length })}
            </span>
          )}
          <Button data-testid="add-inventory-product-btn" onClick={() => { setProd(emptyProduct); setRestock(emptyRestock); setMode("new"); setAddOpen(true); }}
            className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none h-10">
            <Plus className="w-4 h-4 mr-1" /> {t("inventory.control.addProductBtn")}
          </Button>
        </div>
      </div>
      {isAdmin && (
        <div className="flex items-end gap-2 flex-wrap" data-testid="low-stock-threshold-editor">
          <div>
            <Label className="micro-label text-neutral-500 flex items-center gap-1">
              <BellRing className="w-3 h-3 text-amber-300" /> {t("inventory.control.thresholdLabel")}
            </Label>
            <Input data-testid="low-stock-threshold-input" type="number" min="0" value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono h-9 w-[110px]" />
          </div>
          <div>
            <Label className="micro-label text-neutral-500">{t("inventory.control.storeCurrencyLabel")}</Label>
            <select data-testid="store-currency-select" value={storeCurrency}
              onChange={(e) => setStoreCurrency(e.target.value)}
              className="block h-9 mt-1 bg-[#0a0a0a] border border-white/10 text-sm px-2 text-white w-[180px]">
              <option value="">{t("inventory.control.storeCurrencyAuto")}</option>
              {currencies.map((c) => <option key={c.code} value={c.code}>{`${c.code} — ${c.name}`}</option>)}
            </select>
          </div>
          <Button data-testid="low-stock-threshold-save" onClick={() => setTotpOpen(true)}
            className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none h-9">
            {t("inventory.control.thresholdSave")}
          </Button>
          <p className="text-[0.65rem] text-neutral-500 pb-2 max-w-[420px]">{t("inventory.control.thresholdHint")} {t("inventory.control.fxHint")}</p>
        </div>
      )}
      <div className="tactile-card overflow-auto max-h-[65vh]" data-testid="inventory-control-table">
      <p className="text-[0.65rem] text-neutral-500 px-4 pt-3" data-testid="inventory-count-hint">{t("inventory.control.countHint")}</p>
      <table className="w-full text-sm min-w-[1180px]">
        <thead className="border-b border-white/10 bg-[#0a0a0a] sticky top-0 z-10">
          <tr className="text-left">
            <th className="px-4 py-3 micro-label text-neutral-500">{t("inventory.control.product")}</th>
            <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.control.stock")}</th>
            <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.control.colMin")}</th>
            <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.control.colTarget")}</th>
            <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.control.price")}</th>
            <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.control.cost")}</th>
            <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.control.entries")}</th>
            <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.control.sales")}</th>
            <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.control.invValue")}</th>
            <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.control.soldToday")}</th>
            <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.control.revenueToday")}</th>
            <th className="px-4 py-3 micro-label text-neutral-500">{t("inventory.control.colCount")}</th>
            <th className="px-4 py-3 micro-label text-neutral-500">{t("inventory.control.colDiff")}</th>
            <th className="px-4 py-3 micro-label text-neutral-500">{t("inventory.control.status")}</th>
            <th className="px-4 py-3 micro-label text-neutral-500">{t("inventory.control.actions")}</th>
          </tr>
        </thead>
        <tbody>
          {loading && (
            <tr><td colSpan="15" className="text-center text-neutral-500 py-8">…</td></tr>
          )}
          {!loading && rows.length === 0 && (
            <tr><td colSpan="15" className="text-center text-neutral-500 py-8">{t("inventory.control.empty")}</td></tr>
          )}
          {!loading && rows.length > 0 && visible.length === 0 && (
            <tr><td colSpan="15" className="text-center text-neutral-500 py-8" data-testid="inventory-search-empty">{t("inventory.control.searchEmpty")}</td></tr>
          )}
          {visible.map((r) => (
            <tr key={r.product_id} className="border-b border-white/5" data-testid={`inventory-row-${r.product_id}`}>
              <td className="px-4 py-3">
                {r.name}
                {!r.is_active && <span className="ml-2 text-[0.6rem] uppercase text-neutral-500">({t("inventory.control.inactive")})</span>}
              </td>
              <td className="px-4 py-3 font-mono text-right" data-testid={`inventory-stock-${r.product_id}`}>{r.stock}</td>
              <td className="px-4 py-3 text-right" data-testid={`inventory-min-cell-${r.product_id}`}>
                <input type="number" min="0"
                  data-testid={`inventory-min-input-${r.product_id}`}
                  value={minDraft[r.product_id] !== undefined ? minDraft[r.product_id] : (r.min_stock ?? "")}
                  onChange={(e) => setMinDraft((d) => ({ ...d, [r.product_id]: e.target.value }))}
                  onKeyDown={(e) => { if (e.key === "Enter") saveMinStock(r); }}
                  onBlur={() => { if (minDraft[r.product_id] !== undefined) saveMinStock(r); }}
                  placeholder={String(threshold || 5)}
                  title={t("inventory.control.minHint")}
                  className="w-16 h-8 bg-[#0a0a0a] border border-white/10 text-sm px-2 text-white font-mono text-right" />
              </td>
              <td className="px-4 py-3 text-right" data-testid={`inventory-target-cell-${r.product_id}`}>
                <input type="number" min="0"
                  data-testid={`inventory-target-input-${r.product_id}`}
                  value={targetDraft[r.product_id] !== undefined ? targetDraft[r.product_id] : (r.target_stock ?? "")}
                  onChange={(e) => setTargetDraft((d) => ({ ...d, [r.product_id]: e.target.value }))}
                  onKeyDown={(e) => { if (e.key === "Enter") saveTargetStock(r); }}
                  onBlur={() => { if (targetDraft[r.product_id] !== undefined) saveTargetStock(r); }}
                  placeholder="—"
                  title={t("inventory.control.targetHint")}
                  className="w-16 h-8 bg-[#0a0a0a] border border-white/10 text-sm px-2 text-white font-mono text-right" />
              </td>
              <td className="px-4 py-3 font-mono text-right text-[#8B5CF6]">{fmt(r.price_usd)}</td>
              <td className="px-4 py-3 font-mono text-right text-neutral-400">{fmt(r.cost_usd)}</td>
              <td className="px-4 py-3 font-mono text-right text-emerald-400">{r.entradas}</td>
              <td className="px-4 py-3 font-mono text-right text-amber-300">{r.ventas}</td>
              <td className="px-4 py-3 font-mono text-right">{fmt(r.inventory_value)}</td>
              <td className="px-4 py-3 font-mono text-right">{r.sold_today}</td>
              <td className="px-4 py-3 font-mono text-right">{fmt(r.revenue_today)}</td>
              <td className="px-4 py-3" data-testid={`inventory-count-cell-${r.product_id}`}>
                {r.count_authorized ? (
                  <span className="text-xs text-sky-300 font-mono">{r.counted_qty}</span>
                ) : (
                  <div className="flex items-center gap-1">
                    <input type="number" min="0"
                      data-testid={`inventory-count-input-${r.product_id}`}
                      value={countDraft[r.product_id] !== undefined ? countDraft[r.product_id] : (r.counted_qty ?? "")}
                      onChange={(e) => setCountDraft((d) => ({ ...d, [r.product_id]: e.target.value }))}
                      onKeyDown={(e) => { if (e.key === "Enter") saveCount(r); }}
                      placeholder={t("inventory.control.countPlaceholder")}
                      className="w-16 h-8 bg-[#0a0a0a] border border-white/10 text-sm px-2 text-white font-mono" />
                    <button data-testid={`inventory-count-save-${r.product_id}`} onClick={() => saveCount(r)}
                      title={t("inventory.control.countSave")} className="text-neutral-400 hover:text-emerald-400">
                      <Check className="w-4 h-4" />
                    </button>
                    {r.counted_qty !== null && r.counted_qty !== undefined && (
                      <button data-testid={`inventory-count-clear-${r.product_id}`} onClick={() => clearCount(r)}
                        title={t("inventory.control.countClear")} className="text-neutral-400 hover:text-red-400">
                        <X className="w-4 h-4" />
                      </button>
                    )}
                  </div>
                )}
              </td>
              <td className="px-4 py-3" data-testid={`inventory-diff-${r.product_id}`}>
                {(() => {
                  const st = COUNT_STATUS[r.count_status] || COUNT_STATUS.sin_conteo;
                  const showNum = r.count_status === "faltante" || r.count_status === "sobrante";
                  return (
                    <span className={`text-[0.65rem] uppercase tracking-wider px-2 py-0.5 border whitespace-nowrap ${st.cls}`} data-testid={`inventory-count-status-${r.product_id}`}>
                      {st.label}{showNum ? ` ${r.count_difference > 0 ? "+" : ""}${r.count_difference}` : ""}
                    </span>
                  );
                })()}
              </td>
              <td className="px-4 py-3">
                <span className={`text-[0.65rem] uppercase tracking-wider px-2 py-0.5 border ${STATUS_STYLES[r.estado]}`} data-testid={`inventory-status-${r.product_id}`}>
                  {statusLabel[r.estado]}
                </span>
              </td>
              <td className="px-4 py-3">
                <div className="flex gap-2">
                  {isAdmin && r.count_status !== "sin_conteo" && r.count_difference !== 0 && !r.count_authorized && (
                    <button
                      onClick={() => setAdjust({ row: r, document: "", note: "" })}
                      data-testid={`inventory-adjust-${r.product_id}`}
                      className="text-neutral-400 hover:text-sky-300"
                      title={t("inventory.control.adjustAction")}
                    >
                      <Wrench className="w-4 h-4" />
                    </button>
                  )}
                  <button
                    onClick={() => toggleActive(r)}
                    data-testid={`inventory-toggle-${r.product_id}`}
                    className="text-neutral-400 hover:text-emerald-400"
                    title={r.is_active ? t("inventory.control.hideAction") : t("inventory.control.publishAction")}
                  >
                    {r.is_active ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
                  </button>
                  <button
                    onClick={() => removeProduct(r)}
                    data-testid={`inventory-delete-${r.product_id}`}
                    className="text-neutral-400 hover:text-[#EF4444]"
                    title={t("inventory.control.deleteAction")}
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      <TotpPromptDialog
        open={totpOpen}
        busy={busy}
        title={t("inventory.control.totpTitle")}
        description={t("inventory.control.totpDesc")}
        onCancel={() => setTotpOpen(false)}
        onConfirm={saveThreshold}
      />

      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-display">
              {mode === "restock" ? t("inventory.control.restockTitle") : t("inventory.control.addProductTitle")}
            </DialogTitle>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-2" data-testid="add-product-mode-toggle">
            <button
              data-testid="mode-new-product"
              onClick={() => setMode("new")}
              className={`h-9 text-xs uppercase tracking-wider border transition-colors ${mode === "new" ? "bg-[#8B5CF6] border-[#8B5CF6] text-white" : "bg-transparent border-white/15 text-neutral-400 hover:text-white"}`}
            >
              {t("inventory.control.modeNew")}
            </button>
            <button
              data-testid="mode-restock"
              onClick={() => setMode("restock")}
              className={`h-9 text-xs uppercase tracking-wider border transition-colors ${mode === "restock" ? "bg-[#8B5CF6] border-[#8B5CF6] text-white" : "bg-transparent border-white/15 text-neutral-400 hover:text-white"}`}
            >
              {t("inventory.control.modeRestock")}
            </button>
          </div>
          {mode === "restock" ? (
            <div className="space-y-3" data-testid="restock-form">
              <p className="text-xs text-neutral-400">{t("inventory.control.restockHint")}</p>
              <div>
                <Label className="micro-label text-neutral-500">{t("inventory.control.restockProduct")}</Label>
                <select
                  data-testid="restock-product-select"
                  value={restock.product_id}
                  onChange={(e) => setRestock({ ...restock, product_id: e.target.value })}
                  className="w-full h-10 mt-1 bg-[#0a0a0a] border border-white/10 text-sm px-3 text-white"
                >
                  <option value="">—</option>
                  {rows.map((r) => <option key={r.product_id} value={r.product_id}>{`${r.name} (stock ${r.stock})`}</option>)}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="micro-label text-neutral-500">{t("inventory.control.restockQty")}</Label>
                  <Input data-testid="restock-qty" type="number" min="1" value={restock.quantity} onChange={(e) => setRestock({ ...restock, quantity: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
                </div>
                <div>
                  <Label className="micro-label text-neutral-500">{t("inventory.control.restockCost")}</Label>
                  <Input data-testid="restock-cost" type="number" step="any" min="0" value={restock.unit_cost} placeholder={t("inventory.movements.defaultFromProduct")} onChange={(e) => setRestock({ ...restock, unit_cost: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
                </div>
              </div>
              <div>
                <Label className="micro-label text-neutral-500">{t("inventory.control.restockSalePrice")}</Label>
                <Input data-testid="restock-sale-price" type="number" step="any" min="0" value={restock.sale_price} placeholder={t("inventory.movements.salePriceHint")} onChange={(e) => setRestock({ ...restock, sale_price: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
              </div>
              <div>
                <Label className="micro-label text-neutral-500">{t("inventory.control.restockNote")}</Label>
                <Input data-testid="restock-note" value={restock.note} onChange={(e) => setRestock({ ...restock, note: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
              <Button data-testid="restock-save-btn" onClick={saveRestock} disabled={addBusy} className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-11">
                {addBusy ? "…" : t("inventory.control.restockSave")}
              </Button>
            </div>
          ) : (
          <div className="space-y-3">
            <div>
              <Label className="micro-label text-neutral-500">{t("inventory.control.formName")}</Label>
              <Input data-testid="inv-product-name" value={prod.name} onChange={(e) => setProd({ ...prod, name: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            {dupMatch && (
              <div className="border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-200" data-testid="duplicate-product-warning">
                {t("inventory.control.duplicateWarning", { name: dupMatch.name })}
                <button
                  data-testid="duplicate-switch-btn"
                  onClick={() => { setMode("restock"); setRestock((f) => ({ ...f, product_id: dupMatch.product_id })); }}
                  className="block mt-2 underline text-amber-300 hover:text-amber-100"
                >
                  {t("inventory.control.duplicateSwitchBtn")}
                </button>
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="micro-label text-neutral-500">{t("inventory.control.formPrice")}</Label>
                <Input data-testid="inv-product-price" type="number" step="any" min="0" value={prod.price_usd} onChange={(e) => setProd({ ...prod, price_usd: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
              </div>
              <div>
                <Label className="micro-label text-neutral-500">{t("inventory.control.formCost")}</Label>
                <Input data-testid="inv-product-cost" type="number" step="any" min="0" value={prod.cost_usd} onChange={(e) => setProd({ ...prod, cost_usd: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="micro-label text-neutral-500">{t("inventory.control.formStock")}</Label>
                <Input data-testid="inv-product-stock" type="number" min="0" value={prod.stock} onChange={(e) => setProd({ ...prod, stock: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
              </div>
              <div>
                <Label className="micro-label text-neutral-500">{t("inventory.control.formCategory")}</Label>
                <Input data-testid="inv-product-category" value={prod.category} onChange={(e) => setProd({ ...prod, category: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("inventory.control.formMinStock")}</Label>
              <Input data-testid="inv-product-min-stock" type="number" min="0" value={prod.min_stock}
                onChange={(e) => setProd({ ...prod, min_stock: e.target.value })}
                placeholder={t("inventory.control.formMinStockHint")}
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("inventory.control.formTargetStock")}</Label>
              <Input data-testid="inv-product-target-stock" type="number" min="0" value={prod.target_stock}
                onChange={(e) => setProd({ ...prod, target_stock: e.target.value })}
                placeholder={t("inventory.control.formTargetStockHint")}
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("inventory.control.formPhoto")}</Label>
              <input data-testid="inv-product-photo" type="file" accept="image/*" onChange={(e) => onProductPhoto(e.target.files?.[0])}
                className="mt-1 block w-full text-xs text-neutral-400 file:mr-3 file:px-3 file:py-2 file:border-0 file:bg-[#8B5CF6] file:text-white file:text-xs" />
              {prod.image_url && <img src={prod.image_url} alt="preview" className="mt-2 h-20 object-cover border border-white/10" />}
            </div>
            <div className="flex items-center gap-3">
              <Switch data-testid="inv-product-active" checked={prod.is_active} onCheckedChange={(v) => setProd({ ...prod, is_active: v })} />
              <span className="text-sm">{t("inventory.control.formActive")}</span>
            </div>
            <Button data-testid="inv-product-save" onClick={createProduct} disabled={addBusy} className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-11">
              {addBusy ? "…" : t("inventory.control.formSave")}
            </Button>
          </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={!!adjust} onOpenChange={(v) => !v && setAdjust(null)}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto" data-testid="count-adjust-dialog">
          <DialogHeader>
            <DialogTitle className="font-display">{t("inventory.control.adjustTitle")}</DialogTitle>
          </DialogHeader>
          {adjust && (
            <div className="space-y-3">
              <p className="text-xs text-neutral-400">
                {t("inventory.control.adjustDesc", { name: adjust.row.name, diff: `${adjust.row.count_difference > 0 ? "+" : ""}${adjust.row.count_difference}` })}
              </p>
              <div>
                <Label className="micro-label text-neutral-500">{t("inventory.control.adjustDoc")}</Label>
                <Input data-testid="count-adjust-document" value={adjust.document}
                  onChange={(e) => setAdjust((a) => ({ ...a, document: e.target.value }))}
                  placeholder={t("inventory.control.adjustDocHint")}
                  className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
              <div>
                <Label className="micro-label text-neutral-500">{t("inventory.control.adjustNote")}</Label>
                <Input data-testid="count-adjust-note" value={adjust.note}
                  onChange={(e) => setAdjust((a) => ({ ...a, note: e.target.value }))}
                  className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
              <Button data-testid="count-adjust-confirm" onClick={doAdjust} disabled={adjustBusy}
                className="w-full bg-sky-700 hover:bg-sky-600 text-white font-bold rounded-none h-11">
                {adjustBusy ? "…" : t("inventory.control.adjustConfirm")}
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
