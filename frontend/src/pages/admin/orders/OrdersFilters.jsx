import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Search } from "lucide-react";

const FILTERS = [
  ["all",                       "admin.orders.filterAll"],
  ["pending",                   "admin.orders.filterPending"],
  ["requires_double_approval",  "admin.orders.filterDouble"],
  ["approved",                  "admin.orders.filterApproved"],
  ["rejected",                  "admin.orders.filterRejected"],
  ["completed",                 "admin.orders.filterCompleted"],
];

/**
 * Search, currency dropdown, status tab strip, and result counter.
 * Fully controlled by the parent.
 */
export default function OrdersFilters({
  filter, onFilterChange,
  userInput, onUserInputChange,
  currencyFilter, onCurrencyFilterChange,
  currencies, total,
}) {
  const { t } = useTranslation();
  return (
    <>
      <div className="flex gap-2 mb-3 flex-wrap items-end">
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500 pointer-events-none" />
          <Input
            data-testid="orders-user-search"
            value={userInput}
            onChange={(e) => onUserInputChange(e.target.value)}
            placeholder={t("admin.orders.searchPlaceholder")}
            className="rounded-none bg-[#0a0a0a] border-white/10 h-9 w-60 pl-9 text-xs"
          />
        </div>
        <Select value={currencyFilter} onValueChange={onCurrencyFilterChange}>
          <SelectTrigger data-testid="orders-currency-filter" className="rounded-none bg-[#0a0a0a] border-white/10 h-9 w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
            <SelectItem value="all">{t("admin.orders.allCurrencies")}</SelectItem>
            {currencies.map((c) => (
              <SelectItem key={c.id || c.code} value={c.code}>{c.code}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {(userInput || currencyFilter !== "all") && (
          <button
            data-testid="orders-clear-filters"
            onClick={() => { onUserInputChange(""); onCurrencyFilterChange("all"); }}
            className="text-xs text-neutral-500 hover:text-[#8B5CF6] underline underline-offset-4 h-9"
          >
            {t("admin.common.clear")}
          </button>
        )}
        <div className="ml-auto text-xs text-neutral-500" data-testid="orders-result-count">
          {total} {total === 1 ? t("admin.orders.resultOne") : t("admin.orders.resultMany")}
        </div>
      </div>
      <div className="flex gap-2 mb-4 flex-wrap">
        {FILTERS.map(([f, key]) => (
          <button
            key={f}
            data-testid={`orders-filter-${f}`}
            onClick={() => onFilterChange(f)}
            className={`micro-label px-3 py-1.5 border transition-colors ${
              filter === f
                ? "bg-[#8B5CF6] text-white border-[#8B5CF6]"
                : "border-white/10 text-neutral-400 hover:text-white"
            }`}
          >
            {t(key)}
          </button>
        ))}
      </div>
    </>
  );
}
