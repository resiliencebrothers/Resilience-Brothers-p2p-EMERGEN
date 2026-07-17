import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { useTranslation, Trans } from "react-i18next";
import { API } from "@/App";
import { toast } from "sonner";
import { TrendingUp, AlertCircle, Banknote, Users, Boxes, Coins, BarChart3 } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";

import { BigStat, RoleCard } from "./revenue/RevenueCards";
import { RevenueByPairTable } from "./revenue/RevenueByPairTable";
import { RevenueDailyTable } from "./revenue/RevenueDailyTable";
import { RevenueMonthlyTable } from "./revenue/RevenueMonthlyTable";
import { RevenueMarketplaceTable } from "./revenue/RevenueMarketplaceTable";
import RevenueAnalyticsDialog from "./revenue/RevenueAnalyticsDialog";

const fmt = (n) => (n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });

export default function AdminRevenue() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [days, setDays] = useState("all");
  const [loading, setLoading] = useState(true);
  const [daily, setDaily] = useState([]);
  const [monthly, setMonthly] = useState([]);
  const [dailyRange, setDailyRange] = useState("30");
  const [exporting, setExporting] = useState(null);
  const [sendingTotp, setSendingTotp] = useState(null);
  const [sendingBusy, setSendingBusy] = useState(false);
  const [openAnalytics, setOpenAnalytics] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = days === "all" ? {} : { days: parseInt(days) };
      const [r, d, m] = await Promise.all([
        axios.get(`${API}/admin/revenue`, { params, withCredentials: true }),
        axios.get(`${API}/admin/revenue/timeseries`,
          { params: { granularity: "day", days: parseInt(dailyRange) }, withCredentials: true }),
        axios.get(`${API}/admin/revenue/timeseries`,
          { params: { granularity: "month" }, withCredentials: true }),
      ]);
      setData(r.data);
      setDaily(d.data.rows || []);
      setMonthly(m.data.rows || []);
    } catch (e) {
      toast.error(e.response?.data?.detail || t("admin.common.genericError"));
    } finally {
      setLoading(false);
    }
  }, [days, dailyRange, t]);
  useEffect(() => { load(); }, [load]);

  const downloadMonth = async (bucket, format) => {
    const [year, month] = bucket.split("-");
    setExporting(`${bucket}-${format}`);
    try {
      const res = await axios.get(
        `${API}/admin/revenue/monthly/export`,
        {
          params: { year: parseInt(year), month: parseInt(month), format },
          withCredentials: true,
          responseType: "blob",
        }
      );
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement("a");
      a.href = url;
      a.download = `ganancia-${bucket}.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      toast.success(t("admin.revenue.downloadedToast", { fmt: format.toUpperCase() }));
    } catch (e) {
      toast.error(t("admin.revenue.exportError"));
    } finally {
      setExporting(null);
    }
  };

  const askSendMonth = (bucket) => {
    const [year, month] = bucket.split("-");
    setSendingTotp({ year: parseInt(year), month: parseInt(month), label: bucket });
  };

  const sendMonthEmail = async (totpCode) => {
    if (!sendingTotp) return;
    setSendingBusy(true);
    try {
      const res = await axios.post(
        `${API}/admin/revenue/monthly/send-now`,
        { year: sendingTotp.year, month: sendingTotp.month, totp_code: totpCode },
        { withCredentials: true }
      );
      const { sent, total_admins } = res.data || {};
      toast.success(t("admin.revenue.sentToast", { sent, total: total_admins }));
      setSendingTotp(null);
    } catch (e) {
      if (!handleTotpError(e, navigate)) {
        toast.error(e.response?.data?.detail || t("admin.common.genericError"));
      }
    } finally {
      setSendingBusy(false);
    }
  };

  if (loading || !data) {
    return <div className="text-neutral-400 micro-label">{t("admin.revenue.loading")}</div>;
  }

  return (
    <div className="space-y-8" data-testid="admin-revenue">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="micro-label text-[#8B5CF6] mb-2">{t("admin.revenue.eyebrow")}</div>
          <h1 className="font-display text-3xl flex items-center gap-3">
            <TrendingUp className="w-8 h-8 text-[#22C55E]" /> {t("admin.revenue.title")}
          </h1>
          <p className="text-neutral-400 mt-2 text-sm max-w-2xl">
            <Trans
              i18nKey="admin.revenue.subtitle"
              components={{ 1: <em /> }}
            />
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Button
            data-testid="open-revenue-analytics"
            variant="outline"
            onClick={() => setOpenAnalytics(true)}
            className="rounded-none border-white/20 hover:bg-white/5 h-11"
            title={t("admin.revenue.statsTitle")}
          >
            <BarChart3 className="w-4 h-4 mr-1" />
            {t("admin.revenue.statsBtn")}
          </Button>
          <Select value={days} onValueChange={setDays}>
            <SelectTrigger
              data-testid="revenue-period"
              className="rounded-none bg-[#0a0a0a] border-white/10 h-11 w-44"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
              <SelectItem value="all">{t("admin.revenue.allTime")}</SelectItem>
              <SelectItem value="7">{t("admin.revenue.last7")}</SelectItem>
              <SelectItem value="30">{t("admin.revenue.last30")}</SelectItem>
              <SelectItem value="90">{t("admin.revenue.last90")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4">
        <BigStat icon={Banknote} label={t("admin.revenue.totalProfit")} value={fmt(data.total_profit_usdt)} unit="USDT" highlight />
        <BigStat icon={TrendingUp} label={t("admin.revenue.p2pProfit")} value={fmt(data.p2p_profit_usdt)} unit="USDT" />
        <BigStat icon={Boxes} label={t("admin.revenue.marketplaceProfit")} value={fmt(data.marketplace_profit_usdt)} unit="USDT" />
        <BigStat
          icon={Coins}
          label={t("admin.revenue.usdtFees")}
          value={fmt(data.conversion_fees_usdt)}
          unit="USDT"
          hint={t("admin.revenue.conversions", { n: data.conversion_fees_count || 0 })}
          testid="revenue-usdt-fees"
        />
        <BigStat icon={Users} label={t("admin.revenue.p2pVolume")} value={fmt(data.total_volume_usdt)} unit="USDT" />
      </div>

      {data.missing_real_rate_pairs.length > 0 && (
        <div className="border border-[#8B5CF6]/40 bg-[#8B5CF6]/5 p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-[#8B5CF6] shrink-0 mt-0.5" />
          <div className="text-sm">
            <div className="font-semibold text-[#8B5CF6] mb-1">{t("admin.revenue.missingReal")}</div>
            <p className="text-neutral-300">
              {t("admin.revenue.missingRealBody")}
            </p>
            <div className="mt-2 font-mono text-xs flex flex-wrap gap-2">
              {data.missing_real_rate_pairs.map(p => (
                <span key={p} className="bg-black/40 border border-white/10 px-2 py-1">{p}</span>
              ))}
            </div>
            <p className="text-xs text-neutral-500 mt-2">
              {t("admin.revenue.missingRealHint")}
            </p>
          </div>
        </div>
      )}

      <div className="grid md:grid-cols-2 gap-4">
        <RoleCard
          title={t("admin.revenue.normalClients")}
          subtitle={t("admin.revenue.normalSub")}
          data={data.by_role.normal}
          accent="border-white/10"
        />
        <RoleCard
          title={t("admin.revenue.vipClients")}
          subtitle={t("admin.revenue.vipSub")}
          data={data.by_role.vip}
          accent="border-[#8B5CF6]/40"
        />
      </div>

      <RevenueByPairTable
        byPair={data.by_pair}
        profitMarginPct={data.profit_margin_pct}
        ordersTotal={data.orders_total}
        fmt={fmt}
      />

      <RevenueDailyTable
        daily={daily}
        dailyRange={dailyRange}
        setDailyRange={setDailyRange}
        fmt={fmt}
      />

      <RevenueMonthlyTable
        monthly={monthly}
        exporting={exporting}
        onDownload={downloadMonth}
        onAskSend={askSendMonth}
        fmt={fmt}
      />

      <RevenueMarketplaceTable marketplace={data.marketplace} fmt={fmt} />

      <RevenueAnalyticsDialog
        open={openAnalytics}
        onOpenChange={setOpenAnalytics}
        data={data}
        monthly={monthly}
        days={days}
      />

      <TotpPromptDialog
        open={!!sendingTotp}
        title={t("admin.revenue.sendReportTitle", { label: sendingTotp?.label ?? "" })}
        description={t("admin.revenue.sendReportDesc")}
        busy={sendingBusy}
        onConfirm={sendMonthEmail}
        onCancel={() => setSendingTotp(null)}
      />
    </div>
  );
}
