import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Search, Printer } from "lucide-react";
import { toast } from "sonner";

const norm = (s) => (s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");

// iter228 — etiquetas imprimibles con código de barras (PDF A4, rejilla 3×8).
export default function LabelsDialog({ open, onOpenChange }) {
  const { t } = useTranslation();
  const [rows, setRows] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [query, setQuery] = useState("");
  const [copies, setCopies] = useState(1);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    axios.get(`${API}/admin/inventory/control`, { withCredentials: true })
      .then((r) => {
        setRows(r.data);
        setSelected(new Set(r.data.filter((x) => !x.barcode).map((x) => x.product_id)));
      })
      .catch(() => {});
    setQuery("");
    setCopies(1);
  }, [open]);

  const visible = useMemo(
    () => rows.filter((r) => !query.trim() || norm(r.name).includes(norm(query))),
    [rows, query]
  );

  const toggle = (id) => {
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });
  };

  const allVisibleSelected = visible.length > 0 && visible.every((r) => selected.has(r.product_id));
  const toggleAllVisible = () => {
    setSelected((s) => {
      const n = new Set(s);
      visible.forEach((r) => (allVisibleSelected ? n.delete(r.product_id) : n.add(r.product_id)));
      return n;
    });
  };

  const generate = async () => {
    const ids = [...selected];
    if (!ids.length) return toast.error(t("inventory.labels.nothingSelected"));
    setBusy(true);
    try {
      const missing = rows.filter((r) => selected.has(r.product_id) && !r.barcode).map((r) => r.product_id);
      if (missing.length) {
        await axios.post(`${API}/admin/inventory/barcode/generate`,
          { product_ids: missing }, { withCredentials: true });
      }
      const r = await axios.get(`${API}/admin/inventory/labels.pdf`, {
        params: { product_ids: ids.join(","), copies: parseInt(copies) || 1 },
        responseType: "blob", withCredentials: true,
      });
      const blobUrl = URL.createObjectURL(new Blob([r.data], { type: "application/pdf" }));
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = `etiquetas_${new Date().toISOString().slice(0, 10)}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(blobUrl);
      toast.success(t("inventory.labels.done"));
      onOpenChange(false);
    } catch {
      toast.error(t("inventory.labels.error"));
    } finally { setBusy(false); }
  };

  const missingCount = rows.filter((r) => selected.has(r.product_id) && !r.barcode).length;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto sm:max-w-[540px]" data-testid="labels-dialog">
        <DialogHeader><DialogTitle className="font-display">{t("inventory.labels.title")}</DialogTitle></DialogHeader>
        <p className="text-xs text-neutral-400">{t("inventory.labels.hint")}</p>
        <div className="relative">
          <Search className="w-4 h-4 text-neutral-500 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
          <Input data-testid="labels-search" value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder={t("inventory.labels.searchPlaceholder")}
            className="rounded-none pl-9 bg-[#0a0a0a] border-white/10 h-9" />
        </div>
        <div className="flex items-center justify-between text-xs">
          <button data-testid="labels-select-all" onClick={toggleAllVisible} className="underline text-neutral-400 hover:text-white">
            {allVisibleSelected ? t("inventory.labels.clearAll") : t("inventory.labels.selectAll")}
          </button>
          <span className="text-neutral-500" data-testid="labels-selected-count">
            {t("inventory.labels.selectedCount", { count: selected.size })}
          </span>
        </div>
        <div className="border border-white/10 max-h-[38vh] overflow-y-auto divide-y divide-white/5" data-testid="labels-list">
          {visible.map((r) => (
            <label key={r.product_id} className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-white/5" data-testid={`labels-row-${r.product_id}`}>
              <input type="checkbox" data-testid={`labels-checkbox-${r.product_id}`}
                checked={selected.has(r.product_id)} onChange={() => toggle(r.product_id)}
                className="accent-[#8B5CF6]" />
              <span className="flex-1 text-sm truncate">{r.name}</span>
              {r.barcode ? (
                <span className="font-mono text-[0.65rem] text-neutral-500">{r.barcode}</span>
              ) : (
                <span className="text-[0.6rem] uppercase tracking-wider px-1.5 py-0.5 border border-amber-500/30 bg-amber-500/10 text-amber-300">
                  {t("inventory.labels.noCode")}
                </span>
              )}
            </label>
          ))}
          {visible.length === 0 && (
            <p className="text-center text-neutral-500 text-sm py-6">{t("inventory.control.searchEmpty")}</p>
          )}
        </div>
        {missingCount > 0 && (
          <p className="text-xs text-amber-300" data-testid="labels-missing-note">
            {t("inventory.labels.missingNote", { count: missingCount })}
          </p>
        )}
        <div className="flex items-end gap-3">
          <div>
            <Label className="micro-label text-neutral-500">{t("inventory.labels.copies")}</Label>
            <Input data-testid="labels-copies" type="number" min="1" max="50" value={copies}
              onChange={(e) => setCopies(e.target.value)}
              className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono h-10 w-[110px]" />
          </div>
          <Button data-testid="labels-generate-btn" onClick={generate} disabled={busy}
            className="flex-1 bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-10">
            <Printer className="w-4 h-4 mr-2" /> {busy ? "…" : t("inventory.labels.generate")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
