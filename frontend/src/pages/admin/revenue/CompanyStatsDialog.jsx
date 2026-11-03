import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import {
  Building2, Package, Truck, LayoutGrid, Loader2, AlertCircle,
  Info, ArrowLeft, TrendingDown,
} from "lucide-react";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

const fmt = (n) => (Number(n) || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });

// Rango rápido → {since, until} en fecha local YYYY-MM-DD.
function computeRange(key) {
  const d = new Date();
  const iso = (x) => x.toISOString().slice(0, 10);
  const today = iso(d);
  if (key === "today") return { since: today, until: today };
  if (key === "7d") {
    const s = new Date(d); s.setDate(s.getDate() - 6);
    return { since: iso(s), until: today };
  }
  if (key === "month") {
    const s = new Date(d.getFullYear(), d.getMonth(), 1);
    return { since: iso(s), until: today };
  }
  if (key === "prevMonth") {
    const s = new Date(d.getFullYear(), d.getMonth() - 1, 1);
    const e = new Date(d.getFullYear(), d.getMonth(), 0);
    return { since: iso(s), until: iso(e) };
  }
  return { since: "", until: "" }; // custom / all
}

const TABS = [
  { id: "summary", icon: LayoutGrid },
  { id: "companies", icon: Building2 },
  { id: "products", icon: Package },
  { id: "messaging", icon: Truck },
];

