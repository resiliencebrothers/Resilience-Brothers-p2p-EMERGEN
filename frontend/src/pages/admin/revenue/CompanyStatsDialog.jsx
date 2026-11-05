import { useState, useEffect, useCallback, useRef } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import {
  Building2, Package, Truck, LayoutGrid, Loader2, AlertCircle,
  Info, ArrowLeft, TrendingDown, TrendingUp, Download,
} from "lucide-react";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Cell,
} from "recharts";

const fmt = (n) => (Number(n) || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });

// Día de negocio (America/Havana) en formato YYYY-MM-DD, independiente de la
// zona del dispositivo (EST-R07). El backend interpreta estas fechas como días
// de esa misma zona.
const BIZ_TZ = "America/Havana";
const bizYMD = (d) => new Intl.DateTimeFormat("en-CA", {
  timeZone: BIZ_TZ, year: "numeric", month: "2-digit", day: "2-digit",
}).format(d);

// Rango rápido → {since, until} en día de negocio YYYY-MM-DD.
function computeRange(key) {
  const now = new Date();
  const today = bizYMD(now);
  const [y, m] = today.split("-").map(Number);
  const ymd = (yy, mm, dd) =>
    `${String(yy).padStart(4, "0")}-${String(mm).padStart(2, "0")}-${String(dd).padStart(2, "0")}`;
  if (key === "today") return { since: today, until: today };
  if (key === "7d") {
    const s = new Date(now); s.setDate(s.getDate() - 6);
    return { since: bizYMD(s), until: today };
  }
  if (key === "month") return { since: ymd(y, m, 1), until: today };
  if (key === "prevMonth") {
    const pm = m === 1 ? 12 : m - 1;
    const py = m === 1 ? y - 1 : y;
    const lastDay = new Date(py, pm, 0).getDate(); // último día del mes anterior
    return { since: ymd(py, pm, 1), until: ymd(py, pm, lastDay) };
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
  const [trendBucket, setTrendBucket] = useState("month");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [summary, setSummary] = useState(null);
  const [companies, setCompanies] = useState(null);
  const [products, setProducts] = useState(null);
  const [municipalities, setMunicipalities] = useState(null);
  const [trend, setTrend] = useState(null);
  // EST-R06 — secuencia para descartar respuestas obsoletas: si cambia el
  // período mientras una carga está en vuelo, sólo se aplica la última.
  const loadSeqRef = useRef(0);

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
    const seq = ++loadSeqRef.current;
    setLoading(true); setError("");
    const params = {};
    if (since) params.since = since;
    if (until) params.until = until;
    try {
      const [s, c, p, m, tr] = await Promise.all([
        axios.get(`${API}/admin/company-stats/summary`, { params, withCredentials: true }),
        axios.get(`${API}/admin/company-stats/companies`, { params: { ...params, sort: compSort }, withCredentials: true }),
        axios.get(`${API}/admin/company-stats/products`, { params: { ...params, kind: prodKind, sort: prodSort }, withCredentials: true }),
        axios.get(`${API}/admin/company-stats/municipalities`, { params, withCredentials: true }),
        axios.get(`${API}/admin/company-stats/trend`, { params: { ...params, bucket: trendBucket }, withCredentials: true }),
      ]);
      if (seq !== loadSeqRef.current) return; // respuesta obsoleta: descartar
      setSummary(s.data); setCompanies(c.data); setProducts(p.data);
      setMunicipalities(m.data); setTrend(tr.data);
    } catch (e) {
      if (seq !== loadSeqRef.current) return;
      setError(e.response?.data?.detail || t("companyStats.error"));
      toast.error(e.response?.data?.detail || t("companyStats.error"));
    } finally {
      if (seq === loadSeqRef.current) setLoading(false);
    }
  }, [open, since, until, compSort, prodSort, prodKind, trendBucket, t]);

  useEffect(() => { load(); }, [load]);

  // Exportación CSV (FASE 2): descarga el dataset COMPLETO del corte/filtros
  // actuales por blob autenticado (no sólo la página visible).
  const downloadCsv = async (path, extra = {}) => {
    const params = { ...extra };
    if (since) params.since = since;
    if (until) params.until = until;
    try {
      const res = await axios.get(`${API}/admin/company-stats/export/${path}`, {
        params, responseType: "blob", withCredentials: true,
      });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      const cd = res.headers["content-disposition"] || "";
      const match = cd.match(/filename="?([^"]+)"?/);
      a.download = match ? match[1] : path;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } catch {
      toast.error(t("companyStats.exportError"));
    }
  };

  const updatedAt = summary?.updated_at
    ? new Date(summary.updated_at).toLocaleString()
    : "—";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="company-stats-dialog"
        className="max-w-[97vw] w-[97vw] h-[94vh] max-h-[94vh] p-0 gap-0 bg-[#0a0a0a] border-white/10 rounded-none flex flex-col"
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
            <div className="text-right text-xs text-neutral-500 pr-8">
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
              {tab === "summary" && (
                <SummaryTab t={t} data={summary} trend={trend}
                  trendBucket={trendBucket} setTrendBucket={setTrendBucket} />
              )}
              {tab === "companies" && (
                <CompaniesTab t={t} data={companies} sort={compSort} setSort={setCompSort}
                  onExport={() => downloadCsv("companies.csv")} />
              )}
              {tab === "products" && (
                <ProductsTab
                  t={t} data={products}
                  kind={prodKind} setKind={setProdKind}
                  sort={prodSort} setSort={setProdSort}
                  onExport={() => downloadCsv("products.csv", { kind: prodKind })}
                />
              )}
              {tab === "messaging" && (
                <MessagingTab t={t} data={municipalities}
                  onExport={() => downloadCsv("municipalities.csv")} />
              )}
            </>
          )}
          {summary?.coverage && <CoverageNote t={t} coverage={summary.coverage} />}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ExportButton({ t, onExport }) {
  return (
    <Button
      data-testid="company-stats-export"
      onClick={onExport}
      variant="outline"
      className="rounded-none border-[#22C55E]/40 text-[#22C55E] hover:bg-[#22C55E]/10 h-9"
    >
      <Download className="w-4 h-4 mr-1" /> {t("companyStats.exportCsv")}
    </Button>
  );
}

