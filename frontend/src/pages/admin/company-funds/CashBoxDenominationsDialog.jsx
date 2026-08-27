import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { Banknote } from "lucide-react";

// iter213 — Control físico de caja por denominación (formato Excel):
// cantidad actual de billetes según los movimientos manuales en efectivo.

export default function CashBoxDenominationsDialog({ open, onOpenChange }) {
  const [rows, setRows] = useState(null);

  useEffect(() => {
    if (!open) return;
    axios.get(`${API}/admin/company-funds/cash-denominations`, { withCredentials: true })
      .then((r) => setRows(r.data))
      .catch(() => setRows([]));
  }, [open]);

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
            Billetes actuales en caja según las entradas y salidas manuales de
            efectivo registradas con desglose (entradas suman, salidas restan).
          </DialogDescription>
        </DialogHeader>

        {rows === null ? (
          <p className="text-sm text-neutral-500 py-6 text-center">Cargando…</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-neutral-500 py-6 text-center" data-testid="cashbox-empty">
            Aún no hay movimientos en efectivo con desglose de billetes.
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
      </DialogContent>
    </Dialog>
  );
}
