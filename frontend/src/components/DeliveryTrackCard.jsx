import { useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import {
  Bike, Phone, PackageCheck, Search, Check, Clock, MessageCircle,
} from "lucide-react";
import { etaFromDelivery } from "@/services/deliveryEta";
import DeliveryChatDialog from "@/components/DeliveryChatDialog";

// iter208 — Card reusable de seguimiento de entrega/recogida. Antes vivía
// dentro de DeliveryTracker.jsx (dashboard). Ahora se usa desde el diálogo
// "Seguir entrega" que abre el cliente por cada retiro/depósito.

const STEPS = ["accepted", "on_the_way", "arrived", "delivered"];

function fmtTime(isoStr) {
  try {
    return new Date(isoStr).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

export default function DeliveryTrackCard({ d }) {
  const { t } = useTranslation();
  const [chatOpen, setChatOpen] = useState(false);
  const eta = etaFromDelivery(d);
  const statusLabel = t(`courierPanel.status.${d.status}`, d.status);
  const stepIdx = STEPS.indexOf(d.status);
  const times = {};
  (d.timeline || []).forEach((e) => { times[e.status] = e.at; });
  const firstName = (d.courier?.name || "").split(" ")[0] || d.courier?.name;

  return (
    <div className="tactile-card p-4 space-y-3" data-testid={`track-card-${d.id}`}>
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm font-medium truncate flex items-center gap-2">
          <Bike className="w-4 h-4 text-[#8B5CF6]" /> {d.amount_label}
        </div>
        <span className={`text-[0.65rem] px-2 py-0.5 border shrink-0 ${
          d.status === "delivered"
            ? "border-[#22C55E]/40 text-[#22C55E]"
            : "border-[#8B5CF6]/40 text-[#A78BFA]"
        }`} data-testid={`track-status-${d.id}`}>
          {statusLabel}
        </span>
      </div>

      {d.status === "available" ? (
        <p className="text-xs text-neutral-500 flex items-center gap-1.5">
          <Search className="w-3.5 h-3.5" /> {t("tracker.searchingCourier")}
        </p>
      ) : (
        <div className="space-y-3">
          {d.courier && (
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
              <span className="text-neutral-400">
                {t("tracker.courierLabel")}:{" "}
                <span className="text-white">{firstName}</span>
              </span>
              {d.courier.phone ? (
                <div className="flex items-center gap-1.5">
                  <a
                    href={`tel:${d.courier.phone}`}
                    data-testid={`track-call-${d.id}`}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 border border-[#22C55E]/40 text-[#22C55E] hover:bg-[#22C55E]/10 transition-colors"
                  >
                    <Phone className="w-3 h-3" /> {d.courier.phone}
                  </a>
                  <a
                    href={`https://wa.me/${d.courier.phone.replace(/[^0-9]/g, "")}`}
                    target="_blank"
                    rel="noreferrer"
                    data-testid={`track-whatsapp-${d.id}`}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 border border-[#22C55E]/40 text-[#22C55E] hover:bg-[#22C55E]/10 transition-colors"
                  >
                    <MessageCircle className="w-3 h-3" /> WhatsApp
                  </a>
                </div>
              ) : (
                <span className="text-[0.65rem] text-neutral-600" data-testid={`track-nophone-${d.id}`}>
                  {t("tracker.noPhone")}
                </span>
              )}
            </div>
          )}

          {/* iter210 — chat en la app con el mensajero (sin números personales) */}
          {STEPS.includes(d.status) && (
            <button
              onClick={() => setChatOpen(true)}
              data-testid={`track-chat-${d.id}`}
              className="w-full inline-flex items-center justify-center gap-2 px-3 py-2 text-xs border border-[#8B5CF6]/40 text-[#A78BFA] hover:bg-[#8B5CF6]/10 transition-colors"
            >
              <MessageCircle className="w-3.5 h-3.5" />
              {t("deliveryChat.openBtn")}
              {d.chat_unread > 0 && (
                <span
                  className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 bg-[#22C55E] text-black text-[10px] font-bold rounded-full animate-pulse"
                  data-testid={`track-chat-unread-${d.id}`}
                >
                  {d.chat_unread}
                </span>
              )}
            </button>
          )}
          <DeliveryChatDialog
            deliveryId={d.id}
            open={chatOpen}
            onClose={() => setChatOpen(false)}
          />

          {d.status === "delivered" ? (
            <p className="text-xs text-[#22C55E] flex items-center gap-1.5" data-testid={`track-delivered-${d.id}`}>
              <PackageCheck className="w-3.5 h-3.5" /> {t("tracker.deliveredNote")}
            </p>
          ) : d.status === "arrived" ? (
            <p className="text-xs text-[#22C55E] flex items-center gap-1.5" data-testid={`track-eta-${d.id}`}>
              <PackageCheck className="w-3.5 h-3.5" /> {t("tracker.arrivedNote")}
            </p>
          ) : eta ? (
            <p className="text-xs text-[#A78BFA] flex items-center gap-1.5" data-testid={`track-eta-${d.id}`}>
              <Clock className="w-3.5 h-3.5" />
              {t("tracker.etaAway", { min: eta.min })}
              <span className="text-neutral-500">· {t("tracker.kmAway", { km: eta.km.toFixed(1) })}</span>
            </p>
          ) : (
            <p className="text-[0.7rem] text-neutral-500" data-testid={`track-noloc-${d.id}`}>
              {t("tracker.noLocation")}
            </p>
          )}

          <ol className="space-y-1.5 border-t border-white/5 pt-2.5" data-testid={`track-steps-${d.id}`}>
            {STEPS.map((s, i) => {
              const reached = stepIdx >= i;
              const current = stepIdx === i && d.status !== "delivered";
              return (
                <li key={s} className="flex items-center gap-2 text-[0.7rem]">
                  <span className={`w-4 h-4 shrink-0 inline-flex items-center justify-center border ${
                    reached
                      ? "border-[#8B5CF6] bg-[#8B5CF6]/20 text-[#A78BFA]"
                      : "border-white/10 text-neutral-600"
                  } ${current ? "animate-pulse" : ""}`}>
                    {reached ? <Check className="w-2.5 h-2.5" /> : null}
                  </span>
                  <span className={reached ? "text-white" : "text-neutral-600"}>
                    {t(`courierPanel.status.${s}`, s)}
                  </span>
                  {times[s] && reached && (
                    <span className="ml-auto text-neutral-500 font-mono">{fmtTime(times[s])}</span>
                  )}
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </div>
  );
}


// iter208 — Hook que carga los delivery jobs activos del cliente y los
// filtra por el refId pasado (id del retiro o depósito). Refresca cada 15s.
export function useDeliveryForRef(refId, enabled = true) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!enabled) return undefined;
    let alive = true;
    const load = () =>
      axios.get(`${API}/vip/deliveries/track`, { withCredentials: true })
        .then((r) => {
          if (!alive) return;
          const all = r.data?.items || [];
          setItems(refId ? all.filter((d) => d.ref_id === refId) : all);
        })
        .catch(() => {})
        .finally(() => { if (alive) setLoading(false); });
    load();
    const iv = setInterval(load, 15000);
    return () => { alive = false; clearInterval(iv); };
  }, [refId, enabled]);

  return { items, loading };
}