function DeltaBadge({ t, comparison }) {
  if (!comparison) return null;
  const up = comparison.delta_usdt >= 0;
  const pct = comparison.delta_pct;
  return (
    <div className="text-xs mt-1 flex items-center gap-1" data-testid="company-stats-delta">
      {up ? <TrendingUp className="w-3 h-3 text-[#22C55E]" /> : <TrendingDown className="w-3 h-3 text-red-400" />}
      <span className={up ? "text-[#22C55E]" : "text-red-400"}>
        {up ? "+" : ""}{fmt(comparison.delta_usdt)}{pct == null ? "" : ` (${up ? "+" : ""}${fmt(pct)}%)`}
      </span>
      <span className="text-neutral-600">
        · {t("companyStats.vsPrev", { from: comparison.previous_since, to: comparison.previous_until })}
      </span>
    </div>
  );
}

function TrendChart({ t, trend, bucket, setBucket }) {
  const rows = trend?.rows || [];
  return (
    <section data-testid="company-stats-trend">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h3 className="micro-label text-[#8B5CF6]">{t("companyStats.trendTitle")}</h3>
        <Select value={bucket} onValueChange={setBucket}>
          <SelectTrigger data-testid="company-stats-trend-bucket" className="rounded-none bg-[#0c0c0c] border-white/10 h-8 w-36 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-[#0c0c0c] border-white/10 rounded-none">
            <SelectItem value="day">{t("companyStats.bucketDay")}</SelectItem>
            <SelectItem value="week">{t("companyStats.bucketWeek")}</SelectItem>
            <SelectItem value="month">{t("companyStats.bucketMonth")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {rows.length === 0 ? (
        <div className="border border-white/10 bg-[#0c0c0c] p-6 text-center text-sm text-neutral-500">
          {t("companyStats.noRows")}
        </div>
      ) : (
        <div className="border border-white/10 bg-[#0c0c0c] p-3" style={{ height: 240 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#ffffff10" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: "#888", fontSize: 11 }} stroke="#ffffff20" />
              <YAxis tick={{ fill: "#888", fontSize: 11 }} stroke="#ffffff20" width={54} />
              <Tooltip
                contentStyle={{ background: "#0c0c0c", border: "1px solid #ffffff20", borderRadius: 0, fontSize: 12 }}
                formatter={(v) => [`${fmt(v)} USDT`, t("companyStats.netCommission")]}
              />
              <Bar dataKey="commission_usdt" radius={[2, 2, 0, 0]}>
                {rows.map((r, i) => (
                  <Cell key={i} fill={r.commission_usdt < 0 ? "#EF4444" : "#8B5CF6"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}

function Stat({ label, value, unit, hint, tone, testid, children }) {
  const color = tone === "neg" ? "text-red-400" : tone === "pos" ? "text-[#22C55E]" : "text-white";
  return (
    <div className="border border-white/10 bg-[#0c0c0c] p-4" data-testid={testid}>
      <div className="micro-label text-neutral-500">{label}</div>
      <div className={`font-display text-2xl mt-1 ${color}`}>
        {value}{unit ? <span className="text-sm text-neutral-500 ml-1">{unit}</span> : null}
      </div>
      {hint ? <div className="text-xs text-neutral-500 mt-1">{hint}</div> : null}
      {children}
    </div>
  );
}

function SummaryTab({ t, data, trend, trendBucket, setTrendBucket }) {
  if (!data) return <Empty t={t} />;
  const e = data.economic, o = data.operational, rec = data.reconciliation;
  const comp = data.comparison, conc = data.concentration;
  return (
    <div className="space-y-6" data-testid="company-stats-summary">
      <section>
        <h3 className="micro-label text-[#8B5CF6] mb-3">{t("companyStats.economicGroup")}</h3>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <Stat label={t("companyStats.netCommission")} value={fmt(e.net_commission_usdt)} unit="USDT" tone={e.net_commission_usdt < 0 ? "neg" : "pos"} testid="stat-net-commission">
            <DeltaBadge t={t} comparison={comp} />
          </Stat>
          <Stat label={t("companyStats.reversedCommission")} value={fmt(e.reversed_commission_usdt)} unit="USDT" hint={t("companyStats.reversedCount", { n: e.reversed_count })} tone={e.reversed_commission_usdt > 0 ? "neg" : undefined} testid="stat-reversed" />
          <Stat label={t("companyStats.messagingOwn")} value={fmt(e.messaging_own_income_usdt)} unit="USDT" hint={t("companyStats.messagingOwnHint")} testid="stat-messaging-own" />
          <Stat label={t("companyStats.unattributed")} value={fmt(e.unattributed_commission_usdt)} unit="USDT" hint={t("companyStats.unattributedHint")} testid="stat-unattributed" />
        </div>
      </section>

      <TrendChart t={t} trend={trend} bucket={trendBucket} setBucket={setTrendBucket} />

      <section>
        <h3 className="micro-label text-[#8B5CF6] mb-3">{t("companyStats.operationalGroup")}</h3>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <Stat label={t("companyStats.grossSales")} value={fmt(o.gross_sales_usdt)} unit="USDT" hint={t("companyStats.grossSalesHint")} testid="stat-gross-sales" />
          <Stat label={t("companyStats.ordersCompleted")} value={fmt(o.orders_completed)} testid="stat-orders" />
          <Stat label={t("companyStats.deliveriesCompleted")} value={fmt(o.deliveries_completed)} testid="stat-deliveries" />
          <Stat label={t("companyStats.companiesContributing")} value={fmt(o.companies_contributing)} hint={t("companyStats.servicesCount", { n: o.services_completed })} testid="stat-companies" />
        </div>
      </section>

      {conc && (
        <section className="border border-white/10 bg-[#0c0c0c] p-4" data-testid="company-stats-concentration">
          <h3 className="micro-label text-[#8B5CF6] mb-2">{t("companyStats.concentrationTitle")}</h3>
          <div className="flex flex-wrap gap-6 text-sm">
            <div><span className="text-neutral-500">{t("companyStats.top5")}: </span><span className="font-mono text-white">{fmt(conc.top5_share_pct)}%</span></div>
            <div><span className="text-neutral-500">{t("companyStats.top10")}: </span><span className="font-mono text-white">{fmt(conc.top10_share_pct)}%</span></div>
            <div><span className="text-neutral-500">{t("companyStats.companiesWord")}: </span><span className="font-mono text-white">{conc.companies_count}</span></div>
          </div>
          <p className="text-xs text-neutral-500 mt-2">{t("companyStats.concentrationHint")}</p>
        </section>
      )}

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

function CompaniesTab({ t, data, sort, setSort, onExport }) {
  if (!data) return <Empty t={t} />;
  const rows = data.rows || [];
  const u = data.unattributed;
  return (
    <div className="space-y-3" data-testid="company-stats-companies">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="text-xs text-neutral-500">{t("companyStats.showingN", { shown: data.shown, total: data.total_companies })}</div>
        <div className="flex items-center gap-2">
          <ExportButton t={t} onExport={onExport} />
          <Select value={sort} onValueChange={setSort}>
          <SelectTrigger data-testid="company-stats-companies-sort" className="rounded-none bg-[#0c0c0c] border-white/10 h-9 w-56 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-[#0c0c0c] border-white/10 rounded-none">
            <SelectItem value="commission">{t("companyStats.sortCommission")}</SelectItem>
            <SelectItem value="gross">{t("companyStats.sortGross")}</SelectItem>
            <SelectItem value="orders">{t("companyStats.sortOrders")}</SelectItem>
          </SelectContent>
        </Select>
        </div>
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
            {/* Fila "Sin atribuir": incluye el caso de SÓLO reversiones (EST-R08) */}
            {u && (u.commission_usdt !== 0 || u.orders !== 0 || u.reversed_commission_usdt !== 0 || u.reversed_orders !== 0) && (
              <tr className="border-t border-[#8B5CF6]/30 bg-[#8B5CF6]/5" data-testid="company-row-unattributed">
                <Td><span className="text-[#A78BFA]">{t("companyStats.unattributedRow")}</span></Td>
                <Td right mono tone={u.commission_usdt < 0 ? "neg" : undefined}>{fmt(u.commission_usdt)}</Td>
                <Td right mono>{fmt(u.gross_usdt)}</Td>
                <Td right mono>{u.orders}</Td>
                <Td right mono tone={u.reversed_commission_usdt > 0 ? "neg" : undefined}>{u.reversed_commission_usdt > 0 ? `-${fmt(u.reversed_commission_usdt)} (${u.reversed_orders || 0})` : "—"}</Td>
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
              <Td right>{data.totals.commission_usdt > 0 ? "100%" : "—"}</Td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

function ProductsTab({ t, data, kind, setKind, sort, setSort, onExport }) {
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
        <div className="flex items-center gap-2">
          <ExportButton t={t} onExport={onExport} />
          <Select value={kind === "services" && sort === "commission" ? "gross" : sort} onValueChange={setSort}>
            <SelectTrigger data-testid="company-stats-products-sort" className="rounded-none bg-[#0c0c0c] border-white/10 h-9 w-52 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#0c0c0c] border-white/10 rounded-none">
              <SelectItem value="quantity">{t("companyStats.sortQuantity")}</SelectItem>
              <SelectItem value="gross">{t("companyStats.sortGross")}</SelectItem>
              {kind !== "services" && (
                <SelectItem value="commission">{t("companyStats.sortCommission")}</SelectItem>
              )}
            </SelectContent>
          </Select>
        </div>
      </div>
      {!data ? <Empty t={t} /> : (
        <div className="overflow-x-auto border border-white/10">
          <table className="w-full min-w-[720px]">
            <thead className="bg-white/5">
              <tr>
                <Th>{t(kind === "services" ? "companyStats.colService" : "companyStats.colProduct")}</Th>
                <Th>{t("companyStats.colCompany")}</Th>
                <Th right>{t("companyStats.colQuantity")}</Th>
                <Th>{t("companyStats.colUnit")}</Th>
                <Th right>{t("companyStats.colGross")}</Th>
                <Th right>{t("companyStats.colCommission")}</Th>
                <Th right>{t("companyStats.colOrders")}</Th>
              </tr>
            </thead>
            <tbody>
              {(data.rows || []).length === 0 && (
                <tr><td colSpan={7} className="px-3 py-6 text-center text-neutral-500 text-sm">{t("companyStats.noRows")}</td></tr>
              )}
              {(data.rows || []).map((r) => (
                <tr key={r.id} className="border-t border-white/5" data-testid={`product-row-${r.id}`}>
                  <Td>{r.name}</Td>
                  <Td>{r.company === "Sin atribuir" ? <span className="text-[#A78BFA]">{t("companyStats.unattributedRow")}</span> : r.company}</Td>
                  <Td right mono>{fmt(r.quantity)}</Td>
                  <Td>{r.unit || "—"}</Td>
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

function MessagingTab({ t, data, onExport }) {
  if (!data) return <Empty t={t} />;
  const rows = data.rows || [];
  return (
    <div className="space-y-3" data-testid="company-stats-messaging">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="text-xs text-neutral-500">{t("companyStats.totalDeliveries", { n: data.total_completed })}</div>
        <ExportButton t={t} onExport={onExport} />
      </div>
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
