import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Shield, Filter } from "lucide-react";

const ACTION_BADGE = {
  "order.approved": "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  "order.rejected": "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30",
  "order.completed": "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  "order.pending": "bg-neutral-700/40 text-neutral-400 border-neutral-700",
  "rate.update": "bg-[#EAB308]/10 text-[#EAB308] border-[#EAB308]/30",
  "user.update": "bg-[#3B82F6]/10 text-[#3B82F6] border-[#3B82F6]/30",
  "settings.update": "bg-[#EAB308]/10 text-[#EAB308] border-[#EAB308]/30",
};

export default function AdminAudit() {
  const [entries, setEntries] = useState([]);
  const [actionFilter, setActionFilter] = useState("all");
  const [actorFilter, setActorFilter] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit: 200 };
      if (actionFilter !== "all") params.action = actionFilter;
      if (actorFilter) params.actor_id = actorFilter;
      const r = await axios.get(`${API}/admin/audit`, { params, withCredentials: true });
      setEntries(r.data);
    } catch (e) {
      toast.error("Error al cargar audit log");
    } finally {
      setLoading(false);
    }
  }, [actionFilter, actorFilter]);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-6" data-testid="admin-audit">
      <div>
        <div className="micro-label text-[#EAB308] mb-2">/ Auditoría</div>
        <h1 className="font-display text-3xl flex items-center gap-3">
          <Shield className="w-8 h-8 text-[#EAB308]" /> Registro de Acciones
        </h1>
        <p className="text-neutral-400 mt-2 text-sm">
          Trazabilidad completa: cada cambio de orden, tasa, usuario y configuración queda registrado con autor y momento exacto.
        </p>
      </div>

      <div className="flex flex-wrap gap-3 items-end">
        <div>
          <div className="micro-label text-neutral-500 mb-1">Filtrar acción</div>
          <Select value={actionFilter} onValueChange={setActionFilter}>
            <SelectTrigger data-testid="audit-action-filter" className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-52">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#141414] border-white/10 text-white rounded-none">
              <SelectItem value="all">Todas las acciones</SelectItem>
              <SelectItem value="order.approved">Órdenes aprobadas</SelectItem>
              <SelectItem value="order.rejected">Órdenes rechazadas</SelectItem>
              <SelectItem value="order.completed">Órdenes completadas</SelectItem>
              <SelectItem value="rate.update">Tasas actualizadas</SelectItem>
              <SelectItem value="user.update">Cambios de usuario</SelectItem>
              <SelectItem value="settings.update">Settings</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div>
          <div className="micro-label text-neutral-500 mb-1">Actor (user_id)</div>
          <Input
            data-testid="audit-actor-filter"
            value={actorFilter}
            onChange={(e) => setActorFilter(e.target.value)}
            placeholder="user_xxxxxx"
            className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-64 font-mono text-xs"
          />
        </div>
      </div>

      <div className="tactile-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-[#0a0a0a] border-b border-white/10">
              <tr className="text-left">
                <th className="px-4 py-3 micro-label text-neutral-500">Cuándo</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Quién</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Rol</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Acción</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Resumen</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Entidad</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan="6" className="text-center text-neutral-500 py-8">Cargando...</td></tr>
              )}
              {!loading && entries.length === 0 && (
                <tr><td colSpan="6" className="text-center text-neutral-500 py-8">Sin registros aún.</td></tr>
              )}
              {entries.map((e) => (
                <tr key={e.id} className="border-b border-white/5 hover:bg-white/5">
                  <td className="px-4 py-3 text-xs text-neutral-400 font-mono whitespace-nowrap">{new Date(e.created_at).toLocaleString()}</td>
                  <td className="px-4 py-3 text-xs">{e.actor_name || e.actor_email}</td>
                  <td className="px-4 py-3"><span className="text-[0.65rem] uppercase tracking-wider text-neutral-500">{e.actor_role}</span></td>
                  <td className="px-4 py-3">
                    <span className={`text-xs uppercase tracking-wider border px-2 py-0.5 font-mono ${ACTION_BADGE[e.action] || "bg-neutral-700/40 text-neutral-300 border-neutral-700"}`}>
                      {e.action}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm">{e.summary}</td>
                  <td className="px-4 py-3 text-xs font-mono text-neutral-500">{e.entity_id?.slice(0, 8) || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
