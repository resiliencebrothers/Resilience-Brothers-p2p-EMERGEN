import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { etaFromDelivery } from "@/services/deliveryEta";
import { MapPin, Truck, Clock, User, Package, DollarSign, Copy, KeyRound, AlertTriangle } from "lucide-react";

// iter208 — Modal con todos los datos de una entrega. Se abre al tocar una fila
// en /admin/deliveries porque en la tabla algunos campos (dirección, cliente,
// etc.) se truncan y no se distinguen bien.

const STATUS_COLOR = {
  available: "text-neutral-400",
  accepted: "text-[#8B5CF6]",
  on_the_way: "text-amber-300",
  arrived: "text-sky-300",
  delivered: "text-[#22C55E]",
  confirmed: "text-[#22C55E]",
  cancelled: "text-[#EF4444]",
};

// iter208 — botón "copiar al toque" para portapapeles.
function CopyBtn({ value, label, testid }) {
  if (!value) return null;
  const copy = async (e) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(String(value));
      toast.success(`${label} copiado`);
    } catch {
      toast.error("No se pudo copiar");
    }
  };
  return (
    <button
      type="button"
      onClick={copy}
      data-testid={testid}
      title={`Copiar ${label.toLowerCase()}`}
      className="inline-flex items-center justify-center w-6 h-6 border border-white/10 hover:border-[#8B5CF6] hover:bg-[#8B5CF6]/10 text-neutral-400 hover:text-[#A78BFA] transition-colors ml-2 shrink-0"
    >
      <Copy className="w-3 h-3" />
    </button>
  );
}

function Row({ label, value, mono = false, testid, copyValue, copyLabel, copyTestid }) {
  if (value == null || value === "" || value === false) return null;
  return (
    <div className="flex flex-col gap-0.5 py-1.5" data-testid={testid}>
      <div className="text-[0.6rem] uppercase tracking-widest text-neutral-500 font-mono">{label}</div>
      <div className="flex items-start justify-between gap-2">
        <div className={`text-sm text-white break-words flex-1 min-w-0 ${mono ? "font-mono" : ""}`}>{value}</div>
        {copyValue && (
          <CopyBtn value={copyValue} label={copyLabel || label} testid={copyTestid} />
        )}
      </div>
    </div>
  );
}

function Section({ icon: Icon, title, children }) {
  return (
    <div className="border border-white/10 bg-[#0a0a0a] p-3 space-y-1">
      <div className="flex items-center gap-2 text-[0.65rem] uppercase tracking-widest text-[#A78BFA] font-mono border-b border-white/10 pb-2 mb-2">
        <Icon className="w-3.5 h-3.5" /> {title}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6">
        {children}
      </div>
    </div>
  );
}

