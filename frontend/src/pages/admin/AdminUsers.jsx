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
import { Search, BarChart3 } from "lucide-react";

import { CurrencyMultiSelect } from "./users/CurrencyMultiSelect";
import { PermissionMultiSelect } from "./users/PermissionMultiSelect";
import { MarketPermsCell } from "./users/MarketPermsCell";
import { UserPhoneCell } from "./users/UserPhoneCell";
import { RejectPhoneDialog } from "./users/RejectPhoneDialog";

const PAGE_SIZE = 50;

const ROLE_LABELS = {
  normal: "Normal",
  vip: "VIP",
  employee: "Staff Member",
  admin: "Admin",
};

const PERM_LABELS = {
  can_edit_product_prices: "modificar precios de productos",
  can_upload_product_images: "subir imágenes de productos",
  can_delete_products: "eliminar productos",
  can_manage_blocklist: "gestionar lista de bloqueos y verificar teléfonos",
};

function renderUserBalance(u) {
  // iter55.32 — simplified to just the USDT-equivalent total. The full
  // per-currency breakdown lives on the dedicated user stats page reachable
  // from the "Ver estadísticas" button (keeps the row uncluttered).
  const totalUsdt = Number(u.vip_balance_usdt || 0);
  if (totalUsdt <= 0) {
    return <span className="text-neutral-600">—</span>;
  }
  return (
    <span
      className="font-mono text-sm text-neutral-300 tabular-nums"
      data-testid={`user-balance-${u.user_id}`}
    >
      {totalUsdt.toLocaleString(undefined, { maximumFractionDigits: 2 })}{" "}
      <span className="text-[0.65rem] text-[#8B5CF6]">USDT</span>
    </span>
  );
}