export default function CompanyStatsDialog({ open, onOpenChange }) {
  const { t } = useTranslation();
  const [tab, setTab] = useState("summary");
  const [quick, setQuick] = useState("month");
  const [since, setSince] = useState(() => computeRange("month").since);
  const [until, setUntil] = useState(() => computeRange("month").until);
  const [prodKind, setProdKind] = useState("products");
  const [compSort, setCompSort] = useState("commission");
  const [prodSort, setProdSort] = useState("commission");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [summary, setSummary] = useState(null);
  const [companies, setCompanies] = useState(null);
  const [products, setProducts] = useState(null);
  const [municipalities, setMunicipalities] = useState(null);

  const applyQuick = (key) => {
    setQuick(key);
    if (key !== "custom" && key !== "all") {
      const r = computeRange(key);
      setSince(r.since); setUntil(r.until);
    } else if (key === "all") {
      setSince(""); setUntil("");
    }
  };

  const load = useCallback(async () => {
    if (!open) return;
    setLoading(true); setError("");
    const params = {};
    if (since) params.since = since;
    if (until) params.until = until;
    try {
      const [s, c, p, m] = await Promise.all([
        axios.get(`${API}/admin/company-stats/summary`, { params, withCredentials: true }),
        axios.get(`${API}/admin/company-stats/companies`, { params: { ...params, sort: compSort }, withCredentials: true }),
        axios.get(`${API}/admin/company-stats/products`, { params: { ...params, kind: prodKind, sort: prodSort }, withCredentials: true }),
        axios.get(`${API}/admin/company-stats/municipalities`, { params, withCredentials: true }),
      ]);
      setSummary(s.data); setCompanies(c.data); setProducts(p.data); setMunicipalities(m.data);
    } catch (e) {
      setError(e.response?.data?.detail || t("companyStats.error"));
      toast.error(e.response?.data?.detail || t("companyStats.error"));
    } finally {
      setLoading(false);
    }
  }, [open, since, until, compSort, prodSort, prodKind, t]);

  useEffect(() => { load(); }, [load]);

  const updatedAt = summary?.updated_at
    ? new Date(summary.updated_at).toLocaleString()
    : "—";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="company-stats-dialog"
        className="max-w-[97vw] w-[97vw] h-[94vh] p-0 gap-0 bg-[#0a0a0a] border-white/10 rounded-none flex flex-col"
      >
        {/* Header */}
        <div className="shrink-0 border-b border-white/10 p-4 sm:p-5 space-y-4">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-3">
              <Button
                data-testid="company-stats-back"
                variant="ghost" size="icon"
                onClick={() => onOpenChange(false)}
                className="rounded-none hover:bg-white/5"
                title={t("companyStats.back")}
              >
                <ArrowLeft className="w-5 h-5" />
              </Button>
              <div>
                <div className="micro-label text-[#8B5CF6]">{t("companyStats.eyebrow")}</div>
                <h2 className="font-display text-2xl flex items-center gap-2">
                  <Building2 className="w-6 h-6 text-[#22C55E]" /> {t("companyStats.title")}
                </h2>
              </div>
            </div>
            <div className="text-right text-xs text-neutral-500">
              <div><span className="text-[#A78BFA] font-mono">{summary?.currency || "USDT"}</span> · {t("companyStats.updatedAt")}</div>
              <div className="font-mono" data-testid="company-stats-updated">{updatedAt}</div>
            </div>
          </div>

          {/* Filters */}
          <div className="flex items-end gap-2 flex-wrap">
            <div>
              <label className="micro-label text-neutral-500 block mb-1">{t("companyStats.quickRange")}</label>
              <Select value={quick} onValueChange={applyQuick}>
                <SelectTrigger data-testid="company-stats-quick" className="rounded-none bg-[#0c0c0c] border-white/10 h-9 w-40 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-[#0c0c0c] border-white/10 rounded-none">
                  <SelectItem value="today">{t("companyStats.rangeToday")}</SelectItem>
                  <SelectItem value="7d">{t("companyStats.range7d")}</SelectItem>
                  <SelectItem value="month">{t("companyStats.rangeMonth")}</SelectItem>
                  <SelectItem value="prevMonth">{t("companyStats.rangePrevMonth")}</SelectItem>
                  <SelectItem value="all">{t("companyStats.rangeAll")}</SelectItem>
                  <SelectItem value="custom">{t("companyStats.rangeCustom")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="micro-label text-neutral-500 block mb-1">{t("companyStats.from")}</label>
              <input
                type="date" value={since}
                data-testid="company-stats-since"
                onChange={(e) => { setSince(e.target.value); setQuick("custom"); }}
                className="rounded-none bg-[#0c0c0c] border border-white/10 h-9 px-2 text-sm font-mono"
              />
            </div>
            <div>
              <label className="micro-label text-neutral-500 block mb-1">{t("companyStats.to")}</label>
              <input
                type="date" value={until}
                data-testid="company-stats-until"
                onChange={(e) => { setUntil(e.target.value); setQuick("custom"); }}
                className="rounded-none bg-[#0c0c0c] border border-white/10 h-9 px-2 text-sm font-mono"
              />
            </div>
            {loading && <Loader2 className="w-5 h-5 animate-spin text-[#8B5CF6] mb-2" data-testid="company-stats-loading" />}
          </div>

          {/* Tabs */}
          <nav className="flex items-center gap-1 overflow-x-auto scrollbar-none" role="tablist">
            {TABS.map((tt) => {
              const Icon = tt.icon;
              const active = tt.id === tab;
              return (
                <button
                  key={tt.id}
                  type="button" role="tab" aria-selected={active}
                  data-testid={`company-stats-tab-${tt.id}`}
                  onClick={() => setTab(tt.id)}
                  className={
                    "flex items-center gap-2 px-4 py-2 text-sm font-medium whitespace-nowrap transition-colors " +
                    (active
                      ? "text-violet-300 border-b-2 border-violet-500"
                      : "text-white/50 hover:text-white")
                  }
                >
                  <Icon className="w-4 h-4" />
                  {t(`companyStats.tabs.${tt.id}`)}
                </button>
              );
            })}
          </nav>
        </div>

        {/* Body */}
        <div className="flex-1 min-w-0 overflow-y-auto overflow-x-hidden p-4 sm:p-5">
          {error ? (
            <div className="border border-red-500/40 bg-red-500/5 p-4 flex items-start gap-3" data-testid="company-stats-error">
              <AlertCircle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
              <div className="text-sm text-red-200">{error}</div>
            </div>
          ) : (
            <>
              {tab === "summary" && <SummaryTab t={t} data={summary} />}
              {tab === "companies" && (
                <CompaniesTab t={t} data={companies} sort={compSort} setSort={setCompSort} />
              )}
              {tab === "products" && (
                <ProductsTab
                  t={t} data={products}
                  kind={prodKind} setKind={setProdKind}
                  sort={prodSort} setSort={setProdSort}
                />
              )}
              {tab === "messaging" && <MessagingTab t={t} data={municipalities} />}
            </>
          )}
          {summary?.coverage && <CoverageNote t={t} coverage={summary.coverage} />}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Stat({ label, value, unit, hint, tone, testid }) {
  const color = tone === "neg" ? "text-red-400" : tone === "pos" ? "text-[#22C55E]" : "text-white";
  return (
    <div className="border border-white/10 bg-[#0c0c0c] p-4" data-testid={testid}>
      <div className="micro-label text-neutral-500">{label}</div>
      <div className={`font-display text-2xl mt-1 ${color}`}>
        {value}{unit ? <span className="text-sm text-neutral-500 ml-1">{unit}</span> : null}
      </div>
      {hint ? <div className="text-xs text-neutral-500 mt-1">{hint}</div> : null}
    </div>
  );
}

function SummaryTab({ t, data }) {
  if (!data) return <Empty t={t} />;
  const e = data.economic, o = data.operational, rec = data.reconciliation;
  return (
    <div className="space-y-6" data-testid="company-stats-summary">
      <section>
        <h3 className="micro-label text-[#8B5CF6] mb-3">{t("companyStats.economicGroup")}</h3>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <Stat label={t("companyStats.netCommission")} value={fmt(e.net_commission_usdt)} unit="USDT" tone={e.net_commission_usdt < 0 ? "neg" : "pos"} testid="stat-net-commission" />
          <Stat label={t("companyStats.reversedCommission")} value={fmt(e.reversed_commission_usdt)} unit="USDT" hint={t("companyStats.reversedCount", { n: e.reversed_count })} tone="neg" testid="stat-reversed" />
          <Stat label={t("companyStats.messagingOwn")} value={fmt(e.messaging_own_income_usdt)} unit="USDT" hint={t("companyStats.messagingOwnHint")} testid="stat-messaging-own" />
          <Stat label={t("companyStats.unattributed")} value={fmt(e.unattributed_commission_usdt)} unit="USDT" hint={t("companyStats.unattributedHint")} testid="stat-unattributed" />
        </div>
      </section>
      <section>
        <h3 className="micro-label text-[#8B5CF6] mb-3">{t("companyStats.operationalGroup")}</h3>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <Stat label={t("companyStats.grossSales")} value={fmt(o.gross_sales_usdt)} unit="USDT" hint={t("companyStats.grossSalesHint")} testid="stat-gross-sales" />
          <Stat label={t("companyStats.ordersCompleted")} value={fmt(o.orders_completed)} testid="stat-orders" />
          <Stat label={t("companyStats.deliveriesCompleted")} value={fmt(o.deliveries_completed)} testid="stat-deliveries" />
          <Stat label={t("companyStats.companiesContributing")} value={fmt(o.companies_contributing)} hint={t("companyStats.servicesCount", { n: o.services_completed })} testid="stat-companies" />
        </div>
      </section>
      {rec && (
        <section className="border border-white/10 bg-[#0c0c0c] p-4" data-testid="company-stats-reconciliation">
          <h3 className="micro-label text-[#8B5CF6] mb-2 flex items-center gap-2">
            <Info className="w-4 h-4" /> {t("companyStats.reconciliationTitle")}
          </h3>
          <div className="text-sm font-mono text-neutral-300 flex flex-wrap items-center gap-2">
            <span>{fmt(rec.companies_commission_usdt)}</span>
            <span className="text-neutral-600">({t("companyStats.companiesWord")})</span>
            <span className="text-[#8B5CF6]">+</span>
            <span>{fmt(rec.unattributed_commission_usdt)}</span>
            <span className="text-neutral-600">({t("companyStats.unattributedWord")})</span>
            <span className="text-[#8B5CF6]">=</span>
            <span className="text-white">{fmt(rec.total_eligible_commission_usdt)}</span>
            <span className="text-neutral-600">USDT</span>
            {rec.balanced
              ? <span className="ml-2 px-2 py-0.5 text-[0.6rem] uppercase tracking-widest border border-[#22C55E]/40 bg-[#22C55E]/10 text-[#22C55E]">{t("companyStats.balanced")}</span>
              : <span className="ml-2 px-2 py-0.5 text-[0.6rem] uppercase tracking-widest border border-red-500/40 bg-red-500/10 text-red-400">{t("companyStats.notBalanced")}</span>}
          </div>
          <p className="text-xs text-neutral-500 mt-2">{t("companyStats.reconciliationHint")}</p>
        </section>
      )}
    </div>
  );
}

function Th({ children, right }) {
  return <th className={`px-3 py-2 micro-label text-neutral-500 font-normal ${right ? "text-right" : "text-left"}`}>{children}</th>;
}
function Td({ children, right, mono, tone }) {
  const color = tone === "neg" ? "text-red-400" : tone === "pos" ? "text-[#22C55E]" : "";
  return <td className={`px-3 py-2 text-sm ${right ? "text-right" : ""} ${mono ? "font-mono" : ""} ${color}`}>{children}</td>;
}

function CompaniesTab({ t, data, sort, setSort }) {
  if (!data) return <Empty t={t} />;
  const rows = data.rows || [];
  const u = data.unattributed;
  return (
    <div className="space-y-3" data-testid="company-stats-companies">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="text-xs text-neutral-500">{t("companyStats.showingN", { shown: data.shown, total: data.total_companies })}</div>
        <Select value={sort} onValueChange={setSort}>
          <SelectTrigger data-testid="company-stats-companies-sort" className="rounded-none bg-[#0c0c0c] border-white/10 h-9 w-48 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-[#0c0c0c] border-white/10 rounded-none">
            <SelectItem value="commission">{t("companyStats.sortCommission")}</SelectItem>
            <SelectItem value="gross">{t("companyStats.sortGross")}</SelectItem>
            <SelectItem value="orders">{t("companyStats.sortOrders")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="overflow-x-auto border border-white/10">
        <table className="w-full min-w-[720px]">
          <thead className="bg-white/5">
            <tr>
              <Th>{t("companyStats.colCompany")}</Th>
              <Th right>{t("companyStats.colCommission")}</Th>
              <Th right>{t("companyStats.colGross")}</Th>
              <Th right>{t("companyStats.colOrders")}</Th>
              <Th right>{t("companyStats.colReversed")}</Th>
              <Th right>{t("companyStats.colShare")}</Th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-6 text-center text-neutral-500 text-sm">{t("companyStats.noCompanies")}</td></tr>
            )}
            {rows.map((r) => (
              <tr key={r.company_id} className="border-t border-white/5" data-testid={`company-row-${r.company_id}`}>
                <Td>{r.company}</Td>
                <Td right mono tone={r.commission_usdt < 0 ? "neg" : "pos"}>{fmt(r.commission_usdt)}</Td>
                <Td right mono>{fmt(r.gross_usdt)}</Td>
                <Td right mono>{r.orders}</Td>
                <Td right mono tone={r.reversed_commission_usdt > 0 ? "neg" : undefined}>
                  {r.reversed_commission_usdt > 0 ? `-${fmt(r.reversed_commission_usdt)} (${r.reversed_orders})` : "—"}
                </Td>
                <Td right mono>{r.share_pct == null ? "—" : `${fmt(r.share_pct)}%`}</Td>
              </tr>
            ))}
            {/* Fila "Sin atribuir" (comisiones válidas sin empresa) */}
            {u && (u.commission_usdt !== 0 || u.orders !== 0) && (
              <tr className="border-t border-[#8B5CF6]/30 bg-[#8B5CF6]/5" data-testid="company-row-unattributed">
                <Td><span className="text-[#A78BFA]">{t("companyStats.unattributedRow")}</span></Td>
                <Td right mono tone={u.commission_usdt < 0 ? "neg" : undefined}>{fmt(u.commission_usdt)}</Td>
                <Td right mono>{fmt(u.gross_usdt)}</Td>
                <Td right mono>{u.orders}</Td>
                <Td right mono>{u.reversed_commission_usdt > 0 ? `-${fmt(u.reversed_commission_usdt)}` : "—"}</Td>
                <Td right mono>{u.share_pct == null ? "—" : `${fmt(u.share_pct)}%`}</Td>
              </tr>
            )}
          </tbody>
          <tfoot>
            <tr className="border-t border-white/10 bg-white/5">
              <Td><span className="micro-label text-neutral-400">{t("companyStats.totalRow")}</span></Td>
              <Td right mono>{fmt(data.totals.commission_usdt)}</Td>
              <Td right mono>{fmt(data.totals.gross_usdt)}</Td>
              <Td right>—</Td>
              <Td right mono>{data.totals.reversed_commission_usdt > 0 ? `-${fmt(data.totals.reversed_commission_usdt)}` : "—"}</Td>
              <Td right>100%</Td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

function ProductsTab({ t, data, kind, setKind, sort, setSort }) {
  return (
    <div className="space-y-3" data-testid="company-stats-products">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-1 border border-white/10">
          <button
            type="button" data-testid="company-stats-kind-products"
            onClick={() => setKind("products")}
            className={`px-3 py-1.5 text-sm ${kind === "products" ? "bg-[#8B5CF6]/20 text-violet-200" : "text-white/50 hover:text-white"}`}
          >{t("companyStats.kindProducts")}</button>
          <button
            type="button" data-testid="company-stats-kind-services"
            onClick={() => setKind("services")}
            className={`px-3 py-1.5 text-sm ${kind === "services" ? "bg-[#8B5CF6]/20 text-violet-200" : "text-white/50 hover:text-white"}`}
          >{t("companyStats.kindServices")}</button>
        </div>
        <Select value={sort} onValueChange={setSort}>
          <SelectTrigger data-testid="company-stats-products-sort" className="rounded-none bg-[#0c0c0c] border-white/10 h-9 w-52 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-[#0c0c0c] border-white/10 rounded-none">
            <SelectItem value="quantity">{t("companyStats.sortQuantity")}</SelectItem>
            <SelectItem value="gross">{t("companyStats.sortGross")}</SelectItem>
            <SelectItem value="commission">{t("companyStats.sortCommission")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {!data ? <Empty t={t} /> : (
        <div className="overflow-x-auto border border-white/10">
          <table className="w-full min-w-[720px]">
            <thead className="bg-white/5">
              <tr>
                <Th>{t(kind === "services" ? "companyStats.colService" : "companyStats.colProduct")}</Th>
                <Th>{t("companyStats.colCompany")}</Th>
                <Th right>{t("companyStats.colQuantity")}</Th>
                <Th right>{t("companyStats.colGross")}</Th>
                <Th right>{t("companyStats.colCommission")}</Th>
                <Th right>{t("companyStats.colOrders")}</Th>
              </tr>
            </thead>
            <tbody>
              {(data.rows || []).length === 0 && (
                <tr><td colSpan={6} className="px-3 py-6 text-center text-neutral-500 text-sm">{t("companyStats.noRows")}</td></tr>
              )}
              {(data.rows || []).map((r) => (
                <tr key={r.id} className="border-t border-white/5" data-testid={`product-row-${r.id}`}>
                  <Td>{r.name}</Td>
                  <Td>{r.company === "Sin atribuir" ? <span className="text-[#A78BFA]">{t("companyStats.unattributedRow")}</span> : r.company}</Td>
                  <Td right mono>{fmt(r.quantity)}</Td>
                  <Td right mono>{fmt(r.gross_usdt)}</Td>
                  <Td right mono tone="pos">{r.commission_usdt == null ? t("companyStats.noBreakdown") : fmt(r.commission_usdt)}</Td>
                  <Td right mono>{r.orders}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {kind === "services" && (
        <p className="text-xs text-neutral-500 flex items-center gap-1">
          <Info className="w-3 h-3" /> {t("companyStats.servicesNote")}
        </p>
      )}
    </div>
  );
}

function MessagingTab({ t, data }) {
  if (!data) return <Empty t={t} />;
  const rows = data.rows || [];
  return (
    <div className="space-y-3" data-testid="company-stats-messaging">
      <div className="text-xs text-neutral-500">{t("companyStats.totalDeliveries", { n: data.total_completed })}</div>
      <div className="overflow-x-auto border border-white/10">
        <table className="w-full min-w-[720px]">
          <thead className="bg-white/5">
            <tr>
              <Th>{t("companyStats.colProvince")}</Th>
              <Th>{t("companyStats.colMunicipality")}</Th>
              <Th right>{t("companyStats.colCompleted")}</Th>
              <Th right>{t("companyStats.colShareDeliveries")}</Th>
              <Th right>{t("companyStats.colFee")}</Th>
              <Th right>{t("companyStats.colOwnShare")}</Th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-6 text-center text-neutral-500 text-sm">{t("companyStats.noDeliveries")}</td></tr>
            )}
            {rows.map((r, i) => (
              <tr key={`${r.province}-${r.municipality}-${i}`} className="border-t border-white/5" data-testid={`municipality-row-${i}`}>
                <Td>{r.province}</Td>
                <Td>{r.registered ? r.municipality : <span className="text-amber-400">{r.municipality}</span>}</Td>
                <Td right mono>{r.completed}</Td>
                <Td right mono>{r.share_pct == null ? "—" : `${fmt(r.share_pct)}%`}</Td>
                <Td right mono>{fmt(r.fee_usdt)}</Td>
                <Td right mono tone="pos">{fmt(r.platform_share_usdt)}</Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-neutral-500 flex items-center gap-1">
        <TrendingDown className="w-3 h-3" /> {t("companyStats.messagingNote")}
      </p>
    </div>
  );
}

function Empty({ t }) {
  return (
    <div className="flex items-center justify-center py-16 text-neutral-500 text-sm" data-testid="company-stats-empty">
      <Loader2 className="w-4 h-4 animate-spin mr-2" /> {t("companyStats.loading")}
    </div>
  );
}

function CoverageNote({ t, coverage }) {
  return (
    <details className="mt-6 border border-white/10 bg-[#0c0c0c] p-3" data-testid="company-stats-coverage">
      <summary className="micro-label text-neutral-500 cursor-pointer flex items-center gap-2">
        <Info className="w-3.5 h-3.5" /> {t("companyStats.coverageTitle")}
      </summary>
      <ul className="mt-2 text-xs text-neutral-400 list-disc list-inside space-y-1">
        {(coverage.notes || []).map((n, i) => <li key={i}>{n}</li>)}
      </ul>
    </details>
  );
}
