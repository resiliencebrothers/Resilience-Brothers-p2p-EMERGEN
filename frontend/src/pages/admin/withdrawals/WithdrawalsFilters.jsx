import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Search } from "lucide-react";

export default function WithdrawalsFilters({
  userInput, onUserInputChange,
  statusFilter, onStatusFilterChange,
  currencyFilter, onCurrencyFilterChange,
  currencies, resultCount,
}) {
  const { t } = useTranslation();
  const hasActiveFilter = userInput || statusFilter !== "all" || currencyFilter !== "all";
  return (
    <div className="flex flex-wrap gap-2 mb-3 items-end">
      <div className="relative">
        <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500 pointer-events-none" />
        <Input
          data-testid="withdrawals-user-search"
          value={userInput}
          onChange={(e) => onUserInputChange(e.target.value)}
          placeholder={t("admin.withdrawals.searchPlaceholder")}
          className="rounded-none bg-[#0a0a0a] border-white/10 h-9 w-60 pl-9 text-xs"
        />
      </div>
      <Select value={statusFilter} onValueChange={onStatusFilterChange}>
        <SelectTrigger data-testid="withdrawals-status-filter" className="rounded-none bg-[#0a0a0a] border-white/10 h-9 w-44">
          <SelectValue />
        </SelectTrigger>
        <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
          <SelectItem value="all">{t("admin.withdrawals.allStatuses")}</SelectItem>
          <SelectItem value="pending">{t("admin.common.pending")}</SelectItem>
          <SelectItem value="approved">{t("admin.withdrawals.statusConfirmedInProgress")}</SelectItem>
          <SelectItem value="paid">{t("admin.withdrawals.statusPaidDelivered")}</SelectItem>
          <SelectItem value="rejected">{t("admin.common.rejected")}</SelectItem>
        </SelectContent>
      </Select>
      <Select value={currencyFilter} onValueChange={onCurrencyFilterChange}>
        <SelectTrigger data-testid="withdrawals-currency-filter" className="rounded-none bg-[#0a0a0a] border-white/10 h-9 w-40">
          <SelectValue />
        </SelectTrigger>
        <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
          <SelectItem value="all">{t("admin.withdrawals.allCurrencies")}</SelectItem>
          {currencies.map((c) => (
            <SelectItem key={c.id || c.code} value={c.code}>{c.code}</SelectItem>
          ))}
        </SelectContent>
      </Select>
      {hasActiveFilter && (
        <button
          data-testid="withdrawals-clear-filters"
          onClick={() => { onUserInputChange(""); onStatusFilterChange("all"); onCurrencyFilterChange("all"); }}
          className="text-xs text-neutral-500 hover:text-[#8B5CF6] underline underline-offset-4 h-9"
        >
          {t("admin.common.clear")}
        </button>
      )}
      <div className="ml-auto text-xs text-neutral-500" data-testid="withdrawals-result-count">
        {resultCount} {resultCount === 1 ? t("admin.withdrawals.resultOne") : t("admin.withdrawals.resultMany")}
      </div>
    </div>
  );
}
