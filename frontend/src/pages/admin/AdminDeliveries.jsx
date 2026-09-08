import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { toast } from "sonner";
import { Truck, Search } from "lucide-react";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";
import { etaFromDelivery } from "@/services/deliveryEta";
import DeliveryDetailsDialog from "./deliveries/DeliveryDetailsDialog";
import MunicipalityRatesTab from "./deliveries/MunicipalityRatesTab";
import CourierPanel from "@/pages/dashboard/CourierPanel";

// iter199 — Admin: gestión de entregas de mensajería + alta de mensajeros.

const STATUSES = ["available", "accepted", "on_the_way", "arrived", "delivered", "confirmed", "cancelled"];

const STATUS_COLOR = {
  available: "text-neutral-400",
  accepted: "text-[#8B5CF6]",
  on_the_way: "text-amber-300",
  arrived: "text-sky-300",
  delivered: "text-[#22C55E]",
  confirmed: "text-[#22C55E]",
  cancelled: "text-[#EF4444]",
};

// iter207c — el staff ve a cuántos minutos está el mensajero de entregar.
function DeliveryEta({ d, t }) {
  if (!["accepted", "on_the_way"].includes(d.status)) return null;
  const eta = etaFromDelivery(d);
  if (!eta) return null;
  return (
    <div
      className="normal-case tracking-normal text-[0.65rem] text-[#A78BFA] mt-1"
      data-testid={`admin-eta-${d.id}`}
    >
      {t("admin.deliveries.etaInline", { min: eta.min, km: eta.km.toFixed(1) })}
      {eta.ageMin != null && (
        <span className="text-neutral-500"> · {t("admin.deliveries.locAge", { m: eta.ageMin })}</span>
      )}
    </div>
  );
}

