import { useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Settings2, Coins, ShieldCheck, ShoppingBag, Phone as PhoneIcon, Shield } from "lucide-react";
import TotpPromptDialog from "@/components/TotpPromptDialog";
import { CurrencyMultiSelect } from "./CurrencyMultiSelect";
import { PermissionMultiSelect } from "./PermissionMultiSelect";
import { MarketPermsCell } from "./MarketPermsCell";
import { UserPhoneCell } from "./UserPhoneCell";

const TABS = [
  { id: "role",       label: "Rol",         icon: Shield },
  { id: "currencies", label: "Monedas",     icon: Coins },
  { id: "perms",      label: "Permisos",    icon: ShieldCheck },
  { id: "market",     label: "Marketplace", icon: ShoppingBag },
  { id: "phone",      label: "Teléfono",    icon: PhoneIcon },
];

const ROLE_LABELS = {
  normal: "Normal",
  vip: "VIP",
  employee: "Staff Member",
  admin: "Admin",
};

/**
 * iter55.33 — Consolidates the previously-inline user functions (role,
 * currencies, permissions, marketplace, phone verification) into a single
 * tabbed dialog reachable from the "Funciones" button in each user row.
 *
 * Why: the previous inline table required horizontal scrolling to reach
 * these controls, and it exposed sensitive functions to every staff member
 * regardless of `user_functions` permission. Now: staff can OPEN the button
 * but the backend enforces the permission — if missing, the affected PUT
 * calls return a Spanish 403 which we surface via toast.
 */
