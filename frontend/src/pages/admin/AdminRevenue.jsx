import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { API } from "@/App";
import { toast } from "sonner";
import { TrendingUp, AlertCircle, Banknote, Users, Boxes, Coins } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";

import { BigStat, RoleCard } from "./revenue/RevenueCards";
import { RevenueByPairTable } from "./revenue/RevenueByPairTable";
import { RevenueDailyTable } from "./revenue/RevenueDailyTable";
import { RevenueMonthlyTable } from "./revenue/RevenueMonthlyTable";
import { RevenueMarketplaceTable } from "./revenue/RevenueMarketplaceTable";

const fmt = (n) => (n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });

export default function AdminRevenue() {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [days, setDays] = useState("all");
  const [loading, setLoading] = useState(true);
  const [daily, setDaily] = useState([]);
  const [monthly, setMonthly] = useState([]);
  const [dailyRange, setDailyRange] = useState("30");
  const [exporting, setExporting] = useState(null); // `${YYYY-MM}-${csv|pdf}`
  const [sendingTotp, setSendingTotp] = useState(null); // { year, month, label }
  const [sendingBusy, setSendingBusy] = useState(false);

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
      toast.error(e.response?.data?.detail || "Error");
    } finally {
      setLoading(false);
    }
  }, [days, dailyRange]);
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
      toast.success(`Descargado ${format.toUpperCase()}`);
    } catch (e) {
      toast.error("Error al exportar");
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
      toast.success(`Reporte enviado a ${sent}/${total_admins} admins`);
      setSendingTotp(null);
    } catch (e) {
      if (!handleTotpError(e, navigate)) {
        toast.error(e.response?.data?.detail || "Error");
      }
    } finally {
      setSendingBusy(false);
    }
  };

  if (loading || !data) {
    return <div className="text-neutral-400 micro-label">Cargando ingresos...</div>;
  }

  return (
    <div className="space-y-8" data-testid="admin-revenue">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="micro-label text-[#8B5CF6] mb-2">/ Ingresos</div>
          <h1 className="font-display text-3xl flex items-center gap-3">
            <TrendingUp className="w-8 h-8 text-[#22C55E]" /> Ganancia del Negocio
          </h1>
          <p className="text-neutral-400 mt-2 text-sm max-w-2xl">
            Ganancia calculada como la diferencia entre la <em>tasa real de salida</em> (mercado) y la tasa
            entregada al cliente. Solo se contabilizan órdenes aprobadas/completadas con tasa real configurada.
          </p>
        </div>
        <Select value={days} onValueChange={setDays}>
          <SelectTrigger
            data-testid="revenue-period"
            className="rounded-none bg-[#0a0a0a] border-white/10 h-11 w-44"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
            <SelectItem value="all">Todo el tiempo</SelectItem>
            <SelectItem value="7">Últimos 7 días</SelectItem>
            <SelectItem value="30">Últimos 30 días</SelectItem>
            <SelectItem value="90">Últimos 90 días</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4">
        <BigStat icon={Banknote} label="Ganancia total" value={fmt(data.total_profit_usdt)} unit="USDT" highlight />
        <BigStat icon={TrendingUp} label="Ganancia P2P" value={fmt(data.p2p_profit_usdt)} unit="USDT" />
        <BigStat icon={Boxes} label="Ganancia Marketplace" value={fmt(data.marketplace_profit_usdt)} unit="USDT" />
        <BigStat
          icon={Coins}
          label="Comisiones USDT"
          value={fmt(data.conversion_fees_usdt)}
          unit="USDT"
          hint={`${data.conversion_fees_count || 0} conversiones`}
          testid="revenue-usdt-fees"
        />
        <BigStat icon={Users} label="Volumen P2P" value={fmt(data.total_volume_usdt)} unit="USDT" />
      </div>

      {data.missing_real_rate_pairs.length > 0 && (
        <div className="border border-[#8B5CF6]/40 bg-[#8B5CF6]/5 p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-[#8B5CF6] shrink-0 mt-0.5" />
          <div className="text-sm">
            <div className="font-semibold text-[#8B5CF6] mb-1">Tasas reales faltantes</div>
            <p className="text-neutral-300">
              Estos pares tienen órdenes pero NO tienen tasa real configurada — sus ganancias no se contabilizan:
            </p>
            <div className="mt-2 font-mono text-xs flex flex-wrap gap-2">
              {data.missing_real_rate_pairs.map(p => (
                <span key={p} className="bg-black/40 border border-white/10 px-2 py-1">{p}</span>
              ))}
            </div>
            <p className="text-xs text-neutral-500 mt-2">
              Configúralas en la sección Tasas → editar par → «Tasa Real de Salida».
            </p>
          </div>
        </div>
      )}

      <div className="grid md:grid-cols-2 gap-4">
        <RoleCard
          title="Clientes Normales"
          subtitle="Margen del spread (tasa estándar)"
          data={data.by_role.normal}
          accent="border-white/10"
        />
        <RoleCard
          title="Clientes VIP"
          subtitle="Margen del spread (tasa preferencial)"
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

      <TotpPromptDialog
        open={!!sendingTotp}
        title={`Enviar reporte mensual ${sendingTotp?.label ?? ""}`}
        description="Se enviará el PDF del mes seleccionado por correo a TODOS los administradores. Ingresa tu código 2FA."
        busy={sendingBusy}
        onConfirm={sendMonthEmail}
        onCancel={() => setSendingTotp(null)}
      />
    </div>
  );
}
