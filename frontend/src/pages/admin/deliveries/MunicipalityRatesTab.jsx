import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import { Plus, Trash2, Save } from "lucide-react";

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

export default function MunicipalityRatesTab() {
  const { t } = useTranslation();
  const [rows, setRows] = useState([]);
  const [newName, setNewName] = useState("");
  const [newPrice, setNewPrice] = useState("");

  const load = useCallback(() => {
    axios.get(`${API}/admin/courier/municipality-rates`, { withCredentials: true })
      .then((r) => setRows(r.data)).catch(() => setRows([]));
  }, []);

  useEffect(() => { load(); }, [load]);

  const add = async () => {
    try {
      await axios.post(`${API}/admin/courier/municipality-rates`,
        { municipality: newName.trim(), price_usdt: parseFloat(newPrice) },
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
      <p className="text-xs text-neutral-400 max-w-2xl">
        {t("admin.deliveries.muniRates.hint")}
      </p>

      <div className="tactile-card p-4 flex flex-wrap items-end gap-2">
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
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.deliveries.muniRates.colMunicipality")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.deliveries.muniRates.colAliases")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.deliveries.muniRates.colPrice")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.deliveries.muniRates.colActive")}</th>
              <th className="px-3 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan="5" className="text-center text-neutral-500 py-8">…</td></tr>
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
