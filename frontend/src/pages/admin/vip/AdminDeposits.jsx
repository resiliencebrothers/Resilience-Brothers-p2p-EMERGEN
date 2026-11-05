import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import axios from "axios";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { API } from "@/App";
import { formatAmount } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Check, X as XIcon, Clock, ExternalLink, Truck, Building2, Search, Landmark, ShieldCheck } from "lucide-react";
import { useLiveRefresh } from "@/hooks/useLiveStream";
import { AssignDepositAccountDialog } from "./AssignDepositAccountDialog";

/**
 * iter113 — Admin queue for client deposits (`deposits` collection).
 * Confirming credits the client's per-currency balance.
 * iter171 — refresh debounced + request cancellation to avoid "Cargando..."
 * stuck when many deposits arrive at once.
 */
const DEPOSIT_EVENTS = ["deposit_created"];

export default function AdminDeposits({ onChanged }) {
  const { t } = useTranslation();
  const [sp, setSp] = useSearchParams();
  const focusId = sp.get("focus");
  const [focusActive, setFocusActive] = useState(!!focusId);
  const [items, setItems] = useState([]);
  const [statusFilter, setStatusFilter] = useState("pending");
  const [methodFilter, setMethodFilter] = useState("all");
  const [userInput, setUserInput] = useState("");
  const [userQuery, setUserQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [rejecting, setRejecting] = useState(null);
  const [assigning, setAssigning] = useState(null);
  const abortRef = useRef(null);
  const initialLoadRef = useRef(true);
  // #2 (rev 6d53890) — el depósito traído por ID vive en estado PROPIO, separado
  // de la lista paginada, para que un refresco de `items` no lo pierda. El fetch
  // por ID se rastrea por estado para distinguir: en curso / encontrado / 404 /
  // error transitorio, sin bloquear reintentos legítimos. `prevFocusRef`
  // resincroniza focusActive cuando cambia el enlace.
  const [focusDeposit, setFocusDeposit] = useState(null);
  const focusStateRef = useRef({ id: null, state: null });
  const focusAbortRef = useRef(null);
  const prevFocusRef = useRef(focusId);

  useEffect(() => {
    const id = setTimeout(() => setUserQuery(userInput.trim()), 300);
    return () => clearTimeout(id);
  }, [userInput]);

  // #3 — mantener focusActive en sync con ?focus= de la URL: si el enlace
  // cambia a un id distinto (o se limpia) SIN desmontar el componente, se
  // reactiva/desactiva el foco. No se dispara por cambios internos (filtros)
  // porque focusId no cambia; preserva la salida manual del foco.
  useEffect(() => {
    if (focusId !== prevFocusRef.current) {
      prevFocusRef.current = focusId;
      setFocusActive(!!focusId);
      // nuevo id → se descarta el estado y el depósito previo y se cancela
      // cualquier búsqueda por ID en vuelo (ya no interesa su respuesta).
      focusStateRef.current = { id: null, state: null };
      setFocusDeposit(null);
      if (focusAbortRef.current) {
        try { focusAbortRef.current.abort(); } catch (_) { /* ignore */ }
        focusAbortRef.current = null;
      }
    }
  }, [focusId]);

  const load = useCallback(async () => {
    if (abortRef.current) {
      try { abortRef.current.abort(); } catch (_) { /* ignore */ }
    }
    const controller = new AbortController();
    abortRef.current = controller;
    if (initialLoadRef.current) setLoading(true);
    try {
      const params = { limit: 300 };
      // P3 — al llegar desde Transacciones con ?focus=<id>, no se filtra por
      // estado para que el depósito buscado sea siempre localizable.
      if (!(focusActive && focusId)) params.status = statusFilter;
      if (methodFilter !== "all") params.method = methodFilter;
      if (userQuery) params.user_q = userQuery;
      const r = await axios.get(`${API}/admin/deposits`, {
        params,
        withCredentials: true,
        signal: controller.signal,
        timeout: 30000,
      });
      setItems(r.data?.items || []);
      onChanged?.();
    } catch (err) {
      if (axios.isCancel(err) || err?.code === "ERR_CANCELED") return;
      toast.error(err?.response?.data?.detail || t("adminDeposits.loadError"));
    } finally {
      if (abortRef.current === controller) {
        setLoading(false);
        initialLoadRef.current = false;
        abortRef.current = null;
      }
    }
  }, [statusFilter, methodFilter, userQuery, t, onChanged, focusActive, focusId]);

  useEffect(() => { load(); }, [load]);
  useLiveRefresh(load, DEPOSIT_EVENTS);

  // Tras una acción del personal (confirmar/rechazar/asignar) el estado del
  // depósito enfocado pudo cambiar: se libera su estado de búsqueda por ID para
  // refrescarlo, sin vaciar la fila mostrada entretanto.
  const reloadAll = useCallback(() => {
    focusStateRef.current = { id: null, state: null };
    load();
  }, [load]);

  // R-02 — el depósito buscado puede ser anterior a los 300 cargados: se trae
  // por ID (respetando permisos y alcance de moneda) y se guarda en estado
  // PROPIO (`focusDeposit`). Se funde con la lista al renderizar, de modo que un
  // refresco de `items` no lo elimine. Estados: en curso (no repetir), encontrado
  // (no repetir), 404 (aviso único, no repetir), transitorio (reintenta). La
  // petición NO se cancela por refrescos de la lista (solo por cambio de id).
  useEffect(() => {
    if (!focusId || loading) return;
    if (items.some((d) => d.id === focusId)) return; // ya está en la lista
    const st = focusStateRef.current;
    if (st.id === focusId && (st.state === "pending" || st.state === "found" || st.state === "notfound")) {
      return; // en curso o ya resuelto para ESTE id
    }
    focusStateRef.current = { id: focusId, state: "pending" };
    const controller = new AbortController();
    focusAbortRef.current = controller;
    axios.get(`${API}/admin/deposits/${focusId}`, { withCredentials: true, signal: controller.signal })
      .then((r) => {
        if (focusStateRef.current.id !== focusId) return; // cambió el id
        if (r.data) {
          focusStateRef.current = { id: focusId, state: "found" };
          setFocusDeposit(r.data);
        }
      })
      .catch((err) => {
        // Cancelada por cambio de id: el nuevo id gestiona su propio estado.
        if (axios.isCancel(err) || err?.code === "ERR_CANCELED") return;
        if (focusStateRef.current.id !== focusId) return;
        if (err?.response?.status === 404) {
          // No encontrado / fuera de alcance: aviso UNA vez, sin reintentos.
          focusStateRef.current = { id: focusId, state: "notfound" };
          toast.error(t("adminDeposits.focusNotFound"));
        } else {
          // Error transitorio (red/servidor): se libera el estado para reintentar.
          focusStateRef.current = { id: null, state: null };
        }
      })
      .finally(() => {
        if (focusAbortRef.current === controller) focusAbortRef.current = null;
      });
  }, [focusId, loading, items, t]);

  // Fila a renderizar: fusiona el depósito enfocado (estado propio) con la lista
  // paginada mientras siga seleccionado y no aparezca ya en `items`.
  const rows = useMemo(() => {
    if (focusId && focusDeposit && focusDeposit.id === focusId
        && !items.some((d) => d.id === focusId)) {
      return [focusDeposit, ...items];
    }
    return items;
  }, [items, focusDeposit, focusId]);

  // P3 — resalta y desplaza hasta el depósito buscado cuando ya cargó la lista.
  useEffect(() => {
    if (!focusId || loading) return;
    const el = document.querySelector(`[data-testid="admin-deposit-row-${focusId}"]`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focusId, loading, rows]);

  useEffect(() => () => {
    if (abortRef.current) {
      try { abortRef.current.abort(); } catch (_) { /* ignore */ }
    }
    if (focusAbortRef.current) {
      try { focusAbortRef.current.abort(); } catch (_) { /* ignore */ }
    }
  }, []);

  const confirm = async (id, movementId) => {
    try {
      const body = movementId ? { evidence_movement_id: movementId } : {};
      await axios.post(`${API}/admin/deposits/${id}/confirm`, body, { withCredentials: true });
      toast.success(t("adminDeposits.confirmedToast"));
      reloadAll();
    } catch (err) {
      const det = err?.response?.data?.detail;
      if (det?.code === "EVIDENCE_ALREADY_USED") {
        // DR02 — la misma evidencia ya respalda otro depósito: el personal
        // puede identificar OTRA transferencia real con un ID de movimiento.
        const mid = window.prompt(`${det.message}\n\n${t("adminDeposits.movementPrompt")}`, "");
        if (mid && mid.trim()) return confirm(id, mid.trim());
        toast.error(det.message);
        return;
      }
      toast.error((typeof det === "string" ? det : det?.message) || t("adminDeposits.actionError"));
    }
  };

  return (
    <div className="space-y-4" data-testid="admin-deposits">
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500 pointer-events-none" />
          <Input
            data-testid="deposits-user-search"
            value={userInput}
            onChange={(e) => setUserInput(e.target.value)}
            placeholder={t("admin.withdrawals.searchPlaceholder")}
            className="rounded-none bg-[#0a0a0a] border-white/10 h-9 w-56 pl-9 text-xs"
          />
        </div>
        {["pending", "confirmed", "rejected"].map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => { setStatusFilter(s); setFocusActive(false); }}
            data-testid={`deposits-filter-${s}`}
            className={`text-xs uppercase tracking-widest px-3 py-1.5 border font-mono transition-colors ${
              statusFilter === s && !focusActive
                ? "bg-[#8B5CF6]/10 border-[#8B5CF6] text-[#8B5CF6]"
                : "bg-transparent border-white/10 text-neutral-400 hover:border-white/30"
            }`}
          >
            {t(`adminVipLedgerOps.filter.${s}`)}
          </button>
        ))}
        <span className="w-px h-5 bg-white/10 mx-1" aria-hidden="true" />
        {["all", "cash", "transfer", "crypto"].map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMethodFilter(m)}
            data-testid={`deposits-method-filter-${m}`}
            className={`text-xs uppercase tracking-widest px-3 py-1.5 border font-mono transition-colors ${
              methodFilter === m
                ? "bg-emerald-500/10 border-emerald-500 text-emerald-400"
                : "bg-transparent border-white/10 text-neutral-400 hover:border-white/30"
            }`}
          >
            {m === "all" ? t("adminDeposits.methodAll") : t(`deposits.method.${m}`)}
          </button>
        ))}
      </div>

      {focusActive && focusId && (
        <div
          className="flex items-center justify-between gap-3 border border-[#8B5CF6]/40 bg-[#8B5CF6]/5 px-3 py-2 text-xs text-[#A78BFA]"
          data-testid="deposits-focus-banner"
        >
          <span>{t("adminDeposits.focusBanner")}</span>
          <button
            type="button"
            onClick={() => {
              setFocusActive(false);
              setStatusFilter("pending");
              const next = new URLSearchParams(sp);
              next.delete("focus");
              setSp(next, { replace: true });
            }}
            data-testid="deposits-focus-clear"
            className="uppercase tracking-widest text-[#8B5CF6] hover:underline"
          >
            {t("adminDeposits.focusClear")}
          </button>
        </div>
      )}

      <div className="tactile-card overflow-x-auto overflow-y-auto max-h-[70vh]" data-testid="admin-deposits-scroll">
        <table className="w-full text-sm min-w-[980px]">
          <thead className="border-b border-white/10 bg-[#0a0a0a] sticky top-0 z-10">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminDeposits.colClient")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("adminDeposits.colAmount")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminDeposits.colMethod")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminDeposits.colProof")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 whitespace-nowrap">{t("adminDeposits.colCreated")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminDeposits.colStatus")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminDeposits.colActions")}</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan="7" className="text-center text-neutral-500 py-8">{t("admin.common.loadingEllipsis")}</td></tr>
            )}
            {!loading && rows.length === 0 && (
              <tr><td colSpan="7" className="text-center text-neutral-500 py-8" data-testid="admin-deposits-empty">
                {t("adminDeposits.empty")}
              </td></tr>
            )}
            {!loading && rows.map((d) => (
              <tr key={d.id} className={`border-b border-white/5${d.id === focusId ? " ring-2 ring-[#8B5CF6] ring-inset bg-[#8B5CF6]/5" : ""}`} data-testid={`admin-deposit-row-${d.id}`}>
                <td className="px-4 py-3">
                  <div className="text-white text-xs">{d.user_name || "—"}</div>
                  <div className="text-[0.65rem] text-neutral-500 font-mono">{d.user_email}</div>
                  <div className="text-[0.6rem] uppercase text-neutral-600">{d.user_role}</div>
                </td>
                <td className="px-4 py-3 font-mono text-emerald-400 text-right">
                  {formatAmount(d.amount)}
                  <span className="text-[0.6rem] text-neutral-500 ml-1">{d.currency}</span>
                  {d.usdt_equivalent != null && (
                    <div className="text-[0.6rem] text-neutral-500">≈ {Number(d.usdt_equivalent).toFixed(2)} USDT</div>
                  )}
                </td>
                <td className="px-4 py-3 text-xs">
                  <div className="text-neutral-300 uppercase font-mono">{t(`deposits.method.${d.method}`, d.method)}</div>
                  {d.cash_mode === "courier" && (
                    <div className="mt-1 space-y-0.5 text-[0.65rem] text-amber-400" data-testid={`deposit-courier-${d.id}`}>
                      <div className="flex items-center gap-1"><Truck className="w-3 h-3" /> {t("adminDeposits.courier")}</div>
                      <div className="text-neutral-400">{d.contact_name} · {d.pickup_phone}</div>
                      <div className="text-neutral-500 max-w-[220px]">{d.pickup_address}</div>
                    </div>
                  )}
                  {d.cash_mode === "office" && (
                    <div className="mt-1 flex items-center gap-1 text-[0.65rem] text-[#A78BFA]" data-testid={`deposit-office-${d.id}`}>
                      <Building2 className="w-3 h-3" /> {t("adminDeposits.office")}
                    </div>
                  )}
                  {d.account_holder && (
                    <div className="text-[0.65rem] text-neutral-500 mt-0.5">
                      {t("adminVipLedgerOps.holderLabel")}: <span className="text-neutral-300">{d.account_holder}</span>
                    </div>
                  )}
                  {d.method !== "cash" && (
                    <div className="text-[0.65rem] mt-0.5 space-y-0.5" data-testid={`deposit-account-${d.id}`}>
                      <div className="flex items-center gap-1 flex-wrap">
                        <Landmark className="w-3 h-3 text-neutral-500" />
                        <span className="text-neutral-500">{t("adminDeposits.expectedAccountShort")}:</span>
                        {d.payment_account_label ? (
                          <span className="text-neutral-300">
                            {d.payment_account_label}
                            {d.payment_account_network && (
                              <span className="ml-1 text-[0.55rem] uppercase font-mono text-[#A78BFA]">{d.payment_account_network}</span>
                            )}
                          </span>
                        ) : (
                          <span className="text-neutral-600">{t("adminDeposits.accountMissing")}</span>
                        )}
                      </div>
                      <div className="flex items-center gap-1 flex-wrap" data-testid={`deposit-confirmed-account-${d.id}`}>
                        <span className="text-neutral-500">{t("adminDeposits.confirmedAccountShort")}:</span>
                        {d.confirmed_account_label ? (
                          <span className="text-emerald-400 inline-flex items-center gap-1">
                            <ShieldCheck className="w-3 h-3" />{d.confirmed_account_label}
                          </span>
                        ) : (
                          <span className="text-amber-400">{t("adminDeposits.accountNotVerified")}</span>
                        )}
                        <button
                          type="button"
                          onClick={() => setAssigning(d)}
                          data-testid={`deposit-assign-account-${d.id}`}
                          className="text-[#A78BFA] hover:underline underline-offset-2"
                        >
                          {d.confirmed_account_label ? t("adminDeposits.changeAccount") : t("adminDeposits.confirmAccount")}
                        </button>
                      </div>
                    </div>
                  )}
                  {d.tx_hash && (
                    <div className="text-[0.65rem] text-emerald-400 font-mono mt-0.5 max-w-[200px] truncate" title={d.tx_hash}>
                      {d.tx_hash}
                    </div>
                  )}
                  {(d.evidence_already_used_by || d.evidence_reused_from) && (
                    <div
                      className="text-[0.65rem] text-red-400 mt-0.5 max-w-[220px]"
                      data-testid={`deposit-evidence-warning-${d.id}`}
                    >
                      ⚠ {t("adminDeposits.evidenceReused", {
                        id: String(d.evidence_already_used_by || d.evidence_reused_from?.deposit_id || "").slice(0, 12),
                      })}
                    </div>
                  )}
                  {d.note && <div className="text-[0.65rem] italic text-neutral-500 mt-0.5 max-w-[220px]">{d.note}</div>}
                </td>
                <td className="px-4 py-3 text-xs">
                  {d.proof_url ? (
                    <a
                      href={d.proof_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      data-testid={`deposit-proof-link-${d.id}`}
                      className="inline-flex items-center gap-1 text-[#8B5CF6] hover:underline"
                    >
                      {t("adminVipLedgerOps.viewProof")} <ExternalLink className="w-3 h-3" />
                    </a>
                  ) : <span className="text-neutral-600">—</span>}
                </td>
                <td className="px-4 py-3 text-xs text-neutral-500 whitespace-nowrap">
                  {new Date(d.created_at).toLocaleString()}
                </td>
                <td className="px-4 py-3"><Pill status={d.status} t={t} /></td>
                <td className="px-4 py-3">
                  {d.status === "pending" ? (
                    <div className="flex flex-col gap-1">
                      <div className="flex gap-2">
                        <ConfirmDepositBtn d={d} onConfirm={() => confirm(d.id)} />
                        <Button
                          onClick={() => setRejecting(d)}
                          data-testid={`admin-deposit-reject-${d.id}`}
                          variant="ghost"
                          className="rounded-none border border-[#EF4444]/40 text-[#EF4444] hover:bg-[#EF4444]/10 h-8 px-3 text-xs"
                        >
                          <XIcon className="w-3 h-3 mr-1" /> {t("adminDeposits.reject")}
                        </Button>
                      </div>
                      {d.method === "cash" && d.cash_mode === "courier" && (
                        <DepositPickupHint d={d} t={t} />
                      )}
                    </div>
                  ) : (
                    <span className="text-xs text-neutral-500">
                      {d.reviewed_at ? new Date(d.reviewed_at).toLocaleDateString() : "—"}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <RejectDepositDialog
        deposit={rejecting}
        onClose={() => setRejecting(null)}
        onDone={() => { setRejecting(null); reloadAll(); }}
      />
      <AssignDepositAccountDialog
        deposit={assigning}
        onClose={() => setAssigning(null)}
        onDone={() => { setAssigning(null); reloadAll(); }}
      />
    </div>
  );
}


// iter208 — bloquea "Confirmar" para depósitos CASH con recogida por mensajero
// hasta que el mensajero marque la recogida como entregada.
function ConfirmDepositBtn({ d, onConfirm }) {
  const { t } = useTranslation();
  const needsCourier = d.method === "cash" && d.cash_mode === "courier";
  const status = d.courier_delivery_status;
  const blocked = needsCourier && !["delivered", "confirmed"].includes(status);
  return (
    <Button
      onClick={onConfirm}
      disabled={blocked}
      data-testid={`admin-deposit-confirm-${d.id}`}
      className="rounded-none bg-emerald-500 hover:bg-emerald-400 text-black h-8 px-3 text-xs font-semibold disabled:opacity-40 disabled:cursor-not-allowed"
    >
      <Check className="w-3 h-3 mr-1" /> {t("adminDeposits.confirm")}
    </Button>
  );
}


function DepositPickupHint({ d, t }) {
  const status = d.courier_delivery_status;
  if (!status) {
    return (
      <div className="text-[0.65rem] text-amber-400" data-testid={`deposit-pickup-hint-${d.id}`}>
        {t("adminDeposits.pickupLock.noJob")}
      </div>
    );
  }
  if (!d.courier_delivery_assigned) {
    return (
      <div className="text-[0.65rem] text-amber-400" data-testid={`deposit-pickup-hint-${d.id}`}>
        {t("adminDeposits.pickupLock.noCourier")}
      </div>
    );
  }
  if (!["delivered", "confirmed"].includes(status)) {
    return (
      <div className="text-[0.65rem] text-amber-400" data-testid={`deposit-pickup-hint-${d.id}`}>
        {t("adminDeposits.pickupLock.notDelivered", {
          courier: d.courier_delivery_courier_name || t("adminDeposits.pickupLock.courierFallback"),
        })}
      </div>
    );
  }
  return (
    <div className="text-[0.65rem] text-[#22C55E]" data-testid={`deposit-pickup-hint-${d.id}`}>
      {t("adminDeposits.pickupLock.ready")}
    </div>
  );
}


function Pill({ status, t }) {
  const map = {
    pending:   { cls: "border-amber-500/40 bg-amber-500/5 text-amber-400", Icon: Clock },
    confirmed: { cls: "border-emerald-500/40 bg-emerald-500/5 text-emerald-400", Icon: Check },
    rejected:  { cls: "border-[#EF4444]/40 bg-[#EF4444]/10 text-[#EF4444]", Icon: XIcon },
  }[status] || {};
  const Icon = map.Icon || Clock;
  return (
    <span className={`inline-flex items-center gap-1 text-[0.6rem] uppercase tracking-widest px-1.5 py-0.5 border font-mono ${map.cls || ""}`}>
      <Icon className="w-3 h-3" /> {t(`deposits.status.${status}`, status)}
    </span>
  );
}


function RejectDepositDialog({ deposit, onClose, onDone }) {
  const { t } = useTranslation();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (deposit) setNote(""); }, [deposit]);

  const submit = async () => {
    if (!deposit) return;
    setBusy(true);
    try {
      await axios.post(
        `${API}/admin/deposits/${deposit.id}/reject`,
        { admin_note: note.trim() },
        { withCredentials: true },
      );
      toast.success(t("adminDeposits.rejectedToast"));
      onDone?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("adminDeposits.actionError"));
    } finally { setBusy(false); }
  };

  return (
    <Dialog open={!!deposit} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent
        data-testid="admin-deposit-reject-dialog"
        className="bg-[#0c0c0c] border border-[#EF4444]/30 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle>{t("adminDeposits.rejectTitle")}</DialogTitle>
        </DialogHeader>
        <textarea
          data-testid="admin-deposit-reject-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
          maxLength={300}
          placeholder={t("adminDeposits.rejectPlaceholder")}
          className="w-full mt-3 bg-black/40 border border-white/10 rounded-none px-3 py-2 text-sm text-white placeholder:text-neutral-600 focus:border-[#EF4444]/50 focus:outline-none"
        />
        <div className="flex justify-end gap-2 pt-3 border-t border-white/5 mt-2">
          <Button variant="ghost" onClick={onClose} className="rounded-none text-neutral-400">
            {t("common.cancel")}
          </Button>
          <Button
            onClick={submit}
            disabled={busy}
            data-testid="admin-deposit-reject-confirm"
            className="rounded-none bg-[#EF4444] hover:bg-[#F87171] text-white disabled:opacity-40"
          >
            {t("adminDeposits.reject")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
