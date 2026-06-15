import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";

export default function AdminUsers() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState([]);
  const [editing, setEditing] = useState({});

  const load = async () => {
    const r = await axios.get(`${API}/admin/users`, { withCredentials: true });
    setUsers(r.data);
  };
  useEffect(() => { load(); }, []);

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
    <div data-testid="admin-users">
      <div className="mb-6">
        <div className="micro-label text-[#EAB308] mb-2">/ Usuarios</div>
        <h1 className="font-display text-3xl">Gestión de Clientes</h1>
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
                          {role === "normal" ? "Normal" : role === "vip" ? "VIP" : role === "employee" ? "Empleado" : "Admin"}
                        </SelectItem>
                      ))}
                      {/* Show current role if not in allowedRoles (for employees viewing admins) */}
                      {!allowedRoles.includes(u.role) && (
                        <SelectItem key={u.role} value={u.role} disabled>
                          {u.role === "admin" ? "Admin" : "Empleado"}
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
    </div>
  );
}
