/**
 * iter83 — TransactionFilters
 *
 * Pure presentational component that renders the filter row of the
 * History section: currency select, since/until date inputs, min/max
 * amount inputs, a "clear" chip when any filter is active, and the
 * CSV/PDF export buttons.
 *
 * The full filter shape is passed in as a single `filters` prop coming
 * from `useTransactionsQuery()` so this file has zero data-fetch logic.
 */
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Download, FileText } from "lucide-react";
import QuickDateRange from "@/components/QuickDateRange";

export default function TransactionFilters({ filters }) {
  const { t } = useTranslation();
  const {
    currency, setCurrency,
    since, setSince,
    until, setUntil,
    minAmount, setMinAmount,
    maxAmount, setMaxAmount,
    currencies,
    hasFilters,
    clearFilters,
    downloadExport,
  } = filters;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-3 items-end justify-between">
      <div className="flex flex-wrap gap-3 items-end">
        <div>
          <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.filters.currency")}</div>
          <Select value={currency || "all"} onValueChange={(v) => setCurrency(v === "all" ? "" : v)}>
            <SelectTrigger data-testid="my-tx-currency" className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
              <SelectItem value="all">{t("myTransactions.filters.all")}</SelectItem>
              {currencies.map((c) => (
                <SelectItem key={c.code} value={c.code}>{c.code}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.filters.since")}</div>
          <Input
            type="date" data-testid="my-tx-since" value={since}
            onChange={(e) => setSince(e.target.value)}
            className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-40 font-mono text-xs"
          />
        </div>
        <div>
          <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.filters.until")}</div>
          <Input
            type="date" data-testid="my-tx-until" value={until}
            onChange={(e) => setUntil(e.target.value)}
            className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-40 font-mono text-xs"
          />
        </div>
        <div>
          <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.filters.min")}</div>
          <Input
            type="number" min="0" step="0.01" data-testid="my-tx-min"
            value={minAmount} onChange={(e) => setMinAmount(e.target.value)}
            placeholder="0"
            className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-24 font-mono text-xs"
          />
        </div>
        <div>
          <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.filters.max")}</div>
          <Input
            type="number" min="0" step="0.01" data-testid="my-tx-max"
            value={maxAmount} onChange={(e) => setMaxAmount(e.target.value)}
            placeholder="∞"
            className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-24 font-mono text-xs"
          />
        </div>
        {hasFilters && (
          <button
            data-testid="my-tx-clear" onClick={clearFilters}
            className="text-xs text-neutral-500 hover:text-[#8B5CF6] underline underline-offset-4 h-10"
          >
            {t("myTransactions.filters.clear")}
          </button>
        )}
      </div>
      <div className="flex gap-2">
        <Button
          data-testid="my-tx-export-csv" onClick={() => downloadExport("csv")}
          className="rounded-none bg-transparent border border-white/15 hover:border-[#8B5CF6]/60 hover:bg-[#8B5CF6]/5 text-white h-10 px-4 font-mono text-xs uppercase tracking-wider"
        >
          <Download className="w-3.5 h-3.5 mr-2" /> CSV
        </Button>
        <Button
          data-testid="my-tx-export-pdf" onClick={() => downloadExport("pdf")}
          className="rounded-none bg-[#8B5CF6] hover:bg-[#8B5CF6]/90 text-white h-10 px-4 font-mono text-xs uppercase tracking-wider font-bold"
        >
          <FileText className="w-3.5 h-3.5 mr-2" /> PDF
        </Button>
      </div>
      </div>
      <QuickDateRange
        since={since}
        until={until}
        onRangeChange={({ since: s, until: u }) => { setSince(s); setUntil(u); }}
        testIdPrefix="my-tx-quick"
      />
    </div>
  );
}
