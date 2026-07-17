import { useEffect, useState } from "react";
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
  const [autoMonthlyAudit, setAutoMonthlyAudit] = useState(true);
  const [savingThreshold, setSavingThreshold] = useState(false);
  const [pendingSettings, setPendingSettings] = useState(null);
  const [pendingAudit, setPendingAudit] = useState(null);

  const load = async () => {
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
      setAutoMonthlyAudit(set.data.auto_send_monthly_audit !== false);
    } catch (e) {
      toast.error(t("adminOverview.loadError"));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const saveThreshold = () => {
    const v = parseFloat(threshold);
    if (!v || v < 0) return toast.error(t("adminOverview.alerts.invalidThreshold"));
    const def = defensivePct === "" ? null : parseFloat(defensivePct);
    const trimmedEmail = opsEmail.trim();
    if (trimmedEmail && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)) {
      return toast.error(t("adminOverview.alerts.invalidEmail"));
    }
    setPendingSettings({
      vip_threshold_usdt: v,
      defensive_margin_pct: def,
      ops_notifications_email: trimmedEmail || null,
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
          <div className="flex-1 min-w-[200px]">
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