export default function UserFunctionsDialog({
  user, open, onClose, currencies, permCatalog, allowedRoles,
  isAdmin, canManageBlocklist,
  onUserUpdated,  // called after any successful mutation so the parent can refresh
}) {
  const [tab, setTab] = useState("role");
  const [pendingTotp, setPendingTotp] = useState(null);
  const [busy, setBusy] = useState(false);
  const [rejectingPhone, setRejectingPhone] = useState(null);
  // Local pending edits — persisted to backend only when the user hits the
  // "Guardar" button inside each MultiSelect. This mirrors the previous
  // inline table behavior.
  const [pendingCurrencies, setPendingCurrencies] = useState(null);
  const [pendingPerms, setPendingPerms] = useState(null);

  if (!user) return null;

  const putUserField = async (field, value, totpCode) => {
    setBusy(true);
    try {
      const body = { [field]: value };
      if (totpCode) body.totp_code = totpCode;
      const r = await axios.put(`${API}/admin/users/${user.user_id}`, body, {
        withCredentials: true,
      });
      onUserUpdated?.(r.data);
      toast.success("Cambio guardado.");
      setPendingTotp(null);
      return true;
    } catch (e) {
      const detail = e.response?.data?.detail;
      if (typeof detail === "object" && detail?.code === "TOTP_CODE_REQUIRED") {
        setPendingTotp({ field, value });
        return false;
      }
      if (e.response?.status === 403) {
        toast.error(typeof detail === "string"
          ? detail
          : "Acceso restringido — pídele a un admin el permiso 'Funciones de usuario'.");
      } else {
        toast.error(typeof detail === "string" ? detail : "Error al guardar.");
      }
      return false;
    } finally {
      setBusy(false);
    }
  };

  const saveRole = (role) => putUserField("role", role);
  const saveAllowedCurrencies = (list) => putUserField("allowed_currencies", list);
  const savePermissions = (list) => putUserField("allowed_permissions", list);
  const saveMarketPerm = (key, value) => putUserField(key, value);
  const saveAccountStatus = (status) => putUserField("account_status", status);

  const verifyPhone = async (totpCode) => {
    setBusy(true);
    try {
      await axios.post(`${API}/admin/users/${user.user_id}/verify-phone`,
                         { totp_code: totpCode }, { withCredentials: true });
      toast.success("Teléfono verificado.");
      setPendingTotp(null);
      onUserUpdated?.({ ...user, phone_verified_at: new Date().toISOString() });
    } catch (e) {
      const detail = e.response?.data?.detail;
      if (typeof detail === "object" && detail?.code === "TOTP_CODE_REQUIRED") {
        setPendingTotp({ action: "verify-phone" });
        return;
      }
      if (e.response?.status === 403) {
        toast.error(typeof detail === "string" ? detail
          : "Acceso restringido — pídele a un admin el permiso 'Funciones de usuario'.");
      } else {
        toast.error(typeof detail === "string" ? detail : "Error al verificar teléfono.");
      }
    } finally {
      setBusy(false);
    }
  };

  const rejectPhone = (target) => setRejectingPhone(target);

  const confirmRejectPhone = async (reason, totpCode) => {
    if (!rejectingPhone) return;
    setBusy(true);
    try {
      await axios.post(`${API}/admin/users/${rejectingPhone.user_id}/reject-phone`,
                         { reason, totp_code: totpCode }, { withCredentials: true });
      toast.success("Teléfono rechazado.");
      setRejectingPhone(null);
      setPendingTotp(null);
      onUserUpdated?.({ ...user, phone_verified_at: null });
    } catch (e) {
      const detail = e.response?.data?.detail;
      if (typeof detail === "object" && detail?.code === "TOTP_CODE_REQUIRED") {
        setPendingTotp({ action: "reject-phone", reason });
        return;
      }
      toast.error(typeof detail === "string" ? detail : "Error al rechazar teléfono.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
        <DialogContent
          className="bg-[#0c0c0c] border border-white/10 text-white rounded-none max-w-3xl max-h-[85vh] overflow-y-auto"
          data-testid="user-functions-dialog"
        >
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Settings2 className="w-5 h-5 text-[#8B5CF6]" />
              Funciones de {user.name || user.email}
            </DialogTitle>
          </DialogHeader>

          <nav className="flex gap-1 border-b border-white/10 -mx-6 px-6 overflow-x-auto">
            {TABS.filter((tt) => tt.id !== "perms" || user.role === "employee").map((tt) => {
              const Icon = tt.icon;
              const active = tab === tt.id;
              return (
                <button
                  key={tt.id}
                  onClick={() => setTab(tt.id)}
                  data-testid={`user-functions-tab-${tt.id}`}
                  className={
                    "flex items-center gap-2 px-3 py-2 text-xs font-medium whitespace-nowrap " +
                    (active
                      ? "text-violet-300 border-b-2 border-violet-500 -mb-px"
                      : "text-white/50 hover:text-white")
                  }
                >
                  <Icon className="w-3.5 h-3.5" /> {tt.label}
                </button>
              );
            })}
          </nav>

          <div className="mt-4 space-y-4">
            {tab === "role" && (
              <div data-testid="uf-role-tab">
                <div className="micro-label text-neutral-500 mb-2">Rol actual</div>
                <Select value={user.role} onValueChange={saveRole}
                          disabled={!isAdmin && (user.role === "admin" || user.role === "employee")}>
                  <SelectTrigger className="rounded-none w-full bg-[#0a0a0a] border-white/10 h-11"
                                   data-testid="uf-role-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                    {allowedRoles.map((r) => (
                      <SelectItem key={r} value={r}>{ROLE_LABELS[r] || r}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                <div className="mt-6">
                  <div className="micro-label text-neutral-500 mb-2">Estado de la cuenta</div>
                  <Select value={user.account_status || "active"} onValueChange={saveAccountStatus}>
                    <SelectTrigger className="rounded-none w-full bg-[#0a0a0a] border-white/10 h-11"
                                     data-testid="uf-status-select">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                      <SelectItem value="active">Activo</SelectItem>
                      <SelectItem value="under_review">En revisión</SelectItem>
                      <SelectItem value="blocked">Bloqueado</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            )}

            {tab === "currencies" && (
              <div data-testid="uf-currencies-tab">
                <div className="micro-label text-neutral-500 mb-3">Monedas autorizadas</div>
                {user.role === "employee" ? (
                  <CurrencyMultiSelect
                    userId={user.user_id}
                    allCurrencies={currencies}
                    selected={pendingCurrencies ?? (user.allowed_currencies || [])}
                    onToggle={(code, isOn) => {
                      const cur = pendingCurrencies ?? (user.allowed_currencies || []);
                      const next = isOn
                        ? [...new Set([...cur, code])]
                        : cur.filter((c) => c !== code);
                      setPendingCurrencies(next);
                    }}
                    onSave={() => saveAllowedCurrencies(pendingCurrencies ?? (user.allowed_currencies || []))}
                    onClear={() => setPendingCurrencies([])}
                  />
                ) : (
                  <p className="text-sm text-neutral-500">
                    Este control aplica sólo a Staff Members. Clientes ({user.role}) pueden operar
                    con todas las monedas activas.
                  </p>
                )}
              </div>
            )}

            {tab === "perms" && user.role === "employee" && (
              <div data-testid="uf-perms-tab">
                <div className="micro-label text-neutral-500 mb-3">Permisos granulares</div>
                <PermissionMultiSelect
                  userId={user.user_id}
                  catalog={permCatalog}
                  selected={pendingPerms ?? (user.allowed_permissions || [])}
                  onToggle={(code, isOn) => {
                    const cur = pendingPerms ?? (user.allowed_permissions || []);
                    const next = isOn
                      ? [...new Set([...cur, code])]
                      : cur.filter((c) => c !== code);
                    setPendingPerms(next);
                  }}
                  onSave={() => savePermissions(pendingPerms ?? (user.allowed_permissions || []))}
                  onClear={() => setPendingPerms([])}
                />
                <p className="text-xs text-neutral-500 mt-3 leading-relaxed">
                  Si la lista queda vacía, el staff tendrá acceso completo (comportamiento legacy).
                  Solo un admin puede modificar estos permisos.
                </p>
              </div>
            )}

            {tab === "market" && (
              <div data-testid="uf-market-tab">
                <div className="micro-label text-neutral-500 mb-3">Permisos del marketplace</div>
                <MarketPermsCell
                  user={user}
                  onToggle={(key, value) => saveMarketPerm(key, value)}
                />
              </div>
            )}

            {tab === "phone" && (
              <div data-testid="uf-phone-tab">
                <div className="micro-label text-neutral-500 mb-3">Verificación de teléfono</div>
                <UserPhoneCell
                  user={user}
                  canManageBlocklist={canManageBlocklist}
                  onVerify={() => verifyPhone()}
                  onReject={() => rejectPhone({ user_id: user.user_id, phone: user.phone, email: user.email })}
                />
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      <TotpPromptDialog
        open={!!pendingTotp}
        title="Confirma esta acción"
        description="Ingresa tu código 2FA para modificar este usuario."
        onConfirm={(code) => {
          if (pendingTotp?.action === "verify-phone") verifyPhone(code);
          else if (pendingTotp?.action === "reject-phone") confirmRejectPhone(pendingTotp.reason, code);
          else if (pendingTotp?.field) putUserField(pendingTotp.field, pendingTotp.value, code);
        }}
        onCancel={() => setPendingTotp(null)}
        busy={busy}
      />

      {rejectingPhone && (
        <Dialog open onOpenChange={() => setRejectingPhone(null)}>
          <DialogContent className="bg-[#0c0c0c] border border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>Rechazar teléfono</DialogTitle>
            </DialogHeader>
            <textarea
              className="w-full bg-[#0a0a0a] border border-white/10 p-3 text-sm rounded-none"
              rows={3}
              placeholder="Motivo del rechazo (obligatorio)"
              value={rejectingPhone.reason || ""}
              onChange={(e) => setRejectingPhone({ ...rejectingPhone, reason: e.target.value })}
              data-testid="uf-phone-reject-reason"
            />
            <div className="flex justify-end gap-2 mt-3">
              <Button onClick={() => setRejectingPhone(null)}
                        className="rounded-none bg-transparent border border-white/15 text-white">
                Cancelar
              </Button>
              <Button
                onClick={() => confirmRejectPhone(rejectingPhone.reason || "")}
                disabled={busy || (rejectingPhone.reason || "").trim().length < 3}
                className="rounded-none bg-red-600 hover:bg-red-500 text-white font-bold"
                data-testid="uf-phone-reject-confirm"
              >
                Confirmar rechazo
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
