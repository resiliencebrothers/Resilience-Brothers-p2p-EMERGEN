import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { useTranslation, Trans } from "react-i18next";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";
import { toast } from "sonner";
import { Users, ListChecks, Database, ArrowUpRight, ArrowDownLeft, Coins, TrendingUp, BellRing, FileText } from "lucide-react";
import { Switch } from "@/components/ui/switch";

export default function AdminOverview() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [threshold, setThreshold] = useState("");
  const [defensivePct, setDefensivePct] = useState("");
  const [opsEmail, setOpsEmail] = useState("");
  const [officeAddress, setOfficeAddress] = useState("");
  // iter198 — courier fee tariff (USDT/km) + free-above threshold.
  const [courierRate, setCourierRate] = useState("");
  const [courierFreeMin, setCourierFreeMin] = useState("");
  const [courierMinFee, setCourierMinFee] = useState("");
  const [officeLat, setOfficeLat] = useState("");
  const [officeLon, setOfficeLon] = useState("");
  // iter192 — provinces with cash-delivery availability (null = all).
  const [cashProvinces, setCashProvinces] = useState(null);
  const [allProvinces, setAllProvinces] = useState([]);
  const [autoMonthlyAudit, setAutoMonthlyAudit] = useState(true);
  const [autoMonthlyVipLedger, setAutoMonthlyVipLedger] = useState(true);
  const [savingThreshold, setSavingThreshold] = useState(false);
  const [pendingSettings, setPendingSettings] = useState(null);
  const [pendingAudit, setPendingAudit] = useState(null);
  const [pendingVipLedger, setPendingVipLedger] = useState(null);
  const [runningVipLedger, setRunningVipLedger] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, set] = await Promise.all([
        axios.get(`${API}/admin/stats`, { withCredentials: true }),
        axios.get(`${API}/admin/settings`, { withCredentials: true }),
      ]);
      setStats(s.data);
      setThreshold(String(set.data.vip_threshold_usdt));
      setDefensivePct(set.data.defensive_margin_pct == null ? "" : String(set.data.defensive_margin_pct));
      setOpsEmail(set.data.ops_notifications_email || "");
      setOfficeAddress(set.data.office_address || "");
      setCourierRate(String(set.data.courier_rate_usdt_per_km ?? 0.5));
      setCourierFreeMin(String(set.data.courier_free_min_usdt ?? 1000));
      setCourierMinFee(String(set.data.courier_min_fee_usdt ?? 2));
      setOfficeLat(set.data.office_latitude != null ? String(set.data.office_latitude) : "");
      setOfficeLon(set.data.office_longitude != null ? String(set.data.office_longitude) : "");
      setCashProvinces(set.data.cash_provinces ?? null);
      setAutoMonthlyAudit(set.data.auto_send_monthly_audit !== false);
      setAutoMonthlyVipLedger(set.data.auto_send_monthly_vip_ledger !== false);
    } catch (e) {
      toast.error(t("adminOverview.loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    axios.get(`${API}/vip/cash-provinces`, { withCredentials: true })
      .then((r) => setAllProvinces((r.data?.provinces || []).map((p) => p.name)))
      .catch(() => setAllProvinces([]));
  }, []);

  const saveThreshold = () => {
    const v = parseFloat(threshold);
    if (!v || v < 0) return toast.error(t("adminOverview.alerts.invalidThreshold"));
    const def = defensivePct === "" ? null : parseFloat(defensivePct);
    const trimmedEmail = opsEmail.trim();
    if (trimmedEmail && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)) {
      return toast.error(t("adminOverview.alerts.invalidEmail"));
    }
    const cRate = parseFloat(courierRate);
    const cMin = parseFloat(courierFreeMin);
    const cMinFee = parseFloat(courierMinFee);
    if (Number.isNaN(cRate) || cRate < 0 || Number.isNaN(cMin) || cMin < 0
        || Number.isNaN(cMinFee) || cMinFee < 0) {
      return toast.error(t("adminOverview.alerts.invalidCourier"));
    }
    const lat = officeLat.trim() === "" ? null : parseFloat(officeLat);
    const lon = officeLon.trim() === "" ? null : parseFloat(officeLon);
    if ((lat !== null && (Number.isNaN(lat) || lat < -90 || lat > 90))
        || (lon !== null && (Number.isNaN(lon) || lon < -180 || lon > 180))) {
      return toast.error(t("adminOverview.alerts.invalidOfficeCoords"));
    }
    setPendingSettings({
      vip_threshold_usdt: v,
      defensive_margin_pct: def,
      ops_notifications_email: trimmedEmail || null,
      office_address: officeAddress.trim() || null,
      cash_provinces: cashProvinces,
      courier_rate_usdt_per_km: cRate,
      courier_free_min_usdt: cMin,
      courier_min_fee_usdt: cMinFee,
      office_latitude: lat,
      office_longitude: lon,
    });
  };

  const confirmSettingsWithTotp = async (code) => {
    setSavingThreshold(true);
    try {
      await axios.put(
        `${API}/admin/settings`,
        { ...pendingSettings, totp_code: code },
        { withCredentials: true }
      );
      toast.success(t("adminOverview.alerts.settingsSaved"));
      setPendingSettings(null);
    } catch (e) {
      if (!handleTotpError(e, navigate)) toast.error(t("adminOverview.alerts.saveError"));
    } finally {
      setSavingThreshold(false);
    }
  };

  const toggleAutoMonthlyAudit = (checked) => {
    setAutoMonthlyAudit(checked);
    setPendingAudit(checked);
  };

  const confirmAuditToggleWithTotp = async (code) => {
    setSavingThreshold(true);
    try {
      await axios.put(
        `${API}/admin/settings`,
        { auto_send_monthly_audit: pendingAudit, totp_code: code },
        { withCredentials: true }
      );
      toast.success(pendingAudit
        ? t("adminOverview.alerts.auditToggleOn")
        : t("adminOverview.alerts.auditToggleOff"));
      setPendingAudit(null);
    } catch (e) {
      setAutoMonthlyAudit(!pendingAudit);
      if (!handleTotpError(e, navigate)) toast.error(t("adminOverview.alerts.toggleError"));
    } finally {
      setSavingThreshold(false);
    }
  };

  const cancelAuditToggle = () => {
    setAutoMonthlyAudit(!pendingAudit);
    setPendingAudit(null);
  };

  const toggleAutoMonthlyVipLedger = (checked) => {
    setAutoMonthlyVipLedger(checked);
    setPendingVipLedger(checked);
  };

  const confirmVipLedgerToggleWithTotp = async (code) => {
    setSavingThreshold(true);
    try {
      await axios.put(
        `${API}/admin/settings`,
        { auto_send_monthly_vip_ledger: pendingVipLedger, totp_code: code },
        { withCredentials: true }
      );
      toast.success(pendingVipLedger
        ? t("adminOverview.alerts.vipLedgerToggleOn")
        : t("adminOverview.alerts.vipLedgerToggleOff"));
      setPendingVipLedger(null);
    } catch (e) {
      setAutoMonthlyVipLedger(!pendingVipLedger);
      if (!handleTotpError(e, navigate)) toast.error(t("adminOverview.alerts.toggleError"));
    } finally {
      setSavingThreshold(false);
    }
  };

  const cancelVipLedgerToggle = () => {
    setAutoMonthlyVipLedger(!pendingVipLedger);
    setPendingVipLedger(null);
  };

  const runVipLedgerNow = async () => {
    setRunningVipLedger(true);
    try {
      const r = await axios.post(
        `${API}/admin/vip-ledger/monthly-mailing/run-now`,
        {}, { withCredentials: true },
      );
      const d = r.data || {};
      toast.success(t("adminOverview.alerts.vipLedgerRanSummary", {
        period: d.period || "-",
        sent: d.sent ?? 0,
        skipped: d.skipped_empty ?? 0,
        failed: d.failed ?? 0,
      }));
    } catch {
      toast.error(t("adminOverview.alerts.vipLedgerRunError"));
    } finally {
      setRunningVipLedger(false);
    }
  };

  const seed = async () => {
    try {
      await axios.post(`${API}/admin/seed`, {}, { withCredentials: true });
      toast.success(t("adminOverview.seedSuccess"));
      load();
    } catch (e) { toast.error(t("adminOverview.seedError")); }
  };

  if (loading || !stats) {
    return <div className="text-neutral-400 micro-label">{t("adminOverview.loadingStats")}</div>;
  }

  const c = stats.counters;

  return (
    <div className="space-y-8" data-testid="admin-overview">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="micro-label text-[#8B5CF6] mb-2">{t("adminOverview.eyebrow")}</div>
          <h1 className="font-display text-3xl">{t("adminOverview.title")}</h1>
          <p className="text-neutral-400 mt-2 text-sm">{t("adminOverview.subtitle")}</p>
        </div>
        <Button data-testid="seed-btn" onClick={seed} className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none">
          <Database className="w-4 h-4 mr-2" /> {t("adminOverview.seedButton")}
        </Button>
      </div>

      {/* COUNTERS */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <Stat icon={Users} label={t("adminOverview.counters.users")} value={c.users_total} sub={t("adminOverview.counters.usersVip", { count: c.users_vip })} />
        <Stat icon={ListChecks} label={t("adminOverview.counters.orders")} value={c.orders_total} />
        <Stat icon={ListChecks} label={t("adminOverview.counters.pending")} value={c.orders_pending} accent />
        <Stat icon={ArrowDownToLineIcon} label={t("adminOverview.counters.withdrawalsPending")} value={c.withdrawals_pending} accent={c.withdrawals_pending > 0} />
        <Stat icon={TrendingUp} label={t("adminOverview.counters.vipActive")} value={c.users_vip} />
      </div>

      {/* ADMIN SETTINGS — VIP threshold alert */}
      <div className="tactile-card p-6" data-testid="admin-settings-card">
        <div className="flex items-start gap-3 mb-4">
          <BellRing className="w-5 h-5 text-[#8B5CF6] mt-1" />
          <div>
            <h3 className="font-display text-lg">{t("adminOverview.alerts.title")}</h3>
            <p className="text-xs text-neutral-500 mt-1">{t("adminOverview.alerts.body")}</p>
          </div>
        </div>
        <div className="flex items-end gap-3 flex-wrap">
          <div className="flex-1 min-w-0 sm:min-w-[200px]">
            <label className="micro-label text-neutral-500 text-[0.65rem]">{t("adminOverview.alerts.thresholdLabel")}</label>
            <Input
              type="number"
              min="0"
              step="100"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              className="mt-1 rounded-none bg-black/40 border-white/10"
              data-testid="vip-threshold-input"
            />
          </div>
          <Button
            onClick={saveThreshold}
            disabled={savingThreshold}
            className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none"
            data-testid="save-threshold-btn"
          >
            {savingThreshold ? t("adminOverview.alerts.saving") : t("adminOverview.alerts.save")}
          </Button>
        </div>

        {/* Centralised ops mailbox */}
        <div className="mt-6 pt-6 border-t border-white/5">
          <label className="micro-label text-neutral-500 text-[0.65rem]">
            {t("adminOverview.alerts.opsMailLabel")}
          </label>
          <Input
            type="email"
            placeholder={t("adminOverview.alerts.opsMailPlaceholder")}
            value={opsEmail}
            onChange={(e) => setOpsEmail(e.target.value)}
            className="mt-1 rounded-none bg-black/40 border-white/10"
            data-testid="ops-notifications-email-input"
          />
          <p className="text-[0.7rem] text-neutral-500 mt-2 leading-relaxed">
            <Trans
              i18nKey="adminOverview.alerts.opsMailHint"
              components={{ 1: <strong className="text-neutral-300" /> }}
            />
          </p>
        </div>

        {/* iter113 — company office address (shown to cash depositors ≤ courier threshold) */}
        <div className="mt-6 pt-6 border-t border-white/5">
          <label className="micro-label text-neutral-500 text-[0.65rem]">
            {t("adminOverview.alerts.officeAddressLabel")}
          </label>
          <Input
            type="text"
            placeholder={t("adminOverview.alerts.officeAddressPlaceholder")}
            value={officeAddress}
            onChange={(e) => setOfficeAddress(e.target.value)}
            maxLength={300}
            className="mt-1 rounded-none bg-black/40 border-white/10"
            data-testid="office-address-input"
          />
          <p className="text-[0.7rem] text-neutral-500 mt-2 leading-relaxed">
            {t("adminOverview.alerts.officeAddressHint")}
          </p>
        </div>

        {/* iter192 — provinces with cash-delivery availability */}
        <div className="mt-6 pt-6 border-t border-white/5" data-testid="cash-provinces-block">
          <label className="micro-label text-neutral-500 text-[0.65rem]">
            {t("adminOverview.alerts.cashProvincesLabel")}
          </label>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-3 gap-y-2 mt-2">
            {allProvinces.map((p) => {
              const checked = cashProvinces === null || cashProvinces.includes(p);
              return (
                <label
                  key={p}
                  className="flex items-center gap-2 text-xs text-neutral-300 cursor-pointer select-none"
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={(e) => {
                      const base = cashProvinces === null ? [...allProvinces] : [...cashProvinces];
                      const next = e.target.checked
                        ? [...new Set([...base, p])]
                        : base.filter((x) => x !== p);
                      setCashProvinces(next);
                    }}
                    data-testid={`cash-province-toggle-${p.replace(/\s+/g, "-")}`}
                    className="accent-[#8B5CF6] w-3.5 h-3.5"
                  />
                  {p}
                </label>
              );
            })}
          </div>
          <p className="text-[0.7rem] text-neutral-500 mt-2 leading-relaxed">
            {t("adminOverview.alerts.cashProvincesHint")}
          </p>
        </div>

        {/* iter198 — courier fee per km for cash withdrawals */}
        <div className="mt-6 pt-6 border-t border-white/5" data-testid="courier-fee-settings-block">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label className="micro-label text-neutral-500 text-[0.65rem]">
                {t("adminOverview.alerts.courierRateLabel")}
              </label>
              <Input
                type="number"
                min="0"
                step="0.05"
                value={courierRate}
                onChange={(e) => setCourierRate(e.target.value)}
                className="mt-1 rounded-none bg-black/40 border-white/10"
                data-testid="courier-rate-input"
              />
            </div>
            <div>
              <label className="micro-label text-neutral-500 text-[0.65rem]">
                {t("adminOverview.alerts.courierMinFeeLabel")}
              </label>
              <Input
                type="number"
                min="0"
                step="0.5"
                value={courierMinFee}
                onChange={(e) => setCourierMinFee(e.target.value)}
                className="mt-1 rounded-none bg-black/40 border-white/10"
                data-testid="courier-min-fee-input"
              />
            </div>
            <div>
              <label className="micro-label text-neutral-500 text-[0.65rem]">
                {t("adminOverview.alerts.courierFreeMinLabel")}
              </label>
              <Input
                type="number"
                min="0"
                step="50"
                value={courierFreeMin}
                onChange={(e) => setCourierFreeMin(e.target.value)}
                className="mt-1 rounded-none bg-black/40 border-white/10"
                data-testid="courier-free-min-input"
              />
            </div>
          </div>
          <p className="text-[0.7rem] text-neutral-500 mt-2 leading-relaxed">
            {t("adminOverview.alerts.courierHint")}
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4">
            <div>
              <label className="micro-label text-neutral-500 text-[0.65rem]">
                {t("adminOverview.alerts.officeLatLabel")}
              </label>
              <Input
                type="number"
                step="0.0001"
                value={officeLat}
                onChange={(e) => setOfficeLat(e.target.value)}
                placeholder="23.1136"
                className="mt-1 rounded-none bg-black/40 border-white/10 font-mono"
                data-testid="office-lat-input"
              />
            </div>
            <div>
              <label className="micro-label text-neutral-500 text-[0.65rem]">
                {t("adminOverview.alerts.officeLonLabel")}
              </label>
              <Input
                type="number"
                step="0.0001"
                value={officeLon}
                onChange={(e) => setOfficeLon(e.target.value)}
                placeholder="-82.3666"
                className="mt-1 rounded-none bg-black/40 border-white/10 font-mono"
                data-testid="office-lon-input"
              />
            </div>
          </div>
          <p className="text-[0.7rem] text-neutral-500 mt-2 leading-relaxed">
            {t("adminOverview.alerts.officeCoordsHint")}
          </p>
        </div>

        {/* Auto-send monthly audit report toggle */}
        <div
          className="mt-6 pt-6 border-t border-white/5"
          data-testid="auto-audit-toggle-card"
        >
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div className="flex items-start gap-3 min-w-0">
              <FileText className="w-5 h-5 text-[#8B5CF6] mt-0.5 shrink-0" />
              <div className="min-w-0">
                <label className="micro-label text-neutral-500 text-[0.65rem] block">
                  {t("adminOverview.alerts.auditLabel")}
                </label>
                <p className="text-[0.7rem] text-neutral-500 mt-2 leading-relaxed max-w-xl">
                  <Trans
                    i18nKey="adminOverview.alerts.auditBody"
                    components={{
                      1: <strong className="text-neutral-300" />,
                      2: <strong className="text-neutral-300" />,
                      3: <strong className="text-neutral-300" />,
                    }}
                  />
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3 shrink-0">
              <span
                className={`micro-label text-[0.65rem] ${autoMonthlyAudit ? "text-[#8B5CF6]" : "text-neutral-500"}`}
                data-testid="auto-audit-status-label"
              >
                {autoMonthlyAudit ? t("adminOverview.alerts.auditActive") : t("adminOverview.alerts.auditInactive")}
              </span>
              <Switch
                checked={autoMonthlyAudit}
                onCheckedChange={toggleAutoMonthlyAudit}
                disabled={savingThreshold || pendingAudit !== null}
                data-testid="auto-audit-toggle"
                aria-label={t("adminOverview.alerts.auditLabel")}
              />
            </div>
          </div>
        </div>

        {/* Auto-send monthly VIP ledger PDF toggle (iter111.3) */}
        <div
          className="mt-6 pt-6 border-t border-white/5"
          data-testid="auto-vip-ledger-toggle-card"
        >
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div className="flex items-start gap-3 min-w-0">
              <FileText className="w-5 h-5 text-[#8B5CF6] mt-0.5 shrink-0" />
              <div className="min-w-0">
                <label className="micro-label text-neutral-500 text-[0.65rem] block">
                  {t("adminOverview.alerts.vipLedgerLabel")}
                </label>
                <p className="text-[0.7rem] text-neutral-500 mt-2 leading-relaxed max-w-xl">
                  {t("adminOverview.alerts.vipLedgerBody")}
                </p>
                <Button
                  onClick={runVipLedgerNow}
                  disabled={runningVipLedger}
                  variant="ghost"
                  data-testid="vip-ledger-run-now-btn"
                  className="mt-2 rounded-none border border-white/10 hover:border-[#8B5CF6]/60 hover:text-[#8B5CF6] text-neutral-300 h-7 px-2 text-[0.6rem] uppercase tracking-widest font-mono"
                >
                  {runningVipLedger
                    ? t("adminOverview.alerts.vipLedgerRunning")
                    : t("adminOverview.alerts.vipLedgerRunNow")}
                </Button>
              </div>
            </div>
            <div className="flex items-center gap-3 shrink-0">
              <span
                className={`micro-label text-[0.65rem] ${autoMonthlyVipLedger ? "text-[#8B5CF6]" : "text-neutral-500"}`}
                data-testid="auto-vip-ledger-status-label"
              >
                {autoMonthlyVipLedger ? t("adminOverview.alerts.auditActive") : t("adminOverview.alerts.auditInactive")}
              </span>
              <Switch
                checked={autoMonthlyVipLedger}
                onCheckedChange={toggleAutoMonthlyVipLedger}
                disabled={savingThreshold || pendingVipLedger !== null}
                data-testid="auto-vip-ledger-toggle"
                aria-label={t("adminOverview.alerts.vipLedgerLabel")}
              />
            </div>
          </div>
        </div>
      </div>

      {/* MAIN STATS GRID */}
      <div className="grid lg:grid-cols-3 gap-6">
        <BigCard
          icon={ArrowDownLeft}
          title={t("adminOverview.cards.inflow")}
          subtitle={t("adminOverview.cards.inflowSub")}
          items={stats.inflow.items}
          total={stats.inflow.total_usdt}
          unit={t("adminOverview.cards.ordersUnit")}
          field="count"
          totalLabel={t("adminOverview.cards.totalEquivalent")}
          noDataLabel={t("adminOverview.cards.noData")}
          dataTestId="stat-inflow"
        />
        <BigCard
          icon={ArrowUpRight}
          title={t("adminOverview.cards.outflow")}
          subtitle={t("adminOverview.cards.outflowSub")}
          items={stats.outflow.items}
          total={stats.outflow.total_usdt}
          unit={t("adminOverview.cards.ordersUnit")}
          field="count"
          totalLabel={t("adminOverview.cards.totalEquivalent")}
          noDataLabel={t("adminOverview.cards.noData")}
          dataTestId="stat-outflow"
        />
        <BigCard
          icon={Coins}
          title={t("adminOverview.cards.vipHoldings")}
          subtitle={t("adminOverview.cards.vipHoldingsSub")}
          items={stats.vip_holdings.items}
          total={stats.vip_holdings.total_usdt}
          unit=""
          field={null}
          highlight
          totalLabel={t("adminOverview.cards.totalEquivalent")}
          noDataLabel={t("adminOverview.cards.noData")}
          dataTestId="stat-vip-holdings"
        />
      </div>

      <TotpPromptDialog
        open={!!pendingSettings}
        title={t("adminOverview.alerts.totpTitle")}
        description={t("adminOverview.alerts.totpDescription")}
        busy={savingThreshold}
        onConfirm={confirmSettingsWithTotp}
        onCancel={() => setPendingSettings(null)}
      />

      <TotpPromptDialog
        open={pendingAudit !== null}
        title={pendingAudit ? t("adminOverview.alerts.totpAuditOn") : t("adminOverview.alerts.totpAuditOff")}
        description={pendingAudit ? t("adminOverview.alerts.totpAuditOnDesc") : t("adminOverview.alerts.totpAuditOffDesc")}
        busy={savingThreshold}
        onConfirm={confirmAuditToggleWithTotp}
        onCancel={cancelAuditToggle}
      />

      <TotpPromptDialog
        open={pendingVipLedger !== null}
        title={pendingVipLedger ? t("adminOverview.alerts.totpVipLedgerOn") : t("adminOverview.alerts.totpVipLedgerOff")}
        description={pendingVipLedger ? t("adminOverview.alerts.totpVipLedgerOnDesc") : t("adminOverview.alerts.totpVipLedgerOffDesc")}
        busy={savingThreshold}
        onConfirm={confirmVipLedgerToggleWithTotp}
        onCancel={cancelVipLedgerToggle}
      />
    </div>
  );
}

