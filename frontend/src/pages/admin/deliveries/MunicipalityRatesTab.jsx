import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import { Plus, Trash2, Save, Layers, LoaderCircle } from "lucide-react";

// iter211 — Tarifas fijas de mensajería por municipio (fallback cuando el
// mapa no ubica la dirección del cliente). Editable por admin/staff con
// permiso de Mensajería.

function RateRow({ r, onSaved, onDeleted }) {
  const { t } = useTranslation();
  const [price, setPrice] = useState(String(r.price_usdt));
  const [aliases, setAliases] = useState((r.aliases || []).join(", "));
  const [busy, setBusy] = useState(false);

  const dirty = price !== String(r.price_usdt)
    || aliases !== (r.aliases || []).join(", ");

  const save = async (extra = {}) => {
    setBusy(true);
    try {
      await axios.put(`${API}/admin/courier/municipality-rates/${r.id}`,
        { price_usdt: parseFloat(price), aliases, ...extra },
        { withCredentials: true });
      toast.success(t("admin.deliveries.muniRates.saved"));
      onSaved();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(t("admin.deliveries.muniRates.deleteConfirm", { name: r.municipality }))) return;
    try {
      await axios.delete(`${API}/admin/courier/municipality-rates/${r.id}`,
        { withCredentials: true });
      toast.success(t("admin.deliveries.muniRates.deleted"));
      onDeleted();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    }
  };

  return (
    <tr className={`border-b border-white/5 ${r.active ? "" : "opacity-50"}`} data-testid={`muni-rate-row-${r.id}`}>
      <td className="px-3 py-2.5 text-sm text-neutral-400" data-testid={`muni-province-${r.id}`}>{r.province || "La Habana"}</td>
      <td className="px-3 py-2.5 text-sm">{r.municipality}</td>
      <td className="px-3 py-2.5">
        <Input
          value={aliases}
          onChange={(e) => setAliases(e.target.value)}
          placeholder={t("admin.deliveries.muniRates.aliasesPlaceholder")}
          data-testid={`muni-aliases-${r.id}`}
          className="rounded-none bg-[#0a0a0a] border-white/10 h-8 text-xs"
        />
      </td>
      <td className="px-3 py-2.5 w-28">
        <Input
          type="number"
          min="0.5"
          step="0.5"
          value={price}
          onChange={(e) => setPrice(e.target.value)}
          data-testid={`muni-price-${r.id}`}
          className="rounded-none bg-[#0a0a0a] border-white/10 h-8 font-mono text-xs w-24"
        />
      </td>
      <td className="px-3 py-2.5">
        <Switch
          checked={!!r.active}
          onCheckedChange={(v) => save({ active: v })}
          data-testid={`muni-active-${r.id}`}
        />
      </td>
      <td className="px-3 py-2.5 text-right whitespace-nowrap">
        <Button
          size="sm"
          disabled={!dirty || busy}
          onClick={() => save()}
          data-testid={`muni-save-${r.id}`}
          className="bg-[#22C55E] text-black rounded-none h-7 text-xs mr-1.5 disabled:opacity-30"
        >
          <Save className="w-3 h-3" />
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={remove}
          data-testid={`muni-delete-${r.id}`}
          className="border-[#EF4444]/40 text-[#EF4444] rounded-none h-7 text-xs hover:bg-[#EF4444]/10"
        >
          <Trash2 className="w-3 h-3" />
        </Button>
      </td>
    </tr>
  );
}

