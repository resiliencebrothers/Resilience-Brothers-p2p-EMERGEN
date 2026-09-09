import { useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { BillInputs, cleanCounts } from "./BillInputs";

// iter233 — nuevo/editar movimiento (entrada/salida) con desglose opcional.
export function MovementDialog({ open, onOpenChange, box, fund, editMov, onSaved }) {
  const { t } = useTranslation();
  // H01 — espejo del Fondo de Empresa: solo se completa el desglose pendiente
  const linked = !!(editMov?.source_adjustment_id || editMov?.source_withdrawal_id || editMov?.source_transfer_id);
  const [type, setType] = useState(editMov?.type || "entrada");
  const [amount, setAmount] = useState(editMov?.amount ?? "");
  const [concept, setConcept] = useState(editMov?.concept || "");
  const [responsible, setResponsible] = useState(editMov?.responsible || "");
  const [counts, setCounts] = useState(editMov?.denominations || {});
  const [busy, setBusy] = useState(false);

  const save = async () => {
    const amt = parseFloat(amount);
    if (!linked) {
      if (!amt || amt <= 0) return toast.error(t("cashbox.amountRequired"));
      if (!concept.trim()) return toast.error(t("cashbox.conceptRequired"));
    }
    setBusy(true);
    try {
      const payload = linked
        ? { denominations: cleanCounts(counts) }
        : {
            amount: amt, concept: concept.trim(), responsible: responsible.trim(),
            denominations: cleanCounts(counts),
          };
      if (editMov) {
        await axios.put(`${API}/cashbox/boxes/${box.id}/movimientos/${editMov.id}`,
          payload, { withCredentials: true });
      } else {
        await axios.post(`${API}/cashbox/boxes/${box.id}/movimientos`,
          { ...payload, fund, type }, { withCredentials: true });
      }
      toast.success(t("cashbox.movementSaved"));
      onOpenChange(false);
      onSaved();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto" data-testid="cashbox-movement-dialog">
        <DialogHeader>
          <DialogTitle className="font-display">
            {editMov ? t("cashbox.editMovement") : t("cashbox.newMovement")} — {fund}
          </DialogTitle>
          <DialogDescription className="text-xs text-neutral-400">
            {linked ? t("cashbox.linkedDenomsOnly") : t("cashbox.billsOptionalHint")}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          {!editMov && (
            <div className="grid grid-cols-2 gap-2">
              <button data-testid="cashbox-type-entrada" onClick={() => setType("entrada")}
                className={`h-10 text-xs uppercase tracking-wider border transition-colors ${type === "entrada" ? "bg-emerald-500/20 border-emerald-400 text-emerald-300" : "border-white/15 text-neutral-400"}`}>
                {t("cashbox.entrada")}
              </button>
              <button data-testid="cashbox-type-salida" onClick={() => setType("salida")}
                className={`h-10 text-xs uppercase tracking-wider border transition-colors ${type === "salida" ? "bg-red-500/20 border-red-400 text-red-300" : "border-white/15 text-neutral-400"}`}>
                {t("cashbox.salida")}
              </button>
            </div>
          )}
          <div>
            <Label className="micro-label text-neutral-500">{t("cashbox.amount")} ({fund})</Label>
            <Input data-testid="cashbox-mov-amount" type="number" step="any" min="0" value={amount}
              disabled={linked}
              onChange={(e) => setAmount(e.target.value)}
              className={`rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono ${linked ? "opacity-60" : ""}`} />
          </div>
          <div>
            <Label className="micro-label text-neutral-500">{t("cashbox.concept")}</Label>
            <Input data-testid="cashbox-mov-concept" value={concept} maxLength={200}
              disabled={linked}
              onChange={(e) => setConcept(e.target.value)}
              placeholder={t("cashbox.conceptPlaceholder")}
              className={`rounded-none mt-1 bg-[#0a0a0a] border-white/10 ${linked ? "opacity-60" : ""}`} />
          </div>
          <div>
            <Label className="micro-label text-neutral-500">{t("cashbox.responsible")}</Label>
            <Input data-testid="cashbox-mov-responsible" value={responsible} maxLength={80}
              disabled={linked}
              onChange={(e) => setResponsible(e.target.value)}
              className={`rounded-none mt-1 bg-[#0a0a0a] border-white/10 ${linked ? "opacity-60" : ""}`} />
          </div>
          <BillInputs fund={fund} counts={counts} onChange={setCounts} testPrefix="mov-bills" />
          <p className="text-[0.65rem] text-neutral-500">{t("cashbox.billsOptionalHint")}</p>
          <Button data-testid="cashbox-mov-save" onClick={save} disabled={busy}
            className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-11">
            {busy ? "…" : t("cashbox.save")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