function Stat({ icon: Icon, label, value, sub, accent }) {
  return (
    <div className="tactile-card p-4">
      <Icon className={`w-4 h-4 mb-2 ${accent ? "text-[#8B5CF6]" : "text-neutral-500"}`} />
      <div className="micro-label text-neutral-500 text-[0.65rem]">{label}</div>
      <div className={`font-display text-2xl mt-1 ${accent ? "text-[#8B5CF6]" : ""}`}>{value}</div>
      {sub && <div className="text-xs text-neutral-500 mt-0.5">{sub}</div>}
    </div>
  );
}

function BigCard({ icon: Icon, title, subtitle, items, total, unit, field, highlight, totalLabel, noDataLabel, dataTestId }) {
  return (
    <div className={`tactile-card p-6 ${highlight ? "glow-yellow" : ""}`} data-testid={dataTestId}>
      <div className="flex items-start justify-between mb-4">
        <div>
          <Icon className="w-5 h-5 text-[#8B5CF6] mb-3" />
          <h3 className="font-display text-lg">{title}</h3>
          <p className="text-xs text-neutral-500 mt-1">{subtitle}</p>
        </div>
      </div>
      <div className="border-b border-white/5 pb-4 mb-4">
        <div className="micro-label text-neutral-500 text-[0.6rem]">{totalLabel}</div>
        <div className="font-display text-3xl text-[#8B5CF6] mt-1">
          {(total || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })} <span className="text-base text-neutral-400">USDT</span>
        </div>
      </div>
      {items.length === 0 ? (
        <p className="text-neutral-500 text-sm">{noDataLabel}</p>
      ) : (
        <div className="space-y-2 max-h-64 overflow-y-auto">
          {items.map((it) => (
            <div key={it.currency} className="flex items-center justify-between border-b border-white/5 py-2 last:border-0">
              <div>
                <div className="font-mono text-sm font-semibold">{it.currency}</div>
                {field && <div className="text-[0.65rem] text-neutral-500 uppercase tracking-wider">{it[field]} {unit}</div>}
              </div>
              <div className="text-right">
                <div className="font-mono text-sm">{it.total.toLocaleString(undefined, { maximumFractionDigits: 4 })}</div>
                <div className="text-[0.65rem] text-neutral-500">
                  ≈ {it.usdt_equivalent != null ? `${it.usdt_equivalent.toLocaleString(undefined, { maximumFractionDigits: 2 })} USDT` : "—"}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ArrowDownToLineIcon(props) {
  // simple replacement to avoid an extra import
  return <ListChecks {...props} />;
}
