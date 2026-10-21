/**
 * Panel de Comisiones — Marketplace Empresas.
 *
 * Desglose POR PEDIDO de la venta bruta, la comisión del 1 % que retiene la
 * plataforma (en USDT) y el neto liquidado a la empresa vendedora. Vive dentro
 * de la sección "Fondo Empresa" del dashboard de ingresos y es visible para el
 * admin o el miembro del staff con permiso `company_funds`.
 *
 * Dos vistas: "Por pedido" (detalle) y "Por empresa" (subtotales ordenados por
 * comisión → quién genera más). Buscador por nombre de empresa; al pulsar una
 * fila agrupada se filtra el detalle por esa empresa.
 */
import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { toast } from "sonner";
import {
  Percent, TrendingUp, Banknote, Package, ChevronLeft, ChevronRight,
  RotateCcw, Search, X, Trophy, Building2, Download,
} from "lucide-react";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useLiveRefresh } from "@/hooks/useLiveStream";

const PAGE_SIZE = 25;

const fmt2 = (n) =>
  Number(n || 0).toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });

// La comisión del 1 % puede ser sub-céntimo (0,10 USDT → 0,001): hasta 6 dec.
const fmtFine = (n) =>
  Number(n || 0).toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 6,
  });

const fmtDate = (iso) => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      day: "2-digit", month: "short", year: "numeric",
    });
  } catch {
    return "—";
  }
};

