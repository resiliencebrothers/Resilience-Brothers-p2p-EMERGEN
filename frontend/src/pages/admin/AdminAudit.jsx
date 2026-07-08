import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Pagination } from "@/components/Pagination";
import MonthlyAuditReport from "@/pages/admin/audit/MonthlyAuditReport";
import { Shield, Download, FileText } from "lucide-react";

const ACTION_BADGE = {
  "order.approved": "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  "order.rejected": "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30",
  "order.completed": "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  "order.pending": "bg-neutral-700/40 text-neutral-400 border-neutral-700",
  "rate.update": "bg-[#EAB308]/10 text-[#EAB308] border-[#EAB308]/30",
  "user.update": "bg-[#3B82F6]/10 text-[#3B82F6] border-[#3B82F6]/30",
  "settings.update": "bg-[#EAB308]/10 text-[#EAB308] border-[#EAB308]/30",
};

const PAGE_SIZE = 50;

export default function AdminAudit() {
  const [entries, setEntries] = useState([]);
  const [actionFilter, setActionFilter] = useState("all");
  const [actorFilter, setActorFilter] = useState("");
  const [sinceFilter, setSinceFilter] = useState("");
  const [untilFilter, setUntilFilter] = useState("");
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  // Reset to first page whenever filters change
  useEffect(() => {
    setPage(0);
  }, [actionFilter, actorFilter, sinceFilter, untilFilter]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit: PAGE_SIZE, offset: page * PAGE_SIZE };
      if (actionFilter !== "all") params.action = actionFilter;
      if (actorFilter) params.actor_id = actorFilter;
      if (sinceFilter) params.since = sinceFilter;
      if (untilFilter) params.until = untilFilter;
      const r = await axios.get(`${API}/admin/audit`, { params, withCredentials: true });
      setEntries(r.data);
      const headerTotal = Number(r.headers["x-total-count"]);
      setTotal(Number.isFinite(headerTotal) ? headerTotal : r.data.length);
    } catch (e) {
      toast.error("Error al cargar audit log");
    } finally {
      setLoading(false);
    }
  }, [actionFilter, actorFilter, sinceFilter, untilFilter, page]);
  useEffect(() => { load(); }, [load]);

  const downloadExport = async (kind) => {
    try {
      const params = new URLSearchParams();
      if (actionFilter !== "all") params.set("action", actionFilter);
      if (actorFilter) params.set("actor_id", actorFilter);
      if (sinceFilter) params.set("since", sinceFilter);
      if (untilFilter) params.set("until", untilFilter);
      const url = `${API}/admin/audit/export.${kind}?${params.toString()}`;
      const r = await axios.get(url, { responseType: "blob", withCredentials: true });
      const blobUrl = URL.createObjectURL(new Blob([r.data], { type: r.headers["content-type"] }));
      const a = document.createElement("a");
      a.href = blobUrl;
      const ts = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
      a.download = `audit_log_${ts}.${kind}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(blobUrl);
      toast.success(`Audit log exportado (${kind.toUpperCase()})`);
    } catch (e) {
      toast.error(`Error al exportar ${kind.toUpperCase()}`);
    }
  };

  const clearDates = () => { setSinceFilter(""); setUntilFilter(""); };

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

      {/* iter55.17 — Monthly executive audit report */}
      <MonthlyAuditReport />

      <div className="flex flex-wrap gap-3 items-end justify-between">
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
          <div>
            <div className="micro-label text-neutral-500 mb-1">Desde</div>
            <Input
              type="date"
              data-testid="audit-since-filter"
              value={sinceFilter}
              onChange={(e) => setSinceFilter(e.target.value)}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-40 font-mono text-xs"
            />
          </div>
          <div>
            <div className="micro-label text-neutral-500 mb-1">Hasta</div>
            <Input
              type="date"
              data-testid="audit-until-filter"
              value={untilFilter}
              onChange={(e) => setUntilFilter(e.target.value)}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-40 font-mono text-xs"
            />
          </div>
          {(sinceFilter || untilFilter) && (
            <button
              data-testid="audit-clear-dates"
              onClick={clearDates}
              className="text-xs text-neutral-500 hover:text-[#EAB308] underline underline-offset-4 h-10"
            >
              limpiar fechas
            </button>
          )}
        </div>
        <div className="flex gap-2">
          <Button
            data-testid="audit-export-csv"
            onClick={() => downloadExport("csv")}
            className="rounded-none bg-transparent border border-white/15 hover:border-[#EAB308]/60 hover:bg-[#EAB308]/5 text-white h-10 px-4 font-mono text-xs uppercase tracking-wider"
          >
            <Download className="w-3.5 h-3.5 mr-2" /> CSV
          </Button>
          <Button
            data-testid="audit-export-pdf"
            onClick={() => downloadExport("pdf")}
            className="rounded-none bg-[#EAB308] hover:bg-[#EAB308]/90 text-black h-10 px-4 font-mono text-xs uppercase tracking-wider font-bold"
          >
            <FileText className="w-3.5 h-3.5 mr-2" /> PDF
          </Button>
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
                <th className="px-4 py-3 micro-label text-neutral-500">Permisos al momento</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Acción</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Resumen</th>
                <th className="px-4 py-3 micro-label text-neutral-500">Entidad</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan="7" className="text-center text-neutral-500 py-8">Cargando...</td></tr>
              )}
              {!loading && entries.length === 0 && (
                <tr><td colSpan="7" className="text-center text-neutral-500 py-8">Sin registros aún.</td></tr>
              )}
              {entries.map((e) => (
                <tr key={e.id} className="border-b border-white/5 hover:bg-white/5">
                  <td className="px-4 py-3 text-xs text-neutral-400 font-mono whitespace-nowrap">{new Date(e.created_at).toLocaleString()}</td>
                  <td className="px-4 py-3 text-xs">{e.actor_name || e.actor_email}</td>
                  <td className="px-4 py-3"><span className="text-[0.65rem] uppercase tracking-wider text-neutral-500">{e.actor_role}</span></td>
                  <td className="px-4 py-3">
                    <PermissionsCell effective={e.actor_permissions_effective} raw={e.actor_permissions} />
                  </td>
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

      {total > 0 && (
        <Pagination
          page={page}
          total={total}
          pageSize={PAGE_SIZE}
          loading={loading}
          onPageChange={setPage}
          testidPrefix="audit-pagination"
        />
      )}
    </div>
  );
}


/**
 * iter55.16b — Compact "permissions at time of action" cell for the audit log.
 * Renders a color-coded badge and expands the raw list on hover.
 *
 *  - "all"                 → 'ADMIN' badge (green)
 *  - "all_staff_default"   → 'STAFF · sin restricción' badge (neutral)
 *  - array of codes        → 'N permisos' badge with tooltip listing codes
 */
function PermissionsCell({ effective, raw }) {
  if (effective === "all") {
    return (
      <span className="inline-flex items-center px-2 py-0.5 text-[0.65rem] uppercase tracking-wider bg-emerald-500/10 text-emerald-300 border border-emerald-500/30"
            data-testid="audit-perms-admin">
        Admin · sin límite
      </span>
    );
  }
  if (effective === "all_staff_default" || (Array.isArray(effective) && effective.length === 0)) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 text-[0.65rem] uppercase tracking-wider bg-neutral-500/10 text-neutral-400 border border-neutral-500/30"
            data-testid="audit-perms-open">
        Staff · sin restricción
      </span>
    );
  }
  const codes = Array.isArray(effective) ? effective : (raw || []);
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 text-[0.65rem] uppercase tracking-wider bg-[#EAB308]/10 text-[#EAB308] border border-[#EAB308]/30 cursor-help"
      title={codes.join(" · ")}
      data-testid="audit-perms-scoped"
    >
      {codes.length} permiso{codes.length === 1 ? "" : "s"}
    </span>
  );
}
