import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCashDenoms, DEFAULT_CASH_DENOMS } from "@/hooks/useCashDenoms";

export const DENOMS = DEFAULT_CASH_DENOMS;

// iter277 — total independiente de la lista: suma denominación×cantidad de
// lo tecleado (así los billetes añadidos por el admin nunca se pierden).
export const denomsTotal = (fund, counts) =>
  Object.entries(counts || {}).reduce(
    (s, [d, q]) => s + (parseInt(d) || 0) * (parseInt(q) || 0), 0);

// iter233 — grid de inputs "cantidad de billetes por denominación".
export function BillInputs({ fund, counts, onChange, testPrefix = "bills" }) {
  const { t } = useTranslation();
  const lists = useCashDenoms();
  const list = lists[fund] || DENOMS[fund] || [];
  return (
    <div>
      <Label className="micro-label text-neutral-500">{t("cashbox.billsLabel")}</Label>
      <div className="grid grid-cols-3 sm:grid-cols-4 gap-2 mt-1">
        {list.map((d) => (
          <div key={d} className="flex items-center gap-1">
            <span className="text-[0.65rem] font-mono text-neutral-500 w-10 text-right shrink-0">{d}×</span>
            <Input
              data-testid={`${testPrefix}-denom-${d}`}
              type="number" min="0" placeholder="0"
              value={counts[String(d)] ?? ""}
              onChange={(e) => onChange({ ...counts, [String(d)]: e.target.value })}
              className="rounded-none h-8 bg-[#0a0a0a] border-white/10 font-mono text-xs px-2"
            />
          </div>
        ))}
      </div>
      <p className="text-[0.65rem] text-neutral-500 mt-1 font-mono" data-testid={`${testPrefix}-total`}>
        {t("cashbox.billsTotal")}: {denomsTotal(fund, counts).toLocaleString()} {fund}
      </p>
    </div>
  );
}

export const cleanCounts = (counts) => {
  const out = {};
  Object.entries(counts).forEach(([d, q]) => {
    const n = parseInt(q);
    if (n > 0) out[d] = n;
  });
  return Object.keys(out).length ? out : null;
};
