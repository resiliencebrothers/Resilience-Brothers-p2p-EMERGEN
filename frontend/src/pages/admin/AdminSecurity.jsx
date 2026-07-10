import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import { Shield, RefreshCw, Users, MapPin, Ban, AlertOctagon, Wifi, LogOut, Cloud, Plus, Trash2 } from "lucide-react";

// Static column headers — hoisted to module scope to avoid re-allocation
// on every render (each Panel had inline arrays in its `headers` prop).
const HEADERS_NEW_IP = ["Fecha", "Email", "Rol", "IP", "User-Agent"];
const HEADERS_RATE_LIMITED = ["IP", "Hits", "Último", "Endpoints"];
const HEADERS_ORIGIN_VIOLATIONS = ["Fecha", "Origin", "IP", "Método", "Path"];
const HEADERS_LOGIN_BURSTS = ["Identifier", "Fallos", "Último intento"];

/**
 * AdminSecurity — read-only operational security dashboard.
 *
 * Panels:
 *  1. Active sessions grouped by role + top-20 staff sessions (with revoke button)
 *  2. Admin/employee logins from new IPs (last 7 days)
 *  3. Top 10 IPs blocked by the rate limiter
 *  4. Latest 20 origin-allowlist violations
 *  5. Failed-login bursts by identifier
 *
 * Admin-only. Requires role=admin (employees get 403 from the API).
 */
