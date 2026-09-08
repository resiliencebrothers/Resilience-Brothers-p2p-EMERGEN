import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Settings2, Coins, ShieldCheck, ShoppingBag, Phone as PhoneIcon, Shield, Layers, Ban, Wallet, Truck, Boxes } from "lucide-react";
import TotpPromptDialog from "@/components/TotpPromptDialog";
import { CurrencyMultiSelect, NO_CURRENCIES } from "./CurrencyMultiSelect";
import { PermissionMultiSelect } from "./PermissionMultiSelect";
import { MarketPermsCell } from "./MarketPermsCell";
import { UserPhoneCell } from "./UserPhoneCell";

const TABS = [
  { id: "role",       label: "Rol",         icon: Shield },
  { id: "currencies", label: "Monedas",     icon: Coins },
  { id: "perms",      label: "Permisos",    icon: ShieldCheck },
  { id: "batchpairs", label: "Lotes",       icon: Layers },
  { id: "market",     label: "Marketplace", icon: ShoppingBag },
  { id: "phone",      label: "Teléfono",    icon: PhoneIcon },
];

const ROLE_LABELS = {
  normal: "Normal",
  vip: "VIP",
  employee: "Staff Member",
  admin: "Admin",
};

// iter245 — perfiles predefinidos: permisos + monedas en un clic.
// iter251 — las plantillas SUMAN a lo ya concedido (no reemplazan).
const STAFF_TEMPLATES = [
  {
    id: "cajero", label: "Cajero", icon: Wallet,
    perms: ["orders", "withdrawals", "company_funds", "quick_view"],
    currencies: [],
    desc: "Suma: órdenes, retiros VIP, fondos de caja y cola de trabajo · todas las monedas",
  },
  {
    id: "mensajeria", label: "Mensajería", icon: Truck,
    perms: ["deliveries", "quick_view"],
    currencies: ["__NONE__"],
    desc: "Suma: gestión de entregas y mensajeros · monedas actuales sin cambios",
  },
  {
    id: "inventario", label: "Inventario", icon: Boxes,
    perms: ["products", "quick_view"],
    currencies: ["__NONE__"],
    desc: "Suma: tienda física, inventario y productos · monedas actuales sin cambios",
  },
];

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

  // iter244 — BUG FIX: al cambiar de usuario, descartar TODO estado pendiente
  // (selecciones sin guardar, TOTP en curso). Sin esto, guardar en el usuario
  // B aplicaba las funciones editadas para el usuario A. El padre además
  // monta el diálogo con key={user_id} como primera línea de defensa.
  useEffect(() => {
    setPendingCurrencies(null);
    setPendingPerms(null);
    setPendingTotp(null);
    setRejectingPhone(null);
    setTab("role");
  }, [user?.user_id]);

  // Memoise the visible tab list — the filter is trivial but running it
  // per render also drops the `perms` tab when the user is not an
  // employee. Recompute only when the role actually flips.
  const visibleTabs = useMemo(
    () => TABS.filter((tt) => !["perms", "batchpairs"].includes(tt.id) || user?.role === "employee"),
    [user?.role]
  );

  if (!user) return null;

  const putUserFields = async (fields, totpCode, successMsg) => {
    setBusy(true);
    try {
      const body = { ...fields };
      if (totpCode) body.totp_code = totpCode;
      const r = await axios.put(`${API}/admin/users/${user.user_id}`, body, {
        withCredentials: true,
      });
      onUserUpdated?.(r.data);
      toast.success(successMsg || "Cambio guardado.");
      setPendingTotp(null);
      return true;
    } catch (e) {
      const detail = e.response?.data?.detail;
      const status = e.response?.status;
      // TOTP step-up required → open the prompt and stop.
      if (typeof detail === "object" && detail?.code === "TOTP_CODE_REQUIRED") {
        setPendingTotp({ fields, successMsg });
        return false;
      }
      // Close the TOTP prompt if it was open — the retry failed for a
      // reason other than TOTP.
      setPendingTotp(null);
      // Prefer the backend's own detail string whenever present so the
      // staff sees exactly WHICH permission is missing.
      if (typeof detail === "string" && detail.trim()) {
        toast.error(detail);
      } else if (status === 403) {
        toast.error("Acceso restringido — pídele a un admin el permiso 'Funciones de usuario'.");
      } else {
        toast.error("Error al guardar.");
      }
      return false;
    } finally {
      setBusy(false);
    }
  };

  const putUserField = (field, value, totpCode) =>
    putUserFields({ [field]: value }, totpCode);

  // iter245 — aplica un perfil predefinido (permisos + monedas) en un clic.
  // iter251 — BUG FIX: la plantilla SUMA a lo ya concedido (incluidas las
  // selecciones sin guardar); antes reemplazaba la lista completa y se
  // perdían los permisos anteriores (y viceversa).
  const applyTemplate = async (tpl) => {
    const currentPerms = pendingPerms ?? (user.allowed_permissions || []);
    const mergedPerms = [...new Set([...currentPerms, ...tpl.perms])];
    const currentCurrencies = pendingCurrencies ?? (user.allowed_currencies || []);
    let mergedCurrencies;
    if (tpl.currencies.length === 0) {
      // La plantilla otorga TODAS las monedas ([] = sin restricción).
      mergedCurrencies = [];
    } else if (tpl.currencies.includes("__NONE__")) {
      // La plantilla no aporta monedas → conservar las actuales tal cual.
      mergedCurrencies = currentCurrencies;
    } else {
      mergedCurrencies = [...new Set([
        ...currentCurrencies.filter((c) => c !== "__NONE__"),
        ...tpl.currencies,
      ])];
    }
    const ok = await putUserFields(
      {
        allowed_permissions: mergedPerms,
        allowed_currencies: mergedCurrencies,
        // iter252 — registrar el delta exacto para poder revertirlo luego.
        applied_templates: {
          ...(user.applied_templates || {}),
          [tpl.id]: {
            added_perms: tpl.perms.filter((p) => !currentPerms.includes(p)),
            prev_currencies: currentCurrencies,
            set_currencies: mergedCurrencies,
            currencies_changed:
              JSON.stringify([...currentCurrencies].sort()) !==
              JSON.stringify([...mergedCurrencies].sort()),
            applied_at: new Date().toISOString(),
          },
        },
      },
      undefined,
      `Plantilla «${tpl.label}» aplicada (permisos sumados).`,
    );
    if (ok) {
      setPendingPerms(null);
      setPendingCurrencies(null);
    }
  };

  // iter252 — revierte EXACTAMENTE lo que la plantilla sumó: quita solo los
  // permisos que añadió (los previos y los añadidos a mano se conservan) y
  // restaura las monedas solo si nadie las cambió después de aplicarla.
  const removeTemplate = async (tpl) => {
    // iter252b — refetch fresco antes de calcular la reversión: si otro admin
    // cambió permisos/monedas desde que se abrió el diálogo, la heurística
    // "nadie las cambió después" usa el estado real y no un prop obsoleto.
    let fresh = user;
    try {
      const fr = await axios.get(`${API}/admin/users`, {
        params: { q: user.email, limit: 5 }, withCredentials: true,
      });
      fresh = (fr.data || []).find((u) => u.user_id === user.user_id) || user;
    } catch { /* sin red: usar el prop como fallback */ }
    const rec = fresh.applied_templates?.[tpl.id] || user.applied_templates?.[tpl.id];
    if (!rec) return;
    const currentPerms = pendingPerms ?? (fresh.allowed_permissions || []);
    const added = rec.added_perms || [];
    const newPerms = currentPerms.filter((p) => !added.includes(p));
    const currentCurrencies = pendingCurrencies ?? (fresh.allowed_currencies || []);
    let newCurrencies = currentCurrencies;
    if (rec.currencies_changed &&
        JSON.stringify([...currentCurrencies].sort()) ===
        JSON.stringify([...(rec.set_currencies || [])].sort())) {
      newCurrencies = rec.prev_currencies || [];
    }
    const remaining = { ...(fresh.applied_templates || user.applied_templates || {}) };
    delete remaining[tpl.id];
    const ok = await putUserFields(
      {
        allowed_permissions: newPerms,
        allowed_currencies: newCurrencies,
        applied_templates: remaining,
      },
      undefined,
      `Plantilla «${tpl.label}» quitada (solo lo que sumó).`,
    );
    if (ok) {
      setPendingPerms(null);
      setPendingCurrencies(null);
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
            {visibleTabs.map((tt) => {
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
                {!isAdmin && (user.role === "admin" || user.role === "employee") && (
                  <p className="text-xs text-neutral-500 mt-2 italic">
                    Solo un admin puede modificar el rol de otro staff / admin.
                  </p>
                )}

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
                      const cur = (pendingCurrencies ?? (user.allowed_currencies || []))
                        .filter((c) => c !== NO_CURRENCIES);
                      const next = isOn
                        ? [...new Set([...cur, code])]
                        : cur.filter((c) => c !== code);
                      setPendingCurrencies(next);
                    }}
                    onSave={() => saveAllowedCurrencies(pendingCurrencies ?? (user.allowed_currencies || []))}
                    onClear={() => setPendingCurrencies([])}
                    onRestrictAll={() => setPendingCurrencies([NO_CURRENCIES])}
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
                <div className="micro-label text-neutral-500 mb-2">Plantillas rápidas</div>
                <div className="grid sm:grid-cols-3 gap-2 mb-5" data-testid="staff-templates">
                  {STAFF_TEMPLATES.map((tpl) => {
                    const Icon = tpl.icon;
                    const applied = !!user.applied_templates?.[tpl.id];
                    return (
                      <div
                        key={tpl.id}
                        className={`border px-3 py-2.5 transition-colors group ${
                          applied ? "border-[#8B5CF6]/50" : "border-white/10 hover:border-[#8B5CF6]/60"
                        }`}
                      >
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => applyTemplate(tpl)}
                          data-testid={`staff-template-${tpl.id}`}
                          className="text-left w-full"
                        >
                          <span className="flex items-center gap-2 text-sm font-semibold text-white group-hover:text-[#8B5CF6]">
                            <Icon className="w-4 h-4 text-[#8B5CF6]" /> {tpl.label}
                            {applied && (
                              <span
                                data-testid={`staff-template-applied-${tpl.id}`}
                                className="text-[0.6rem] uppercase tracking-wide text-[#8B5CF6] border border-[#8B5CF6]/40 px-1.5 py-0.5"
                              >
                                Aplicada
                              </span>
                            )}
                          </span>
                          <span className="block text-[0.65rem] text-neutral-500 mt-1 leading-snug">
                            {tpl.desc}
                          </span>
                        </button>
                        {applied && (
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => removeTemplate(tpl)}
                            data-testid={`staff-template-remove-${tpl.id}`}
                            className="mt-2 w-full text-[0.65rem] uppercase tracking-wide text-red-300/80 hover:text-red-300 border border-red-400/20 hover:border-red-400/50 py-1 transition-colors"
                          >
                            Quitar lo que sumó
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
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

            {tab === "batchpairs" && user.role === "employee" && (
              <div data-testid="uf-batchpairs-tab">
                <div className="micro-label text-neutral-500 mb-3">Pares de lotes VIP autorizados</div>
                <BatchPairsSelect
                  selected={user.allowed_batch_pairs || []}
                  onSave={(list) => putUserField("allowed_batch_pairs", list)}
                  busy={busy}
                />
                <p className="text-xs text-neutral-500 mt-3 leading-relaxed">
                  Lista vacía = acceso a TODOS los pares (legacy). «Sin acceso a lotes» bloquea
                  todos los pares para este staff. Con pares seleccionados, solo podrá trabajar
                  esos pares. Solo un admin puede modificarlo.
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
          else if (pendingTotp?.fields) putUserFields(pendingTotp.fields, code, pendingTotp.successMsg);
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


/** iter113 — checkbox grid of VIP batch pairs for staff RBAC.
 *  iter202 — modo explícito "Sin acceso a lotes" (sentinel "none"). */
function BatchPairsSelect({ selected, onSave, busy }) {
  const [catalog, setCatalog] = useState([]);
  const [pending, setPending] = useState(null);
  const list = pending ?? selected;
  const noAccess = list.includes("none");

  useEffect(() => {
    axios.get(`${API}/admin/vip-batch-pairs`, { withCredentials: true })
      .then((r) => setCatalog(r.data?.items || []))
      .catch(() => setCatalog([]));
  }, []);

  const toggle = (pair) => {
    // Elegir un par desactiva el modo "sin acceso".
    const base = noAccess ? [] : list;
    const next = base.includes(pair) ? base.filter((p) => p !== pair) : [...base, pair];
    setPending(next);
  };

  return (
    <div>
      <button
        type="button"
        onClick={() => setPending(noAccess ? [] : ["none"])}
        data-testid="uf-batch-pairs-none"
        className={`w-full flex items-center gap-2 text-left px-3 py-2.5 mb-3 border text-xs font-medium transition-colors ${
          noAccess
            ? "border-red-500 bg-red-500/10 text-red-400"
            : "border-white/10 text-neutral-400 hover:border-red-500/50 hover:text-red-400"
        }`}
      >
        <Ban className="w-3.5 h-3.5 shrink-0" />
        {noAccess
          ? "Sin acceso a lotes — este staff no podrá trabajar NINGÚN lote"
          : "Sin acceso a lotes (bloquear todos los pares)"}
      </button>
      <div className={`grid grid-cols-2 sm:grid-cols-3 gap-2 max-h-56 overflow-y-auto pr-1 ${noAccess ? "opacity-40" : ""}`}>
        {catalog.length === 0 && (
          <div className="col-span-full text-xs text-neutral-500">Sin pares configurados.</div>
        )}
        {catalog.map((p) => {
          const on = !noAccess && list.includes(p.pair);
          return (
            <button
              key={p.pair}
              type="button"
              onClick={() => toggle(p.pair)}
              data-testid={`uf-batch-pair-${p.from_code}-${p.to_code}`}
              className={`text-left px-2.5 py-2 border text-xs font-mono transition-colors ${
                on
                  ? "border-[#8B5CF6] bg-[#8B5CF6]/10 text-[#A78BFA]"
                  : "border-white/10 text-neutral-400 hover:border-white/30"
              }`}
            >
              {p.from_code} → {p.to_code}
            </button>
          );
        })}
      </div>
      <div className="flex gap-2 mt-3">
        <Button
          onClick={() => onSave(list)}
          disabled={busy || pending === null}
          data-testid="uf-batch-pairs-save"
          className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white h-9 px-4 text-xs disabled:opacity-40"
        >
          Guardar pares
        </Button>
        <Button
          onClick={() => setPending([])}
          variant="ghost"
          data-testid="uf-batch-pairs-clear"
          className="rounded-none border border-white/10 text-neutral-400 h-9 px-4 text-xs"
        >
          Vaciar (acceso total)
        </Button>
      </div>
    </div>
  );
}