export default function AdminUsers() {
  const { user: currentUser } = useAuth();
  const navigate = useNavigate();
  const [users, setUsers] = useState([]);
  const [editingCurrencies, setEditingCurrencies] = useState({});
  const [editingPermissions, setEditingPermissions] = useState({});
  const [permCatalog, setPermCatalog] = useState([]);
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [currencies, setCurrencies] = useState([]);
  // Pending 2FA: { user_id, payload, label, kind? }
  const [pendingTotp, setPendingTotp] = useState(null);
  // Reject-phone flow: { user_id, phone, email } shown in a dialog to capture the reason
  const [rejectingPhone, setRejectingPhone] = useState(null);
  const [rejectReason, setRejectReason] = useState("");

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

  const saveRole = (user_id, role) =>
    setPendingTotp({ user_id, payload: { role }, label: `cambiar rol a ${role}` });

  const saveAllowedCurrencies = (user_id, list) => {
    const clean = (list || []).map((c) => String(c).toUpperCase()).filter(Boolean);
    setPendingTotp({
      user_id,
      payload: { allowed_currencies: clean },
      label: clean.length
        ? `asignar monedas (${clean.join(", ")})`
        : "quitar restricción de monedas",
    });
  };

  const saveAllowedPermissions = (user_id, list) => {
    const clean = (list || []).filter(Boolean);
    setPendingTotp({
      user_id,
      payload: { allowed_permissions: clean },
      label: clean.length
        ? `asignar ${clean.length} permiso(s) al staff`
        : "quitar restricción de permisos (acceso completo staff)",
    });
  };

  const saveMarketPerm = (user_id, perm, value) =>
    setPendingTotp({
      user_id,
      payload: { [perm]: value },
      label: `${value ? "otorgar" : "revocar"} permiso para ${PERM_LABELS[perm]}`,
    });

  const verifyEmailManually = (user_id, email) =>
    setPendingTotp({
      kind: "verify-email",
      user_id,
      payload: {},
      label: `verificar manualmente el email de ${email}`,
    });

  const verifyPhoneManually = (user_id, phone, email) =>
    setPendingTotp({
      kind: "verify-phone",
      user_id,
      payload: {},
      label: `verificar el teléfono ${phone} de ${email}`,
    });

  const openRejectPhone = (user_id, phone, email) => {
    setRejectingPhone({ user_id, phone, email });
    setRejectReason("");
  };

  const closeRejectPhone = () => {
    setRejectingPhone(null);
    setRejectReason("");
  };

  const confirmRejectPhone = () => {
    if (!rejectingPhone) return;
    const reason = rejectReason.trim();
    if (reason.length < 3) {
      toast.error("Escribe un motivo (mínimo 3 caracteres)");
      return;
    }
    const { user_id, phone, email } = rejectingPhone;
    setRejectingPhone(null);
    setPendingTotp({
      kind: "reject-phone",
      user_id,
      payload: { reason, notes: "" },
      label: `RECHAZAR teléfono ${phone} de ${email} y bloquear su número`,
    });
  };

  const confirmWithTotp = async (code) => {
    const { user_id, payload, kind } = pendingTotp;
    try {
      if (kind === "verify-email") {
        await axios.post(`${API}/admin/users/${user_id}/verify-email`,
          { totp_code: code }, { withCredentials: true });
        toast.success("Email verificado manualmente");
      } else if (kind === "verify-phone") {
        await axios.post(`${API}/admin/users/${user_id}/verify-phone`,
          { totp_code: code }, { withCredentials: true });
        toast.success("Teléfono verificado manualmente. Cuenta activada.");
      } else if (kind === "reject-phone") {
        await axios.post(`${API}/admin/users/${user_id}/reject-phone`,
          { ...payload, totp_code: code }, { withCredentials: true });
        toast.success("Teléfono rechazado y bloqueado. Cuenta en revisión.");
      } else {
        await axios.put(`${API}/admin/users/${user_id}`,
          { ...payload, totp_code: code }, { withCredentials: true });
        toast.success("Usuario actualizado");
        if ("allowed_currencies" in payload) {
          setEditingCurrencies((prev) => ({ ...prev, [user_id]: undefined }));
        }
        if ("allowed_permissions" in payload) {
          setEditingPermissions((prev) => ({ ...prev, [user_id]: undefined }));
        }
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
              <th className="px-4 py-3 micro-label text-neutral-500">Saldo (USDT eq.)</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Monedas autorizadas</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Funciones autorizadas</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Teléfono</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Permisos Mercado</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Registrado</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan="9" className="text-center text-neutral-500 py-8">Cargando...</td>
              </tr>
            )}
            {!loading && users.length === 0 && (
              <tr>
                <td colSpan="9" className="text-center text-neutral-500 py-8">Sin resultados</td>
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
                <td className="px-4 py-3">
                  <Select
                    value={u.role}
                    onValueChange={(v) => saveRole(u.user_id, v)}
                    disabled={!isAdmin && (u.role === "admin" || u.role === "employee")}
                  >
                    <SelectTrigger
                      data-testid={`role-${u.user_id}`}
                      className="rounded-none w-32 h-9 bg-[#0a0a0a] border-white/10"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                      {allowedRoles.map(role => (
                        <SelectItem key={role} value={role}>
                          {ROLE_LABELS[role] || role}
                        </SelectItem>
                      ))}
                      {!allowedRoles.includes(u.role) && (
                        <SelectItem key={u.role} value={u.role} disabled>
                          {ROLE_LABELS[u.role] || u.role}
                        </SelectItem>
                      )}
                    </SelectContent>
                  </Select>
                </td>
                <td
                  className="px-4 py-3 font-mono text-neutral-300"
                  data-testid={`balance-${u.user_id}`}
                >
                  <div className="flex items-center gap-2">
                    <div className="flex-1">{renderUserBalance(u)}</div>
                    {(u.role === "vip" || u.role === "normal") && (
                      <button
                        type="button"
                        onClick={() => navigate(`/admin/users/${u.user_id}/stats`)}
                        className="text-neutral-500 hover:text-[#8B5CF6] transition-colors p-1 border border-white/10 hover:border-[#8B5CF6]/40"
                        title="Ver estadísticas completas del usuario"
                        data-testid={`user-stats-btn-${u.user_id}`}
                      >
                        <BarChart3 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </td>
                <td className="px-4 py-3">
                  {u.role === "employee" ? (
                    <CurrencyMultiSelect
                      userId={u.user_id}
                      allCurrencies={currencies}
                      selected={editingCurrencies[u.user_id] ?? (u.allowed_currencies || [])}
                      onToggle={(code, isOn) => {
                        const current = editingCurrencies[u.user_id] ?? (u.allowed_currencies || []);
                        const next = isOn
                          ? [...new Set([...current, code])]
                          : current.filter((c) => c !== code);
                        setEditingCurrencies({ ...editingCurrencies, [u.user_id]: next });
                      }}
                      onSave={() =>
                        saveAllowedCurrencies(
                          u.user_id,
                          editingCurrencies[u.user_id] ?? (u.allowed_currencies || [])
                        )
                      }
                      onClear={() =>
                        setEditingCurrencies({ ...editingCurrencies, [u.user_id]: [] })
                      }
                    />
                  ) : (
                    <span className="text-neutral-600 text-xs">— sin restricción —</span>
                  )}
                </td>
                <td className="px-4 py-3">
                  {u.role === "employee" ? (
                    isAdmin ? (
                      <PermissionMultiSelect
                        userId={u.user_id}
                        catalog={permCatalog}
                        selected={editingPermissions[u.user_id] ?? (u.allowed_permissions || [])}
                        onToggle={(code, isOn) => {
                          const current = editingPermissions[u.user_id] ?? (u.allowed_permissions || []);
                          const next = isOn
                            ? [...new Set([...current, code])]
                            : current.filter((c) => c !== code);
                          setEditingPermissions({ ...editingPermissions, [u.user_id]: next });
                        }}
                        onSave={() =>
                          saveAllowedPermissions(
                            u.user_id,
                            editingPermissions[u.user_id] ?? (u.allowed_permissions || [])
                          )
                        }
                        onClear={() =>
                          setEditingPermissions({ ...editingPermissions, [u.user_id]: [] })
                        }
                      />
                    ) : (
                      <span className="text-neutral-600 text-xs" title="Solo un admin puede modificar permisos de staff">
                        {(u.allowed_permissions?.length ?? 0) === 0
                          ? "— sin restricción —"
                          : `${u.allowed_permissions.length} permiso(s)`}
                      </span>
                    )
                  ) : (
                    <span className="text-neutral-600 text-xs">— n/a —</span>
                  )}
                </td>
                <td className="px-4 py-3">
                  <UserPhoneCell
                    user={u}
                    canManageBlocklist={canManageBlocklist}
                    onVerify={() => verifyPhoneManually(u.user_id, u.phone, u.email)}
                    onReject={() => openRejectPhone(u.user_id, u.phone, u.email)}
                  />
                </td>
                <td className="px-4 py-3">
                  {u.role === "employee" ? (
                    <MarketPermsCell
                      user={u}
                      onToggle={(perm, value) => saveMarketPerm(u.user_id, perm, value)}
                    />
                  ) : u.role === "admin" ? (
                    <span className="text-[0.65rem] text-[#8B5CF6] uppercase tracking-widest">
                      acceso total
                    </span>
                  ) : (
                    <span className="text-neutral-600 text-xs">—</span>
                  )}
                </td>
                <td className="px-4 py-3 text-xs text-neutral-500">
                  {new Date(u.created_at).toLocaleDateString()}
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

      <RejectPhoneDialog
        target={rejectingPhone}
        reason={rejectReason}
        setReason={setRejectReason}
        onClose={closeRejectPhone}
        onConfirm={confirmRejectPhone}
      />
    </div>
  );
}
