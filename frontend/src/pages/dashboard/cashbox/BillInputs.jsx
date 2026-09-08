import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const DENOMS = {
  CUP: [5000, 2000, 1000, 500, 200, 100, 50, 20, 10, 5, 3, 1],
  USD: [100, 50, 20, 10, 5, 2, 1],
};

export const denomsTotal = (fund, counts) =>
  DENOMS[fund].reduce((s, d) => s + d * (parseInt(counts[String(d)]) || 0), 0);

// iter233 — grid de inputs "cantidad de billetes por denominación".
export function BillInputs({ fund, counts, onChange, testPrefix = "bills" }) {
  const { t } = useTranslation();
  return (
    <div>
      <Label className="micro-label text-neutral-500">{t("cashbox.billsLabel")}</Label>
      <div className="grid grid-cols-3 sm:grid-cols-4 gap-2 mt-1">
        {DENOMS[fund].map((d) => (
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
