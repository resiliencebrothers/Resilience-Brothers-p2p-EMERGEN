import { useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { BillInputs, cleanCounts, denomsTotal } from "./BillInputs";

const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });

// iter233 — arqueo: contar billetes físicos y comparar contra el sistema.
export function ArqueoDialog({ open, onOpenChange, box, fund, systemBalance, onSaved }) {
  const { t } = useTranslation();
  const [counts, setCounts] = useState({});
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const total = denomsTotal(fund, counts);
  const diff = Math.round((total - (systemBalance || 0)) * 100) / 100;

  const save = async () => {
    setBusy(true);
    try {
      const r = await axios.post(`${API}/cashbox/boxes/${box.id}/arqueos`,
        { fund, counted: cleanCounts(counts) || {}, note: note.trim() },
        { withCredentials: true });
      toast.success(r.data.status === "cuadrada"
        ? t("cashbox.arqueoSquared")
        : t("cashbox.arqueoDiff", { diff: fmt(r.data.difference), fund }));
      onOpenChange(false);
      setCounts({}); setNote("");
      onSaved();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto" data-testid="cashbox-arqueo-dialog">
        <DialogHeader>
          <DialogTitle className="font-display">{t("cashbox.arqueoTitle")} — {fund}</DialogTitle>
          <DialogDescription className="text-xs text-neutral-400">{t("cashbox.arqueoHint")}</DialogDescription>
        </DialogHeader>
        <BillInputs fund={fund} counts={counts} onChange={setCounts} testPrefix="arqueo-bills" />
        <div className="border border-white/10 p-3 font-mono text-sm space-y-1">
          <div className="flex justify-between"><span className="text-neutral-500">{t("cashbox.arqueoCounted")}:</span><span>{fmt(total)} {fund}</span></div>
          <div className="flex justify-between"><span className="text-neutral-500">{t("cashbox.arqueoSystem")}:</span><span>{fmt(systemBalance)} {fund}</span></div>
          <div className="flex justify-between" data-testid="arqueo-difference">
            <span className="text-neutral-500">{t("cashbox.arqueoDifference")}:</span>
            <span className={diff === 0 ? "text-emerald-400" : "text-red-400"}>
              {diff === 0 ? t("cashbox.squared") : `${diff > 0 ? "+" : ""}${fmt(diff)} ${fund}`}
            </span>
          </div>
        </div>
        <div>
          <Label className="micro-label text-neutral-500">{t("cashbox.arqueoNote")}</Label>
          <Input data-testid="arqueo-note" value={note} maxLength={200}
            onChange={(e) => setNote(e.target.value)}
            className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
        </div>
        <Button data-testid="arqueo-save" onClick={save} disabled={busy}
          className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-11">
          {busy ? "…" : t("cashbox.arqueoSave")}
        </Button>
      </DialogContent>
    </Dialog>
  );
}
