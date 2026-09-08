import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Checkbox } from "@/components/ui/checkbox";
import { ChevronDown, X } from "lucide-react";

const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
const todayStr = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n) => new Date(Date.now() - n * 86400000).toISOString().slice(0, 10);

function Kpi({ label, value, tone = "", testid }) {
  return (
    <div className="tactile-card px-5 py-4" data-testid={testid}>
      <div className="micro-label text-neutral-500 mb-1">{label}</div>
      <div className={`font-display text-2xl ${tone}`}>{value}</div>
    </div>
  );
}

export default function InventoryDashboardTab() {
  const { t } = useTranslation();
  const [start, setStart] = useState(todayStr());
  const [end, setEnd] = useState(todayStr());
  // iter224 — selección múltiple de mercancías (vacío = todas).
  const [selected, setSelected] = useState([]);
  const [pickerQuery, setPickerQuery] = useState("");
  const [products, setProducts] = useState([]);
  const [data, setData] = useState(null);
  // iter225 — tabla de rotación por mercancía.
  const [rotation, setRotation] = useState([]);

  const load = useCallback((s, e, ids) => {
    const params = { start: s, end: e };
    if (ids && ids.length) params.product_ids = ids.join(",");
    axios.get(`${API}/admin/inventory/dashboard`, { params, withCredentials: true })
      .then((r) => setData(r.data)).catch(() => {});
    axios.get(`${API}/admin/inventory/rotation`, { params, withCredentials: true })
      .then((r) => setRotation(r.data)).catch(() => {});
  }, []);

  useEffect(() => {
    load(start, end, selected);
    axios.get(`${API}/admin/inventory/control`, { withCredentials: true })
      .then((r) => setProducts(r.data)).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const quick = (days) => {
    const s = days === 0 ? todayStr() : daysAgo(days);
    const e = todayStr();
    setStart(s); setEnd(e); load(s, e, selected);
  };

  const toggleProduct = (pid) => {
    const next = selected.includes(pid)
      ? selected.filter((x) => x !== pid)
      : [...selected, pid];
    setSelected(next);
    load(start, end, next);
  };

  const clearSelection = () => { setSelected([]); load(start, end, []); };

  const norm = (s) => (s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  const pickerItems = products.filter((p) => !pickerQuery.trim() || norm(p.name).includes(norm(pickerQuery)));

  return (
    <div className="space-y-6" data-testid="inventory-dashboard">
      <div className="flex items-end gap-3 flex-wrap">
        <div>
          <div className="micro-label text-neutral-500">{t("inventory.dashboard.productLabel")}</div>
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" data-testid="inv-dash-product-picker"
                className="rounded-none border-white/10 h-10 mt-1 min-w-[220px] justify-between text-sm font-normal">
                <span className="truncate">
                  {selected.length === 0
                    ? t("inventory.dashboard.productAll")
                    : t("inventory.dashboard.productsSelected", { count: selected.length })}
                </span>
                <ChevronDown className="w-4 h-4 ml-2 text-neutral-500" />
              </Button>
            </PopoverTrigger>
            <PopoverContent align="start" className="bg-[#1A1730] border-white/10 text-white rounded-none w-[300px] p-3">
              <Input
                data-testid="inv-dash-product-search"
                value={pickerQuery}
                onChange={(e) => setPickerQuery(e.target.value)}
                placeholder={t("inventory.dashboard.productSearch")}
                className="rounded-none bg-[#0a0a0a] border-white/10 h-9 mb-2"
              />
              <div className="max-h-[260px] overflow-y-auto space-y-1" data-testid="inv-dash-product-list">
                {pickerItems.map((p) => (
                  <label key={p.product_id} className="flex items-center gap-2 px-1 py-1.5 hover:bg-white/5 cursor-pointer text-sm">
                    <Checkbox
                      data-testid={`inv-dash-product-check-${p.product_id}`}
                      checked={selected.includes(p.product_id)}
                      onCheckedChange={() => toggleProduct(p.product_id)}
                    />
                    <span className="truncate">{p.name}</span>
                  </label>
                ))}
                {pickerItems.length === 0 && (
                  <div className="text-xs text-neutral-500 py-3 text-center">—</div>
                )}
              </div>
              {selected.length > 0 && (
                <Button variant="outline" size="sm" data-testid="inv-dash-clear-selection"
                  onClick={clearSelection}
                  className="rounded-none border-white/10 text-xs w-full mt-2">
                  <X className="w-3 h-3 mr-1" /> {t("inventory.dashboard.clearSelection")}
                </Button>
              )}
            </PopoverContent>
          </Popover>
        </div>
        <Button variant="outline" data-testid="inv-dash-today" onClick={() => quick(0)} className="rounded-none border-white/10 text-xs">{t("inventory.dashboard.today")}</Button>
        <Button variant="outline" data-testid="inv-dash-7d" onClick={() => quick(7)} className="rounded-none border-white/10 text-xs">{t("inventory.dashboard.last7")}</Button>
        <Button variant="outline" data-testid="inv-dash-30d" onClick={() => quick(30)} className="rounded-none border-white/10 text-xs">{t("inventory.dashboard.last30")}</Button>
        <div>
          <div className="micro-label text-neutral-500">{t("inventory.dashboard.from")}</div>
          <Input data-testid="inv-dash-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10 w-[160px]" />
        </div>
        <div>
          <div className="micro-label text-neutral-500">{t("inventory.dashboard.to")}</div>
          <Input data-testid="inv-dash-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10 w-[160px]" />
        </div>
        <Button data-testid="inv-dash-apply" onClick={() => load(start, end, selected)} className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none">{t("inventory.dashboard.apply")}</Button>
      </div>

      {data && (
        <>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <Kpi testid="kpi-units-sold" label={t("inventory.dashboard.unitsSold")} value={fmt(data.units_sold)} />
            <Kpi testid="kpi-revenue" label={t("inventory.dashboard.revenue")} value={fmt(data.sales_revenue)} tone="text-[#8B5CF6]" />
            <Kpi testid="kpi-cogs" label={t("inventory.dashboard.cogs")} value={fmt(data.cogs)} tone="text-neutral-300" />
            <Kpi testid="kpi-profit" label={t("inventory.dashboard.profit")} value={fmt(data.profit)} tone={data.profit >= 0 ? "text-emerald-400" : "text-red-400"} />
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-4">
            <Kpi testid="kpi-margin" label={t("inventory.dashboard.margin")} value={`${fmt(data.margin_pct)}%`} />
            <Kpi testid="kpi-profitability" label={t("inventory.dashboard.profitability")} value={`${fmt(data.profitability_pct)}%`} tone="text-emerald-400" />
            <Kpi testid="kpi-purchases" label={t("inventory.dashboard.purchases")} value={fmt(data.purchases_out)} tone="text-amber-300" />
            <Kpi testid="kpi-net-flow" label={t("inventory.dashboard.netFlow")} value={fmt(data.net_cash_flow)} tone={data.net_cash_flow >= 0 ? "text-emerald-400" : "text-red-400"} />
            <Kpi testid="kpi-inv-value" label={t("inventory.dashboard.invValue")} value={fmt(data.inventory_value)} />
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-4">
            <Kpi testid="kpi-units-stock" label={t("inventory.dashboard.unitsInStock")} value={fmt(data.units_in_stock)} />
            {data.vip_commission_earned !== null && data.vip_commission_earned !== undefined && (
              <Kpi testid="kpi-vip-commission" label={t("inventory.dashboard.vipCommission")} value={fmt(data.vip_commission_earned)} tone="text-amber-300" />
            )}
          </div>

          {/* iter225 — rotación de inventario por mercancía */}
          <div>
            <h3 className="font-display text-lg mb-3">{t("inventory.dashboard.rotationTitle")}</h3>
            <p className="text-xs text-neutral-500 mb-3">{t("inventory.dashboard.rotationHint")}</p>
            <div className="tactile-card overflow-auto max-h-[55vh]" data-testid="inventory-rotation-table">
              <table className="w-full text-sm min-w-[900px]">
                <thead className="border-b border-white/10 bg-[#0a0a0a] sticky top-0 z-10">
                  <tr className="text-left">
                    <th className="px-4 py-3 micro-label text-neutral-500">{t("inventory.dashboard.rotProduct")}</th>
                    <th className="px-4 py-3 micro-label text-neutral-500">{t("inventory.dashboard.rotSuggestion")}</th>
                    <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.dashboard.rotSold")}</th>
                    <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.dashboard.rotDaily")}</th>
                    <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.dashboard.rotStock")}</th>
                    <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.dashboard.rotSellout")}</th>
                    <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.dashboard.rotRotation")}</th>
                    <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.dashboard.rotLastRestock")}</th>
                    <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("inventory.dashboard.rotRestockCycle")}</th>
                  </tr>
                </thead>
                <tbody>
                  {rotation.length === 0 && (
                    <tr><td colSpan="9" className="text-center text-neutral-500 py-8">—</td></tr>
                  )}
                  {rotation.map((r) => (
                    <tr key={r.product_id} className={`border-b border-white/5 ${r.restock_suggestion === "ya" ? "bg-red-500/5" : ""}`} data-testid={`rotation-row-${r.product_id}`}>
                      <td className="px-4 py-3">{r.name}</td>
                      <td className="px-4 py-3" data-testid={`rotation-suggestion-${r.product_id}`}>
                        {r.restock_suggestion === "ya" && (
                          <span className="text-[0.65rem] uppercase tracking-wider px-2 py-0.5 border bg-red-500/10 text-red-400 border-red-500/30 whitespace-nowrap">
                            {t("inventory.dashboard.rotRestockNow", { qty: r.suggested_qty })}
                          </span>
                        )}
                        {r.restock_suggestion === "pronto" && (
                          <span className="text-[0.65rem] uppercase tracking-wider px-2 py-0.5 border bg-amber-500/10 text-amber-300 border-amber-500/30 whitespace-nowrap">
                            {t("inventory.dashboard.rotRestockSoon", { qty: r.suggested_qty })}
                          </span>
                        )}
                        {!r.restock_suggestion && <span className="text-neutral-600">—</span>}
                      </td>
                      <td className="px-4 py-3 font-mono text-right text-amber-300">{r.sold}</td>
                      <td className="px-4 py-3 font-mono text-right">{fmt(r.daily_rate)}</td>
                      <td className="px-4 py-3 font-mono text-right">{r.stock}</td>
                      <td className={`px-4 py-3 font-mono text-right ${r.sellout_days !== null && r.sellout_days <= 3 ? "text-red-400" : ""}`}>
                        {r.sellout_days !== null ? t("inventory.dashboard.rotDays", { count: fmt(r.sellout_days) }) : "—"}
                      </td>
                      <td className="px-4 py-3 font-mono text-right text-[#8B5CF6]">{fmt(r.rotation)}×</td>
                      <td className="px-4 py-3 font-mono text-right text-neutral-400">
                        {r.days_since_restock !== null ? t("inventory.dashboard.rotDaysAgo", { count: r.days_since_restock }) : "—"}
                      </td>
                      <td className="px-4 py-3 font-mono text-right text-neutral-400">
                        {r.restock_cycle_days !== null ? t("inventory.dashboard.rotDays", { count: fmt(r.restock_cycle_days) }) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
