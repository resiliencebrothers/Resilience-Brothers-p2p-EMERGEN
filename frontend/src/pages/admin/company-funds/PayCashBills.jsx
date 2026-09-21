/**
 * iter277/iter285 — PayCashBills
 *
 * Desglose de billetes que salen de una cuenta de efectivo al pagar un
 * retiro de empresa. El total debe coincidir con el monto (validado aquí y
 * en el backend). Reutilizado por el prompt de pago y el retiro en 1 paso.
 */
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCashDenoms } from "@/hooks/useCashDenoms";

export default function PayCashBills({ currency, amount, counts, onChange, t }) {
  const denomsMap = useCashDenoms();
  const list = denomsMap[currency] || [];
  const total = Object.entries(counts).reduce(
    (s, [d, q]) => s + (parseInt(d) || 0) * (parseInt(q) || 0), 0);
  const ok = Math.abs(total - amount) <= 0.01;
  return (
    <div
      className="border border-[#22C55E]/25 bg-[#22C55E]/[0.04] p-3 space-y-2"
      data-testid="cw-pay-denominations-block"
    >
      <Label className="micro-label text-neutral-400">
        {t("admin.companyFunds.payDenomsLabel", { currency })}
      </Label>
      <div className="grid grid-cols-3 gap-1.5">
        {list.map((d) => (
          <div key={d} className="flex items-center gap-1">
            <span className="text-[0.6rem] font-mono text-neutral-500 w-9 text-right shrink-0">{d}×</span>
            <Input
              data-testid={`cw-pay-denom-${d}`}
              type="number" min="0" placeholder="0"
              value={counts[String(d)] ?? ""}
              onChange={(e) => onChange({ ...counts, [String(d)]: e.target.value })}
              className="rounded-none h-8 bg-[#0a0a0a] border-white/10 font-mono text-xs px-1.5"
            />
          </div>
        ))}
      </div>
      <div className="flex justify-between text-xs pt-1 border-t border-white/10" data-testid="cw-pay-denoms-total">
        <span className="text-neutral-500">{t("admin.companyFunds.denomsCounted")}:</span>
        <span className={`font-mono ${ok ? "text-[#22C55E]" : "text-[#EF4444]"}`}>
          {total.toLocaleString()} / {amount.toLocaleString()} {currency}
        </span>
      </div>
    </div>
  );
}
