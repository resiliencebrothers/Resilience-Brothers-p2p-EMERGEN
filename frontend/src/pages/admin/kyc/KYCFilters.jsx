import { useTranslation } from "react-i18next";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Search, RefreshCw, Clock, CheckCircle2, XCircle, Info } from "lucide-react";

const STATUS_TABS = [
  { key: "pending",         labelKey: "admin.kycAdmin.tabPending",   icon: Clock },
  { key: "needs_more_info", labelKey: "admin.kycAdmin.tabMoreInfo",  icon: Info },
  { key: "verified",        labelKey: "admin.kycAdmin.tabVerified",  icon: CheckCircle2 },
  { key: "rejected",        labelKey: "admin.kycAdmin.tabRejected",  icon: XCircle },
];

/**
 * Filter bar: status tabs · search · min-risk · reload.
 * Fully controlled — parent owns state.
 */
export default function KYCFilters({
  tab, onTabChange,
  search, onSearchChange,
  minRisk, onMinRiskChange,
  onRefresh,
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col md:flex-row gap-3 md:items-center">
      <Tabs value={tab} onValueChange={onTabChange} className="w-full md:w-auto">
        <TabsList className="bg-black/40 border border-white/10">
          {STATUS_TABS.map(({ key, labelKey, icon: Icon }) => (
            <TabsTrigger
              key={key}
              value={key}
              data-testid={`kyc-tab-${key}`}
              className="data-[state=active]:bg-[#8B5CF6] data-[state=active]:text-white text-xs"
            >
              <Icon className="w-3.5 h-3.5 mr-1.5" /> {t(labelKey)}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <div className="relative flex-1 md:max-w-xs ml-auto">
        <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
        <Input
          data-testid="kyc-search-input"
          placeholder={t("admin.kycAdmin.searchPlaceholder")}
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          className="pl-9 bg-black/40 border-white/10 text-white text-sm"
        />
      </div>

      <div className="flex items-center gap-2">
        <label className="text-xs text-neutral-500 whitespace-nowrap">
          {t("admin.kycAdmin.minRisk")}
        </label>
        <Input
          type="number"
          min={0}
          max={100}
          value={minRisk}
          onChange={(e) => onMinRiskChange(parseInt(e.target.value || "0", 10))}
          className="w-16 bg-black/40 border-white/10 text-white text-xs text-center"
          data-testid="kyc-min-risk-input"
        />
      </div>

      <Button
        data-testid="kyc-refresh-btn"
        onClick={onRefresh}
        size="sm"
        variant="outline"
        className="border-white/10 text-neutral-300 hover:bg-white/5"
      >
        <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> {t("admin.common.reload")}
      </Button>
    </div>
  );
}