// Prop. Tarifa-Municipio — "Añadir provincia completa": el admin elige una
// provincia del catálogo de Cuba, ve todos sus municipios y pone el precio de
// entrega de cada uno (uno a uno). Los que deje en blanco no se activan. Los ya
// configurados aparecen prellenados y se actualizan al guardar.
function BulkProvinceDialog({ onDone }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [provinces, setProvinces] = useState([]);
  const [province, setProvince] = useState("");
  const [munis, setMunis] = useState(null);
  const [prices, setPrices] = useState({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const onOpenChange = async (v) => {
    setOpen(v);
    if (v && provinces.length === 0) {
      try {
        const r = await axios.get(`${API}/admin/courier/province-catalog`, { withCredentials: true });
        setProvinces(r.data?.provinces || []);
      } catch { setProvinces([]); }
    }
    if (!v) { setProvince(""); setMunis(null); setPrices({}); }
  };

  const pickProvince = async (p) => {
    setProvince(p); setMunis(null); setPrices({}); setLoading(true);
    try {
      const r = await axios.get(`${API}/admin/courier/province-catalog/municipalities`, {
        params: { province: p }, withCredentials: true,
      });
      const list = r.data?.municipalities || [];
      setMunis(list);
      const init = {};
      list.forEach((m) => { if (m.configured && m.price_usdt != null) init[m.municipality] = String(m.price_usdt); });
      setPrices(init);
    } catch { setMunis([]); } finally { setLoading(false); }
  };

  const setPrice = (name, val) => setPrices((prev) => ({ ...prev, [name]: val }));

  const items = (munis || [])
    .map((m) => ({ municipality: m.municipality, price_usdt: parseFloat(prices[m.municipality]) }))
    .filter((it) => it.price_usdt > 0);

  const save = async () => {
    if (items.length === 0) { toast.error(t("admin.deliveries.muniRates.bulkNothing")); return; }
    setSaving(true);
    try {
      const r = await axios.post(`${API}/admin/courier/municipality-rates/bulk`,
        { province, items }, { withCredentials: true });
      toast.success(t("admin.deliveries.muniRates.bulkSaved", {
        created: r.data?.created || 0, updated: r.data?.updated || 0,
      }));
      onOpenChange(false);
      onDone();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    } finally { setSaving(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button data-testid="muni-bulk-open-btn" className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none h-9 text-xs shrink-0">
          <Layers className="w-4 h-4 mr-1.5" /> {t("admin.deliveries.muniRates.bulkBtn")}
        </Button>
      </DialogTrigger>
      <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto sm:max-w-lg" data-testid="muni-bulk-dialog">
        <DialogHeader>
          <DialogTitle className="font-display">{t("admin.deliveries.muniRates.bulkTitle")}</DialogTitle>
        </DialogHeader>
        <p className="text-xs text-neutral-400">{t("admin.deliveries.muniRates.bulkIntro")}</p>

        <div>
          <label className="micro-label text-neutral-500">{t("admin.deliveries.muniRates.bulkProvinceLabel")}</label>
          <Select value={province} onValueChange={pickProvince}>
            <SelectTrigger data-testid="muni-bulk-province" className="h-10 rounded-none mt-1 bg-[#0a0a0a] border-white/10 text-sm">
              <SelectValue placeholder={t("admin.deliveries.muniRates.bulkProvincePlaceholder")} />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white max-h-64">
              {provinces.map((p) => (<SelectItem key={p} value={p} data-testid={`muni-bulk-prov-opt-${p}`}>{p}</SelectItem>))}
            </SelectContent>
          </Select>
        </div>

        {loading && (
          <div className="flex items-center gap-2 text-sm text-neutral-500 py-6" data-testid="muni-bulk-loading">
            <LoaderCircle className="w-4 h-4 animate-spin" /> {t("admin.deliveries.muniRates.bulkLoading")}
          </div>
        )}

        {!loading && munis && munis.length > 0 && (
          <div className="border border-white/10 divide-y divide-white/5 max-h-[45vh] overflow-y-auto" data-testid="muni-bulk-list">
            {munis.map((m) => (
              <div key={m.municipality} className="px-3 py-2 flex items-center justify-between gap-3" data-testid={`muni-bulk-row-${m.municipality}`}>
                <span className="text-sm text-neutral-200 flex-1">
                  {m.municipality}
                  {m.configured && (
                    <span className="ml-2 text-[0.6rem] uppercase tracking-wider px-1.5 py-0.5 bg-emerald-500/10 text-emerald-300 border border-emerald-500/20" data-testid={`muni-bulk-configured-${m.municipality}`}>
                      {t("admin.deliveries.muniRates.bulkConfigured")}
                    </span>
                  )}
                </span>
                <Input
                  type="number" min="0.5" step="0.5"
                  value={prices[m.municipality] || ""}
                  onChange={(e) => setPrice(m.municipality, e.target.value)}
                  placeholder={t("admin.deliveries.muniRates.bulkPricePlaceholder")}
                  data-testid={`muni-bulk-price-${m.municipality}`}
                  className="rounded-none bg-[#0a0a0a] border-white/10 h-8 font-mono text-xs w-28"
                />
              </div>
            ))}
          </div>
        )}

        <DialogFooter>
          <Button
            onClick={save}
            disabled={saving || items.length === 0}
            data-testid="muni-bulk-save-btn"
            className="bg-[#22C55E] text-black rounded-none h-10 disabled:opacity-30"
          >
            {saving ? <LoaderCircle className="w-4 h-4 animate-spin mr-1.5" /> : <Save className="w-4 h-4 mr-1.5" />}
            {t("admin.deliveries.muniRates.bulkSave", { count: items.length })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function MunicipalityRatesTab() {
  const { t } = useTranslation();
  const [rows, setRows] = useState([]);
  const [newName, setNewName] = useState("");
  const [newProvince, setNewProvince] = useState("La Habana");
  const [newPrice, setNewPrice] = useState("");

  const load = useCallback(() => {
    axios.get(`${API}/admin/courier/municipality-rates`, { withCredentials: true })
      .then((r) => setRows(r.data)).catch(() => setRows([]));
  }, []);

  useEffect(() => { load(); }, [load]);

  const add = async () => {
    try {
      await axios.post(`${API}/admin/courier/municipality-rates`,
        { municipality: newName.trim(), province: newProvince.trim() || "La Habana", price_usdt: parseFloat(newPrice) },
        { withCredentials: true });
      toast.success(t("admin.deliveries.muniRates.created"));
      setNewName(""); setNewPrice("");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    }
  };

  return (
    <div className="space-y-4" data-testid="muni-rates-tab">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <p className="text-xs text-neutral-400 max-w-2xl">
          {t("admin.deliveries.muniRates.hint")}
        </p>
        <BulkProvinceDialog onDone={load} />
      </div>

      <div className="tactile-card p-4 flex flex-wrap items-end gap-2">
        <div className="w-40">
          <label className="micro-label text-neutral-500">{t("admin.deliveries.muniRates.colProvince")}</label>
          <Input
            value={newProvince}
            onChange={(e) => setNewProvince(e.target.value)}
            placeholder={t("admin.deliveries.muniRates.provincePlaceholder")}
            data-testid="muni-new-province"
            className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10"
          />
        </div>
        <div className="flex-1 min-w-[180px]">
          <label className="micro-label text-neutral-500">{t("admin.deliveries.muniRates.colMunicipality")}</label>
          <Input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder={t("admin.deliveries.muniRates.addPlaceholder")}
            data-testid="muni-new-name"
            className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10"
          />
        </div>
        <div className="w-32">
          <label className="micro-label text-neutral-500">{t("admin.deliveries.muniRates.colPrice")}</label>
          <Input
            type="number"
            min="0.5"
            step="0.5"
            value={newPrice}
            onChange={(e) => setNewPrice(e.target.value)}
            data-testid="muni-new-price"
            className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10 font-mono"
          />
        </div>
        <Button
          onClick={add}
          disabled={newName.trim().length < 3 || !(parseFloat(newPrice) > 0)}
          data-testid="muni-add-btn"
          className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none h-10 disabled:opacity-30"
        >
          <Plus className="w-4 h-4 mr-1.5" /> {t("admin.deliveries.muniRates.addBtn")}
        </Button>
      </div>

      <div className="tactile-card overflow-x-auto">
        <table className="w-full text-sm min-w-[720px]">
          <thead className="border-b border-white/10 bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.deliveries.muniRates.colProvince")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.deliveries.muniRates.colMunicipality")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.deliveries.muniRates.colAliases")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.deliveries.muniRates.colPrice")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.deliveries.muniRates.colActive")}</th>
              <th className="px-3 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan="6" className="text-center text-neutral-500 py-8">…</td></tr>
            )}
            {rows.map((r) => (
              <RateRow key={`${r.id}-${r.price_usdt}-${r.active}`} r={r} onSaved={load} onDeleted={load} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
