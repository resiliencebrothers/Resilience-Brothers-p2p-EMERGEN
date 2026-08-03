// iter113 — dialog to log a real client operation (mirrors Excel "Operaciones" sheet).
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { toast } from "sonner";
import { computeUnit, computeDirect, fmt } from "./calc";

const todayStr = () => new Date().toISOString().slice(0, 10);

const emptyForm = () => ({
  mode: "combined", op_date: todayStr(), client_name: "", currency: "", payment_currency: "",
  quantity: "1", sell_price: "", buy_price: "", buy_pct: "", sell_pct: "", note: "",
});

export default function OperationDialog({ open, onOpenChange, currencies, pctFor, onCreate }) {
  const { t } = useTranslation();
  const [form, setForm] = useState(emptyForm());
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (open) setForm(emptyForm()); }, [open]);

  const set = (key) => (e) => setForm((p) => ({ ...p, [key]: e.target.value }));
  const setSel = (key) => (v) => {
    setForm((p) => {
      const next = { ...p, [key]: v };
      if (key === "payment_currency") {
        const pct = pctFor(v);
        next.buy_pct = String(pct.buy_pct ?? 0);
        next.sell_pct = String(pct.sell_pct ?? 0);
      }
      return next;
    });
  };

  const isDirect = form.mode === "direct";
  const preview = isDirect
    ? computeDirect({ sell: form.sell_price, buy: form.buy_price, buyPct: form.buy_pct })
    : computeUnit({ sell: form.sell_price, buy: form.buy_price, buyPct: form.buy_pct, sellPct: form.sell_pct });
  const netTotal = preview.netGain * (Number(form.quantity) || 0);

  const submit = async () => {
    if (!form.client_name.trim() || !form.currency || !form.payment_currency
      || !(Number(form.quantity) > 0) || !(Number(form.sell_price) > 0)) {
      toast.error(t("profitability.dialog.missing"));
      return;
    }
    setBusy(true);
    try {
      await onCreate({
        mode: form.mode,
        op_date: form.op_date,
        client_name: form.client_name.trim(),
        currency: form.currency,
        payment_currency: form.payment_currency,
        quantity: Number(form.quantity),
        sell_price: Number(form.sell_price),
        buy_price: Number(form.buy_price) || 0,
        buy_pct: Number(form.buy_pct) || 0,
        sell_pct: isDirect ? 0 : (Number(form.sell_pct) || 0),
        note: form.note.trim(),
      });
      onOpenChange(false);
    } catch {
      toast.error(t("common.saveError", "Error al guardar"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg" data-testid="op-dialog">
        <DialogHeader>
          <DialogTitle>{t("profitability.dialog.title")}</DialogTitle>
          <DialogDescription>{t("profitability.dialog.description")}</DialogDescription>
        </DialogHeader>
        <div className="flex gap-2">
          {["direct", "combined"].map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setForm((p) => ({ ...p, mode: m }))}
              data-testid={`op-mode-${m}`}
              className={`px-3 py-1.5 rounded-full text-xs border transition-colors ${form.mode === m
                ? "border-[#8B5CF6]/60 text-[#A78BFA] bg-[#8B5CF6]/10 font-semibold"
                : "border-white/10 text-neutral-500 hover:text-neutral-300"}`}
            >
              {t(m === "direct" ? "profitability.dialog.mode1" : "profitability.dialog.mode2")}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("profitability.dialog.date")}>
            <Input type="date" value={form.op_date} onChange={set("op_date")} data-testid="op-date-input" />
          </Field>
          <Field label={t("profitability.dialog.client")}>
            <Input value={form.client_name} onChange={set("client_name")} placeholder={t("profitability.dialog.clientPlaceholder")} data-testid="op-client-input" />
          </Field>
          <Field label={t("profitability.dialog.currency")}>
            <CurrencySelect value={form.currency} onChange={setSel("currency")} currencies={currencies} testid="op-currency-select" />
          </Field>
          <Field label={t("profitability.dialog.paymentCurrency")}>
            <CurrencySelect value={form.payment_currency} onChange={setSel("payment_currency")} currencies={currencies} testid="op-payment-select" />
          </Field>
          <Field label={t("profitability.dialog.quantity")}>
            <Input type="number" step="any" min="0" value={form.quantity} onChange={set("quantity")} data-testid="op-qty-input" />
          </Field>
          <Field label={t(isDirect ? "profitability.calc.m1SellPrice" : "profitability.dialog.sellPrice")}>
            <Input type="number" step="any" min="0" value={form.sell_price} onChange={set("sell_price")} data-testid="op-sell-input" />
          </Field>
          <Field label={t(isDirect ? "profitability.calc.m1BuyPrice" : "profitability.dialog.buyPrice")}>
            <Input type="number" step="any" min="0" value={form.buy_price} onChange={set("buy_price")} data-testid="op-buy-input" />
          </Field>
          <Field label={t(isDirect ? "profitability.calc.m1CostPct" : "profitability.dialog.buyPct")}>
            <Input type="number" step="any" min="0" value={form.buy_pct} onChange={set("buy_pct")} data-testid="op-buypct-input" />
          </Field>
          {!isDirect && (
            <Field label={t("profitability.dialog.sellPct")}>
              <Input type="number" step="any" min="0" value={form.sell_pct} onChange={set("sell_pct")} data-testid="op-sellpct-input" />
            </Field>
          )}
          <Field label={t("profitability.dialog.note")}>
            <Input value={form.note} onChange={set("note")} data-testid="op-note-input" />
          </Field>
        </div>

        <div className="flex items-center justify-between rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2">
          <span className="text-xs text-neutral-500">{t("profitability.dialog.preview")}</span>
          <span className={`font-mono text-sm font-semibold ${netTotal >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"}`} data-testid="op-preview-net">
            {fmt(netTotal)} {form.payment_currency}
          </span>
        </div>

        <Button onClick={submit} disabled={busy} className="w-full" data-testid="op-submit-btn">
          {t("profitability.dialog.save")}
        </Button>
      </DialogContent>
    </Dialog>
  );
}

function Field({ label, children }) {
  return (
    <div className="space-y-1">
      <Label className="text-xs text-neutral-400">{label}</Label>
      {children}
    </div>
  );
}

function CurrencySelect({ value, onChange, currencies, testid }) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger data-testid={testid}><SelectValue placeholder="—" /></SelectTrigger>
      <SelectContent>
        {currencies.map((c) => (
          <SelectItem key={c.code} value={c.code}>{c.code} — {c.name}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