export default function CommissionsPanel() {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [days, setDays] = useState("all");
  const [view, setView] = useState("orders"); // "orders" | "company"
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [companyId, setCompanyId] = useState("");  // filtro exacto desde vista agrupada
  const [companyLabel, setCompanyLabel] = useState("");
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);

  // Debounce del buscador de texto.
  useEffect(() => {
    const id = setTimeout(() => { setDebounced(search.trim()); setPage(0); }, 400);
    return () => clearTimeout(id);
  }, [search]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { skip: page * PAGE_SIZE, limit: PAGE_SIZE };
      if (days !== "all") params.days = parseInt(days);
      if (companyId) params.company_id = companyId;
      else if (debounced) params.company = debounced;
      const res = await axios.get(`${API}/admin/company-funds/commissions`, {
        params, withCredentials: true,
      });
      setData(res.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || t("admin.common.genericError"));
    } finally {
      setLoading(false);
    }
  }, [days, page, debounced, companyId, t]);

  useEffect(() => { load(); }, [load]);
  useLiveRefresh(load, ["ledger_changed", "order_status_changed"]);

  const onPeriodChange = (v) => { setPage(0); setDays(v); };

  // Al pulsar una empresa en la vista agrupada → filtrar detalle por esa empresa.
  const focusCompany = (c) => {
    setCompanyId(c.company_id);
    setCompanyLabel(c.company);
    setSearch("");
    setDebounced("");
    setPage(0);
    setView("orders");
  };

  const clearCompanyFilter = () => {
    setCompanyId("");
    setCompanyLabel("");
    setSearch("");
    setDebounced("");
    setPage(0);
  };

  // Descarga CSV del desglose, respetando periodo + filtro de empresa + vista
  // activa ("orders" → por pedido, "company" → subtotales por empresa).
  const exportCsv = async () => {
    setExporting(true);
    try {
      const params = new URLSearchParams();
      if (days !== "all") params.set("days", String(parseInt(days)));
      if (companyId) params.set("company_id", companyId);
      else if (debounced) params.set("company", debounced);
      params.set("group", view);
      const url = `${API}/admin/company-funds/commissions/export.csv?${params.toString()}`;
      const r = await axios.get(url, { responseType: "blob", withCredentials: true });
      const blobUrl = URL.createObjectURL(
        new Blob([r.data], { type: r.headers["content-type"] || "text/csv" }));
      const a = document.createElement("a");
      a.href = blobUrl;
      const ts = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
      a.download = `comisiones_${view}_${ts}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(blobUrl);
      toast.success(t("admin.commissions.exportedToast"));
    } catch (e) {
      toast.error(e.response?.data?.detail || t("admin.commissions.exportError"));
    } finally {
      setExporting(false);
    }
  };

  const totals = data?.totals || {};
  const rows = data?.rows || [];
  const byCompany = data?.by_company || [];
  const total = data?.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const activeFilter = companyId ? companyLabel : debounced;

  return (
    <section className="tactile-card p-5 space-y-5" data-testid="commissions-panel">
      {/* Header */}
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <div className="flex items-center gap-2 text-[0.6rem] uppercase tracking-widest text-[#8B5CF6]">
            <Percent className="w-3.5 h-3.5" />
            {t("admin.commissions.eyebrow")}
          </div>
          <h3 className="font-display text-xl mt-1">{t("admin.commissions.title")}</h3>
          <p className="text-neutral-400 text-sm mt-1 max-w-2xl">
            {t("admin.commissions.subtitle")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            data-testid="commissions-export"
            onClick={exportCsv}
            disabled={exporting || loading}
            variant="outline"
            className="rounded-none border-white/15 hover:bg-white/5 h-10 text-xs uppercase tracking-wide"
          >
            <Download className="w-3.5 h-3.5 mr-2" />
            {exporting ? t("admin.commissions.exporting") : t("admin.commissions.exportCsv")}
          </Button>
          <Select value={days} onValueChange={onPeriodChange}>
            <SelectTrigger
              data-testid="commissions-period"
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-40"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
              <SelectItem value="all">{t("admin.commissions.allTime")}</SelectItem>
              <SelectItem value="7">{t("admin.commissions.last7")}</SelectItem>
              <SelectItem value="30">{t("admin.commissions.last30")}</SelectItem>
              <SelectItem value="90">{t("admin.commissions.last90")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Summary tiles */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <SummaryTile
          icon={Banknote} label={t("admin.commissions.totalSales")}
          value={fmt2(totals.gross_usdt)} unit="USDT"
          testid="commissions-total-sales"
        />
        <SummaryTile
          icon={Percent} label={t("admin.commissions.totalCommission")}
          value={fmtFine(totals.commission_usdt)} unit="USDT" accent="violet"
          testid="commissions-total-commission"
        />
        <SummaryTile
          icon={TrendingUp} label={t("admin.commissions.totalNet")}
          value={fmt2(totals.net_usdt)} unit="USDT" accent="green"
          testid="commissions-total-net"
        />
        <SummaryTile
          icon={Package} label={t("admin.commissions.orders")}
          value={String(totals.orders ?? 0)}
          testid="commissions-total-orders"
        />
      </div>

      {totals.reversed_orders > 0 && (
        <div
          className="flex items-center gap-2 text-xs text-[#F59E0B] border border-[#F59E0B]/25 bg-[#F59E0B]/5 px-3 py-2 rounded-sm"
          data-testid="commissions-reversed-note"
        >
          <RotateCcw className="w-3.5 h-3.5 shrink-0" />
          {t("admin.commissions.reversedNote", {
            n: totals.reversed_orders,
            amount: fmtFine(totals.reversed_commission_usdt),
          })}
        </div>
      )}

      {/* Toolbar: view toggle + search */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="inline-flex border border-white/10 rounded-sm overflow-hidden" data-testid="commissions-view-toggle">
          <button
            type="button"
            data-testid="commissions-view-orders"
            onClick={() => setView("orders")}
            className={`px-3 h-9 text-xs uppercase tracking-wide transition-colors ${
              view === "orders" ? "bg-[#8B5CF6] text-white" : "text-neutral-400 hover:bg-white/5"
            }`}
          >
            {t("admin.commissions.viewByOrder")}
          </button>
          <button
            type="button"
            data-testid="commissions-view-company"
            onClick={() => setView("company")}
            className={`px-3 h-9 text-xs uppercase tracking-wide transition-colors ${
              view === "company" ? "bg-[#8B5CF6] text-white" : "text-neutral-400 hover:bg-white/5"
            }`}
          >
            {t("admin.commissions.viewByCompany")}
          </button>
        </div>

        <div className="relative w-full sm:w-64">
          <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-neutral-500 pointer-events-none" />
          <Input
            data-testid="commissions-search"
            value={companyId ? companyLabel : search}
            disabled={!!companyId}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("admin.commissions.searchPlaceholder")}
            className="rounded-none bg-[#0a0a0a] border-white/10 h-9 pl-8 pr-8 text-sm"
          />
          {activeFilter && (
            <button
              type="button"
              data-testid="commissions-clear-search"
              onClick={clearCompanyFilter}
              title={t("admin.commissions.clearSearch")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-neutral-500 hover:text-white"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {companyId && (
        <div className="text-xs text-neutral-400" data-testid="commissions-active-filter">
          {t("admin.commissions.filteringBy", { name: companyLabel })}
        </div>
      )}

      {/* ====== VIEW: BY COMPANY ====== */}
      {view === "company" && (
        <div className="overflow-x-auto">
          <p className="text-[0.65rem] text-neutral-500 mb-2 flex items-center gap-1.5">
            <Building2 className="w-3 h-3" /> {t("admin.commissions.companyHint")}
          </p>
          <table className="w-full text-sm border-collapse" data-testid="commissions-company-table">
            <thead>
              <tr className="text-[0.6rem] uppercase tracking-widest text-neutral-500 border-b border-white/10">
                <th className="text-left font-medium py-2 pr-3 w-8">{t("admin.commissions.colRank")}</th>
                <th className="text-left font-medium py-2 pr-3">{t("admin.commissions.colCompany")}</th>
                <th className="text-right font-medium py-2 pr-3">{t("admin.commissions.colOrders")}</th>
                <th className="text-right font-medium py-2 pr-3">{t("admin.commissions.colSale")}</th>
                <th className="text-right font-medium py-2 pr-3">{t("admin.commissions.colCommission")}</th>
                <th className="text-right font-medium py-2 pl-3">{t("admin.commissions.colNet")}</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={6} className="py-6 text-center text-neutral-500" data-testid="commissions-company-loading">
                  {t("admin.commissions.loading")}
                </td></tr>
              )}
              {!loading && byCompany.length === 0 && (
                <tr><td colSpan={6} className="py-8 text-center text-neutral-500" data-testid="commissions-company-empty">
                  {t("admin.commissions.emptyCompany")}
                </td></tr>
              )}
              {!loading && byCompany.map((c, i) => (
                <tr
                  key={c.company_id || i}
                  onClick={() => focusCompany(c)}
                  className="border-b border-white/5 hover:bg-white/[0.04] transition-colors cursor-pointer"
                  data-testid={`commission-company-row-${c.company_id || i}`}
                >
                  <td className="py-2.5 pr-3 text-neutral-500 tabular-nums">
                    {i === 0 ? (
                      <Trophy className="w-4 h-4 text-[#F59E0B]" title={t("admin.commissions.topEarner")} />
                    ) : i + 1}
                  </td>
                  <td className="py-2.5 pr-3 text-neutral-100 font-medium">{c.company}</td>
                  <td className="py-2.5 pr-3 text-right tabular-nums text-neutral-300">{c.orders}</td>
                  <td className="py-2.5 pr-3 text-right font-mono tabular-nums text-neutral-200">{fmt2(c.gross_usdt)}</td>
                  <td className="py-2.5 pr-3 text-right font-mono tabular-nums text-[#8B5CF6]">{fmtFine(c.commission_usdt)}</td>
                  <td className="py-2.5 pl-3 text-right font-mono tabular-nums text-[#22C55E]">{fmt2(c.net_usdt)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ====== VIEW: BY ORDER ====== */}
      {view === "orders" && (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm border-collapse" data-testid="commissions-table">
              <thead>
                <tr className="text-[0.6rem] uppercase tracking-widest text-neutral-500 border-b border-white/10">
                  <th className="text-left font-medium py-2 pr-3">{t("admin.commissions.colDate")}</th>
                  <th className="text-left font-medium py-2 pr-3">{t("admin.commissions.colCompany")}</th>
                  <th className="text-left font-medium py-2 pr-3">{t("admin.commissions.colProduct")}</th>
                  <th className="text-right font-medium py-2 pr-3">{t("admin.commissions.colSale")}</th>
                  <th className="text-right font-medium py-2 pr-3">{t("admin.commissions.colCommission")}</th>
                  <th className="text-right font-medium py-2 pl-3">{t("admin.commissions.colNet")}</th>
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr><td colSpan={6} className="py-6 text-center text-neutral-500" data-testid="commissions-loading">
                    {t("admin.commissions.loading")}
                  </td></tr>
                )}
                {!loading && rows.length === 0 && (
                  <tr><td colSpan={6} className="py-8 text-center text-neutral-500" data-testid="commissions-empty">
                    {t("admin.commissions.empty")}
                  </td></tr>
                )}
                {!loading && rows.map((r) => (
                  <tr
                    key={r.id}
                    className="border-b border-white/5 hover:bg-white/[0.02] transition-colors"
                    data-testid={`commission-row-${r.id}`}
                  >
                    <td className="py-2.5 pr-3 text-neutral-400 whitespace-nowrap">{fmtDate(r.date)}</td>
                    <td className="py-2.5 pr-3 text-neutral-200">{r.company}</td>
                    <td className="py-2.5 pr-3 text-neutral-300">
                      <span className="text-neutral-500 tabular-nums">{r.quantity}×</span> {r.product_name}
                    </td>
                    <td className="py-2.5 pr-3 text-right font-mono tabular-nums text-neutral-200">
                      {fmt2(r.gross_usdt)}
                    </td>
                    <td className="py-2.5 pr-3 text-right font-mono tabular-nums">
                      <span className={r.reversed ? "text-neutral-500 line-through" : "text-[#8B5CF6]"}>
                        {fmtFine(r.commission_usdt)}
                      </span>
                      <span className="text-[0.6rem] text-neutral-600 ml-1">
                        {Number(r.commission_pct || 0)}%
                      </span>
                      {r.reversed && (
                        <span className="block text-[0.55rem] text-[#F59E0B] uppercase tracking-wide">
                          {t("admin.commissions.reversed")}
                        </span>
                      )}
                    </td>
                    <td className="py-2.5 pl-3 text-right font-mono tabular-nums text-[#22C55E]">
                      {fmt2(r.net_usdt)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {total > PAGE_SIZE && (
            <div className="flex items-center justify-between gap-3 pt-1">
              <span className="text-xs text-neutral-500" data-testid="commissions-page-info">
                {t("admin.commissions.pageInfo", { page: page + 1, pages: totalPages })}
              </span>
              <div className="flex items-center gap-2">
                <Button
                  data-testid="commissions-prev"
                  variant="outline" size="sm"
                  disabled={page === 0 || loading}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  className="rounded-none border-white/15 hover:bg-white/5 h-9"
                >
                  <ChevronLeft className="w-4 h-4" />
                </Button>
                <Button
                  data-testid="commissions-next"
                  variant="outline" size="sm"
                  disabled={page + 1 >= totalPages || loading}
                  onClick={() => setPage((p) => p + 1)}
                  className="rounded-none border-white/15 hover:bg-white/5 h-9"
                >
                  <ChevronRight className="w-4 h-4" />
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function SummaryTile({ icon: Icon, label, value, unit, accent, testid }) {
  const color =
    accent === "violet" ? "text-[#8B5CF6]"
      : accent === "green" ? "text-[#22C55E]"
        : "text-neutral-100";
  return (
    <div className="px-3 py-3 border border-white/10 bg-white/[0.02] rounded-sm" data-testid={testid}>
      <div className="flex items-center gap-1.5 text-[0.55rem] uppercase tracking-widest text-neutral-500">
        <Icon className="w-3 h-3" />
        <span className="truncate">{label}</span>
      </div>
      <div className={`font-display text-xl mt-1 tabular-nums ${color}`}>
        {value}
        {unit && <span className="text-[0.6rem] text-neutral-500 ml-1 font-sans">{unit}</span>}
      </div>
    </div>
  );
}
