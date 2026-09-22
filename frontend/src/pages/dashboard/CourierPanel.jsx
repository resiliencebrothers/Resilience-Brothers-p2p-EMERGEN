import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { Bike, MapPin, Package, ArrowDownToLine, CheckCircle2, Clock, LocateFixed, X, MessageCircle, AlertTriangle, Banknote, KeyRound, Phone } from "lucide-react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import DeliveryChatDialog from "@/components/DeliveryChatDialog";
import { useLiveEvent } from "@/hooks/useLiveStream";

// iter199 — Panel del Mensajero (Fase 2): tomar entregas, avanzar estados
// (en camino → llegué → entregado) y ver ganancias (80% de la tarifa).

const NEXT_ACTION = {
  accepted: { status: "on_the_way", key: "courierPanel.startBtn" },
  on_the_way: { status: "arrived", key: "courierPanel.arrivedBtn" },
  arrived: { status: "delivered", key: "courierPanel.deliveredBtn" },
};

const STATUS_COLOR = {
  available: "text-neutral-400",
  accepted: "text-[#8B5CF6]",
  on_the_way: "text-amber-300",
  arrived: "text-sky-300",
  delivered: "text-[#22C55E]",
  confirmed: "text-[#22C55E]",
  cancelled: "text-[#EF4444]",
};

// Mejora #3 auditoría — tipos de incidencia que el mensajero puede reportar.
const INCIDENT_TYPES = [
  "no_responde", "direccion_incorrecta", "importe_diferente",
  "no_entregado", "reprogramar",
];

// Mejora #4 — antigüedad legible de un trabajo en cola.
function fmtAge(iso, t) {
  if (!iso) return null;
  const min = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (min < 60) return t("courierPanel.ageMin", { min });
  return t("courierPanel.ageHours", { h: Math.floor(min / 60) });
}