function DeliveriesTab({ navigate }) {
  const { t } = useTranslation();
  const [rows, setRows] = useState([]);
  const [couriers, setCouriers] = useState([]);
  const [statusFilter, setStatusFilter] = useState("all");
  const [pendingConfirm, setPendingConfirm] = useState(null);
  const [detailsRow, setDetailsRow] = useState(null);
  // iter216 — resumen del día de TODO el equipo.
  // iter217 — con selector de fecha para revisar jornadas pasadas.
  const [summary, setSummary] = useState(null);
  const todayStr = new Date().toISOString().slice(0, 10);
  const [summaryDate, setSummaryDate] = useState(todayStr);

  const load = useCallback(() => {
    const params = statusFilter !== "all" ? { status: statusFilter } : {};
    axios.get(`${API}/admin/deliveries`, { params, withCredentials: true })
      .then((r) => setRows(r.data)).catch(() => setRows([]));
    axios.get(`${API}/admin/couriers`, { withCredentials: true })
      .then((r) => setCouriers(r.data)).catch(() => setCouriers([]));
  }, [statusFilter]);

  useEffect(() => {
    const fetchSummary = () =>
      axios.get(`${API}/admin/deliveries/summary`, {
        params: { date: summaryDate }, withCredentials: true,
      }).then((r) => setSummary(r.data)).catch(() => {});
    fetchSummary();
    const iv = setInterval(fetchSummary, 20000);
    return () => clearInterval(iv);
  }, [summaryDate]);

  useEffect(() => {
    load();
    const iv = setInterval(load, 20000);
    return () => clearInterval(iv);
  }, [load]);

  const assign = async (d, courierId) => {
    try {
      await axios.post(`${API}/admin/deliveries/${d.id}/assign`,
        { courier_id: courierId }, { withCredentials: true });
      toast.success(t("admin.deliveries.assigned"));
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    }
  };

  const confirmWithTotp = async (code) => {
    try {
      await axios.post(`${API}/admin/deliveries/${pendingConfirm.id}/confirm`,
        { totp_code: code }, { withCredentials: true });
      toast.success(t("admin.deliveries.confirmed"));
      setPendingConfirm(null);
      load();
    } catch (e) {
      if (!handleTotpError(e, navigate)) {
        toast.error(e.response?.data?.detail || "Error");
      }
    }
  };

  const cancel = async (d) => {
    try {
      await axios.post(`${API}/admin/deliveries/${d.id}/cancel`, {}, { withCredentials: true });
      toast.success(t("admin.deliveries.cancelled"));
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    }
  };

  return (
    <div className="space-y-4">
      {/* iter216 — Resumen del día de TODO el equipo (iter217: fecha elegible) */}
      {summary && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="micro-label text-neutral-500">{t("admin.deliveries.summary.dateLabel")}</span>
            <input
              type="date"
              value={summaryDate}
              max={todayStr}
              onChange={(e) => e.target.value && setSummaryDate(e.target.value)}
              data-testid="team-summary-date"
              className="bg-[#0a0a0a] border border-white/10 text-white text-xs px-2 h-8 rounded-none [color-scheme:dark]"
            />
            {summaryDate !== todayStr && (
              <button
                onClick={() => setSummaryDate(todayStr)}
                data-testid="team-summary-today-btn"
                className="text-xs text-[#8B5CF6] hover:underline"
              >
                {t("admin.deliveries.summary.todayBtn")}
              </button>
            )}
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-testid="team-summary-cards">
          <div className="tactile-card p-3.5" data-testid="team-confirmed-today">
            <div className="micro-label text-neutral-500">
              {summaryDate === todayStr
                ? t("admin.deliveries.summary.confirmedToday")
                : t("admin.deliveries.summary.confirmedOn", { d: summaryDate })}
            </div>
            <div className="font-display text-2xl mt-1">{summary.confirmed_count}</div>
            <div className="text-[0.65rem] text-neutral-500 mt-0.5">
              {t("admin.deliveries.summary.totalFees", { v: summary.total_fees_usdt })}
            </div>
          </div>
          <div className="tactile-card p-3.5" data-testid="team-courier-earned">
            <div className="micro-label text-neutral-500">
              {summaryDate === todayStr
                ? t("admin.deliveries.summary.teamEarned")
                : t("admin.deliveries.summary.teamEarnedOn", { d: summaryDate })}
            </div>
            <div className="font-display text-2xl mt-1 text-[#22C55E]">
              {summary.courier_earned_usdt} <span className="text-sm">USDT</span>
            </div>
            <div className="text-[0.65rem] text-neutral-500 mt-0.5 truncate" data-testid="team-by-courier">
              {(summary.by_courier || []).length > 0
                ? summary.by_courier.map((c) => `${c.courier_name} ${c.count}×(${c.earned_usdt})`).join(" · ")
                : t("admin.deliveries.summary.noneToday")}
            </div>
          </div>
          <div className="tactile-card p-3.5" data-testid="team-platform-earned">
            <div className="micro-label text-neutral-500">
              {summaryDate === todayStr
                ? t("admin.deliveries.summary.platformEarned")
                : t("admin.deliveries.summary.platformEarnedOn", { d: summaryDate })}
            </div>
            <div className="font-display text-2xl mt-1 text-[#8B5CF6]">
              {summary.platform_earned_usdt} <span className="text-sm">USDT</span>
            </div>
            <div className="text-[0.65rem] text-neutral-500 mt-0.5">
              {t("admin.deliveries.summary.splitNote")}
            </div>
          </div>
          <div className="tactile-card p-3.5" data-testid="team-active-now">
            <div className="micro-label text-neutral-500">{t("admin.deliveries.summary.activeNow")}</div>
            <div className="font-display text-2xl mt-1 text-amber-400">{summary.active_count}</div>
            <div className="text-[0.65rem] text-neutral-500 mt-0.5">
              {t("admin.deliveries.summary.activeDetail", {
                available: summary.available_count,
                pending: summary.delivered_pending_count,
              })}
            </div>
          </div>
          </div>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => setStatusFilter("all")}
          data-testid="deliveries-filter-all"
          className={`px-3 py-1.5 text-xs border ${statusFilter === "all" ? "border-[#8B5CF6] text-[#8B5CF6]" : "border-white/10 text-neutral-500"}`}
        >
          {t("admin.deliveries.filterAll")}
        </button>
        {STATUSES.map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            data-testid={`deliveries-filter-${s}`}
            className={`px-3 py-1.5 text-xs border ${statusFilter === s ? "border-[#8B5CF6] text-[#8B5CF6]" : "border-white/10 text-neutral-500"}`}
          >
            {t(`courierPanel.status.${s}`)}
          </button>
        ))}
      </div>

      <div className="tactile-card overflow-x-auto">
        <table className="w-full text-sm min-w-[900px]">
          <thead className="border-b border-white/10 bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.deliveries.colOp")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.deliveries.colClient")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.deliveries.colAddress")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.deliveries.colFee")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.deliveries.colCourier")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.deliveries.colStatus")}</th>
              <th className="px-3 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan="7" className="text-center text-neutral-500 py-8">{t("admin.deliveries.empty")}</td></tr>
            )}
            {rows.map((d) => (
              <tr
                key={d.id}
                className="border-b border-white/5 hover:bg-white/[0.02] cursor-pointer transition-colors"
                data-testid={`delivery-row-${d.id}`}
                onClick={() => setDetailsRow(d)}
              >
                <td className="px-3 py-3">
                  <div className="text-xs">{t(
                    d.kind === "withdrawal" ? "courierPanel.kindWithdrawal"
                    : d.kind === "deposit" ? "courierPanel.kindDeposit"
                    : "courierPanel.kindRedemption"
                  )}</div>
                  <div className="font-mono text-[0.65rem] text-neutral-500">#{d.ref_id?.slice(0, 8)} · {d.amount_label}</div>
                </td>
                <td className="px-3 py-3 text-xs">{d.client_name}</td>
                <td className="px-3 py-3 text-xs max-w-[220px]">
                  <span className="block truncate">{d.address}{d.province ? ` · ${d.province}` : ""}</span>
                  {d.delivery_latitude != null && d.delivery_longitude != null && (
                    <a
                      href={`https://www.google.com/maps/dir/?api=1&destination=${d.delivery_latitude},${d.delivery_longitude}`}
                      target="_blank"
                      rel="noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      data-testid={`admin-delivery-map-${d.id}`}
                      className="text-[0.65rem] text-[#8B5CF6] hover:text-[#A78BFA] underline underline-offset-2"
                    >
                      Ver en mapa (GPS)
                    </a>
                  )}
                </td>
                <td className="px-3 py-3 font-mono text-xs">
                  {d.km > 0 ? `${d.km} km · ` : ""}{d.fee_usdt} USDT
                  <div className="text-[0.6rem] text-[#22C55E]">{d.courier_share_usdt} / <span className="text-neutral-500">{d.platform_share_usdt}</span></div>
                </td>
                <td className="px-3 py-3 text-xs" onClick={(e) => e.stopPropagation()}>
                  {["available", "accepted"].includes(d.status) ? (
                    <Select value={d.courier_id || ""} onValueChange={(v) => assign(d, v)}>
                      <SelectTrigger className="h-8 w-[150px] rounded-none bg-[#0a0a0a] border-white/10 text-xs" data-testid={`assign-courier-${d.id}`}>
                        <SelectValue placeholder={t("admin.deliveries.assignPlaceholder")} />
                      </SelectTrigger>
                      <SelectContent className="bg-[#1A1730] border-white/10 text-white max-h-64">
                        {couriers.map((c) => (
                          <SelectItem key={c.user_id} value={c.user_id}>{c.name || c.email}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (d.courier_name || "—")}
                </td>
                <td className={`px-3 py-3 text-xs uppercase tracking-wider ${STATUS_COLOR[d.status] || ""}`}>
                  {t(`courierPanel.status.${d.status}`)}
                  <DeliveryEta d={d} t={t} />
                </td>
                <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
                  <div className="flex gap-1.5 justify-end">
                    {d.status === "delivered" && (
                      <Button
                        size="sm"
                        onClick={() => setPendingConfirm(d)}
                        data-testid={`confirm-delivery-${d.id}`}
                        className="bg-[#22C55E] text-black rounded-none h-7 text-xs"
                      >
                        {t("admin.deliveries.confirmBtn")}
                      </Button>
                    )}
                    {!["confirmed", "cancelled"].includes(d.status) && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => cancel(d)}
                        data-testid={`cancel-delivery-${d.id}`}
                        className="border-[#EF4444]/40 text-[#EF4444] rounded-none h-7 text-xs hover:bg-[#EF4444]/10"
                      >
                        ✕
                      </Button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <TotpPromptDialog
        open={!!pendingConfirm}
        title={t("admin.deliveries.confirmTotpTitle")}
        description={pendingConfirm
          ? t("admin.deliveries.confirmTotpDesc", {
              share: pendingConfirm.courier_share_usdt,
              courier: pendingConfirm.courier_name || "",
            })
          : ""}
        onConfirm={confirmWithTotp}
        onCancel={() => setPendingConfirm(null)}
      />

      <DeliveryDetailsDialog
        delivery={detailsRow}
        open={!!detailsRow}
        onClose={() => setDetailsRow(null)}
      />
    </div>
  );
}

function CouriersTab({ navigate }) {
  const { t } = useTranslation();
  const [couriers, setCouriers] = useState([]);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [pendingToggle, setPendingToggle] = useState(null);

  const load = useCallback(() => {
    axios.get(`${API}/admin/couriers`, { withCredentials: true })
      .then((r) => setCouriers(r.data)).catch(() => setCouriers([]));
  }, []);

  useEffect(() => { load(); }, [load]);

  const search = async () => {
    if (query.trim().length < 2) return;
    try {
      const r = await axios.get(`${API}/admin/users`, {
        params: { q: query.trim(), limit: 10 }, withCredentials: true,
      });
      setResults(r.data?.users || r.data || []);
    } catch {
      setResults([]);
    }
  };

  const toggleWithTotp = async (code) => {
    try {
      await axios.put(`${API}/admin/users/${pendingToggle.user_id}`,
        { is_courier: pendingToggle.enable, totp_code: code },
        { withCredentials: true });
      toast.success(pendingToggle.enable
        ? t("admin.deliveries.courierEnabled")
        : t("admin.deliveries.courierDisabled"));
      setPendingToggle(null);
      setResults([]);
      setQuery("");
      load();
    } catch (e) {
      if (!handleTotpError(e, navigate)) {
        toast.error(e.response?.data?.detail || "Error");
      }
    }
  };

  return (
    <div className="space-y-6">
      <div className="tactile-card p-4 space-y-3">
        <div className="micro-label text-neutral-500">{t("admin.deliveries.addCourierLabel")}</div>
        <div className="flex gap-2">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()}
            placeholder={t("admin.deliveries.searchPlaceholder")}
            data-testid="courier-search-input"
            className="rounded-none bg-[#0a0a0a] border-white/10 h-10"
          />
          <Button onClick={search} data-testid="courier-search-btn" className="bg-[#8B5CF6] text-white rounded-none h-10">
            <Search className="w-4 h-4" />
          </Button>
        </div>
        {results.length > 0 && (
          <div className="border border-white/10 divide-y divide-white/5">
            {results.map((u) => (
              <div key={u.user_id} className="flex items-center justify-between px-3 py-2 text-sm">
                <div>
                  <div>{u.name}</div>
                  <div className="text-xs text-neutral-500">{u.email} · {u.role}{u.is_courier ? " · mensajero" : ""}</div>
                </div>
                {!u.is_courier && (
                  <Button
                    size="sm"
                    onClick={() => setPendingToggle({ user_id: u.user_id, enable: true, name: u.name })}
                    data-testid={`make-courier-${u.user_id}`}
                    className="bg-[#22C55E] text-black rounded-none h-7 text-xs"
                  >
                    {t("admin.deliveries.makeCourierBtn")}
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="tactile-card overflow-x-auto">
        <table className="w-full text-sm min-w-[640px]">
          <thead className="border-b border-white/10 bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.deliveries.colName")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.deliveries.colRole")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.deliveries.colPhone")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.deliveries.colEarned")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.deliveries.colCompleted")}</th>
              <th className="px-3 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {couriers.map((c) => (
              <tr key={c.user_id} className="border-b border-white/5" data-testid={`courier-row-${c.user_id}`}>
                <td className="px-3 py-3">
                  <div>{c.name}</div>
                  <div className="text-xs text-neutral-500">{c.email}</div>
                </td>
                <td className="px-3 py-3 text-xs uppercase">
                  {c.role}{c.is_courier ? <span className="text-[#8B5CF6]"> · {t("admin.deliveries.courierBadge")}</span> : ""}
                </td>
                <td className="px-3 py-3 text-xs" data-testid={`courier-phone-${c.user_id}`}>
                  {c.phone ? (
                    <a href={`tel:${c.phone}`} className="font-mono text-[#22C55E] hover:underline">{c.phone}</a>
                  ) : (
                    <span className="text-amber-400">{t("admin.deliveries.noPhone")}</span>
                  )}
                </td>
                <td className="px-3 py-3 font-mono text-[#22C55E]">{c.earned_usdt} USDT</td>
                <td className="px-3 py-3 font-mono">{c.deliveries_count}</td>
                <td className="px-3 py-3 text-right">
                  {c.is_courier && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setPendingToggle({ user_id: c.user_id, enable: false, name: c.name })}
                      data-testid={`remove-courier-${c.user_id}`}
                      className="border-[#EF4444]/40 text-[#EF4444] rounded-none h-7 text-xs hover:bg-[#EF4444]/10"
                    >
                      {t("admin.deliveries.removeCourierBtn")}
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <TotpPromptDialog
        open={!!pendingToggle}
        title={t("admin.deliveries.toggleTotpTitle")}
        description={pendingToggle?.name || ""}
        onConfirm={toggleWithTotp}
        onCancel={() => setPendingToggle(null)}
      />
    </div>
  );
}

export default function AdminDeliveries() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [tab, setTab] = useState("deliveries");
  // iter209 — El staff/admin también puede ser mensajero: pestaña "Mis
  // entregas" con el mismo flujo Aceptar/Rechazar del panel del mensajero.
  const [myCounts, setMyCounts] = useState({ reserved: 0, active: 0 });
  const autoOpened = useRef(false);

  useEffect(() => {
    const load = () =>
      axios.get(`${API}/courier/deliveries`, { withCredentials: true })
        .then((r) => {
          const reserved = (r.data?.available || []).filter((d) => d.reserved_for_me).length;
          const active = (r.data?.mine || []).filter((d) => d.status !== "delivered").length;
          setMyCounts({ reserved, active });
          if (reserved > 0 && !autoOpened.current) {
            autoOpened.current = true;
            setTab("my");
          }
        })
        .catch(() => {});
    load();
    const iv = setInterval(load, 25000);
    return () => clearInterval(iv);
  }, []);

  const myBadge = myCounts.reserved + myCounts.active;

  return (
    <div className="space-y-6" data-testid="admin-deliveries-page">
      <div>
        <div className="micro-label text-[#8B5CF6] mb-2">{t("admin.deliveries.eyebrow")}</div>
        <h1 className="font-display text-3xl flex items-center gap-3">
          <Truck className="w-8 h-8 text-[#8B5CF6]" /> {t("admin.deliveries.title")}
        </h1>
      </div>

      <div className="flex gap-2 border-b border-white/10 overflow-x-auto">
        <button
          onClick={() => setTab("deliveries")}
          data-testid="admin-tab-deliveries"
          className={`px-4 py-2.5 text-sm border-b-2 -mb-px whitespace-nowrap ${tab === "deliveries" ? "border-[#8B5CF6] text-[#8B5CF6]" : "border-transparent text-neutral-500 hover:text-white"}`}
        >
          {t("admin.deliveries.tabDeliveries")}
        </button>
        <button
          onClick={() => setTab("my")}
          data-testid="admin-tab-my-deliveries"
          className={`px-4 py-2.5 text-sm border-b-2 -mb-px whitespace-nowrap flex items-center gap-2 ${tab === "my" ? "border-[#8B5CF6] text-[#8B5CF6]" : "border-transparent text-neutral-500 hover:text-white"}`}
        >
          {t("admin.deliveries.tabMy")}
          {myBadge > 0 && (
            <span
              data-testid="admin-tab-my-badge"
              className={`inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 text-[10px] font-bold rounded-full ${
                myCounts.reserved > 0 ? "bg-[#22C55E] text-black animate-pulse" : "bg-[#8B5CF6] text-white"
              }`}
            >
              {myBadge}
            </span>
          )}
        </button>
        <button
          onClick={() => setTab("couriers")}
          data-testid="admin-tab-couriers"
          className={`px-4 py-2.5 text-sm border-b-2 -mb-px whitespace-nowrap ${tab === "couriers" ? "border-[#8B5CF6] text-[#8B5CF6]" : "border-transparent text-neutral-500 hover:text-white"}`}
        >
          {t("admin.deliveries.tabCouriers")}
        </button>
        <button
          onClick={() => setTab("rates")}
          data-testid="admin-tab-muni-rates"
          className={`px-4 py-2.5 text-sm border-b-2 -mb-px whitespace-nowrap ${tab === "rates" ? "border-[#8B5CF6] text-[#8B5CF6]" : "border-transparent text-neutral-500 hover:text-white"}`}
        >
          {t("admin.deliveries.tabMuniRates")}
        </button>
      </div>

      {tab === "deliveries" ? <DeliveriesTab navigate={navigate} />
        : tab === "my" ? <div data-testid="admin-my-deliveries"><CourierPanel embedded /></div>
        : tab === "rates" ? <MunicipalityRatesTab />
        : <CouriersTab navigate={navigate} />}
    </div>
  );
}
