import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Checkbox } from "@/components/ui/checkbox";
import { Pagination } from "@/components/Pagination";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import { Search, ChevronDown } from "lucide-react";

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

  const verifyEmailManually = (user_id, email) => {
    setPendingTotp({
      kind: "verify-email",
      user_id,
      payload: {},
      label: `verificar manualmente el email de ${email}`,
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
      if (!handleTotpError(e, navigate)) toast.error(e.response?.data?.detail || "Error");
    }
  };

  const isAdmin = currentUser?.role === "admin";
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
              <th className="px-4 py-3 micro-label text-neutral-500">Registrado</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan="6" className="text-center text-neutral-500 py-8">Cargando...</td></tr>}
            {!loading && users.length === 0 && <tr><td colSpan="6" className="text-center text-neutral-500 py-8">Sin resultados</td></tr>}
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
