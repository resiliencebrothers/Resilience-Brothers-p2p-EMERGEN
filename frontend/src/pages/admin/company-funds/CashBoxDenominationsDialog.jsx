import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Banknote, Plus } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import { invalidateCashDenoms } from "@/hooks/useCashDenoms";

// iter213/iter277 — Caja física por denominación: billetes actuales = suma
// del estado canónico de TODAS las cuentas de efectivo (último conteo de
// cada cuenta ± movimientos con desglose posteriores).

export default function CashBoxDenominationsDialog({ open, onOpenChange }) {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [rows, setRows] = useState(null);

  const load = useCallback(() => {
    axios.get(`${API}/admin/company-funds/cash-denominations`, { withCredentials: true })
      .then((r) => setRows(r.data))
      .catch(() => setRows([]));
  }, []);

  useEffect(() => {
    if (!open) return;
    load();
  }, [open, load]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="cashbox-denominations-dialog"
        className="bg-[#1A1730] border-white/10 text-white rounded-none max-w-2xl max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="font-display flex items-center gap-2">
            <Banknote className="w-5 h-5 text-[#22C55E]" /> Caja física por denominación
          </DialogTitle>
          <DialogDescription className="text-neutral-500 text-xs">
            Billetes actuales de todas las cuentas de efectivo: el último
            desglose contado de cada cuenta más los depósitos, retiros y
            traslados con desglose registrados después.
          </DialogDescription>
        </DialogHeader>

        {rows === null ? (
          <p className="text-sm text-neutral-500 py-6 text-center">Cargando…</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-neutral-500 py-6 text-center" data-testid="cashbox-empty">
            Aún no hay cuentas de efectivo con desglose de billetes.
          </p>
        ) : (
          <div className="grid sm:grid-cols-2 gap-4">
            {rows.map((r) => (
              <div
                key={r.currency}
                className="border border-white/10 bg-[#0a0a0a]"
                data-testid={`cashbox-${r.currency}`}
              >
                <div className="flex items-center justify-between px-3 py-2 border-b border-white/10">
                  <span className="font-mono text-sm text-[#22C55E]">Fondo {r.currency}</span>
                  <span className="text-[0.65rem] text-neutral-500">{r.total_bills} billetes</span>
                </div>
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-neutral-500">
                      <th className="px-3 py-1.5 font-normal micro-label">Denominación</th>
                      <th className="px-3 py-1.5 font-normal micro-label text-right">Billetes</th>
                      <th className="px-3 py-1.5 font-normal micro-label text-right">Valor</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.denominations.map((d) => (
                      <tr
                        key={d.denomination}
                        className={`border-t border-white/5 ${d.count === 0 ? "opacity-40" : ""} ${d.count < 0 ? "text-[#EF4444]" : ""}`}
                      >
                        <td className="px-3 py-1.5 font-mono">{d.denomination}</td>
                        <td className="px-3 py-1.5 font-mono text-right" data-testid={`cashbox-${r.currency}-${d.denomination}`}>
                          {d.count}
                        </td>
                        <td className="px-3 py-1.5 font-mono text-right">{d.value.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="border-t border-white/10">
                      <td className="px-3 py-2 micro-label text-neutral-500">Total</td>
                      <td></td>
                      <td className="px-3 py-2 font-mono text-right text-[#22C55E]" data-testid={`cashbox-total-${r.currency}`}>
                        {r.total_value.toLocaleString()} {r.currency}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            ))}
          </div>
        )}

        {isAdmin && <AddDenominationForm onAdded={load} />}
      </DialogContent>
    </Dialog>
  );
}

// iter277 — el admin puede añadir denominaciones nuevas (p. ej. un billete
// de 10000 CUP) que quedan disponibles en todos los desgloses.
function AddDenominationForm({ onAdded }) {
  const [currency, setCurrency] = useState("CUP");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await axios.post(
        `${API}/admin/company-funds/denominations-config`,
        { currency, denomination: parseInt(value, 10) },
        { withCredentials: true },
      );
      toast.success(`Billete de ${parseInt(value, 10).toLocaleString()} ${currency} añadido`);
      invalidateCashDenoms();
      setValue("");
      onAdded?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || "No se pudo añadir la denominación");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="border border-white/10 bg-white/[0.02] p-3 mt-2" data-testid="add-denomination-form">
      <p className="micro-label text-neutral-400 mb-2">Añadir denominación nueva</p>
      <div className="flex items-end gap-2">
        <Select value={currency} onValueChange={setCurrency}>
          <SelectTrigger
            data-testid="add-denom-currency"
            className="rounded-none bg-[#0a0a0a] border-white/10 h-9 w-24"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
            <SelectItem value="CUP">CUP</SelectItem>
            <SelectItem value="USD">USD</SelectItem>
          </SelectContent>
        </Select>
        <Input
          data-testid="add-denom-value"
          type="number" min="1" step="1"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Valor del billete (ej. 10000)"
          className="rounded-none bg-[#0a0a0a] border-white/10 h-9 font-mono text-xs flex-1"
        />
        <Button
          data-testid="add-denom-submit"
          size="sm"
          disabled={busy || !(parseInt(value, 10) > 0)}
          onClick={submit}
          className="bg-[#22C55E] hover:bg-[#16A34A] text-black rounded-none h-9"
        >
          <Plus className="w-4 h-4 mr-1" /> Añadir
        </Button>
      </div>
      <p className="text-[0.65rem] text-neutral-500 mt-2">
        La nueva denominación aparecerá en todos los desgloses de billetes
        (depósitos, retiros, traslados, conteos y arqueos).
      </p>
    </div>
  );
}
