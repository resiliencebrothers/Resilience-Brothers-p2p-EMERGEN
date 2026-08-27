import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { Upload, ListChecks, History, Settings2, Landmark, Gauge, Coins } from "lucide-react";
import { API } from "@/App";
import AdminPageHeader from "@/components/AdminPageHeader";
import { useLiveEvent } from "@/hooks/useLiveStream";
import ImportTab from "./reconciliation/ImportTab";
import TransactionsTab from "./reconciliation/TransactionsTab";
import HistoryTab from "./reconciliation/HistoryTab";
import ConfigTab from "./reconciliation/ConfigTab";
import DashboardTab from "./reconciliation/DashboardTab";

/**
 * iter167 — Conciliación Bancaria hub.
 * Tabs: Importar | Movimientos (filters cover auto/review/unmatched/dups) |
 * Historial (imports + files) | Configuración (rules).
 */
const TABS = [
  { id: "import",  labelKey: "reconciliation.tabs.import",  icon: Upload },
  { id: "moves",   labelKey: "reconciliation.tabs.moves",   icon: ListChecks, countKey: "manual_review" },
  { id: "dashboard", labelKey: "reconciliation.tabs.dashboard", icon: Gauge },
  { id: "history", labelKey: "reconciliation.tabs.history", icon: History },
  { id: "config",  labelKey: "reconciliation.tabs.config",  icon: Settings2 },
];

export default function AdminReconciliation() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const [summary, setSummary] = useState(null);
  const [currencies, setCurrencies] = useState([]);

  const activeId = params.get("tab") || "import";
  const active = TABS.find((tt) => tt.id === activeId) || TABS[0];
  const currency = params.get("currency") || "";

  const loadSummary = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/admin/reconciliation/summary`, {
        params: currency ? { currency } : {}, withCredentials: true,
      });
      setSummary(r.data);
      setCurrencies(r.data?.currencies || []);
    } catch { /* badge best-effort */ }
  }, [currency]);

  useEffect(() => { loadSummary(); }, [loadSummary]);
  useLiveEvent("reconciliation_import", loadSummary);

  const buildParams = (tabId, cur) => {
    const next = {};
    if (tabId !== "import") next.tab = tabId;
    if (cur) next.currency = cur;
    return next;
  };
  const setTab = (id) => setParams(buildParams(id, currency));
  const setCurrency = (c) => setParams(buildParams(activeId, c));

  return (
    <div className="space-y-5" data-testid="admin-reconciliation">
      <AdminPageHeader
        eyebrow={t("reconciliation.eyebrow")}
        title={t("reconciliation.title")}
        subtitle={t("reconciliation.subtitle")}
        icon={Landmark}
        testid="reconciliation-header"
      />
      <nav
        className="flex items-center gap-1 border-b border-white/10 pb-1 overflow-x-auto scrollbar-none"
        role="tablist"
        data-testid="reconciliation-tabs"
      >
        {TABS.map((tt) => {
          const Icon = tt.icon;
          const isActive = tt.id === active.id;
          const count = tt.countKey ? summary?.[tt.countKey] || 0 : 0;
          return (
            <button
              key={tt.id}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => setTab(tt.id)}
              data-testid={`reconciliation-tab-${tt.id}`}
              className={
                "relative flex items-center gap-2 px-4 py-2.5 text-sm font-medium whitespace-nowrap " +
                "transition-all duration-200 outline-none focus-visible:ring-2 focus-visible:ring-violet-500 " +
                (isActive
                  ? "text-violet-300 after:absolute after:left-3 after:right-3 after:-bottom-[7px] after:h-[2px] after:bg-violet-500 after:rounded-full"
                  : "text-white/50 hover:text-white hover:bg-white/[0.03] rounded-md")
              }
            >
              <Icon className="w-4 h-4" />
              {t(tt.labelKey)}
              {count > 0 && (
                <span className="inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1 text-[0.6rem] font-bold border border-amber-500/50 bg-amber-500/10 text-amber-400">
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {currencies.length > 0 && (
        <div
          className="flex items-center gap-1.5 flex-wrap"
          data-testid="reconciliation-currency-filter"
        >
          <span className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-widest text-neutral-500 mr-1">
            <Coins className="w-3.5 h-3.5" /> {t("reconciliation.currencyFilter.label")}
          </span>
          <button
            type="button"
            data-testid="recon-currency-all"
            onClick={() => setCurrency("")}
            className={`text-xs uppercase tracking-widest px-3 py-1.5 border font-mono transition-colors ${
              !currency
                ? "bg-violet-500/10 border-violet-500 text-violet-300"
                : "bg-transparent border-white/10 text-neutral-400 hover:border-white/30"
            }`}
          >
            {t("reconciliation.currencyFilter.all")}
          </button>
          {currencies.map((c) => (
            <button
              key={c}
              type="button"
              data-testid={`recon-currency-${c}`}
              onClick={() => setCurrency(c)}
              className={`text-xs uppercase tracking-widest px-3 py-1.5 border font-mono transition-colors ${
                currency === c
                  ? "bg-violet-500/10 border-violet-500 text-violet-300"
                  : "bg-transparent border-white/10 text-neutral-400 hover:border-white/30"
              }`}
            >
              {c}
            </button>
          ))}
          {currency && (
            <span
              className="text-[10px] uppercase tracking-wider text-violet-300/80 border border-violet-500/30 bg-violet-500/5 px-2 py-1"
              data-testid="recon-currency-scope-note"
            >
              {t("reconciliation.currencyFilter.scopeNote", { currency })}
            </span>
          )}
        </div>
      )}

      {active.id === "import" && <ImportTab onProcessed={loadSummary} />}
      {active.id === "moves" && <TransactionsTab onChanged={loadSummary} currency={currency} />}
      {active.id === "dashboard" && <DashboardTab currency={currency} />}
      {active.id === "history" && <HistoryTab currency={currency} />}
      {active.id === "config" && <ConfigTab />}
    </div>
  );
}