export default function AdminSecurity() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [revoking, setRevoking] = useState(null);
  const [cfData, setCfData] = useState(null);
  const [cfLoading, setCfLoading] = useState(true);
  const [cfDialogOpen, setCfDialogOpen] = useState(false);
  const [cfForm, setCfForm] = useState({ ip: "", notes: "" });
  const [cfSubmitting, setCfSubmitting] = useState(false);
  const [cfDeleting, setCfDeleting] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/admin/security/audit`, { withCredentials: true });
      setData(r.data);
    } catch (e) {
      const detail = e.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "No se pudo cargar el panel de seguridad");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadCloudflare = useCallback(async () => {
    setCfLoading(true);
    try {
      const r = await axios.get(`${API}/admin/security/cloudflare/blocks`, { withCredentials: true });
      setCfData(r.data);
    } catch (e) {
      const detail = e.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "No se pudo cargar la blocklist de Cloudflare");
    } finally {
      setCfLoading(false);
    }
  }, []);

  useEffect(() => { load(); loadCloudflare(); }, [load, loadCloudflare]);

  const revokeSessions = async (userId, email) => {
    if (!window.confirm(`¿Revocar TODAS las sesiones de ${email}?\nEl usuario tendrá que iniciar sesión de nuevo.`)) return;
    setRevoking(userId);
    try {
      const r = await axios.post(
        `${API}/admin/security/sessions/${userId}/revoke`,
        {},
        { withCredentials: true }
      );
      toast.success(`Revocadas ${r.data.revoked} sesión(es) de ${email}`);
      await load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "No se pudieron revocar");
    } finally {
      setRevoking(null);
    }
  };

  const submitCfBlock = async () => {
    const ip = cfForm.ip.trim();
    if (!ip) {
      toast.error("Ingresa una dirección IP");
      return;
    }
    setCfSubmitting(true);
    try {
      const r = await axios.post(
        `${API}/admin/security/cloudflare/blocks`,
        { ip, notes: cfForm.notes.trim() },
        { withCredentials: true }
      );
      if (r.data?.already_blocked) {
        toast.info(`La IP ${ip} ya estaba en la blocklist`);
      } else if (r.data?.cf_ok) {
        toast.success(`IP ${ip} bloqueada en app + Cloudflare WAF`);
      } else if (r.data?.created) {
        toast.success(`IP ${ip} bloqueada a nivel aplicación`);
      } else {
        toast.warning(`No se pudo bloquear: ${r.data?.reason || "revisa logs"}`);
      }
      setCfDialogOpen(false);
      setCfForm({ ip: "", notes: "" });
      await loadCloudflare();
    } catch (e) {
      toast.error(e.response?.data?.detail || "No se pudo crear el bloqueo");
    } finally {
      setCfSubmitting(false);
    }
  };

  const deleteCfBlock = async (blockId, ip) => {
    if (!window.confirm(`¿Desbloquear ${ip}?\nSe eliminará la regla en Cloudflare (si aplica) y el registro pasará a 'deleted'.`)) return;
    setCfDeleting(blockId);
    try {
      await axios.delete(
        `${API}/admin/security/cloudflare/blocks/${blockId}`,
        { withCredentials: true }
      );
      toast.success(`IP ${ip} desbloqueada`);
      await loadCloudflare();
    } catch (e) {
      toast.error(e.response?.data?.detail || "No se pudo desbloquear");
    } finally {
      setCfDeleting(null);
    }
  };

  if (loading) return <div className="text-sm text-neutral-500">Cargando panel de seguridad...</div>;
  if (!data) return null;

  return (
    <div data-testid="admin-security-page" className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl flex items-center gap-2">
            <Shield className="w-7 h-7 text-[#EAB308]" /> Auditoría de Seguridad
          </h1>
          <p className="text-sm text-neutral-400 mt-1">
            Ventana: <span className="text-white">últimos {data.window_days} días</span> · Generado: {data.generated_at?.slice(0, 16).replace("T", " ")}
          </p>
        </div>
        <Button
          data-testid="security-refresh-btn"
          onClick={load}
          size="sm"
          variant="outline"
          className="border-white/10 text-neutral-300 hover:bg-white/5"
        >
          <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> Recargar
        </Button>
      </div>

      {/* SUMMARY CARDS */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <SummaryCard
          icon={Users}
          label="Sesiones activas"
          value={data.active_sessions.total}
          hint={Object.entries(data.active_sessions.by_role).map(([r, n]) => `${r}: ${n}`).join(" · ")}
          testId="security-sessions-total"
        />
        <SummaryCard
          icon={MapPin}
          label="Admins desde IP nueva"
          value={data.admin_new_ip_logins.length}
          hint="últimos 7 días"
          tone={data.admin_new_ip_logins.length > 0 ? "warn" : "default"}
          testId="security-new-ip-count"
        />
        <SummaryCard
          icon={Ban}
          label="IPs bloqueadas (rate limit)"
          value={data.top_rate_limited_ips.reduce((s, r) => s + r.hits, 0)}
          hint={`${data.top_rate_limited_ips.length} IPs distintas`}
          tone={data.top_rate_limited_ips.length > 0 ? "warn" : "default"}
          testId="security-rate-limit-count"
        />
        <SummaryCard
          icon={AlertOctagon}
          label="Origen bloqueado (403)"
          value={data.recent_origin_violations.length}
          hint="últimos 7 días"
          tone={data.recent_origin_violations.length > 0 ? "danger" : "default"}
          testId="security-origin-block-count"
        />
      </div>

      {/* STAFF ACTIVE SESSIONS */}
      <Panel
        icon={Wifi}
        title="Sesiones de staff activas"
        subtitle="Sesiones no expiradas de admins y empleados. Revoca cualquiera que no reconozcas."
      >
        {data.active_sessions.staff_active.length === 0 && <Empty text="Ninguna sesión de staff activa." />}
        <ul className="space-y-2">
          {data.active_sessions.staff_active.map((s) => (
            <li key={s.user_id + s.created_at} className="flex flex-wrap items-center justify-between gap-2 border border-white/5 bg-black/30 px-3 py-2">
              <div className="min-w-0">
                <div className="text-sm text-white font-semibold truncate">{s.email || s.user_id}</div>
                <div className="text-[0.65rem] text-neutral-500">
                  <span className="text-[#EAB308] uppercase font-bold">{s.role}</span>
                  {" · "}Creada {s.created_at?.slice(0, 16).replace("T", " ")}
                  {" · "}Expira {s.expires_at?.slice(0, 16).replace("T", " ")}
                </div>
              </div>
              <Button
                size="sm"
                variant="outline"
                data-testid={`revoke-sessions-btn-${s.user_id}`}
                onClick={() => revokeSessions(s.user_id, s.email)}
                disabled={revoking === s.user_id}
                className="bg-[#EF4444]/10 border-[#EF4444]/40 text-[#EF4444] hover:bg-[#EF4444]/20"
              >
                <LogOut className="w-3.5 h-3.5 mr-1" /> Revocar
              </Button>
            </li>
          ))}
        </ul>
      </Panel>

      {/* NEW IP LOGINS */}
      <Panel
        icon={MapPin}
        title="Logins de staff desde IP nueva"
        subtitle="Un admin o empleado inició sesión desde una IP que no habíamos visto en los últimos 90 días. Verifica que sea legítimo."
      >
        {data.admin_new_ip_logins.length === 0 && <Empty text="Ningún login desde IP nueva. ✅" />}
        <TableSimple
          headers={HEADERS_NEW_IP}
          rows={data.admin_new_ip_logins.map((e) => [
            e.created_at?.slice(0, 16).replace("T", " "),
            e.user_email || "-",
            e.extra?.role || "-",
            e.ip,
            (e.user_agent || "-").slice(0, 60),
          ])}
        />
      </Panel>

      {/* TOP RATE-LIMITED IPS */}
      <Panel
        icon={Ban}
        title="Top IPs bloqueadas por rate limit"
        subtitle="Las 10 IPs con más golpes 429 en los últimos 7 días. Considera bloquearlas en Cloudflare si abusan."
      >
        {data.top_rate_limited_ips.length === 0 && <Empty text="Ninguna IP alcanzó el límite. ✅" />}
        <TableSimple
          headers={HEADERS_RATE_LIMITED}
          rows={data.top_rate_limited_ips.map((r) => [
            r.ip,
            r.hits,
            r.last_seen?.slice(0, 16).replace("T", " "),
            r.top_paths.slice(0, 3).join(", "),
          ])}
        />
      </Panel>

      {/* ORIGIN VIOLATIONS */}
      <Panel
        icon={AlertOctagon}
        title="Violaciones de allowlist Origin"
        subtitle="POST/PUT/DELETE bloqueados por venir de un Origin no permitido. Cada línea es un intento potencial de CSRF."
      >
        {data.recent_origin_violations.length === 0 && <Empty text="Ninguna violación. ✅" />}
        <TableSimple
          headers={HEADERS_ORIGIN_VIOLATIONS}
          rows={data.recent_origin_violations.map((e) => [
            e.created_at?.slice(0, 16).replace("T", " "),
            e.origin || "-",
            e.ip,
            e.method,
            e.path,
          ])}
        />
      </Panel>

      {/* LOGIN BURSTS */}
      <Panel
        icon={AlertOctagon}
        title="Ráfagas de logins fallidos"
        subtitle="Identifiers con más intentos fallidos en los últimos 7 días. Alto conteo puede indicar credential-stuffing."
      >
        {data.recent_login_bursts.length === 0 && <Empty text="Sin ráfagas anormales. ✅" />}
        <TableSimple
          headers={HEADERS_LOGIN_BURSTS}
          rows={data.recent_login_bursts.map((r) => [
            r.identifier,
            r.failed_attempts,
            r.last_seen?.slice(0, 16).replace("T", " "),
          ])}
        />
      </Panel>

      {/* IP BLOCKLIST (APP-LEVEL) */}
      <Panel
        icon={Cloud}
        title="Blocklist de IPs (aplicación)"
        subtitle="IPs bloqueadas a nivel aplicación: cualquier request de estas IPs recibe 403 antes de tocar la lógica de negocio. El scanner automático puede añadirlas cuando detecta floods. Si además configuras Cloudflare (CF_API_TOKEN + CF_ZONE_ID), el bloqueo también se aplica al borde."
      >
        <div className="mb-3 flex flex-wrap items-center gap-3 text-[0.7rem]">
          <span className="px-2 py-1 border border-emerald-500/40 bg-emerald-500/10 text-emerald-300">
            Enforcement app-level: activo ✓
          </span>
          <span className={`px-2 py-1 border ${cfData?.configured ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300" : "border-neutral-500/40 bg-neutral-500/10 text-neutral-400"}`}>
            Cloudflare edge: {cfData?.configured ? "configurado ✓" : "sin credenciales"}
          </span>
          <span className={`px-2 py-1 border ${cfData?.auto_block_enabled ? "border-[#EAB308]/40 bg-[#EAB308]/10 text-[#FEF3C7]" : "border-neutral-500/40 bg-neutral-500/10 text-neutral-400"}`}>
            Auto-block: {cfData?.auto_block_enabled ? "activo" : "solo app-level"}
          </span>
          <div className="ml-auto flex gap-2">
            <Button
              data-testid="cf-refresh-btn"
              onClick={loadCloudflare}
              size="sm"
              variant="outline"
              className="border-white/10 text-neutral-300 hover:bg-white/5"
            >
              <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> Recargar
            </Button>
            <Button
              data-testid="cf-add-block-btn"
              onClick={() => setCfDialogOpen(true)}
              size="sm"
              className="bg-[#EAB308] text-black hover:bg-[#EAB308]/90"
            >
              <Plus className="w-3.5 h-3.5 mr-1.5" /> Bloquear IP
            </Button>
          </div>
        </div>

        {cfLoading && <div className="text-xs text-neutral-500">Cargando blocklist…</div>}
        {!cfLoading && cfData?.items?.length === 0 && <Empty text="Ningún bloqueo registrado." />}
        {!cfLoading && cfData?.items?.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs" data-testid="cf-blocks-table">
              <thead>
                <tr className="text-[0.6rem] uppercase tracking-wider text-neutral-500 border-b border-white/5">
                  <th className="text-left py-2 pr-3 font-semibold">IP</th>
                  <th className="text-left py-2 pr-3 font-semibold">Estado</th>
                  <th className="text-left py-2 pr-3 font-semibold">Origen</th>
                  <th className="text-left py-2 pr-3 font-semibold">Notas</th>
                  <th className="text-left py-2 pr-3 font-semibold">Creado</th>
                  <th className="text-left py-2 pr-3 font-semibold">Acción</th>
                </tr>
              </thead>
              <tbody>
                {cfData.items.map((b) => (
                  <tr key={b.id} className="border-b border-white/5" data-testid={`cf-block-row-${b.id}`}>
                    <td className="py-1.5 pr-3 text-white font-mono text-[0.7rem]">{b.ip}</td>
                    <td className="py-1.5 pr-3">
                      <span className={`px-1.5 py-0.5 text-[0.6rem] uppercase font-bold ${statusStyle(b.status)}`}>
                        {b.status}
                      </span>
                    </td>
                    <td className="py-1.5 pr-3 text-neutral-400 text-[0.7rem]">{b.source}</td>
                    <td className="py-1.5 pr-3 text-neutral-400 text-[0.7rem] max-w-xs truncate" title={b.notes}>{b.notes || "-"}</td>
                    <td className="py-1.5 pr-3 text-neutral-400 font-mono text-[0.7rem]">{b.created_at?.slice(0, 16).replace("T", " ")}</td>
                    <td className="py-1.5 pr-3">
                      {b.status === "active" || b.status === "failed" ? (
                        <Button
                          data-testid={`cf-unblock-btn-${b.id}`}
                          size="sm"
                          variant="outline"
                          onClick={() => deleteCfBlock(b.id, b.ip)}
                          disabled={cfDeleting === b.id}
                          className="bg-[#EF4444]/10 border-[#EF4444]/40 text-[#EF4444] hover:bg-[#EF4444]/20 h-6 px-2 text-[0.65rem]"
                        >
                          <Trash2 className="w-3 h-3 mr-1" /> Desbloquear
                        </Button>
                      ) : (
                        <span className="text-neutral-600 text-[0.65rem] italic">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Dialog open={cfDialogOpen} onOpenChange={setCfDialogOpen}>
        <DialogContent data-testid="cf-block-dialog" className="bg-neutral-950 border-white/10">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-white">
              <Cloud className="w-5 h-5 text-[#EAB308]" /> Bloquear IP en Cloudflare WAF
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="text-[0.7rem] uppercase tracking-wider text-neutral-500">IP</label>
              <Input
                data-testid="cf-block-ip-input"
                placeholder="203.0.113.42"
                value={cfForm.ip}
                onChange={(e) => setCfForm({ ...cfForm, ip: e.target.value })}
                className="bg-black/40 border-white/10 text-white font-mono"
              />
            </div>
            <div>
              <label className="text-[0.7rem] uppercase tracking-wider text-neutral-500">Notas (opcional)</label>
              <Textarea
                data-testid="cf-block-notes-input"
                placeholder="Motivo del bloqueo…"
                value={cfForm.notes}
                onChange={(e) => setCfForm({ ...cfForm, notes: e.target.value })}
                className="bg-black/40 border-white/10 text-white text-sm"
                rows={2}
              />
            </div>
            {!cfData?.configured && (
              <div className="text-[0.7rem] text-blue-300 border border-blue-500/30 bg-blue-500/5 px-3 py-2">
                ℹ️ El bloqueo se aplicará a <strong>nivel aplicación</strong> (403 antes de la lógica de negocio). Si además configuras <code>CF_API_TOKEN</code> y <code>CF_ZONE_ID</code>, el bloqueo se replica al borde de Cloudflare para defense-in-depth.
              </div>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setCfDialogOpen(false)}
              className="border-white/10 text-neutral-300 hover:bg-white/5"
            >
              Cancelar
            </Button>
            <Button
              data-testid="cf-block-submit-btn"
              onClick={submitCfBlock}
              disabled={cfSubmitting || !cfForm.ip.trim()}
              className="bg-[#EF4444] text-white hover:bg-[#EF4444]/90"
            >
              {cfSubmitting ? "Bloqueando…" : "Confirmar bloqueo"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function statusStyle(status) {
  const map = {
    active: "border border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
    pending_create: "border border-[#EAB308]/40 bg-[#EAB308]/10 text-[#FEF3C7]",
    pending_delete: "border border-[#EAB308]/40 bg-[#EAB308]/10 text-[#FEF3C7]",
    deleted: "border border-neutral-500/40 bg-neutral-500/10 text-neutral-400",
    failed: "border border-[#EF4444]/40 bg-[#EF4444]/10 text-[#FEE2E2]",
  };
  return map[status] || "border border-neutral-500/40 bg-neutral-500/10 text-neutral-400";
}

function SummaryCard({ icon: Icon, label, value, hint, tone = "default", testId }) {
  const cls = {
    default: "border-white/5 bg-black/30 text-white",
    warn: "border-[#EAB308]/30 bg-[#EAB308]/5 text-[#FEF3C7]",
    danger: "border-[#EF4444]/40 bg-[#EF4444]/5 text-[#FEE2E2]",
  }[tone];
  return (
    <div data-testid={testId} className={`border ${cls} px-4 py-3`}>
      <div className="flex items-center gap-2 text-[0.65rem] uppercase tracking-wider text-neutral-500 mb-1">
        <Icon className="w-3.5 h-3.5" /> {label}
      </div>
      <div className="text-2xl font-bold">{value}</div>
      {hint && <div className="text-[0.65rem] text-neutral-500 mt-1">{hint}</div>}
    </div>
  );
}

function Panel({ icon: Icon, title, subtitle, children }) {
  return (
    <div className="border border-white/5 bg-black/20 p-4">
      <div className="flex items-start gap-2 mb-3">
        <Icon className="w-4 h-4 text-[#EAB308] mt-0.5" />
        <div>
          <div className="text-sm font-semibold text-white">{title}</div>
          <div className="text-[0.7rem] text-neutral-500 leading-relaxed">{subtitle}</div>
        </div>
      </div>
      {children}
    </div>
  );
}

function Empty({ text }) {
  return <div className="text-xs text-neutral-500 italic border border-white/5 bg-black/30 px-3 py-3 text-center">{text}</div>;
}

function TableSimple({ headers, rows }) {
  if (!rows || rows.length === 0) return null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-[0.6rem] uppercase tracking-wider text-neutral-500 border-b border-white/5">
            {headers.map((h) => (
              <th key={h} className="text-left py-2 pr-3 font-semibold">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={`${row[0]}-${i}`} className="border-b border-white/5">
              {row.map((cell, j) => (
                <td key={`${row[0]}-${j}`} className="py-1.5 pr-3 text-neutral-300 font-mono text-[0.7rem]">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
