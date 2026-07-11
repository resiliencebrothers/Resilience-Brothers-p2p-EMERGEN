import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Activity, TrendingUp, Wallet, ArrowUpRight, CheckCircle, Clock } from "lucide-react";
import { Link } from "react-router-dom";
import BalanceConverterCard from "@/components/BalanceConverterCard";

export default function OverviewView() {
  const { user } = useAuth();
  const [rates, setRates] = useState([]);
  const [orders, setOrders] = useState([]);
  const [withdrawals, setWithdrawals] = useState([]);
  const [balances, setBalances] = useState(null);

  useEffect(() => {
    axios.get(`${API}/rates`).then(r => setRates(r.data)).catch(() => {});
    axios.get(`${API}/orders/mine`, { withCredentials: true }).then(r => setOrders(r.data)).catch(() => {});
    axios.get(`${API}/vip/balances`, { withCredentials: true }).then(r => setBalances(r.data)).catch(() => {});
    // iter55.22 — include VIP withdrawals so a "cash approved / En progreso" retiro
    // counts as pending until it's actually delivered/paid.
    axios.get(`${API}/vip/withdrawals/mine`, { withCredentials: true })
      .then(r => setWithdrawals(r.data))
      .catch(() => {});
  }, []);

  const isVip = user?.role === "vip" || user?.role === "admin";
  const isStaff = user?.role === "admin" || user?.role === "employee";
  const isClient = user && !isStaff;

  // iter55.22 / .25 — an order/withdrawal counts as "pendiente" for the
  // client while the operation is not yet finalised, but the semantics of
  // `approved` differ by type:
  //   • orders.approved      = "Confirmado" (staff validated + paid) → NOT pending
  //   • withdrawals.approved = "En progreso" for cash (approved but coins not
  //                             handed out yet) → still pending
  // If we lumped both together, a client with one confirmed order plus one
  // pending order would see "PENDIENTES: 2" but only 1 row in the history
  // — reported as a bug on 11 Feb 2026.
  const ORDER_IN_FLIGHT = new Set(["pending", "requires_double_approval"]);
  const WITHDRAWAL_IN_FLIGHT = new Set(["pending", "approved", "requires_double_approval"]);

  const pendingOrders = orders.filter(o => ORDER_IN_FLIGHT.has(o.status)).length;
  const pendingWithdrawals = withdrawals.filter(w => WITHDRAWAL_IN_FLIGHT.has(w.status)).length;
  const pending = pendingOrders + pendingWithdrawals;

  // Completed = terminal successful state for each type.
  //   • orders: delivered / completed / approved (Confirmado is a success)
  //   • withdrawals: paid
  const completedOrders = orders.filter(
    o => o.status === "delivered" || o.status === "completed" || o.status === "approved"
  ).length;
  const completedWithdrawals = withdrawals.filter(w => w.status === "paid").length;
  const approved = completedOrders + completedWithdrawals;

  return (
    <div className="space-y-8" data-testid="overview-view">
      <div>
        <div className="micro-label text-[#EAB308] mb-2">/ Dashboard</div>
        <h1 className="font-display text-3xl lg:text-4xl">Hola, {user?.name?.split(" ")[0]}.</h1>
        <p className="text-neutral-400 mt-2">
          {isVip ? "Cuenta VIP · Tasas preferenciales activas" : "Cuenta Estándar · Tasa según estatus"}
        </p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard icon={Wallet} label="Saldo Total" value={`${(balances?.total_usdt || 0).toFixed(2)}`} sub="USDT equivalente" />
        <StatCard icon={Clock} label="Pendientes" value={pending} sub="órdenes" />
        <StatCard icon={CheckCircle} label="Completadas" value={approved} sub="órdenes" />
        <StatCard icon={Activity} label="Estatus" value={user?.role?.toUpperCase()} sub="nivel" />
      </div>

      {/* iter50 — Converter widget visible to normal + vip clients */}
      {isClient && (
        <BalanceConverterCard
          onConverted={() =>
            axios.get(`${API}/vip/balances`, { withCredentials: true })
              .then((r) => setBalances(r.data))
              .catch(() => {})
          }
        />
      )}

      <div className="grid lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 tactile-card p-6">
          <div className="flex items-center justify-between mb-6">
            <h2 className="font-display text-xl flex items-center gap-2"><TrendingUp className="w-5 h-5 text-[#EAB308]" /> Tasas Vigentes</h2>
            <Link to="/dashboard/exchange" className="micro-label text-[#EAB308] hover:underline">Operar →</Link>
          </div>
          <div className="space-y-2">
            {rates.length === 0 && <p className="text-neutral-500 text-sm">No hay tasas configuradas aún.</p>}
            {rates.map(r => (
              <div key={r.id} className="flex items-center justify-between border-b border-white/5 py-3 last:border-0">
                <div>
                  <span className="font-mono text-sm">{r.from_code} → {r.to_code}</span>
                </div>
                <div className="text-right">
                  <div className="font-mono text-sm">
                    {isVip ? (
                      <span className="text-[#22C55E]">{r.rate_vip}</span>
                    ) : (
                      <span>{r.rate_normal}</span>
                    )}
                  </div>
                  <div className="micro-label text-neutral-500 text-[0.6rem]">
                    {isVip ? "TASA VIP" : `VIP: ${r.rate_vip}`}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="tactile-card p-6">
          <h2 className="font-display text-xl mb-4">Acciones Rápidas</h2>
          <div className="space-y-2">
            <Link to="/dashboard/exchange" data-testid="quick-exchange" className="block border border-white/10 hover:border-[#EAB308] p-4 transition-colors group">
              <div className="flex items-center justify-between">
                <span className="font-medium">Nuevo Intercambio</span>
                <ArrowUpRight className="w-4 h-4 text-neutral-500 group-hover:text-[#EAB308]" />
              </div>
              <div className="micro-label text-neutral-500 mt-1">Cripto ↔ Fiat</div>
            </Link>
            <Link to="/dashboard/orders" data-testid="quick-orders" className="block border border-white/10 hover:border-[#EAB308] p-4 transition-colors group">
              <div className="flex items-center justify-between">
                <span className="font-medium">Ver Órdenes</span>
                <ArrowUpRight className="w-4 h-4 text-neutral-500 group-hover:text-[#EAB308]" />
              </div>
              <div className="micro-label text-neutral-500 mt-1">Historial completo</div>
            </Link>
            {isClient && (
              <Link to="/dashboard/marketplace" data-testid="quick-marketplace" className="block border border-white/10 hover:border-[#EAB308] p-4 transition-colors group">
                <div className="flex items-center justify-between">
                  <span className="font-medium">Marketplace</span>
                  <ArrowUpRight className="w-4 h-4 text-neutral-500 group-hover:text-[#EAB308]" />
                </div>
                <div className="micro-label text-neutral-500 mt-1">Canjea tu saldo</div>
              </Link>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function StatCard({ icon: Icon, label, value, sub }) {
  return (
    <div className="tactile-card p-5">
      <Icon className="w-5 h-5 text-[#EAB308] mb-3" />
      <div className="micro-label text-neutral-500">{label}</div>
      <div className="font-display text-2xl mt-1">{value}</div>
      <div className="text-xs text-neutral-500 mt-1">{sub}</div>
    </div>
  );
}
