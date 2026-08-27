/**
 * iter194/195 — FundAccountSelect
 *
 * Shared optional selector of internal company accounts (payment accounts +
 * custom fund accounts) for a given currency. Used by the manual adjustment
 * dialog and the "paid from account" attribution on withdrawals.
 *
 * `autoMode` (iter195): when the currency has 0 accounts renders nothing and
 * with exactly 1 account renders an informative note instead of the select —
 * the backend auto-attributes the single account, so no question is needed.
 */
import { useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Landmark } from "lucide-react";

export const UNASSIGNED = "__unassigned__";

export default function FundAccountSelect({
  currency, value, onChange,
  label, unassignedLabel = "Sin asignar",
  testId = "fund-account-select",
  autoMode = false,
}) {
  const { t } = useTranslation();
  const [options, setOptions] = useState(null);

  useEffect(() => {
    if (!currency) { setOptions(null); return undefined; }
    let alive = true;
    axios
      .get(`${API}/admin/fund-accounts/options`, {
        params: { currency }, withCredentials: true,
      })
      .then((r) => { if (alive) setOptions(r.data || []); })
      .catch(() => { if (alive) setOptions([]); });
    return () => { alive = false; };
  }, [currency]);

  if (!currency || options === null) return null;

  if (autoMode && options.length === 0) return null;
  if (autoMode && options.length === 1) {
    return (
      <div
        className="text-[0.7rem] text-neutral-400 flex items-center gap-1.5 border border-white/10 bg-white/[0.02] px-2.5 py-2"
        data-testid={`${testId}-auto`}
      >
        <Landmark className="w-3.5 h-3.5 text-[#8B5CF6] flex-shrink-0" />
        <span>{t("admin.companyFunds.singleAccountNote", { label: options[0].label })}</span>
      </div>
    );
  }

  return (
    <div>
      {label && <Label className="micro-label text-neutral-500">{label}</Label>}
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger
          data-testid={testId}
          className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10"
        >
          <SelectValue placeholder={unassignedLabel} />
        </SelectTrigger>
        <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
          <SelectItem value={UNASSIGNED}>{unassignedLabel}</SelectItem>
          {options.map((o) => (
            <SelectItem key={o.id} value={o.id}>{o.label}</SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
