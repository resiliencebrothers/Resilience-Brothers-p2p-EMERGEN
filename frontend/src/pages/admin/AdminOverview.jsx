import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { Users, ListChecks, Package, Database, ArrowDownUp, ArrowUpRight, ArrowDownLeft, Coins, TrendingUp, BellRing } from "lucide-react";

export default function AdminOverview() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [threshold, setThreshold] = useState("");
  const [savingThreshold, setSavingThreshold] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [s, set] = await Promise.all([
        axios.get(`${API}/admin/stats`, { withCredentials: true }),
        axios.get(`${API}/admin/settings`, { withCredentials: true }),
      ]);
      setStats(s.data);
      setThreshold(String(set.data.vip_threshold_usdt));
    } catch (e) {
      toast.error("Error al cargar estadísticas");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const saveThreshold = async () => {
    const v = parseFloat(threshold);
    if (!v || v < 0) return toast.error("Umbral inválido");
    setSavingThreshold(true);
    try {
      await axios.put(`${API}/admin/settings`, { vip_threshold_usdt: v }, { withCredentials: true });
      toast.success("Umbral actualizado");
    } catch (e) {
      toast.error("Error al guardar");
    } finally {
      setSavingThreshold(false);
    }
  };

  const seed = async () => {
    try {
      await axios.post(`${API}/admin/seed`, {}, { withCredentials: true });
      toast.success("Datos seed creados");
      load();
    } catch (e) { toast.error("Error al hacer seed"); }
  };

  if (loading || !stats) {
    return <div className="text-neutral-400 micro-label">Cargando estadísticas...</div>;
  }

  const c = stats.counters;

  return (
    <div className="space-y-8" data-testid="admin-overview">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="micro-label text-[#EAB308] mb-2">/ Control Room</div>
          <h1 className="font-display text-3xl">Panel de Administración</h1>
          <p className="text-neutral-400 mt-2 text-sm">Vista consolidada de operaciones · valores en USDT como base.</p>
        </div>
        <Button data-testid="seed-btn" onClick={seed} className="bg-[#EAB308] hover:bg-[#FACC15] text-black rounded-none">
          <Database className="w-4 h-4 mr-2" /> Cargar datos demo
        </Button>
      </div>

      {/* COUNTERS */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <Stat icon={Users} label="Usuarios" value={c.users_total} sub={`${c.users_vip} VIP`} />
        <Stat icon={ListChecks} label="Órdenes" value={c.orders_total} />
        <Stat icon={ListChecks} label="Pendientes" value={c.orders_pending} accent />
        <Stat icon={ArrowDownToLineIcon} label="Retiros pend." value={c.withdrawals_pending} accent={c.withdrawals_pending > 0} />
        <Stat icon={TrendingUp} label="VIPs activos" value={c.users_vip} />
      </div>

      {/* ADMIN SETTINGS — VIP threshold alert */}
      <div className="tactile-card p-6" data-testid="admin-settings-card">
        <div className="flex items-start gap-3 mb-4">
          <BellRing className="w-5 h-5 text-[#EAB308] mt-1" />
          <div>
            <h3 className="font-display text-lg">Alertas Automáticas</h3>
            <p className="text-xs text-neutral-500 mt-1">
              Cuando un cliente VIP acumule (en USDT) un saldo igual o superior a este umbral,
              todos los administradores recibirán una alerta (push + email).
            </p>
          </div>
        </div>
        <div className="flex items-end gap-3 flex-wrap">
          <div className="flex-1 min-w-[200px]">
            <label className="micro-label text-neutral-500 text-[0.65rem]">UMBRAL VIP (USDT)</label>
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
            className="bg-[#EAB308] hover:bg-[#FACC15] text-black rounded-none"
            data-testid="save-threshold-btn"
          >
            {savingThreshold ? "Guardando..." : "Guardar"}
          </Button>
        </div>
      </div>

      {/* MAIN STATS GRID */}
      <div className="grid lg:grid-cols-3 gap-6">
        <BigCard
          icon={ArrowDownLeft}
          title="Volumen entrante"
          subtitle="Total que clientes han enviado a la plataforma"
          items={stats.inflow.items}
          total={stats.inflow.total_usdt}
          unit="ORDS"
          field="count"
          dataTestId="stat-inflow"
        />
        <BigCard
          icon={ArrowUpRight}
          title="Volumen entregado"
          subtitle="Total que clientes han recibido"
          items={stats.outflow.items}
          total={stats.outflow.total_usdt}
          unit="ORDS"
          field="count"
          dataTestId="stat-outflow"
        />
        <BigCard
          icon={Coins}
          title="Saldo acumulado VIP"
          subtitle="Dinero dentro de la plataforma de clientes VIP"
          items={stats.vip_holdings.items}
          total={stats.vip_holdings.total_usdt}
          unit=""
          field={null}
          highlight
          dataTestId="stat-vip-holdings"
        />
      </div>
    </div>
  );
}

function Stat({ icon: Icon, label, value, sub, accent }) {
  return (
    <div className="tactile-card p-4">
      <Icon className={`w-4 h-4 mb-2 ${accent ? "text-[#EAB308]" : "text-neutral-500"}`} />
      <div className="micro-label text-neutral-500 text-[0.65rem]">{label}</div>
      <div className={`font-display text-2xl mt-1 ${accent ? "text-[#EAB308]" : ""}`}>{value}</div>
      {sub && <div className="text-xs text-neutral-500 mt-0.5">{sub}</div>}
    </div>
  );
}

function BigCard({ icon: Icon, title, subtitle, items, total, unit, field, highlight, dataTestId }) {
  return (
    <div className={`tactile-card p-6 ${highlight ? "glow-yellow" : ""}`} data-testid={dataTestId}>
      <div className="flex items-start justify-between mb-4">
        <div>
          <Icon className="w-5 h-5 text-[#EAB308] mb-3" />
          <h3 className="font-display text-lg">{title}</h3>
          <p className="text-xs text-neutral-500 mt-1">{subtitle}</p>
        </div>
      </div>
      <div className="border-b border-white/5 pb-4 mb-4">
        <div className="micro-label text-neutral-500 text-[0.6rem]">TOTAL EQUIVALENTE</div>
        <div className="font-display text-3xl text-[#EAB308] mt-1">
          {(total || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })} <span className="text-base text-neutral-400">USDT</span>
        </div>
      </div>
      {items.length === 0 ? (
        <p className="text-neutral-500 text-sm">Sin datos aún.</p>
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
