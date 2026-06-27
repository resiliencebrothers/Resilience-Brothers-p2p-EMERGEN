import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Checkbox } from "@/components/ui/checkbox";
import { Pagination } from "@/components/Pagination";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import { Search, ChevronDown, Ban } from "lucide-react";

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
  const [editingCurrencies, setEditingCurrencies] = useState({});
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [currencies, setCurrencies] = useState([]);
  // Pending 2FA: { user_id, payload, label }
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

  // Load active currencies once (for employee allowed_currencies UI)
  useEffect(() => {
    axios.get(`${API}/currencies`).then(r => setCurrencies(r.data || [])).catch(() => {});
  }, []);

  const saveRole = (user_id, role) => {
    setPendingTotp({
      user_id,
      payload: { role },
      label: `cambiar rol a ${role}`,
    });
  };

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

  const PERM_LABELS = {
    can_edit_product_prices: "modificar precios de productos",
    can_upload_product_images: "subir imágenes de productos",
    can_delete_products: "eliminar productos",
    can_manage_blocklist: "gestionar lista de bloqueos y verificar teléfonos",
  };

  const saveMarketPerm = (user_id, perm, value) => {
    setPendingTotp({
      user_id,
      payload: { [perm]: value },
      label: `${value ? "otorgar" : "revocar"} permiso para ${PERM_LABELS[perm]}`,
    });
  };

  const verifyEmailManually = (user_id, email) => {
    setPendingTotp({
      kind: "verify-email",
      user_id,
      payload: {},
      label: `verificar manualmente el email de ${email}`,
    });
  };

  const verifyPhoneManually = (user_id, phone, email) => {
    setPendingTotp({
      kind: "verify-phone",
      user_id,
      payload: {},
      label: `verificar el teléfono ${phone} de ${email}`,
    });
  };

  // iter28 — reject-phone flow: open dialog for reason, then prompt 2FA, then POST.
  const openRejectPhone = (user_id, phone, email) => {
    setRejectingPhone({ user_id, phone, email });
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
        await axios.post(
          `${API}/admin/users/${user_id}/verify-email`,
          { totp_code: code },
          { withCredentials: true }
        );
        toast.success("Email verificado manualmente");
      } else if (kind === "verify-phone") {
        await axios.post(
          `${API}/admin/users/${user_id}/verify-phone`,
          { totp_code: code },
          { withCredentials: true }
        );
        toast.success("Teléfono verificado manualmente. Cuenta activada.");
      } else if (kind === "reject-phone") {
        await axios.post(
          `${API}/admin/users/${user_id}/reject-phone`,
          { ...payload, totp_code: code },
          { withCredentials: true }
        );
        toast.success("Teléfono rechazado y bloqueado. Cuenta en revisión.");
      } else {
        await axios.put(
          `${API}/admin/users/${user_id}`,
          { ...payload, totp_code: code },
          { withCredentials: true }
        );
        toast.success("Usuario actualizado");
        if ("allowed_currencies" in payload) {
          setEditingCurrencies((prev) => ({ ...prev, [user_id]: undefined }));
        }
      }
      setPendingTotp(null);
      load();
    } catch (e) {
      if (!handleTotpError(e, navigate)) toast.error(e.response?.data?.detail?.message || e.response?.data?.detail || "Error");
    }
  };

  const isAdmin = currentUser?.role === "admin";
  // iter28 — admin OR staff with can_manage_blocklist may verify/reject phones
  const canManageBlocklist = isAdmin || (currentUser?.role === "employee" && !!currentUser?.can_manage_blocklist);
  const allowedRoles = isAdmin
    ? ["normal", "vip", "employee", "admin"]
    : ["normal", "vip"];

  return (
    <div data-testid="admin-users" className="space-y-4">
      <div className="mb-6">
        <div className="micro-label text-[#EAB308] mb-2">/ Usuarios</div>
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
            <SelectTrigger data-testid="users-role-filter" className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#141414] border-white/10 text-white rounded-none">
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
            className="text-xs text-neutral-500 hover:text-[#EAB308] underline underline-offset-4 h-10"
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
              <th className="px-4 py-3 micro-label text-neutral-500">Teléfono</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Permisos Mercado</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Registrado</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan="8" className="text-center text-neutral-500 py-8">Cargando...</td></tr>}
            {!loading && users.length === 0 && <tr><td colSpan="8" className="text-center text-neutral-500 py-8">Sin resultados</td></tr>}
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
                          className="text-[0.65rem] uppercase tracking-widest text-[#EAB308] hover:text-[#FACC15] underline underline-offset-4"
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
                    <SelectTrigger data-testid={`role-${u.user_id}`} className="rounded-none w-32 h-9 bg-[#0a0a0a] border-white/10"><SelectValue /></SelectTrigger>
                    <SelectContent className="bg-[#141414] border-white/10 text-white rounded-none">
                      {allowedRoles.map(role => (
                        <SelectItem key={role} value={role}>
                          {ROLE_LABELS[role] || role}
                        </SelectItem>
                      ))}
                      {/* Show current role if not in allowedRoles (for employees viewing admins) */}
                      {!allowedRoles.includes(u.role) && (
                        <SelectItem key={u.role} value={u.role} disabled>
                          {ROLE_LABELS[u.role] || u.role}
                        </SelectItem>
                      )}
                    </SelectContent>
                  </Select>
                </td>
                <td className="px-4 py-3 font-mono text-neutral-300" data-testid={`balance-${u.user_id}`}>
                  {(() => {
                    const legacy = Number(u.vip_balance_usd || 0);
                    const dict = u.vip_balances || {};
                    const parts = [];
                    if (legacy > 0) parts.push(`${legacy.toLocaleString(undefined, { maximumFractionDigits: 2 })} USD`);
                    Object.entries(dict).filter(([, v]) => Number(v) > 0).forEach(([k, v]) => parts.push(`${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })} ${k}`));
                    return parts.length ? parts.join(" · ") : <span className="text-neutral-600">—</span>;
                  })()}
                </td>
                <td className="px-4 py-3">
                  {u.role === "employee" ? (
                    <CurrencyMultiSelect
                      userId={u.user_id}
                      allCurrencies={currencies}
                      selected={editingCurrencies[u.user_id] ?? (u.allowed_currencies || [])}
                      onToggle={(code, isOn) => {
                        const current = editingCurrencies[u.user_id] ?? (u.allowed_currencies || []);
                        const next = isOn ? [...new Set([...current, code])] : current.filter((c) => c !== code);
                        setEditingCurrencies({ ...editingCurrencies, [u.user_id]: next });
                      }}
                      onSave={() => saveAllowedCurrencies(u.user_id, editingCurrencies[u.user_id] ?? (u.allowed_currencies || []))}
                      onClear={() => {
                        setEditingCurrencies({ ...editingCurrencies, [u.user_id]: [] });
                      }}
                    />
                  ) : (
                    <span className="text-neutral-600 text-xs">— sin restricción —</span>
                  )}
                </td>
                <td className="px-4 py-3">
                  {u.phone ? (
                    <div className="flex flex-col gap-1">
                      <span className="font-mono text-xs text-neutral-300" data-testid={`phone-${u.user_id}`}>{u.phone}</span>
                      {u.phone_verified ? (
                        <span className="text-[0.6rem] uppercase tracking-widest px-1.5 py-0.5 border border-[#22C55E]/40 text-[#22C55E] bg-[#22C55E]/10 self-start">Verificado</span>
                      ) : (canManageBlocklist ? (
                        <div className="flex gap-2 self-start">
                          <button
                            type="button"
                            data-testid={`verify-phone-btn-${u.user_id}`}
                            onClick={() => verifyPhoneManually(u.user_id, u.phone, u.email)}
                            className="text-[0.65rem] uppercase tracking-widest text-[#22C55E] hover:text-[#4ADE80] underline underline-offset-4"
                            title="Marcar como verificado y activar cuenta (requiere 2FA)"
                          >
                            ✓ Verificar
                          </button>
                          <button
                            type="button"
                            data-testid={`reject-phone-btn-${u.user_id}`}
                            onClick={() => openRejectPhone(u.user_id, u.phone, u.email)}
                            className="text-[0.65rem] uppercase tracking-widest text-[#EF4444] hover:text-[#FCA5A5] underline underline-offset-4"
                            title="Rechazar y bloquear (requiere 2FA)"
                          >
                            ✕ Rechazar
                          </button>
                        </div>
                      ) : (
                        <span className="text-[0.6rem] uppercase tracking-widest text-neutral-600 self-start" title="Sin permiso 'Bloqueos' — pídeselo a un admin">Pendiente</span>
                      ))}
                      {u.account_status && u.account_status !== "active" && u.role !== "admin" && u.role !== "employee" && (
                        <span
                          data-testid={`account-status-${u.user_id}`}
                          className={`text-[0.6rem] uppercase tracking-widest px-1.5 py-0.5 self-start ${u.account_status === "blocked" ? "border border-[#EF4444]/40 text-[#EF4444] bg-[#EF4444]/10" : "border border-[#EAB308]/40 text-[#EAB308] bg-[#EAB308]/10"}`}
                        >
                          {u.account_status === "blocked" ? "Bloqueada" : "En revisión"}
                        </span>
                      )}
                    </div>
                  ) : (
                    <span className="text-neutral-600 text-xs">— legacy —</span>
                  )}
                </td>
                <td className="px-4 py-3">
                  {u.role === "employee" ? (
                    <MarketPermsCell user={u} onToggle={(perm, value) => saveMarketPerm(u.user_id, perm, value)} />
                  ) : u.role === "admin" ? (
                    <span className="text-[0.65rem] text-[#EAB308] uppercase tracking-widest">acceso total</span>
                  ) : (
                    <span className="text-neutral-600 text-xs">—</span>
                  )}
                </td>
                <td className="px-4 py-3 text-xs text-neutral-500">{new Date(u.created_at).toLocaleDateString()}</td>
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

      {/* iter28 — Reject-phone reason dialog */}
      <Dialog open={!!rejectingPhone} onOpenChange={(o) => { if (!o) { setRejectingPhone(null); setRejectReason(""); } }}>
        <DialogContent data-testid="reject-phone-dialog" className="bg-[#0A0A0A] border-white/10 text-white rounded-none">
          <DialogHeader>
            <DialogTitle className="font-display text-2xl flex items-center gap-2">
              <Ban className="w-6 h-6 text-[#EF4444]" /> Rechazar y bloquear teléfono
            </DialogTitle>
            <DialogDescription className="text-neutral-500 text-xs">
              El número <span className="font-mono text-[#EF4444]">{rejectingPhone?.phone}</span> de{" "}
              <span className="text-neutral-300">{rejectingPhone?.email}</span> se agregará a la lista de bloqueados.
              La cuenta del usuario quedará <strong className="text-[#EAB308]">en revisión</strong> y no podrá operar
              en la plataforma. Esta acción se puede revertir borrando el contacto de la lista de bloqueos.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label className="micro-label text-neutral-500">Motivo del bloqueo *</Label>
              <Textarea
                data-testid="reject-phone-reason-input"
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                placeholder="Ej: comprobante falsificado, sospecha de estafa en grupo de WhatsApp, etc."
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 min-h-[100px]"
                autoFocus
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" onClick={() => { setRejectingPhone(null); setRejectReason(""); }} className="rounded-none">Cancelar</Button>
              <Button
                data-testid="reject-phone-confirm"
                onClick={confirmRejectPhone}
                disabled={rejectReason.trim().length < 3}
                className="bg-[#EF4444] hover:bg-[#DC2626] text-white font-bold rounded-none"
              >
                Continuar al 2FA
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}


