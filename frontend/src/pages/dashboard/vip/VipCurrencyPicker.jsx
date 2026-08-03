import { useState, useEffect } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { TrendingUp } from "lucide-react";

/**
 * iter112 — Shared currency picker for the VIP batch/ledger dialogs.
 * Fed by `GET /api/vip/batch-currencies` (only currencies with a configured
 * USDT conversion path). Includes a representative-rate hint so the VIP sees
 * the applicable rate before creating a batch / deposit / payout.
 */
export function useVipCurrencies(open) {
  const [currencies, setCurrencies] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return undefined;
    let ignore = false;
    setLoading(true);
    axios.get(`${API}/vip/batch-currencies`, { withCredentials: true })
      .then((r) => { if (!ignore) setCurrencies(r.data?.items || []); })
      .catch(() => { if (!ignore) setCurrencies([]); })
      .finally(() => { if (!ignore) setLoading(false); });
    return () => { ignore = true; };
  }, [open]);

  return { currencies, loading };
}

function trimNumber(n) {
  const decimals = n >= 100 ? 2 : 4;
  return Number(n.toFixed(decimals)).toLocaleString(undefined, {
    maximumFractionDigits: decimals,
  });
}

export function formatVipRate(cur) {
  if (!cur || !cur.usdt_per_unit || cur.code === "USDT") return null;
  const v = Number(cur.usdt_per_unit);
  if (v >= 1) return `1 ${cur.code} = ${trimNumber(v)} USDT`;
  return `1 USDT = ${trimNumber(1 / v)} ${cur.code}`;
}

export function VipCurrencySelect({ value, onChange, currencies, loading, testid }) {
  const { t } = useTranslation();
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger
        data-testid={testid}
        className="rounded-none bg-black/40 border-white/10 text-white h-10 mt-1 font-mono"
      >
        <SelectValue
          placeholder={loading ? t("admin.common.loadingEllipsis") : t("vipCurrencies.placeholder")}
        />
      </SelectTrigger>
      <SelectContent className="bg-[#0c0c0c] border border-white/10 rounded-none max-h-64">
        {currencies.map((c) => (
          <SelectItem key={c.code} value={c.code} className="rounded-none font-mono">
            {c.code} — {c.name}
          </SelectItem>
        ))}
        {!loading && currencies.length === 0 && (
          <div className="px-3 py-2 text-xs text-neutral-500">
            {t("vipCurrencies.empty")}
          </div>
        )}
      </SelectContent>
    </Select>
  );
}

export function RateHint({ currency, currencies, testid }) {
  const { t } = useTranslation();
  const cur = currencies.find((c) => c.code === currency);
  if (!cur) return null;
  const label = formatVipRate(cur);
  return (
    <div
      data-testid={testid}
      className="mt-2 flex items-center gap-2 border border-[#8B5CF6]/30 bg-[#8B5CF6]/5 px-3 py-2"
    >
      <TrendingUp className="w-3.5 h-3.5 text-[#8B5CF6] shrink-0" />
      <div className="text-xs">
        <span className="text-neutral-400">{t("vipCurrencies.rateLabel")}: </span>
        <span className="text-white font-mono font-semibold">
          {label || t("vipCurrencies.baseCurrency")}
        </span>
      </div>
    </div>
  );
}