function DeliveryCard({ d, actionLabel, onAction, actionTestId, waiting, reservedBadge, onReject, onChat, onIncident, showAge }) {
  const { t } = useTranslation();
  return (
    <div
      className={`tactile-card p-4 space-y-2 ${
        reservedBadge ? "border border-[#8B5CF6]/60 shadow-[0_0_20px_rgba(139,92,246,0.15)]" : ""
      }`}
      data-testid={`delivery-card-${d.id}`}
    >
      {reservedBadge && (
        <div
          className="text-[0.65rem] uppercase tracking-widest text-[#A78BFA] font-mono flex items-center gap-1.5"
          data-testid={`delivery-reserved-${d.id}`}
        >
          <Bike className="w-3 h-3" /> {t("courierPanel.reservedForYou")}
        </div>
      )}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          {d.kind === "withdrawal"
            ? <ArrowDownToLine className="w-4 h-4 text-[#8B5CF6]" />
            : d.kind === "deposit"
              ? <ArrowDownToLine className="w-4 h-4 text-[#22C55E] rotate-180" />
              : <Package className="w-4 h-4 text-[#8B5CF6]" />}
          {t(
            d.kind === "withdrawal" ? "courierPanel.kindWithdrawal"
            : d.kind === "deposit" ? "courierPanel.kindDeposit"
            : "courierPanel.kindRedemption"
          )}
          <span className="font-mono text-xs text-neutral-500">#{d.ref_id?.slice(0, 8)}</span>
        </div>
        <span className={`text-[0.65rem] uppercase tracking-wider ${STATUS_COLOR[d.status] || ""}`}>
          {t(`courierPanel.status.${d.status}`)}
        </span>
      </div>
      {showAge && (
        <div
          className={`text-[0.65rem] flex items-center gap-1 ${
            (Date.now() - new Date(d.created_at).getTime()) / 60000 > 60
              ? "text-amber-300" : "text-neutral-500"
          }`}
          data-testid={`delivery-age-${d.id}`}
        >
          <Clock className="w-3 h-3" /> {fmtAge(d.created_at, t)}
        </div>
      )}
      <div className="text-sm text-neutral-300">{d.client_name} — {d.amount_label}</div>
      {d.has_open_incident && (
        <div
          className="text-[0.65rem] text-amber-300 flex items-center gap-1"
          data-testid={`delivery-incident-badge-${d.id}`}
        >
          <AlertTriangle className="w-3 h-3" /> {t("courierPanel.openIncident")}
        </div>
      )}
      {/* Mejora #7 (Fase C) — destino estructurado: receptor, municipio y
          provincia por separado, con botones directos de llamada y mapa */}
      <div className="text-xs text-neutral-500 flex items-start gap-1.5">
        <MapPin className="w-3.5 h-3.5 shrink-0 mt-0.5" />
        <span data-testid={`delivery-destination-${d.id}`}>
          {d.receiver_name ? (
            <span className="text-neutral-300">{d.receiver_name} · </span>
          ) : null}
          {d.address}
          {d.municipality ? ` · ${d.municipality}` : ""}
          {d.province ? ` · ${d.province}` : ""}
        </span>
      </div>
      {(d.receiver_phone || d.delivery_latitude != null || d.address) && (
        <div className="flex gap-2" data-testid={`delivery-contact-actions-${d.id}`}>
          {d.receiver_phone && (
            <a
              href={`tel:${String(d.receiver_phone).replace(/[^+\d]/g, "")}`}
              data-testid={`delivery-call-${d.id}`}
              className="flex-1 inline-flex items-center justify-center gap-1.5 px-2 py-1.5 text-[0.7rem] border border-[#22C55E]/40 text-[#22C55E] hover:bg-[#22C55E]/10 transition-colors"
            >
              <Phone className="w-3 h-3" /> {t("courierPanel.callBtn")} {d.receiver_phone}
            </a>
          )}
          {(d.delivery_latitude != null && d.delivery_longitude != null) ? (
            <a
              href={`https://www.google.com/maps/dir/?api=1&destination=${d.delivery_latitude},${d.delivery_longitude}`}
              target="_blank"
              rel="noreferrer"
              data-testid={`delivery-map-link-${d.id}`}
              className="flex-1 inline-flex items-center justify-center gap-1.5 px-2 py-1.5 text-[0.7rem] border border-[#8B5CF6]/40 text-[#A78BFA] hover:bg-[#8B5CF6]/10 transition-colors"
            >
              <MapPin className="w-3 h-3" /> {t("courierPanel.mapBtn")}
            </a>
          ) : d.address ? (
            <a
              href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent([d.address, d.municipality, d.province, "Cuba"].filter(Boolean).join(", "))}`}
              target="_blank"
              rel="noreferrer"
              data-testid={`delivery-map-link-${d.id}`}
              className="flex-1 inline-flex items-center justify-center gap-1.5 px-2 py-1.5 text-[0.7rem] border border-[#8B5CF6]/40 text-[#A78BFA] hover:bg-[#8B5CF6]/10 transition-colors"
            >
              <MapPin className="w-3 h-3" /> {t("courierPanel.mapBtn")}
            </a>
          ) : null}
        </div>
      )}
      <div className="flex items-center justify-between text-xs font-mono border-t border-white/5 pt-2">
        <span className="text-neutral-500">{d.km > 0 ? `${d.km} km` : "—"} · {d.fee_usdt} USDT</span>
        <span className="text-[#22C55E] font-semibold" data-testid={`delivery-share-${d.id}`}>
          {t("courierPanel.yourShare")}: {d.courier_share_usdt} USDT
        </span>
      </div>
      {onChat && (
        <button
          onClick={onChat}
          data-testid={`courier-chat-${d.id}`}
          className="w-full inline-flex items-center justify-center gap-2 px-3 py-2 text-xs border border-[#8B5CF6]/40 text-[#A78BFA] hover:bg-[#8B5CF6]/10 transition-colors"
        >
          <MessageCircle className="w-3.5 h-3.5" />
          {t("deliveryChat.openBtnCourier")}
          {d.chat_unread > 0 && (
            <span
              className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 bg-[#22C55E] text-black text-[10px] font-bold rounded-full animate-pulse"
              data-testid={`courier-chat-unread-${d.id}`}
            >
              {d.chat_unread}
            </span>
          )}
        </button>
      )}
      {onIncident && (
        <button
          onClick={onIncident}
          data-testid={`courier-incident-${d.id}`}
          className="w-full inline-flex items-center justify-center gap-2 px-3 py-2 text-xs border border-amber-400/30 text-amber-300 hover:bg-amber-400/10 transition-colors"
        >
          <AlertTriangle className="w-3.5 h-3.5" />
          {t("courierPanel.reportIncident")}
        </button>
      )}
      {onAction && (
        <div className="flex gap-2">
          <Button
            onClick={onAction}
            data-testid={actionTestId}
            className={`flex-1 rounded-none h-10 ${
              reservedBadge
                ? "bg-[#22C55E] hover:bg-[#4ADE80] text-black font-semibold"
                : "bg-[#8B5CF6] hover:bg-[#A78BFA] text-white"
            }`}
          >
            {actionLabel}
          </Button>
          {onReject && (
            <Button
              onClick={onReject}
              data-testid={`reject-reservation-${d.id}`}
              variant="outline"
              className="rounded-none h-10 border-[#EF4444]/40 text-[#EF4444] hover:bg-[#EF4444]/10"
              title={t("courierPanel.rejectBtn")}
            >
              <X className="w-4 h-4" />
            </Button>
          )}
        </div>
      )}
      {waiting && (
        <p className="text-[0.7rem] text-amber-300 flex items-center gap-1.5" data-testid={`delivery-waiting-${d.id}`}>
          <Clock className="w-3.5 h-3.5" /> {t("courierPanel.waitingConfirm")}
        </p>
      )}
    </div>
  );
}

export default function CourierPanel({ embedded = false }) {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [loadError, setLoadError] = useState(false);
  const [tab, setTab] = useState("mine");

  const [sharing, setSharing] = useState(false);
  const [lastGpsAt, setLastGpsAt] = useState(null);
  // Mejora #4 — filtros de la cola de disponibles (tipo y zona).
  const [kindFilter, setKindFilter] = useState("all");
  const [zoneFilter, setZoneFilter] = useState("all");
  const watchRef = useRef(null);
  const lastSentRef = useRef(0);

  // iter207 — compartir ubicación en vivo con los clientes de mis entregas.
  const stopSharing = useCallback(() => {
    if (watchRef.current != null && navigator.geolocation) {
      navigator.geolocation.clearWatch(watchRef.current);
    }
    watchRef.current = null;
    setSharing(false);
  }, []);

  const startSharing = () => {
    if (!navigator.geolocation) {
      toast.error(t("courier.geoUnsupported"));
      return;
    }
    watchRef.current = navigator.geolocation.watchPosition(
      (pos) => {
        const now = Date.now();
        if (now - lastSentRef.current < 15000) return;
        lastSentRef.current = now;
        axios.post(`${API}/courier/location`,
          { lat: pos.coords.latitude, lon: pos.coords.longitude },
          { withCredentials: true })
          .then((r) => setLastGpsAt(r.data?.at || new Date().toISOString()))
          .catch(() => {});
      },
      () => {
        toast.error(t("courier.geoDenied"));
        stopSharing();
      },
      { enableHighAccuracy: true, maximumAge: 10000 },
    );
    setSharing(true);
  };

  useEffect(() => () => stopSharing(), [stopSharing]);

  const load = useCallback(() => {
    axios.get(`${API}/courier/deliveries`, { withCredentials: true })
      .then((r) => { setData(r.data); setLoadError(false); })
      .catch(() => setLoadError(true));
  }, []);

  useEffect(() => { load(); }, [load]);

  // MSG10 — refresco por eventos en vivo + respaldo por intervalo y al
  // recuperar el foco: una asignación externa aparece sin recarga manual.
  useLiveEvent("delivery_changed", load);
  useEffect(() => {
    const iv = setInterval(load, 30000);
    const onVis = () => { if (!document.hidden) load(); };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      clearInterval(iv);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [load]);

  const claim = async (d) => {
    try {
      await axios.post(`${API}/courier/deliveries/${d.id}/claim`, {}, { withCredentials: true });
      toast.success(t("courierPanel.claimed"));
      setTab("mine");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
      load();
    }
  };

  const postStatus = async (id, body) => {
    try {
      await axios.post(`${API}/courier/deliveries/${id}/status`,
        body, { withCredentials: true });
      toast.success(t(`courierPanel.status.${body.status}`));
      load();
      return true;
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
      // Mejora #5 — mostrar el conflicto y refrescar SIN dar por completado
      // un envío que el servidor rechazó.
      if (e.response?.status === 409) load();
      return false;
    }
  };

  const advance = async (d) => {
    const next = NEXT_ACTION[d.status];
    if (!next) return;
    // Mejora #2 — la entrega exige el PIN del cliente (o excepción con motivo).
    if (next.status === "delivered" && d.pin_required) {
      setPinFor(d);
      setPinValue("");
      setPinNoPin(false);
      setPinReason("");
      return;
    }
    await postStatus(d.id, { status: next.status });
  };

  // Mejora #2 — diálogo de PIN de entrega.
  const [pinFor, setPinFor] = useState(null);
  const [pinValue, setPinValue] = useState("");
  const [pinNoPin, setPinNoPin] = useState(false);
  const [pinReason, setPinReason] = useState("");
  const [pinBusy, setPinBusy] = useState(false);

  const submitPin = async () => {
    if (!pinFor) return;
    const body = { status: "delivered" };
    if (pinNoPin) {
      if (pinReason.trim().length < 5) {
        toast.error(t("courierPanel.pinReasonMin"));
        return;
      }
      body.pin_exception_reason = pinReason.trim();
    } else {
      if (!/^\d{4}$/.test(pinValue.trim())) {
        toast.error(t("courierPanel.pinLenErr"));
        return;
      }
      body.pin = pinValue.trim();
    }
    setPinBusy(true);
    const ok = await postStatus(pinFor.id, body);
    setPinBusy(false);
    if (ok) setPinFor(null);
  };

  // Mejora #3 — reportar incidencia sobre una entrega activa.
  const [incidentFor, setIncidentFor] = useState(null);
  const [incType, setIncType] = useState("no_responde");
  const [incNote, setIncNote] = useState("");
  const [incNextAt, setIncNextAt] = useState("");
  const [incBusy, setIncBusy] = useState(false);

  const submitIncident = async () => {
    if (!incidentFor) return;
    if (incNote.trim().length < 5) {
      toast.error(t("courierPanel.incidentMinNote"));
      return;
    }
    setIncBusy(true);
    try {
      await axios.post(`${API}/courier/deliveries/${incidentFor.id}/incident`,
        { type: incType, note: incNote.trim(),
          next_attempt_at: incNextAt || null },
        { withCredentials: true });
      toast.success(t("courierPanel.incidentSent"));
      setIncidentFor(null);
      setIncNote("");
      setIncNextAt("");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    } finally {
      setIncBusy(false);
    }
  };

  // iter208 — rechazar reserva del admin con motivo.
  const [rejecting, setRejecting] = useState(null);  // { id, ...delivery }
  const [rejectReason, setRejectReason] = useState("");
  const [rejectBusy, setRejectBusy] = useState(false);
  // iter210 — chat con el cliente de una entrega activa.
  const [chatFor, setChatFor] = useState(null);

  const submitReject = async () => {
    if (!rejecting) return;
    if (rejectReason.trim().length < 5) {
      toast.error(t("courierPanel.rejectMinReason"));
      return;
    }
    setRejectBusy(true);
    try {
      await axios.post(`${API}/courier/deliveries/${rejecting.id}/reject-reservation`,
        { reason: rejectReason.trim() }, { withCredentials: true });
      toast.success(t("courierPanel.rejectedOk"));
      setRejecting(null);
      setRejectReason("");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    } finally {
      setRejectBusy(false);
    }
  };

  // iter208 — auto-abre la pestaña "Disponibles" si hay reservadas para
  // el mensajero (se ejecuta ANTES del guard de loading para respetar las
  // reglas de hooks — corre en cada render, no depende de `data`).
  const reservedCount = data
    ? data.available.filter((d) => d.reserved_for_me).length
    : 0;
  useEffect(() => {
    if (reservedCount > 0) setTab("available");
  }, [reservedCount]);

  if (!data) {
    // MSG10 — error visible con reintento en vez de un spinner eterno.
    if (loadError) {
      return (
        <div className="text-center py-12 space-y-3" data-testid="courier-panel-error">
          <p className="text-sm text-neutral-400">{t("courierPanel.loadError")}</p>
          <Button
            onClick={load}
            data-testid="courier-panel-retry"
            className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white h-9 text-xs"
          >
            {t("common.retry")}
          </Button>
        </div>
      );
    }
    return <div className="text-neutral-500 py-12 text-center" data-testid="courier-panel-loading">…</div>;
  }

  const tabs = [
    { id: "available", label: t("courierPanel.tabAvailable"), count: data.available.length, badge: reservedCount },
    { id: "mine", label: t("courierPanel.tabMine"), count: data.mine.length, badge: 0 },
    { id: "history", label: t("courierPanel.tabHistory"), count: data.history.length, badge: 0 },
  ];

  return (
    <div className="space-y-8" data-testid="courier-panel">
      {!embedded && (
        <div>
          <div className="micro-label text-[#8B5CF6] mb-2">{t("courierPanel.eyebrow")}</div>
          <h1 className="font-display text-3xl flex items-center gap-3">
            <Bike className="w-8 h-8 text-[#8B5CF6]" /> {t("courierPanel.title")}
          </h1>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="tactile-card px-5 py-4">
          <div className="micro-label text-neutral-500">{t("courierPanel.earnedLabel")}</div>
          <div className="font-display text-2xl text-[#22C55E]" data-testid="courier-earned-total">
            {data.earnings.confirmed_usdt} <span className="text-sm text-neutral-400">USDT</span>
          </div>
        </div>
        <div className="tactile-card px-5 py-4">
          <div className="micro-label text-neutral-500">{t("courierPanel.pendingLabel")}</div>
          <div className="font-display text-2xl text-amber-300" data-testid="courier-pending-total">
            {data.earnings.pending_usdt} <span className="text-sm text-neutral-400">USDT</span>
          </div>
        </div>
        <div className="tactile-card px-5 py-4">
          <div className="micro-label text-neutral-500">{t("courierPanel.completedLabel")}</div>
          <div className="font-display text-2xl" data-testid="courier-completed-count">
            {data.earnings.completed_count}
          </div>
        </div>
      </div>

      {/* Mejora #1 — efectivo del negocio/clientes que el mensajero debe rendir */}
      {(data.cash_pending || []).length > 0 && (
        <div className="tactile-card p-4 border border-amber-400/30 bg-amber-400/5" data-testid="courier-cash-pending">
          <div className="micro-label text-amber-300 flex items-center gap-2">
            <Banknote className="w-4 h-4" /> {t("courierPanel.cashPendingTitle")}
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-1 mt-2">
            {data.cash_pending.map((c) => (
              <div key={c.currency} className="font-mono text-lg text-amber-300" data-testid={`courier-cash-${c.currency}`}>
                {c.pending} <span className="text-xs text-neutral-400">{c.currency}</span>
              </div>
            ))}
          </div>
          <div className="text-[0.65rem] text-neutral-500 mt-1.5">{t("courierPanel.cashPendingHint")}</div>
        </div>
      )}

      <div className="flex gap-2 border-b border-white/10">
        {tabs.map((tb) => (
          <button
            key={tb.id}
            onClick={() => setTab(tb.id)}
            data-testid={`courier-tab-${tb.id}`}
            className={`px-4 py-2.5 text-sm transition-colors border-b-2 -mb-px flex items-center gap-2 ${
              tab === tb.id
                ? "border-[#8B5CF6] text-[#8B5CF6]"
                : "border-transparent text-neutral-500 hover:text-white"
            }`}
          >
            {tb.label} {tb.count > 0 && <span className="font-mono text-xs">({tb.count})</span>}
            {tb.badge > 0 && (
              <span
                className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 bg-[#22C55E] text-black text-[10px] font-bold rounded-full animate-pulse"
                data-testid={`courier-tab-${tb.id}-badge`}
              >
                {tb.badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {tab === "available" && (
        <div className="space-y-4" data-testid="courier-available-list">
          {data.available.length === 0 && (
            <p className="text-neutral-500 col-span-full text-center py-10">{t("courierPanel.emptyAvailable")}</p>
          )}
          {data.available.some((d) => d.reserved_for_me) && (
            <div className="tactile-card p-3 border border-[#8B5CF6]/40 bg-[#8B5CF6]/5" data-testid="courier-reserved-notice">
              <div className="text-xs text-[#A78BFA] font-medium flex items-center gap-2">
                <Bike className="w-4 h-4" /> {t("courierPanel.reservedNoticeTitle")}
              </div>
              <div className="text-[0.7rem] text-neutral-400 mt-1">
                {t("courierPanel.reservedNoticeBody")}
              </div>
            </div>
          )}
          {/* Mejora #4 — filtros por tipo y zona; atrasados primero */}
          {data.available.length > 0 && (
            <div className="flex flex-wrap gap-2" data-testid="courier-available-filters">
              {["all", "deposit", "withdrawal", "redemption"].map((k) => (
                <button
                  key={k}
                  onClick={() => setKindFilter(k)}
                  data-testid={`courier-filter-kind-${k}`}
                  className={`px-2.5 py-1 text-[0.7rem] border ${
                    kindFilter === k
                      ? "border-[#8B5CF6] text-[#8B5CF6]"
                      : "border-white/10 text-neutral-500"
                  }`}
                >
                  {k === "all" ? t("courierPanel.filterAll")
                    : t(k === "deposit" ? "courierPanel.kindDeposit"
                      : k === "withdrawal" ? "courierPanel.kindWithdrawal"
                      : "courierPanel.kindRedemption")}
                </button>
              ))}
              {[...new Set(data.available.map((d) => d.province).filter(Boolean))].map((p) => (
                <button
                  key={p}
                  onClick={() => setZoneFilter(zoneFilter === p ? "all" : p)}
                  data-testid={`courier-filter-zone-${p}`}
                  className={`px-2.5 py-1 text-[0.7rem] border ${
                    zoneFilter === p
                      ? "border-[#22C55E] text-[#22C55E]"
                      : "border-white/10 text-neutral-500"
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          )}
          <div className="grid sm:grid-cols-2 gap-4">
            {[...data.available.filter((d) => d.reserved_for_me),
              ...data.available.filter((d) => !d.reserved_for_me)]
              .filter((d) => kindFilter === "all" || d.kind === kindFilter)
              .filter((d) => zoneFilter === "all" || d.province === zoneFilter)
              .map((d) => (
              <DeliveryCard
                key={d.id}
                d={d}
                showAge
                reservedBadge={!!d.reserved_for_me}
                actionLabel={d.reserved_for_me ? t("courierPanel.acceptBtn") : t("courierPanel.claimBtn")}
                actionTestId={`claim-delivery-${d.id}`}
                onAction={() => claim(d)}
                onReject={d.reserved_for_me ? () => { setRejecting(d); setRejectReason(""); } : undefined}
              />
            ))}
          </div>
        </div>
      )}

      {tab === "mine" && (
        <div className="space-y-4">
          {data.mine.length > 0 && (
            <div className="tactile-card p-4 flex flex-wrap items-center justify-between gap-3" data-testid="courier-live-share">
              <div className="text-xs text-neutral-400 max-w-md space-y-1">
                <div>{sharing ? t("courierPanel.sharingLiveHint") : t("courierPanel.shareLiveHint")}</div>
                {/* Mejora #5 — estado claro de conexión/GPS */}
                {sharing ? (
                  <div className="text-[0.7rem] text-[#22C55E] flex items-center gap-1.5" data-testid="courier-gps-status">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#22C55E] animate-pulse" />
                    {t("courierPanel.gpsActive")}
                    {lastGpsAt && ` · ${t("courierPanel.gpsLastSent", { min: Math.max(0, Math.round((Date.now() - new Date(lastGpsAt).getTime()) / 60000)) })}`}
                  </div>
                ) : (
                  <div className="text-[0.7rem] text-amber-300 flex items-center gap-1.5" data-testid="courier-gps-status">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                    {t("courierPanel.gpsInactive")}
                  </div>
                )}
              </div>
              <Button
                type="button"
                onClick={sharing ? stopSharing : startSharing}
                data-testid="courier-live-share-btn"
                className={`rounded-none h-9 text-xs ${
                  sharing
                    ? "bg-[#22C55E]/15 text-[#22C55E] border border-[#22C55E]/50 hover:bg-[#22C55E]/25"
                    : "bg-[#8B5CF6] hover:bg-[#A78BFA] text-white"
                }`}
              >
                <LocateFixed className={`w-3.5 h-3.5 mr-1.5 ${sharing ? "animate-pulse" : ""}`} />
                {sharing ? t("courierPanel.sharingLive") : t("courierPanel.shareLive")}
              </Button>
            </div>
          )}
        <div className="grid sm:grid-cols-2 gap-4" data-testid="courier-mine-list">
          {data.mine.length === 0 && (
            <p className="text-neutral-500 col-span-full text-center py-10">{t("courierPanel.emptyMine")}</p>
          )}
          {data.mine.map((d) => (
            <DeliveryCard
              key={d.id}
              d={d}
              actionLabel={NEXT_ACTION[d.status] ? t(NEXT_ACTION[d.status].key) : null}
              actionTestId={`advance-delivery-${d.id}`}
              onAction={NEXT_ACTION[d.status] ? () => advance(d) : null}
              onChat={() => setChatFor(d)}
              onIncident={() => { setIncidentFor(d); setIncType("no_responde"); setIncNote(""); setIncNextAt(""); }}
              waiting={d.status === "delivered"}
            />
          ))}
        </div>
        </div>
      )}

      {tab === "history" && (
        <div className="grid sm:grid-cols-2 gap-4" data-testid="courier-history-list">
          {data.history.length === 0 && (
            <p className="text-neutral-500 col-span-full text-center py-10">{t("courierPanel.emptyHistory")}</p>
          )}
          {data.history.map((d) => (
            <div key={d.id} className="tactile-card p-4 flex items-center justify-between gap-3" data-testid={`history-delivery-${d.id}`}>
              <div className="min-w-0">
                <div className="text-sm truncate">{d.client_name} — {d.amount_label}</div>
                <div className="text-xs text-neutral-500">{new Date(d.updated_at).toLocaleString()}</div>
              </div>
              <div className="text-right shrink-0">
                <div className="font-mono text-[#22C55E] text-sm flex items-center gap-1.5">
                  <CheckCircle2 className="w-4 h-4" /> +{d.courier_share_paid_usdt ?? d.courier_share_usdt} USDT
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* iter210 — Chat con el cliente */}
      <DeliveryChatDialog
        deliveryId={chatFor?.id}
        open={!!chatFor}
        onClose={() => { setChatFor(null); load(); }}
      />

      {/* Mejora #2 — PIN de entrega (evidencia) */}
      <Dialog open={!!pinFor} onOpenChange={(o) => !o && setPinFor(null)}>
        <DialogContent
          data-testid="delivery-pin-dialog"
          aria-describedby={undefined}
          className="bg-[#0c0c0c] border border-[#22C55E]/30 text-white rounded-none max-w-sm max-h-[85vh] overflow-y-auto"
        >
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-[#22C55E]">
              <KeyRound className="w-5 h-5" /> {t("courierPanel.pinDialogTitle")}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3 mt-1">
            {!pinNoPin ? (
              <>
                <p className="text-xs text-neutral-400">{t("courierPanel.pinPrompt")}</p>
                <Input
                  data-testid="delivery-pin-input"
                  value={pinValue}
                  onChange={(e) => setPinValue(e.target.value.replace(/\D/g, "").slice(0, 4))}
                  inputMode="numeric"
                  placeholder="••••"
                  className="rounded-none bg-[#0a0a0a] border-white/10 h-12 text-center font-mono text-2xl tracking-[0.5em]"
                />
              </>
            ) : (
              <>
                <p className="text-xs text-amber-300">{t("courierPanel.pinReasonLabel")}</p>
                <Textarea
                  data-testid="delivery-pin-exception-input"
                  value={pinReason}
                  onChange={(e) => setPinReason(e.target.value)}
                  placeholder={t("courierPanel.pinReasonPh")}
                  maxLength={300}
                  rows={3}
                  className="rounded-none bg-[#0a0a0a] border-white/10 text-sm"
                />
              </>
            )}
            <button
              type="button"
              onClick={() => setPinNoPin(!pinNoPin)}
              data-testid="delivery-pin-toggle-exception"
              className="text-[0.7rem] text-neutral-500 hover:text-amber-300 underline underline-offset-2"
            >
              {pinNoPin ? t("courierPanel.pinBackToPin") : t("courierPanel.pinNoPinToggle")}
            </button>
          </div>
          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              onClick={() => setPinFor(null)}
              data-testid="delivery-pin-cancel"
              className="rounded-none border-white/10 text-white hover:bg-white/5"
            >
              {t("common.cancel")}
            </Button>
            <Button
              onClick={submitPin}
              disabled={pinBusy}
              data-testid="delivery-pin-confirm"
              className="rounded-none bg-[#22C55E] hover:bg-[#4ADE80] text-black font-semibold disabled:opacity-40"
            >
              {pinBusy ? "…" : t("courierPanel.pinConfirmBtn")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Mejora #3 — Registrar incidencia */}
      <Dialog open={!!incidentFor} onOpenChange={(o) => !o && setIncidentFor(null)}>
        <DialogContent
          data-testid="incident-dialog"
          aria-describedby={undefined}
          className="bg-[#0c0c0c] border border-amber-400/30 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto"
        >
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-amber-300">
              <AlertTriangle className="w-5 h-5" /> {t("courierPanel.incidentDialogTitle")}
            </DialogTitle>
          </DialogHeader>
          {incidentFor && (
            <div className="space-y-3 mt-1">
              <div className="text-xs text-neutral-400">
                {incidentFor.client_name} — {incidentFor.amount_label}
              </div>
              <div>
                <div className="micro-label text-neutral-500 mb-1">{t("courierPanel.incidentTypeLabel")}</div>
                <Select value={incType} onValueChange={setIncType}>
                  <SelectTrigger className="rounded-none bg-[#0a0a0a] border-white/10 h-10" data-testid="incident-type-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-[#1A1730] border-white/10 text-white">
                    {INCIDENT_TYPES.map((tp) => (
                      <SelectItem key={tp} value={tp} data-testid={`incident-type-${tp}`}>
                        {t(`courierPanel.incident.${tp}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <div className="micro-label text-neutral-500 mb-1">{t("courierPanel.incidentNoteLabel")}</div>
                <Textarea
                  data-testid="incident-note-input"
                  value={incNote}
                  onChange={(e) => setIncNote(e.target.value)}
                  placeholder={t("courierPanel.incidentNotePh")}
                  maxLength={300}
                  rows={3}
                  className="rounded-none bg-[#0a0a0a] border-white/10 text-sm"
                />
              </div>
              <div>
                <div className="micro-label text-neutral-500 mb-1">{t("courierPanel.incidentNextLabel")}</div>
                <input
                  type="datetime-local"
                  value={incNextAt}
                  onChange={(e) => setIncNextAt(e.target.value)}
                  data-testid="incident-next-input"
                  className="w-full bg-[#0a0a0a] border border-white/10 text-white text-sm px-3 h-10 rounded-none [color-scheme:dark]"
                />
              </div>
            </div>
          )}
          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              onClick={() => setIncidentFor(null)}
              data-testid="incident-cancel-btn"
              className="rounded-none border-white/10 text-white hover:bg-white/5"
            >
              {t("common.cancel")}
            </Button>
            <Button
              onClick={submitIncident}
              disabled={incBusy || incNote.trim().length < 5}
              data-testid="incident-submit-btn"
              className="rounded-none bg-amber-400 hover:bg-amber-300 text-black font-semibold disabled:opacity-40"
            >
              {incBusy ? "…" : t("courierPanel.incidentSubmitBtn")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* iter208 — Diálogo Rechazar Reserva */}
      <Dialog open={!!rejecting} onOpenChange={(o) => !o && setRejecting(null)}>
        <DialogContent
          data-testid="reject-reservation-dialog"
          className="bg-[#0c0c0c] border border-[#EF4444]/30 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto"
        >
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-[#EF4444]">
              <X className="w-5 h-5" /> {t("courierPanel.rejectDialogTitle")}
            </DialogTitle>
          </DialogHeader>
          {rejecting && (
            <div className="space-y-3 mt-2">
              <div className="text-xs text-neutral-400 space-y-1">
                <div className="font-medium text-white">{rejecting.client_name} — {rejecting.amount_label}</div>
                <div className="text-neutral-500">{rejecting.address}{rejecting.province ? ` · ${rejecting.province}` : ""}</div>
              </div>
              <div>
                <div className="micro-label text-neutral-500 mb-1">
                  {t("courierPanel.rejectReasonLabel")}
                </div>
                <Textarea
                  data-testid="reject-reason-input"
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  placeholder={t("courierPanel.rejectPlaceholder")}
                  maxLength={300}
                  rows={3}
                  className="rounded-none bg-[#0a0a0a] border-white/10 text-sm"
                />
                <div className="text-[0.65rem] text-neutral-600 mt-1 text-right font-mono">
                  {rejectReason.length}/300
                </div>
              </div>
            </div>
          )}
          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              onClick={() => setRejecting(null)}
              data-testid="reject-cancel-btn"
              className="rounded-none border-white/10 text-white hover:bg-white/5"
            >
              {t("common.cancel")}
            </Button>
            <Button
              onClick={submitReject}
              disabled={rejectBusy || rejectReason.trim().length < 5}
              data-testid="reject-confirm-btn"
              className="rounded-none bg-[#EF4444] hover:bg-[#F87171] text-white disabled:opacity-40"
            >
              {rejectBusy ? "…" : t("courierPanel.rejectConfirmBtn")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