function fmtDate(iso) {
  if (!iso) return "";
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

export default function DeliveryDetailsDialog({ delivery, open, onClose, onChanged }) {
  const { t } = useTranslation();
  // Mejora #3 — copia local para reflejar resoluciones sin cerrar el diálogo.
  const [row, setRow] = useState(delivery);
  const [resolveNote, setResolveNote] = useState("");
  const [busyId, setBusyId] = useState(null);
  useEffect(() => { setRow(delivery); setResolveNote(""); }, [delivery]);
  if (!row) return null;
  const d = row;

  const resolveIncident = async (iid) => {
    setBusyId(iid);
    try {
      const r = await axios.post(
        `${API}/admin/deliveries/${d.id}/incidents/${iid}/resolve`,
        { note: resolveNote.trim() }, { withCredentials: true });
      setRow(r.data);
      setResolveNote("");
      toast.success(t("admin.deliveries.incidentResolved"));
      onChanged?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    } finally {
      setBusyId(null);
    }
  };

  const eta = etaFromDelivery(d);
  const gps = (d.delivery_latitude != null && d.delivery_longitude != null)
    ? `${d.delivery_latitude}, ${d.delivery_longitude}` : "";
  const mapsUrl = gps
    ? `https://www.google.com/maps/dir/?api=1&destination=${d.delivery_latitude},${d.delivery_longitude}`
    : "";
  const kindLabel = t(
    d.kind === "withdrawal" ? "courierPanel.kindWithdrawal"
    : d.kind === "deposit" ? "courierPanel.kindDeposit"
    : "courierPanel.kindRedemption"
  );
  // iter208 — Extract a phone-like token from the concatenated address for a
  // dedicated "copy phone" button. Withdrawal addresses are formatted as
  // "receiver_name — address — phone" upstream (services/deliveries.py).
  const phoneMatch = (d.address || "").match(/\+?\d[\d\s\-().]{6,}\d/);
  const detectedPhone = phoneMatch ? phoneMatch[0].trim() : "";

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent
        data-testid="delivery-details-dialog"
        className="bg-[#0c0c0c] border border-white/10 text-white rounded-none max-w-3xl max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Truck className="w-5 h-5 text-[#8B5CF6]" />
            {t("admin.deliveries.detailsTitle")} · #{d.id?.slice(0, 8)}
            <span className={`ml-2 text-[0.65rem] uppercase tracking-wider font-mono ${STATUS_COLOR[d.status] || ""}`}>
              {t(`courierPanel.status.${d.status}`)}
            </span>
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-3 mt-2">
          <Section icon={Package} title={t("admin.deliveries.detailsOp")}>
            <Row label={t("admin.deliveries.colOp")} value={kindLabel} testid="dd-kind" />
            <Row label="Ref ID" value={d.ref_id} mono testid="dd-ref-id" />
            <Row label={t("admin.deliveries.detailsAmount")} value={d.amount_label} mono testid="dd-amount" />
            <Row label="ID entrega" value={d.id} mono testid="dd-id" />
          </Section>

          <Section icon={User} title={t("admin.deliveries.detailsClient")}>
            <Row label={t("admin.deliveries.colClient")} value={d.client_name}
                 testid="dd-client-name"
                 copyValue={d.client_name} copyLabel="Cliente"
                 copyTestid="dd-copy-client-name" />
            <Row label="User ID" value={d.user_id} mono testid="dd-user-id" />
            {detectedPhone && (
              <Row label={t("admin.deliveries.detailsPhone")} value={detectedPhone} mono
                   testid="dd-phone"
                   copyValue={detectedPhone} copyLabel="Número"
                   copyTestid="dd-copy-phone" />
            )}
          </Section>

          <Section icon={MapPin} title={t("admin.deliveries.detailsAddress")}>
            <Row label={t("admin.deliveries.detailsProvince")} value={d.province || "—"} testid="dd-province" />
            <Row label={t("admin.deliveries.detailsFullAddress")}
                 value={<span className="whitespace-pre-wrap">{d.address || "—"}</span>}
                 testid="dd-address"
                 copyValue={d.address || ""} copyLabel="Dirección"
                 copyTestid="dd-copy-address" />
            {gps && (
              <>
                <Row label="GPS" value={gps} mono testid="dd-gps"
                     copyValue={gps} copyLabel="GPS"
                     copyTestid="dd-copy-gps" />
                <div className="py-1.5" data-testid="dd-gps-link">
                  <a
                    href={mapsUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-[#8B5CF6] hover:text-[#A78BFA] underline underline-offset-2"
                  >
                    {t("admin.deliveries.detailsOpenMap")}
                  </a>
                </div>
              </>
            )}
          </Section>

          <Section icon={DollarSign} title={t("admin.deliveries.detailsFee")}>
            <Row label="Km" value={d.km > 0 ? `${d.km} km` : "—"} mono testid="dd-km" />
            <Row label={t("admin.deliveries.colFee")} value={`${d.fee_usdt} USDT`} mono testid="dd-fee" />
            <Row label={t("admin.deliveries.detailsCourierShare")}
                 value={`${d.courier_share_usdt} USDT (${d.share_pct_snapshot || 80}%)`}
                 mono testid="dd-courier-share" />
            <Row label={t("admin.deliveries.detailsPlatformShare")}
                 value={`${d.platform_share_usdt} USDT`}
                 mono testid="dd-platform-share" />
          </Section>

          {/* Mejora #2 — evidencia de entrega (PIN) */}
          {(d.delivery_pin || d.pin_exception || d.pin_verified) && (
            <Section icon={KeyRound} title={t("admin.deliveries.pinSection")}>
              <Row label="PIN" value={d.delivery_pin || "—"} mono testid="dd-pin" />
              <Row
                label={t("admin.deliveries.pinStatus")}
                value={d.pin_verified
                  ? t("admin.deliveries.pinVerified")
                  : d.pin_exception
                    ? t("admin.deliveries.pinException", { reason: d.pin_exception.reason })
                    : t("admin.deliveries.pinPending")}
                testid="dd-pin-status"
              />
            </Section>
          )}

          {/* Mejora #3 — incidencias con resolución */}
          {Array.isArray(d.incidents) && d.incidents.length > 0 && (
            <div className="border border-amber-400/30 bg-amber-400/5 p-3 space-y-2" data-testid="dd-incidents">
              <div className="flex items-center gap-2 text-[0.65rem] uppercase tracking-widest text-amber-300 font-mono border-b border-amber-400/20 pb-2">
                <AlertTriangle className="w-3.5 h-3.5" /> {t("admin.deliveries.incidentsTitle")}
              </div>
              {d.incidents.map((inc) => (
                <div key={inc.id} className="border border-white/10 bg-[#0a0a0a] p-2.5 space-y-1" data-testid={`dd-incident-${inc.id}`}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[0.7rem] uppercase text-amber-300">
                      {t(`courierPanel.incident.${inc.type}`, inc.type)}
                    </span>
                    <span className={`text-[0.65rem] uppercase ${inc.status === "open" ? "text-amber-300" : "text-[#22C55E]"}`}>
                      {inc.status === "open"
                        ? t("admin.deliveries.incidentOpen")
                        : t("admin.deliveries.incidentResolvedTag")}
                    </span>
                  </div>
                  <div className="text-xs text-white">{inc.note}</div>
                  <div className="text-[0.65rem] text-neutral-500">
                    {inc.by_name} · {fmtDate(inc.at)}
                    {inc.next_attempt_at ? ` · ${t("admin.deliveries.nextAttempt")}: ${inc.next_attempt_at}` : ""}
                  </div>
                  {inc.status === "resolved" && inc.resolution_note && (
                    <div className="text-[0.7rem] text-[#22C55E] italic">✓ {inc.resolution_note}</div>
                  )}
                  {inc.status === "open" && (
                    <div className="flex gap-2 pt-1">
                      <Input
                        value={resolveNote}
                        onChange={(e) => setResolveNote(e.target.value)}
                        placeholder={t("admin.deliveries.resolveNotePh")}
                        data-testid={`dd-resolve-note-${inc.id}`}
                        className="h-8 text-xs rounded-none bg-[#0c0c0c] border-white/10"
                      />
                      <Button
                        size="sm"
                        disabled={busyId === inc.id}
                        onClick={() => resolveIncident(inc.id)}
                        data-testid={`dd-resolve-${inc.id}`}
                        className="bg-[#22C55E] text-black rounded-none h-8 text-xs shrink-0 disabled:opacity-40"
                      >
                        {busyId === inc.id ? "…" : t("admin.deliveries.resolveBtn")}
                      </Button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          <Section icon={Truck} title={t("admin.deliveries.detailsCourier")}>
            <Row label={t("admin.deliveries.colCourier")}
                 value={d.courier_name || "—"} testid="dd-courier-name" />
            <Row label="Courier ID" value={d.courier_id || "—"} mono testid="dd-courier-id" />
            {d.courier_location && (
              <Row label={t("admin.deliveries.detailsCourierLoc")}
                   value={`${d.courier_location.lat}, ${d.courier_location.lon}`}
                   mono testid="dd-courier-loc" />
            )}
            {eta && (
              <Row label="ETA"
                   value={eta.stale
                     ? t("admin.deliveries.staleLoc", { m: eta.ageMin })
                     : t("admin.deliveries.etaInline", { min: eta.min, km: eta.km.toFixed(1) })
                       + (eta.ageMin != null ? ` · ${t("admin.deliveries.locAge", { m: eta.ageMin })}` : "")}
                   testid="dd-eta" />
            )}
          </Section>

          <Section icon={Clock} title={t("admin.deliveries.detailsTimeline")}>
            <Row label={t("admin.deliveries.detailsCreatedAt")} value={fmtDate(d.created_at)} mono testid="dd-created" />
            <Row label={t("admin.deliveries.detailsUpdatedAt")} value={fmtDate(d.updated_at)} mono testid="dd-updated" />
            {Array.isArray(d.timeline) && d.timeline.length > 0 && (
              <div className="sm:col-span-2 py-1.5" data-testid="dd-timeline-list">
                <div className="text-[0.6rem] uppercase tracking-widest text-neutral-500 font-mono mb-1">
                  {t("admin.deliveries.detailsSteps")}
                </div>
                <ol className="space-y-1">
                  {d.timeline.map((e, i) => (
                    <li key={i} className="text-xs flex items-baseline gap-2 border-l-2 border-[#8B5CF6]/40 pl-2">
                      <span className={`font-mono uppercase ${STATUS_COLOR[e.status] || ""}`}>
                        {t(`courierPanel.status.${e.status}`, e.status)}
                      </span>
                      <span className="text-neutral-500 font-mono text-[0.65rem]">{fmtDate(e.at)}</span>
                      {e.note && <span className="text-neutral-400 italic">· {e.note}</span>}
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </Section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