function CurrencyMultiSelect({ userId, allCurrencies, selected, onToggle, onSave, onClear }) {
  const [open, setOpen] = useState(false);
  const selectedSet = new Set((selected || []).map((c) => String(c).toUpperCase()));
  const label =
    selectedSet.size === 0
      ? "Todas (sin restricción)"
      : selectedSet.size <= 3
      ? Array.from(selectedSet).join(", ")
      : `${selectedSet.size} monedas`;

  return (
    <div className="flex items-center gap-2" data-testid={`allowed-currencies-row-${userId}`}>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="ghost"
            data-testid={`open-currencies-${userId}`}
            className="rounded-none w-44 h-9 justify-between bg-[#0a0a0a] border border-white/10 hover:bg-[#1a1a1a] text-xs font-mono"
          >
            <span className={selectedSet.size === 0 ? "text-neutral-500" : "text-white"}>
              {label}
            </span>
            <ChevronDown className="w-3 h-3 text-neutral-500" />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          className="w-56 p-0 bg-[#141414] border border-white/10 rounded-none text-white"
        >
          <div className="px-3 py-2 micro-label text-neutral-500 border-b border-white/10">
            Selecciona monedas autorizadas
          </div>
          <div className="max-h-60 overflow-y-auto">
            {allCurrencies.length === 0 && (
              <div className="px-3 py-3 text-xs text-neutral-500">No hay monedas configuradas</div>
            )}
            {allCurrencies.map((c) => {
              const code = c.code;
              const isOn = selectedSet.has(code);
              return (
                <label
                  key={c.id || code}
                  className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-white/5"
                  data-testid={`currency-option-${userId}-${code}`}
                >
                  <Checkbox
                    checked={isOn}
                    onCheckedChange={(v) => onToggle(code, !!v)}
                    className="border-white/20 data-[state=checked]:bg-[#EAB308] data-[state=checked]:text-black"
                  />
                  <span className="font-mono text-sm">{code}</span>
                  {c.name && <span className="text-xs text-neutral-500 truncate">· {c.name}</span>}
                </label>
              );
            })}
          </div>
          <div className="border-t border-white/10 px-3 py-2 flex justify-between items-center gap-2">
            <button
              type="button"
              onClick={onClear}
              data-testid={`clear-currencies-${userId}`}
              className="text-xs text-neutral-400 hover:text-[#EF4444]"
            >
              Limpiar (todas)
            </button>
            <Button
              size="sm"
              data-testid={`save-currencies-${userId}`}
              onClick={() => { setOpen(false); onSave(); }}
              className="bg-[#EAB308] hover:bg-[#FACC15] text-black rounded-none h-8 text-xs"
            >
              Guardar
            </Button>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}

function MarketPermsCell({ user, onToggle }) {
  const items = [
    { key: "can_edit_product_prices", label: "Precios", title: "Puede modificar precios y costos de productos" },
    { key: "can_upload_product_images", label: "Imágenes", title: "Puede cambiar la URL de imagen promocional" },
    { key: "can_delete_products", label: "Eliminar", title: "Puede eliminar productos del catálogo" },
    { key: "can_manage_blocklist", label: "Bloqueos", title: "Puede ver y gestionar la lista de bloqueos, y verificar/rechazar teléfonos de usuarios" },
  ];
  return (
    <div className="flex flex-col gap-1.5" data-testid={`market-perms-${user.user_id}`}>
      {items.map(({ key, label, title }) => {
        const on = !!user[key];
        return (
          <label
            key={key}
            title={title}
            className={`flex items-center gap-2 cursor-pointer select-none text-xs ${on ? "text-[#22C55E]" : "text-neutral-500"}`}
          >
            <input
              type="checkbox"
              checked={on}
              onChange={(e) => onToggle(key, e.target.checked)}
              data-testid={`market-perm-${key}-${user.user_id}`}
              className="accent-[#EAB308] w-3.5 h-3.5"
            />
            <span className="font-mono">{label}</span>
          </label>
        );
      })}
    </div>
  );
}

