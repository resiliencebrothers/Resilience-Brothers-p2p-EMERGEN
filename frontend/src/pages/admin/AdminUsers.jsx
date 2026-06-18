import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Pagination } from "@/components/Pagination";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import { Search } from "lucide-react";

const PAGE_SIZE = 50;

const ROLE_LABELS = {
  normal: "Normal",
  vip: "VIP",
  employee: "Empleado",
  admin: "Admin",
};

export default function AdminUsers() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState([]);
  const [editing, setEditing] = useState({});
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  useEffect(() => { setPage(0); }, [search]);

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
      const r = await axios.get(`${API}/admin/users`, { params, withCredentials: true });
      setUsers(r.data);
      const t = Number(r.headers["x-total-count"]);
      setTotal(Number.isFinite(t) ? t : r.data.length);
    } catch (e) {
      toast.error("Error al cargar usuarios");
    } finally {
      setLoading(false);
    }
  }, [page, search]);
  useEffect(() => { load(); }, [load]);

  const saveRole = async (user_id, role) => {
    try {
      await axios.put(`${API}/admin/users/${user_id}`, { role }, { withCredentials: true });
      toast.success("Rol actualizado"); load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    }
  };

  const saveBalance = async (user_id) => {
    const val = parseFloat(editing[user_id]);
    if (isNaN(val)) return toast.error("Valor inválido");
    await axios.put(`${API}/admin/users/${user_id}`, { vip_balance_usd: val }, { withCredentials: true });
    toast.success("Saldo actualizado"); setEditing({ ...editing, [user_id]: undefined }); load();
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
      <div className="flex items-end gap-3 mb-4">
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
        {searchInput && (
          <button
            data-testid="users-clear-search"
            onClick={() => setSearchInput("")}
            className="text-xs text-neutral-500 hover:text-[#EAB308] underline underline-offset-4 h-10"
          >
            limpiar
          </button>
        )}
      </div>
      <div className="tactile-card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="border-b border-white/10 bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">Usuario</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Email</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Rol</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Saldo VIP</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Registrado</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan="5" className="text-center text-neutral-500 py-8">Cargando...</td></tr>}
            {!loading && users.length === 0 && <tr><td colSpan="5" className="text-center text-neutral-500 py-8">Sin resultados</td></tr>}
            {users.map(u => (
              <tr key={u.user_id} className="border-b border-white/5">
                <td className="px-4 py-3 flex items-center gap-2">
                  {u.picture && <img src={u.picture} alt="" className="w-7 h-7 rounded-full" />}
                  <span>{u.name}</span>
                </td>
                <td className="px-4 py-3 text-neutral-400">{u.email}</td>
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
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <Input
                      type="number"
                      defaultValue={u.vip_balance_usd}
                      onChange={e => setEditing({ ...editing, [u.user_id]: e.target.value })}
                      className="rounded-none w-28 h-9 bg-[#0a0a0a] border-white/10 font-mono"
                    />
                    <Button size="sm" onClick={() => saveBalance(u.user_id)} className="bg-[#EAB308] hover:bg-[#FACC15] text-black rounded-none h-9">OK</Button>
                  </div>
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
    </div>
  );
}
