import { useEffect, useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { API } from "@/App";
import { toast } from "sonner";
import { TrendingUp, AlertCircle, Banknote, Users, Boxes, Calendar, Download, FileText, Send } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";

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

  const load = async () => {
    setLoading(true);
    try {
      const params = days === "all" ? {} : { days: parseInt(days) };
      const [r, d, m] = await Promise.all([
        axios.get(`${API}/admin/revenue`, { params, withCredentials: true }),
        axios.get(`${API}/admin/revenue/timeseries`, { params: { granularity: "day", days: parseInt(dailyRange) }, withCredentials: true }),
        axios.get(`${API}/admin/revenue/timeseries`, { params: { granularity: "month" }, withCredentials: true }),
      ]);
      setData(r.data);
      setDaily(d.data.rows || []);
      setMonthly(m.data.rows || []);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    } finally {
      setLoading(false);
    }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [days, dailyRange]);

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
      if (!handleTotpError(e, navigate)) toast.error(e.response?.data?.detail || "Error");
    } finally {
      setSendingBusy(false);
    }
  };

  if (loading || !data) return <div className="text-neutral-400 micro-label">Cargando ingresos...</div>;

  const fmt = (n) => (n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });

  return (
    <div className="space-y-8" data-testid="admin-revenue">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="micro-label text-[#EAB308] mb-2">/ Ingresos</div>
          <h1 className="font-display text-3xl flex items-center gap-3">
            <TrendingUp className="w-8 h-8 text-[#22C55E]" /> Ganancia del Negocio
          </h1>
          <p className="text-neutral-400 mt-2 text-sm max-w-2xl">
            Ganancia calculada como la diferencia entre la <em>tasa real de salida</em> (mercado) y la tasa
            entregada al cliente. Solo se contabilizan órdenes aprobadas/completadas con tasa real configurada.
          </p>
        </div>
        <Select value={days} onValueChange={setDays}>
          <SelectTrigger data-testid="revenue-period" className="rounded-none bg-[#0a0a0a] border-white/10 h-11 w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-[#141414] border-white/10 text-white rounded-none">
            <SelectItem value="all">Todo el tiempo</SelectItem>
            <SelectItem value="7">Últimos 7 días</SelectItem>
            <SelectItem value="30">Últimos 30 días</SelectItem>
            <SelectItem value="90">Últimos 90 días</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* TOP CARDS */}
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <BigStat
          icon={Banknote}
          label="Ganancia total"
          value={`${fmt(data.total_profit_usdt)}`}
          unit="USDT"
          highlight
        />
        <BigStat
          icon={TrendingUp}
          label="Ganancia P2P"
          value={`${fmt(data.p2p_profit_usdt)}`}
          unit="USDT"
        />
        <BigStat
          icon={Boxes}
          label="Ganancia Marketplace"
          value={`${fmt(data.marketplace_profit_usdt)}`}
          unit="USDT"
        />
        <BigStat
          icon={Users}
          label="Volumen P2P"
          value={`${fmt(data.total_volume_usdt)}`}
          unit="USDT"
        />
      </div>

      {/* MISSING RATES WARNING */}
      {data.missing_real_rate_pairs.length > 0 && (
        <div className="border border-[#EAB308]/40 bg-[#EAB308]/5 p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-[#EAB308] shrink-0 mt-0.5" />
          <div className="text-sm">
            <div className="font-semibold text-[#EAB308] mb-1">Tasas reales faltantes</div>
            <p className="text-neutral-300">
              Estos pares tienen órdenes pero NO tienen tasa real configurada — sus ganancias no se contabilizan:
            </p>
            <div className="mt-2 font-mono text-xs flex flex-wrap gap-2">
              {data.missing_real_rate_pairs.map(p => (
                <span key={p} className="bg-black/40 border border-white/10 px-2 py-1">{p}</span>
              ))}
            </div>
            <p className="text-xs text-neutral-500 mt-2">Configúralas en la sección Tasas → editar par → &laquo;Tasa Real de Salida&raquo;.</p>
          </div>
        </div>
      )}

      {/* BY ROLE */}
      <div className="grid md:grid-cols-2 gap-4">
        <RoleCard
          title="Clientes Normales"
          subtitle="Margen 5% comisión + spread"
          data={data.by_role.normal}
          accent="border-white/10"
        />
        <RoleCard
          title="Clientes VIP"
          subtitle="Solo spread (sin comisión)"
          data={data.by_role.vip}
          accent="border-[#EAB308]/40"
        />
      </div>

      {/* BY PAIR */}
      <div className="tactile-card overflow-hidden">
        <div className="px-6 py-4 border-b border-white/10">
          <h2 className="font-display text-lg">Ganancia P2P por par</h2>
          <p className="text-xs text-neutral-500 mt-1">Ordenado por contribución a la ganancia. Margen promedio: {data.profit_margin_pct}% · {data.orders_total} órdenes.</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-[#0a0a0a]">
              <tr className="text-left">
                <th className="px-4 py-3 micro-label text-neutral-500">Par</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Órdenes</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Volumen IN</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Volumen OUT</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Tasa Normal / VIP / Real</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Ganancia</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Margen</th>
              </tr>
            </thead>
            <tbody>
              {data.by_pair.length === 0 && (
                <tr><td colSpan="7" className="text-center text-neutral-500 py-8">Sin datos suficientes. Configura las tasas reales y aprueba órdenes.</td></tr>
              )}
              {data.by_pair.map(p => (
                <tr key={p.pair} className="border-b border-white/5">
                  <td className="px-4 py-3 font-mono font-semibold">{p.pair}</td>
                  <td className="px-4 py-3 font-mono">{p.orders}</td>
                  <td className="px-4 py-3 font-mono">{fmt(p.volume_from)} {p.from_code}</td>
                  <td className="px-4 py-3 font-mono">{fmt(p.volume_to)} {p.to_code}</td>
                  <td className="px-4 py-3 font-mono text-xs">
                    <div>{p.rate_normal} / <span className="text-[#EAB308]">{p.rate_vip}</span> / <span className="text-[#22C55E]">{p.real_rate}</span></div>
                  </td>
                  <td className="px-4 py-3 font-mono">
                    <div className="text-[#22C55E]">{fmt(p.profit_to)} {p.to_code}</div>
                    <div className="text-xs text-neutral-500">≈ {fmt(p.profit_usdt)} USDT</div>
                  </td>
                  <td className="px-4 py-3 font-mono text-[#22C55E]">{p.avg_profit_pct}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {/* DAILY REGISTRY */}
      <div className="tactile-card overflow-hidden" data-testid="revenue-daily-card">
        <div className="px-6 py-4 border-b border-white/10 flex items-center justify-between flex-wrap gap-3">
          <div>
            <h2 className="font-display text-lg flex items-center gap-2">
              <Calendar className="w-5 h-5 text-[#EAB308]" /> Registro Diario
            </h2>
            <p className="text-xs text-neutral-500 mt-1">Ganancia consolidada por día (P2P + Marketplace, en USDT).</p>
          </div>
          <Select value={dailyRange} onValueChange={setDailyRange}>
            <SelectTrigger data-testid="daily-range" className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#141414] border-white/10 text-white rounded-none">
              <SelectItem value="7">Últimos 7 días</SelectItem>
              <SelectItem value="14">Últimos 14 días</SelectItem>
              <SelectItem value="30">Últimos 30 días</SelectItem>
              <SelectItem value="60">Últimos 60 días</SelectItem>
              <SelectItem value="90">Últimos 90 días</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-[#0a0a0a]">
              <tr className="text-left">
                <th className="px-4 py-3 micro-label text-neutral-500">Fecha</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Órdenes</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Volumen</th>
                <th className="px-4 py-3 micro-label text-neutral-500">P2P</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Marketplace</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Total</th>
              </tr>
            </thead>
            <tbody data-testid="daily-rows">
              {daily.length === 0 && (
                <tr><td colSpan="6" className="text-center text-neutral-500 py-8">Sin movimientos en este rango.</td></tr>
              )}
              {daily.map(d => (
                <tr key={d.bucket} className="border-b border-white/5">
                  <td className="px-4 py-3 font-mono">{d.bucket}</td>
                  <td className="px-4 py-3 font-mono">{d.orders}</td>
                  <td className="px-4 py-3 font-mono text-neutral-400">{fmt(d.volume_usdt)} USDT</td>
                  <td className="px-4 py-3 font-mono">{fmt(d.p2p_profit_usdt)} USDT</td>
                  <td className="px-4 py-3 font-mono">{fmt(d.marketplace_profit_usdt)} USDT</td>
                  <td className="px-4 py-3 font-mono text-[#22C55E] font-bold">{fmt(d.total_profit_usdt)} USDT</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* MONTHLY REGISTRY */}
      <div className="tactile-card overflow-hidden" data-testid="revenue-monthly-card">
        <div className="px-6 py-4 border-b border-white/10">
          <h2 className="font-display text-lg flex items-center gap-2">
            <Calendar className="w-5 h-5 text-[#EAB308]" /> Registro Mensual
          </h2>
          <p className="text-xs text-neutral-500 mt-1">
            Descarga el detalle diario de cada mes en CSV o PDF.
            El día 1 de cada mes a las 09:00 UTC el PDF del mes anterior se envía automáticamente a todos los admins.
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-[#0a0a0a]">
              <tr className="text-left">
                <th className="px-4 py-3 micro-label text-neutral-500">Mes</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Órdenes</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Volumen</th>
                <th className="px-4 py-3 micro-label text-neutral-500">P2P</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Marketplace</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Total</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Exportar</th>
              </tr>
            </thead>
            <tbody data-testid="monthly-rows">
              {monthly.length === 0 && (
                <tr><td colSpan="7" className="text-center text-neutral-500 py-8">Aún no hay meses con datos.</td></tr>
              )}
              {monthly.map(m => (
                <tr key={m.bucket} className="border-b border-white/5">
                  <td className="px-4 py-3 font-mono font-semibold">{m.bucket}</td>
                  <td className="px-4 py-3 font-mono">{m.orders}</td>
                  <td className="px-4 py-3 font-mono text-neutral-400">{fmt(m.volume_usdt)} USDT</td>
                  <td className="px-4 py-3 font-mono">{fmt(m.p2p_profit_usdt)} USDT</td>
                  <td className="px-4 py-3 font-mono">{fmt(m.marketplace_profit_usdt)} USDT</td>
                  <td className="px-4 py-3 font-mono text-[#22C55E] font-bold">{fmt(m.total_profit_usdt)} USDT</td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2 flex-wrap">
                      <Button
                        size="sm"
                        data-testid={`export-csv-${m.bucket}`}
                        disabled={exporting === `${m.bucket}-csv`}
                        onClick={() => downloadMonth(m.bucket, "csv")}
                        className="rounded-none bg-transparent border border-white/10 hover:bg-white/5 h-8 text-xs"
                      >
                        <FileText className="w-3 h-3 mr-1" /> CSV
                      </Button>
                      <Button
                        size="sm"
                        data-testid={`export-pdf-${m.bucket}`}
                        disabled={exporting === `${m.bucket}-pdf`}
                        onClick={() => downloadMonth(m.bucket, "pdf")}
                        className="rounded-none bg-[#EAB308] hover:bg-[#FACC15] text-black h-8 text-xs"
                      >
                        <Download className="w-3 h-3 mr-1" /> PDF
                      </Button>
                      <Button
                        size="sm"
                        data-testid={`send-now-${m.bucket}`}
                        onClick={() => askSendMonth(m.bucket)}
                        className="rounded-none bg-transparent border border-[#22C55E]/40 text-[#22C55E] hover:bg-[#22C55E]/10 h-8 text-xs"
                      >
                        <Send className="w-3 h-3 mr-1" /> Enviar
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* MARKETPLACE */}
      <div className="tactile-card overflow-hidden" data-testid="revenue-marketplace">
        <div className="px-6 py-4 border-b border-white/10 flex items-center justify-between flex-wrap gap-2">
          <div>
            <h2 className="font-display text-lg flex items-center gap-2"><Boxes className="w-5 h-5 text-[#EAB308]" /> Ganancia del Marketplace</h2>
            <p className="text-xs text-neutral-500 mt-1">Solo redenciones entregadas (status=delivered). Configura el campo &laquo;Costo&raquo; en cada producto.</p>
          </div>
          <div className="flex items-center gap-4">
            <div className="text-right">
              <div className="micro-label text-neutral-500">Ingreso</div>
              <div className="font-mono font-semibold">${fmt(data.marketplace.total_revenue_usd)}</div>
            </div>
            <div className="text-right">
              <div className="micro-label text-neutral-500">Costo</div>
              <div className="font-mono">${fmt(data.marketplace.total_cost_usd)}</div>
            </div>
            <div className="text-right">
              <div className="micro-label text-[#22C55E]">Ganancia neta</div>
              <div className="font-mono text-[#22C55E] font-bold">${fmt(data.marketplace.total_profit_usd)}</div>
            </div>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-[#0a0a0a]">
              <tr className="text-left">
                <th className="px-4 py-3 micro-label text-neutral-500">Producto</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Unidades</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Canjes</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Ingreso</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Costo</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Ganancia</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Margen</th>
              </tr>
            </thead>
            <tbody>
              {data.marketplace.items.length === 0 && (
                <tr><td colSpan="7" className="text-center text-neutral-500 py-8">Sin canjes entregados aún en este período.</td></tr>
              )}
              {data.marketplace.items.map(p => (
                <tr key={p.product} className="border-b border-white/5">
                  <td className="px-4 py-3">{p.product}</td>
                  <td className="px-4 py-3 font-mono">{p.units}</td>
                  <td className="px-4 py-3 font-mono">{p.redemptions}</td>
                  <td className="px-4 py-3 font-mono">${fmt(p.revenue_usd)}</td>
                  <td className="px-4 py-3 font-mono text-neutral-400">${fmt(p.cost_usd)}</td>
                  <td className="px-4 py-3 font-mono text-[#22C55E]">${fmt(p.profit_usd)}</td>
                  <td className="px-4 py-3 font-mono text-[#22C55E]">{p.margin_pct}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

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

function BigStat({ icon: Icon, label, value, unit, highlight }) {
  return (
    <div className={`tactile-card p-5 ${highlight ? "glow-yellow" : ""}`}>
      <Icon className={`w-5 h-5 mb-3 ${highlight ? "text-[#22C55E]" : "text-[#EAB308]"}`} />
      <div className="micro-label text-neutral-500">{label}</div>
      <div className="font-display text-2xl mt-1">
        {value} <span className="text-sm text-neutral-400">{unit}</span>
      </div>
    </div>
  );
}


function RoleCard({ title, subtitle, data, accent }) {
  return (
    <div className={`tactile-card p-6 border ${accent}`}>
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="font-display text-lg">{title}</h3>
          <p className="text-xs text-neutral-500">{subtitle}</p>
        </div>
      </div>
      <div className="space-y-2 font-mono text-sm">
        <Row label="Órdenes" value={data.orders} />
        <Row label="Volumen" value={`${(data.volume_usdt || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })} USDT`} />
        <Row label="Ganancia generada" value={`${(data.profit_usdt || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })} USDT`} accent />
      </div>
    </div>
  );
}

function Row({ label, value, accent }) {
  return (
    <div className="flex justify-between border-b border-white/5 py-2 last:border-0">
      <span className="text-neutral-500">{label}</span>
      <span className={accent ? "text-[#22C55E] font-semibold" : "text-white"}>{value}</span>
    </div>
  );
}
