import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Download, FileText } from "lucide-react";
import { useTranslation } from "react-i18next";
import { ORIGIN_FILTERS } from "./originMeta";

export function TransactionsFilters({
  direction, setDirection,
  origin, setOrigin,
  currency, setCurrency,
  holderInput, setHolderInput,
  clientInput, setClientInput,
  since, setSince,
  until, setUntil,
  minAmount, setMinAmount,
  maxAmount, setMaxAmount,
  currencies,
  hasFilters,
  onClear,
  onExport,
}) {
  const { t } = useTranslation();
  const tx = (k) => t(`admin.transactions.${k}`);
  return (
    <div className="flex flex-wrap gap-3 items-end justify-between">
      <div className="flex flex-wrap gap-3 items-end">
        <div>
          <div className="micro-label text-neutral-500 mb-1">{tx("filterDirection")}</div>
          <Select value={direction} onValueChange={setDirection}>
            <SelectTrigger
              data-testid="tx-direction-filter"
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-44"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
              <SelectItem value="all">{tx("filterAll")}</SelectItem>
              <SelectItem value="in">{tx("filterInOnly")}</SelectItem>
              <SelectItem value="out">{tx("filterOutOnly")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div>
          <div className="micro-label text-neutral-500 mb-1">{tx("colOrigin")}</div>
          <Select value={origin} onValueChange={setOrigin}>
            <SelectTrigger
              data-testid="tx-origin-filter"
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-48"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
              {Object.keys(ORIGIN_FILTERS).map((k) => (
                <SelectItem key={k} value={k} data-testid={`tx-origin-option-${k}`}>
                  {t(`admin.transactions.originFilter.${k}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <div className="micro-label text-neutral-500 mb-1">{tx("colCurrency")}</div>
          <Select
            value={currency || "all"}
            onValueChange={(v) => setCurrency(v === "all" ? "" : v)}
          >
            <SelectTrigger
              data-testid="tx-currency-filter"
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-36"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
              <SelectItem value="all">{tx("filterAll")}</SelectItem>
              {currencies.map((c) => (
                <SelectItem key={c.code} value={c.code}>{c.code}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <div className="micro-label text-neutral-500 mb-1">{tx("filterHolder")}</div>
          <Input
            data-testid="tx-holder-filter"
            value={holderInput}
            onChange={(e) => setHolderInput(e.target.value)}
            placeholder={tx("filterHolderPh")}
            className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-60 font-mono text-xs"
          />
        </div>
        <div>
          <div className="micro-label text-neutral-500 mb-1">{tx("filterClient")}</div>
          <Input
            data-testid="tx-client-filter"
            value={clientInput}
            onChange={(e) => setClientInput(e.target.value)}
            placeholder={tx("filterClientPh")}
            className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-60 font-mono text-xs"
          />
        </div>
        <div>
          <div className="micro-label text-neutral-500 mb-1">{tx("filterSince")}</div>
          <Input
            type="date"
            data-testid="tx-since-filter"
            value={since}
            onChange={(e) => setSince(e.target.value)}
            className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-40 font-mono text-xs"
          />
        </div>
        <div>
          <div className="micro-label text-neutral-500 mb-1">{tx("filterUntil")}</div>
          <Input
            type="date"
            data-testid="tx-until-filter"
            value={until}
            onChange={(e) => setUntil(e.target.value)}
            className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-40 font-mono text-xs"
          />
        </div>
        <div>
          <div className="micro-label text-neutral-500 mb-1">{tx("filterMin")}</div>
          <Input
            type="number"
            min="0"
            step="0.01"
            data-testid="tx-min-amount"
            value={minAmount}
            onChange={(e) => setMinAmount(e.target.value)}
            placeholder="0"
            className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-28 font-mono text-xs"
          />
        </div>
        <div>
          <div className="micro-label text-neutral-500 mb-1">{tx("filterMax")}</div>
          <Input
            type="number"
            min="0"
            step="0.01"
            data-testid="tx-max-amount"
            value={maxAmount}
            onChange={(e) => setMaxAmount(e.target.value)}
            placeholder="∞"
            className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-28 font-mono text-xs"
          />
        </div>
        {hasFilters && (
          <button
            data-testid="tx-clear-filters"
            onClick={onClear}
            className="text-xs text-neutral-500 hover:text-[#8B5CF6] underline underline-offset-4 h-10"
          >
            {tx("clearFilters")}
          </button>
        )}
      </div>
      <div className="flex gap-2">
        <Button
          data-testid="tx-export-csv"
          onClick={() => onExport("csv")}
          className="rounded-none bg-transparent border border-white/15 hover:border-[#8B5CF6]/60 hover:bg-[#8B5CF6]/5 text-white h-10 px-4 font-mono text-xs uppercase tracking-wider"
        >
          <Download className="w-3.5 h-3.5 mr-2" /> CSV
        </Button>
        <Button
          data-testid="tx-export-pdf"
          onClick={() => onExport("pdf")}
          className="rounded-none bg-[#8B5CF6] hover:bg-[#8B5CF6]/90 text-white h-10 px-4 font-mono text-xs uppercase tracking-wider font-bold"
        >
          <FileText className="w-3.5 h-3.5 mr-2" /> PDF
        </Button>
      </div>
    </div>
  );
}
