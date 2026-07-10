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
import { ArrowDownCircle, ArrowUpCircle } from "lucide-react";
import { toast } from "sonner";

const METHOD_LABELS = {
  transfer: "Transferencia bancaria",
  cash: "Efectivo",
  crypto: "Wallet cripto",
};

const emptyForm = {
  adjustment_type: "inflow",
  currency: "",
  amount: "",
  method: "transfer",
  source_name: "",
  source_account: "",
  note: "",
};

export default function AdjustmentDialog({ open, onOpenChange, currencies, onCreated }) {
  const navigate = useNavigate();
  const [form, setForm] = useState(emptyForm);
  const [askTotp, setAskTotp] = useState(false);
  const [busy, setBusy] = useState(false);

  const reset = () => {
    setForm(emptyForm);
    setAskTotp(false);
  };

  const submit = async (totpCode) => {
    setBusy(true);
    try {
      const body = {
        adjustment_type: form.adjustment_type,
        currency: form.currency,
        amount: parseFloat(form.amount),
        method: form.method,
        source_name: form.source_name.trim(),
        source_account: form.source_account.trim(),
        note: form.note.trim(),
        totp_code: totpCode,
      };
      await axios.post(`${API}/admin/company-funds/adjustments`, body, { withCredentials: true });
      toast.success(
        form.adjustment_type === "inflow"
          ? "Entrada de capital registrada"
          : "Salida de capital registrada"
      );
      reset();
      onOpenChange(false);
      onCreated?.();
    } catch (e) {
      if (!handleTotpError(e, navigate)) {
        toast.error(e.response?.data?.detail || "Error al registrar ajuste");
      }
    } finally {
      setBusy(false);
    }
  };

  const canContinue =
    form.currency &&
    form.amount &&
    parseFloat(form.amount) > 0 &&
    form.source_name.trim().length >= 2 &&
    form.method &&
    (form.method !== "cash" ? form.source_account.trim().length > 0 : true);

  const isInflow = form.adjustment_type === "inflow";

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
          className="bg-[#141414] border-white/10 text-white rounded-none max-w-lg max-h-[85vh] overflow-y-auto"
        >
          <DialogHeader>
            <DialogTitle className="font-display">
              Ajuste manual de capital
            </DialogTitle>
            <DialogDescription className="text-neutral-500 text-xs">
              Registra entradas propias (inyección de capital) o salidas (retiros
              del socio). Se refleja en el balance de la empresa. 2FA requerido.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            {/* Type toggle */}
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                data-testid="adj-type-inflow"
                onClick={() => setForm({ ...form, adjustment_type: "inflow" })}
                className={`flex items-center justify-center gap-2 border h-11 text-sm ${
                  isInflow
                    ? "bg-[#22C55E]/10 border-[#22C55E] text-[#22C55E]"
                    : "bg-[#0a0a0a] border-white/10 text-neutral-400 hover:border-white/20"
                }`}
              >
                <ArrowDownCircle className="w-4 h-4" /> Entrada
              </button>
              <button
                type="button"
                data-testid="adj-type-outflow"
                onClick={() => setForm({ ...form, adjustment_type: "outflow" })}
                className={`flex items-center justify-center gap-2 border h-11 text-sm ${
                  !isInflow
                    ? "bg-[#EF4444]/10 border-[#EF4444] text-[#EF4444]"
                    : "bg-[#0a0a0a] border-white/10 text-neutral-400 hover:border-white/20"
                }`}
              >
                <ArrowUpCircle className="w-4 h-4" /> Salida
              </button>
            </div>

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
                  <SelectContent className="bg-[#141414] border-white/10 text-white rounded-none">
                    {currencies.map((c) => (
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
                  value={form.amount}
                  onChange={(e) => setForm({ ...form, amount: e.target.value })}
                  className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10 font-mono"
                />
              </div>
            </div>

            <div>
              <Label className="micro-label text-neutral-500">Método</Label>
              <Select
                value={form.method}
                onValueChange={(v) => setForm({ ...form, method: v })}
              >
                <SelectTrigger
                  data-testid="adj-method"
                  className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-[#141414] border-white/10 text-white rounded-none">
                  {Object.entries(METHOD_LABELS).map(([v, label]) => (
                    <SelectItem key={v} value={v}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className="micro-label text-neutral-500">
                {isInflow ? "¿Quién aporta?" : "¿A quién / dónde va?"}
              </Label>
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
              className={`w-full rounded-none text-black ${
                isInflow
                  ? "bg-[#22C55E] hover:bg-[#16A34A]"
                  : "bg-[#EF4444] hover:bg-[#DC2626] text-white"
              }`}
            >
              Continuar (2FA)
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <TotpPromptDialog
        open={askTotp}
        title={
          isInflow ? "Confirmar entrada de capital" : "Confirmar salida de capital"
        }
        description="Este movimiento se refleja en el balance de la empresa. Ingresa tu código 2FA."
        busy={busy}
        onConfirm={(code) => submit(code)}
        onCancel={() => setAskTotp(false)}
      />
    </>
  );
}
