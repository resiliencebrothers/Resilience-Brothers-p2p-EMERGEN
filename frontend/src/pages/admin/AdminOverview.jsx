import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { Users, ListChecks, Coins, Package, Database } from "lucide-react";

export default function AdminOverview() {
  const [stats, setStats] = useState({ users: 0, orders: 0, pending: 0, products: 0, currencies: 0, rates: 0 });

  const load = async () => {
    const [u, o, p, c, r] = await Promise.all([
      axios.get(`${API}/admin/users`, { withCredentials: true }),
      axios.get(`${API}/admin/orders`, { withCredentials: true }),
      axios.get(`${API}/products`, { withCredentials: true }),
      axios.get(`${API}/currencies`, { withCredentials: true }),
      axios.get(`${API}/rates`, { withCredentials: true }),
    ]);
    setStats({
      users: u.data.length,
      orders: o.data.length,
      pending: o.data.filter(x => x.status === "pending").length,
      products: p.data.length,
      currencies: c.data.length,
      rates: r.data.length,
    });
  };
  useEffect(() => { load().catch(() => {}); }, []);

  const seed = async () => {
    try {
      await axios.post(`${API}/admin/seed`, {}, { withCredentials: true });
      toast.success("Datos seed creados");
      load();
    } catch (e) { toast.error("Error al hacer seed"); }
  };

  return (
    <div className="space-y-8" data-testid="admin-overview">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="micro-label text-[#EAB308] mb-2">/ Control Room</div>
          <h1 className="font-display text-3xl">Panel de Administración</h1>
        </div>
        <Button data-testid="seed-btn" onClick={seed} className="bg-[#EAB308] hover:bg-[#FACC15] text-black rounded-none">
          <Database className="w-4 h-4 mr-2" /> Cargar datos demo
        </Button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
        <Stat icon={Users} label="Usuarios" value={stats.users} />
        <Stat icon={ListChecks} label="Órdenes totales" value={stats.orders} />
        <Stat icon={ListChecks} label="Pendientes" value={stats.pending} accent />
        <Stat icon={Coins} label="Monedas" value={stats.currencies} />
        <Stat icon={Coins} label="Tasas activas" value={stats.rates} />
        <Stat icon={Package} label="Productos" value={stats.products} />
      </div>
    </div>
  );
}

function Stat({ icon: Icon, label, value, accent }) {
  return (
    <div className="tactile-card p-6">
      <Icon className={`w-5 h-5 mb-3 ${accent ? "text-[#EAB308]" : "text-neutral-400"}`} />
      <div className="micro-label text-neutral-500">{label}</div>
      <div className={`font-display text-3xl mt-1 ${accent ? "text-[#EAB308]" : ""}`}>{value}</div>
    </div>
  );
}
