/**
 * iter277 — Diálogo «Depósito al fondo» (antes «Ajuste manual»).
 *
 * Solo registra ENTRADAS de capital: los retiros del fondo se hacen por el
 * flujo «Retiro» (company withdrawals) para que todo egreso quede en la misma
 * tabla con su estado. Para efectivo (CUP/USD) exige el desglose de billetes
 * y permite elegir la cuenta de efectivo destino.
 */
import { useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";
import FundAccountSelect, { UNASSIGNED } from "@/components/FundAccountSelect";
import { ArrowDownCircle } from "lucide-react";
import { toast } from "sonner";
import { useCashDenoms } from "@/hooks/useCashDenoms";

const METHOD_LABELS = {
  transfer: "Transferencia bancaria",
  cash: "Efectivo",
  crypto: "Wallet cripto",
};

const emptyForm = {
  currency: "",
  amount: "",
  method: "transfer",
  source_name: "",
  source_account: "",
  note: "",
  account_id: UNASSIGNED,
  denoms: {},
};

export default function AdjustmentDialog({ open, onOpenChange, currencies, onCreated }) {
  const navigate = useNavigate();
  const [form, setForm] = useState(emptyForm);
  const [askTotp, setAskTotp] = useState(false);
  const [busy, setBusy] = useState(false);
  // iter277 — denominaciones dinámicas (incluye las añadidas por el admin).
  const CASH_DENOMS = useCashDenoms();
  const isCashCurrency = (code) => Boolean(CASH_DENOMS[code]);

  const reset = () => {
    setForm(emptyForm);
    setAskTotp(false);
  };

  const denomList = form.method === "cash" ? CASH_DENOMS[form.currency] : null;
  const currencyOptions = [];
  {
    // dedupe por código: datos sucios con monedas repetidas rompían las keys
    const seen = new Set();
    (form.method === "cash"
      ? currencies.filter((c) => isCashCurrency(c.code))
      : currencies
    ).forEach((c) => {
      if (!seen.has(c.code)) { seen.add(c.code); currencyOptions.push(c); }
    });
  }
  const denomTotal = denomList
    ? denomList.reduce((s, d) => s + d * (parseInt(form.denoms[d], 10) || 0), 0)
    : 0;
  const effectiveAmount = denomList ? denomTotal : parseFloat(form.amount);

  const setDenom = (d, v) => {
    const n = v === "" ? "" : Math.max(0, parseInt(v, 10) || 0);
    setForm((f) => ({ ...f, denoms: { ...f.denoms, [d]: n } }));
  };

  const submit = async (totpCode) => {
    setBusy(true);
    try {
      const denominations = denomList
        ? Object.fromEntries(
            denomList
              .filter((d) => (parseInt(form.denoms[d], 10) || 0) > 0)
              .map((d) => [String(d), parseInt(form.denoms[d], 10)])
          )
        : null;
      const body = {
        adjustment_type: "inflow",
        currency: form.currency,
        amount: effectiveAmount,
        method: form.method,
        source_name: form.source_name.trim(),
        source_account: form.source_account.trim(),
        note: form.note.trim(),
        account_id: form.account_id !== UNASSIGNED ? form.account_id : null,
        ...(denominations && Object.keys(denominations).length > 0
          ? { denominations }
          : {}),
        totp_code: totpCode,
      };
      await axios.post(`${API}/admin/company-funds/adjustments`, body, { withCredentials: true });
      toast.success("Depósito registrado");
      reset();
      onOpenChange(false);
      onCreated?.();
    } catch (e) {
      if (!handleTotpError(e, navigate)) {
        toast.error(e.response?.data?.detail || "Error al registrar el depósito");
      }
    } finally {
      setBusy(false);
    }
  };

  const canContinue =
    form.currency &&
    (denomList ? denomTotal > 0 : form.amount && parseFloat(form.amount) > 0) &&
    form.source_name.trim().length >= 2 &&
    form.method &&
    (form.method !== "cash" ? form.source_account.trim().length > 0 : true);

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(v) => {
          if (!v) reset();
          onOpenChange(v);
        }}
      >
        <DialogContent
          data-testid="adjustment-dialog"
          className="bg-[#1A1730] border-white/10 text-white rounded-none max-w-lg max-h-[85vh] overflow-y-auto"
        >
          <DialogHeader>
            <DialogTitle className="font-display flex items-center gap-2">
              <ArrowDownCircle className="w-5 h-5 text-[#22C55E]" /> Depósito al fondo
            </DialogTitle>
            <DialogDescription className="text-neutral-500 text-xs">
              Registra una entrada de capital propia (inyección) al fondo de la
              empresa. Los retiros se hacen con el botón «Retiro». 2FA requerido.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="micro-label text-neutral-500">Moneda</Label>
                <Select
                  value={form.currency}
                  onValueChange={(v) => setForm({ ...form, currency: v })}
                >
                  <SelectTrigger
                    data-testid="adj-currency"
                    className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10"
                  >
                    <SelectValue placeholder="Selecciona" />
                  </SelectTrigger>
                  <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                    {currencyOptions.map((c) => (
                      <SelectItem key={c.code} value={c.code}>
                        {c.code} · {c.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="micro-label text-neutral-500">Monto</Label>
                <Input
                  data-testid="adj-amount"
                  type="number"
                  step="any"
                  min="0"
                  value={denomList ? (denomTotal || "") : form.amount}
                  readOnly={!!denomList}
                  onChange={(e) => setForm({ ...form, amount: e.target.value })}
                  placeholder={denomList ? "Se calcula con los billetes" : ""}
                  className={`rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10 font-mono ${denomList ? "opacity-70" : ""}`}
                />
              </div>
            </div>

            {/* iter213 — desglose de billetes (formato Excel de control físico) */}
            {denomList && (
              <div
                className="border border-[#22C55E]/25 bg-[#22C55E]/[0.04] p-3 space-y-2"
                data-testid="adj-denominations-block"
              >
                <div className="flex items-center justify-between">
                  <Label className="micro-label text-neutral-400">
                    Desglose de billetes ({form.currency})
                  </Label>
                  <span className="text-[0.65rem] text-neutral-500">
                    Cantidad de billetes por denominación
                  </span>
                </div>
                <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
                  {denomList.map((d) => (
                    <div key={d}>
                      <Label className="text-[0.65rem] text-neutral-500 font-mono">
                        Billetes de {d}
                      </Label>
                      <Input
                        data-testid={`adj-denom-${d}`}
                        type="number"
                        min="0"
                        step="1"
                        value={form.denoms[d] ?? ""}
                        onChange={(e) => setDenom(d, e.target.value)}
                        placeholder="0"
                        className="rounded-none mt-0.5 bg-[#0a0a0a] border-white/10 h-9 font-mono text-sm"
                      />
                    </div>
                  ))}
                </div>
                <div
                  className="flex justify-between text-xs pt-1 border-t border-white/10"
                  data-testid="adj-denom-total"
                >
                  <span className="text-neutral-500">Importe calculado</span>
                  <span className={`font-mono ${denomTotal > 0 ? "text-[#22C55E]" : "text-neutral-500"}`}>
                    {denomTotal.toLocaleString()} {form.currency}
                  </span>
                </div>
              </div>
            )}

            <div>
              <Label className="micro-label text-neutral-500">Método</Label>
              <Select
                value={form.method}
                onValueChange={(v) =>
                  setForm((f) => ({
                    ...f,
                    method: v,
                    account_id: UNASSIGNED,
                    // iter271 — Efectivo solo existe en CUP/USD: si la moneda
                    // elegida no tiene billetes, se pide elegirla de nuevo.
                    currency:
                      v === "cash" && !isCashCurrency(f.currency)
                        ? ""
                        : f.currency,
                  }))
                }
              >
                <SelectTrigger
                  data-testid="adj-method"
                  className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                  {Object.entries(METHOD_LABELS)
                    .filter(
                      ([v]) =>
                        v !== "cash" ||
                        !form.currency ||
                        isCashCurrency(form.currency)
                    )
                    .map(([v, label]) => (
                      <SelectItem key={v} value={v}>
                        {label}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
              {form.method === "cash" && !form.currency && (
                <p
                  className="text-[0.65rem] text-neutral-500 mt-1"
                  data-testid="adj-cash-currency-hint"
                >
                  El efectivo físico solo existe en CUP y USD.
                </p>
              )}
            </div>

            {/* iter277 — cuenta destino: para efectivo se elige la cuenta de
                efectivo (por defecto la caja «Fondo Resilience»). */}
            {form.currency && form.method === "cash" && (
              <FundAccountSelect
                currency={form.currency}
                value={form.account_id}
                onChange={(v) => setForm({ ...form, account_id: v })}
                label="Cuenta de efectivo (destino)"
                unassignedLabel="Caja «Fondo Resilience» (automática)"
                methodFilter="cash"
                testId="adj-cash-account"
              />
            )}
            {form.currency && form.method !== "cash" && (
              <FundAccountSelect
                currency={form.currency}
                value={form.account_id}
                onChange={(v) => setForm({ ...form, account_id: v })}
                label="Cuenta interna (opcional)"
                testId="adj-account"
              />
            )}

            <div>
              <Label className="micro-label text-neutral-500">¿Quién aporta / entrega?</Label>
              <Input
                data-testid="adj-source-name"
                value={form.source_name}
                onChange={(e) => setForm({ ...form, source_name: e.target.value })}
                placeholder={
                  form.method === "cash"
                    ? "Nombre completo (ej. Juan Pérez)"
                    : form.method === "crypto"
                    ? "Descripción o alias del wallet"
                    : "Nombre del banco o titular"
                }
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10"
              />
            </div>

            {form.method !== "cash" && (
              <div>
                <Label className="micro-label text-neutral-500">
                  {form.method === "crypto"
                    ? "Dirección wallet / TX hash"
                    : "Cuenta bancaria"}
                </Label>
                <Input
                  data-testid="adj-source-account"
                  value={form.source_account}
                  onChange={(e) =>
                    setForm({ ...form, source_account: e.target.value })
                  }
                  placeholder={
                    form.method === "crypto"
                      ? "TRX7pQR9... o hash"
                      : "0012345 · Metropolitano"
                  }
                  className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10 font-mono text-xs"
                />
              </div>
            )}

            <div>
              <Label className="micro-label text-neutral-500">Nota (opcional)</Label>
              <Textarea
                data-testid="adj-note"
                value={form.note}
                onChange={(e) => setForm({ ...form, note: e.target.value })}
                rows={2}
                placeholder="Concepto contable, referencia interna…"
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"
              />
            </div>

            <Button
              data-testid="adj-submit"
              disabled={!canContinue || busy}
              onClick={() => setAskTotp(true)}
              className="w-full rounded-none text-black bg-[#22C55E] hover:bg-[#16A34A]"
            >
              Continuar (2FA)
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <TotpPromptDialog
        open={askTotp}
        title="Confirmar depósito al fondo"
        description="Este depósito se refleja en el balance de la empresa. Ingresa tu código 2FA."
        busy={busy}
        onConfirm={(code) => submit(code)}
        onCancel={() => setAskTotp(false)}
      />
    </>
  );
}
