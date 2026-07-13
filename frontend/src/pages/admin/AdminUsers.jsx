import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { API } from "@/App";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Pagination } from "@/components/Pagination";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import { Search, BarChart3, Settings2 } from "lucide-react";

import UserFunctionsDialog from "./users/UserFunctionsDialog";

const PAGE_SIZE = 50;

const ROLE_LABELS = {
  normal: "Normal",
  vip: "VIP",
  employee: "Staff Member",
  admin: "Admin",
};

export default function AdminUsers() {
  const { user: currentUser } = useAuth();
  const navigate = useNavigate();
  const [users, setUsers] = useState([]);
  const [permCatalog, setPermCatalog] = useState([]);
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [currencies, setCurrencies] = useState([]);
  // Pending 2FA: { user_id, payload, label, kind? } — kept for email verify
  // flow still triggered from the parent (`verifyEmailManually`).
  const [pendingTotp, setPendingTotp] = useState(null);
  // iter55.33 — the consolidated Functions dialog target
  const [functionsUser, setFunctionsUser] = useState(null);

  useEffect(() => { setPage(0); }, [search, roleFilter]);

  // Debounce search input → 300ms
  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput.trim()), 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit: PAGE_SIZE, offset: page * PAGE_SIZE };
      if (search) params.q = search;
      if (roleFilter !== "all") params.role = roleFilter;
      const r = await axios.get(`${API}/admin/users`, { params, withCredentials: true });
      setUsers(r.data);
      const t = Number(r.headers["x-total-count"]);
      setTotal(Number.isFinite(t) ? t : r.data.length);
    } catch (e) {
      toast.error("Error al cargar usuarios");
    } finally {
      setLoading(false);
    }
  }, [page, search, roleFilter]);
  useEffect(() => { load(); }, [load]);

  // Load active currencies once
  useEffect(() => {
    axios.get(`${API}/currencies`).then(r => setCurrencies(r.data || [])).catch(() => {});
  }, []);

  // iter55.16 — load permission catalog once for the multi-select.
  useEffect(() => {
    axios.get(`${API}/admin/permissions/catalog`, { withCredentials: true })
      .then(r => setPermCatalog(r.data?.items || []))
      .catch(() => {});
  }, []);

  const verifyEmailManually = (user_id, email) =>
    setPendingTotp({
      kind: "verify-email",
      user_id,
      payload: {},
      label: `verificar manualmente el email de ${email}`,
    });

  const confirmWithTotp = async (code) => {
    const { user_id, payload, kind } = pendingTotp;
    try {
      if (kind === "verify-email") {
        await axios.post(`${API}/admin/users/${user_id}/verify-email`,
          { totp_code: code }, { withCredentials: true });
        toast.success("Email verificado manualmente");
      } else {
        await axios.put(`${API}/admin/users/${user_id}`,
          { ...payload, totp_code: code }, { withCredentials: true });
        toast.success("Usuario actualizado");
      }
      setPendingTotp(null);
      load();
    } catch (e) {
      if (!handleTotpError(e, navigate)) {
        toast.error(
          e.response?.data?.detail?.message || e.response?.data?.detail || "Error"
        );
      }
    }
  };

  const isAdmin = currentUser?.role === "admin";
  const canManageBlocklist =
    isAdmin ||
    (currentUser?.role === "employee" && !!currentUser?.can_manage_blocklist);
  const allowedRoles = isAdmin
    ? ["normal", "vip", "employee", "admin"]
    : ["normal", "vip"];

  return (
    <div data-testid="admin-users" className="space-y-4">
      <div className="mb-6">
        <div className="micro-label text-[#8B5CF6] mb-2">/ Usuarios</div>
        <h1 className="font-display text-3xl">Gestión de Clientes</h1>
      </div>

      <div className="flex items-end gap-3 mb-4 flex-wrap">
        <div>
          <div className="micro-label text-neutral-500 mb-1">Buscar (nombre o email)</div>
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500 pointer-events-none" />
            <Input
              data-testid="users-search"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="ej. ana@..."
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-80 pl-9 font-mono text-xs"
            />
          </div>
        </div>
        <div>
          <div className="micro-label text-neutral-500 mb-1">Rol</div>
          <Select value={roleFilter} onValueChange={setRoleFilter}>
            <SelectTrigger
              data-testid="users-role-filter"
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-44"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
              <SelectItem value="all">Todos los roles</SelectItem>
              <SelectItem value="normal">Cliente Normal</SelectItem>
              <SelectItem value="vip">VIP</SelectItem>
              <SelectItem value="employee">Staff Member</SelectItem>
              <SelectItem value="admin">Admin</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {(searchInput || roleFilter !== "all") && (
          <button
            data-testid="users-clear-search"
            onClick={() => { setSearchInput(""); setRoleFilter("all"); }}
            className="text-xs text-neutral-500 hover:text-[#8B5CF6] underline underline-offset-4 h-10"
          >
            limpiar filtros
          </button>
        )}
        <div className="ml-auto text-xs text-neutral-500" data-testid="users-result-count">
          {total} {total === 1 ? "resultado" : "resultados"}
        </div>
      </div>

      <div className="tactile-card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="border-b border-white/10 bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">Usuario</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Email</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Rol</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Registrado</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Acciones</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan="5" className="text-center text-neutral-500 py-8">Cargando...</td>
              </tr>
            )}
            {!loading && users.length === 0 && (
              <tr>
                <td colSpan="5" className="text-center text-neutral-500 py-8">Sin resultados</td>
              </tr>
            )}
            {users.map(u => (
              <tr key={u.user_id} className="border-b border-white/5">
                <td className="px-4 py-3 flex items-center gap-2">
                  {u.picture && <img src={u.picture} alt="" className="w-7 h-7 rounded-full" />}
                  <span>{u.name}</span>
                </td>
                <td className="px-4 py-3 text-neutral-400">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span>{u.email}</span>
                    {u.auth_provider === "password" && u.email_verified === false && (
                      <>
                        <span
                          data-testid={`email-unverified-${u.user_id}`}
                          className="text-[0.6rem] uppercase tracking-widest px-1.5 py-0.5 border border-[#EF4444]/40 text-[#EF4444] bg-[#EF4444]/10"
                          title="El usuario aún no verificó su email"
                        >
                          No verificado
                        </span>
                        <button
                          type="button"
                          data-testid={`verify-email-btn-${u.user_id}`}
                          onClick={() => verifyEmailManually(u.user_id, u.email)}
                          className="text-[0.65rem] uppercase tracking-widest text-[#8B5CF6] hover:text-[#A78BFA] underline underline-offset-4"
                          title="Marcar este email como verificado manualmente (requiere 2FA)"
                        >
                          Verificar
                        </button>
                      </>
                    )}
                  </div>
                </td>
                <td
                  className="px-4 py-3"
                  data-testid={`role-cell-${u.user_id}`}
                >
                  <span
                    data-testid={`role-badge-${u.user_id}`}
                    className={
                      "text-[0.65rem] uppercase tracking-widest px-2 py-1 border font-mono " +
                      (u.role === "admin"
                        ? "border-[#8B5CF6]/50 bg-[#8B5CF6]/10 text-[#8B5CF6]"
                        : u.role === "employee"
                        ? "border-emerald-500/40 bg-emerald-500/5 text-emerald-400"
                        : u.role === "vip"
                        ? "border-amber-500/40 bg-amber-500/5 text-amber-400"
                        : "border-white/10 bg-white/5 text-neutral-300")
                    }
                  >
                    {ROLE_LABELS[u.role] || u.role}
                  </span>
                </td>
                <td className="px-4 py-3 text-xs text-neutral-500">
                  {new Date(u.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    {(u.role === "vip" || u.role === "normal") && (
                      <button
                        type="button"
                        onClick={() => navigate(`/admin/users/${u.user_id}/stats`)}
                        className="flex items-center gap-1.5 px-3 py-2 border border-[#8B5CF6]/40 hover:border-[#8B5CF6] hover:bg-[#8B5CF6]/10 text-[#8B5CF6] text-xs uppercase tracking-widest transition-all"
                        title="Ver estadísticas completas del usuario"
                        data-testid={`user-stats-btn-${u.user_id}`}
                      >
                        <BarChart3 className="w-3.5 h-3.5" />
                        Estadísticas
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => setFunctionsUser(u)}
                      className="flex items-center gap-1.5 px-3 py-2 border border-emerald-500/40 hover:border-emerald-500 hover:bg-emerald-500/10 text-emerald-400 text-xs uppercase tracking-widest transition-all"
                      title="Configurar rol, permisos, monedas y accesos"
                      data-testid={`user-perms-btn-${u.user_id}`}
                    >
                      <Settings2 className="w-3.5 h-3.5" />
                      Funciones
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Pagination
        page={page}
        total={total}
        pageSize={PAGE_SIZE}
        loading={loading}
        onPageChange={setPage}
        testidPrefix="users-pagination"
      />

      <TotpPromptDialog
        open={!!pendingTotp}
        title="Confirmar cambio en usuario"
        description={`Vas a ${pendingTotp?.label || "actualizar este usuario"}. Ingresa tu código 2FA.`}
        onConfirm={confirmWithTotp}
        onCancel={() => setPendingTotp(null)}
      />

      <UserFunctionsDialog
        user={functionsUser}
        open={!!functionsUser}
        onClose={() => setFunctionsUser(null)}
        currencies={currencies}
        permCatalog={permCatalog}
        allowedRoles={allowedRoles}
        isAdmin={isAdmin}
        canManageBlocklist={canManageBlocklist}
        onUserUpdated={(fresh) => {
          setFunctionsUser(fresh);
          load();
        }}
      />
    </div>
  );
}
