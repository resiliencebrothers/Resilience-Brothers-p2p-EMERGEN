import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { TrendingUp, AlertCircle, Banknote, Users } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export default function AdminRevenue() {
  const [data, setData] = useState(null);
  const [days, setDays] = useState("all");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const params = days === "all" ? {} : { days: parseInt(days) };
      const r = await axios.get(`${API}/admin/revenue`, { params, withCredentials: true });
      setData(r.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    } finally {
      setLoading(false);
    }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [days]);

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
          label="Margen promedio"
          value={`${data.profit_margin_pct}`}
          unit="%"
        />
        <BigStat
          icon={Users}
          label="Volumen total"
          value={`${fmt(data.total_volume_usdt)}`}
          unit="USDT"
        />
        <BigStat
          icon={AlertCircle}
          label="Órdenes contabilizadas"
          value={data.orders_total}
          unit=""
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
            <p className="text-xs text-neutral-500 mt-2">Configúralas en la sección Tasas → editar par → "Tasa Real de Salida".</p>
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
          <h2 className="font-display text-lg">Ganancia por par</h2>
          <p className="text-xs text-neutral-500 mt-1">Ordenado por contribución a la ganancia.</p>
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
