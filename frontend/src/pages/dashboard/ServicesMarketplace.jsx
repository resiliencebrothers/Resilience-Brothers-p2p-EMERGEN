import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { useLiveEvent } from "@/hooks/useLiveStream";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Calendar } from "@/components/ui/calendar";
import { es as dfEs, enUS as dfEn } from "date-fns/locale";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Wrench, Search, MapPin, Clock, BadgeCheck, CalendarClock, CreditCard, Loader2, CalendarCheck2 } from "lucide-react";
import { toast } from "sonner";

// Pestaña SERVICIOS del mercado (cliente). Fase 2: reserva de turnos con pago
// en USDT (saldo retenido hasta que la empresa confirme), calendario visual
// para elegir día + horario, próximo turno libre en cada tarjeta, y "Mis
// reservas". Toda la superficie usa i18n (es/en).
const norm = (s) => (s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
const toISODate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const startOfToday = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; };

const STATUS_BADGE = {
  pending: "bg-amber-500/10 text-amber-300 border-amber-500/30",
  accepted: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  rejected: "bg-red-500/10 text-red-400 border-red-500/30",
  cancelled: "bg-neutral-500/10 text-neutral-300 border-neutral-500/30",
  expired: "bg-orange-500/10 text-orange-300 border-orange-500/30",
  settled: "bg-sky-500/10 text-sky-300 border-sky-500/30",
};

export default function ServicesMarketplace({ onBooked }) {
  const { t, i18n } = useTranslation();
  const dfLocale = (i18n.language || "es").startsWith("en") ? dfEn : dfEs;
  const [tab, setTab] = useState("browse");
  const [services, setServices] = useState([]);
  const [categories, setCategories] = useState([]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [modality, setModality] = useState("");
  const [detail, setDetail] = useState(null);
  const [bookings, setBookings] = useState([]);
  const [balance, setBalance] = useState(0);

  const load = useCallback(() => {
    axios.get(`${API}/services`, { withCredentials: true })
      .then((r) => setServices(r.data)).catch(() => {});
  }, []);
  const loadBookings = useCallback(() => {
    axios.get(`${API}/bookings/mine`, { withCredentials: true })
      .then((r) => setBookings(r.data)).catch(() => {});
  }, []);
  const loadBalance = useCallback(() => {
    axios.get(`${API}/vip/balances`, { withCredentials: true })
      .then((r) => {
        const u = (r.data?.balances || []).find((b) => (b.code || b.currency) === "USDT");
        setBalance(Number(u?.amount || 0));
      }).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    loadBookings();
    loadBalance();
    axios.get(`${API}/service-categories`, { withCredentials: true })
      .then((r) => setCategories(r.data)).catch(() => {});
  }, [load, loadBookings, loadBalance]);

  useLiveEvent("services_changed", load);

  const catName = (slug) => categories.find((c) => c.slug === slug)?.name || slug;
  const usedCategories = useMemo(
    () => categories.filter((c) => services.some((s) => s.category === c.slug)),
    [categories, services]);

  const modalityLabel = (m) => t(`svcMarket.modality.${m}`, m);
  const priceText = (s) => {
    if (s.pricing_type === "quote") return t("svcMarket.price.quote");
    const unit = { hourly: t("svcMarket.price.perHour"), daily: t("svcMarket.price.perDay"), per_person: t("svcMarket.price.perPerson") }[s.pricing_type] || "";
    return `${s.price_usdt} USDT${unit}`;
  };
  const depositText = (s) => {
    if (!s.deposit_type || s.deposit_type === "none" || !s.deposit_value) return null;
    return s.deposit_type === "percent"
      ? t("svcMarket.deposit.percent", { value: s.deposit_value })
      : t("svcMarket.deposit.fixed", { value: s.deposit_value });
  };

  const visible = services.filter((s) =>
    (!category || s.category === category) &&
    (!modality || s.modality === modality) &&
    (!query.trim() || norm(s.title).includes(norm(query)) ||
      norm(s.description).includes(norm(query)) || norm(s.coverage_zone).includes(norm(query))));

  const afterBooking = () => {
    loadBookings(); loadBalance(); onBooked?.();
  };

  return (
    <div className="space-y-6" data-testid="services-marketplace">
      <div>
        <div className="micro-label text-[#8B5CF6] mb-2">{t("svcMarket.eyebrow")}</div>
        <h2 className="font-display text-2xl flex items-center gap-3">
          <Wrench className="w-6 h-6 text-[#8B5CF6]" /> {t("svcMarket.title")}
        </h2>
        <p className="text-sm text-neutral-400 mt-1">{t("svcMarket.subtitle")}</p>
      </div>

      {/* Tabs: explorar / mis reservas */}
      <div className="flex gap-4 border-b border-white/10">
        <button data-testid="svc-tab-browse" onClick={() => setTab("browse")}
          className={`pb-2 -mb-px text-sm uppercase tracking-wider border-b-2 transition-colors ${tab === "browse" ? "border-[#8B5CF6] text-white" : "border-transparent text-neutral-500 hover:text-neutral-300"}`}>
          {t("svcMarket.tabs.browse")}
        </button>
        <button data-testid="svc-tab-mine" onClick={() => { setTab("mine"); loadBookings(); }}
          className={`pb-2 -mb-px text-sm uppercase tracking-wider border-b-2 transition-colors flex items-center gap-1.5 ${tab === "mine" ? "border-[#8B5CF6] text-white" : "border-transparent text-neutral-500 hover:text-neutral-300"}`}>
          <CalendarCheck2 className="w-4 h-4" /> {t("svcMarket.tabs.mine")}
          {bookings.length > 0 && <span className="text-[0.65rem] bg-[#8B5CF6]/20 text-[#A78BFA] px-1.5 rounded-full">{bookings.length}</span>}
        </button>
      </div>

      {tab === "mine" ? (
        <MyBookings bookings={bookings} onChanged={afterBooking} t={t} />
      ) : (
        <>
          <div className="flex items-center gap-2 flex-wrap">
            <div className="relative w-full sm:w-[340px]">
              <Search className="w-4 h-4 text-neutral-500 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
              <Input data-testid="services-search-input" value={query} onChange={(e) => setQuery(e.target.value)}
                placeholder={t("svcMarket.searchPlaceholder")} className="rounded-none pl-9 bg-[#0a0a0a] border-white/10 h-10" />
            </div>
          </div>

          {usedCategories.length > 0 && (
            <div className="flex gap-2 flex-wrap" data-testid="services-category-chips">
              <button data-testid="services-chip-all" onClick={() => setCategory("")}
                className={`px-3 py-1.5 text-xs uppercase tracking-wider border rounded-full transition-colors ${!category ? "border-[#8B5CF6] text-[#8B5CF6] bg-[#8B5CF6]/10" : "border-white/10 text-neutral-400 hover:text-white"}`}>
                {t("svcMarket.allCategories")}
              </button>
              {usedCategories.map((c) => (
                <button key={c.slug} data-testid={`services-chip-${c.slug}`} onClick={() => setCategory(category === c.slug ? "" : c.slug)}
                  className={`px-3 py-1.5 text-xs uppercase tracking-wider border rounded-full transition-colors ${category === c.slug ? "border-[#8B5CF6] text-[#8B5CF6] bg-[#8B5CF6]/10" : "border-white/10 text-neutral-400 hover:text-white"}`}>
                  {c.name}
                </button>
              ))}
            </div>
          )}

          <div className="flex gap-2 flex-wrap" data-testid="services-modality-chips">
            {["", "local", "domicilio", "remoto", "alquiler"].map((m) => (
              <button key={m || "all"} data-testid={`services-modality-${m || "all"}`} onClick={() => setModality(m)}
                className={`px-3 py-1 text-[0.7rem] uppercase tracking-wider border transition-colors ${modality === m ? "border-sky-400 text-sky-300 bg-sky-500/10" : "border-white/10 text-neutral-400 hover:text-white"}`}>
                {m ? modalityLabel(m) : t("svcMarket.allModalities")}
              </button>
            ))}
          </div>

          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {services.length === 0 && (
              <p className="text-neutral-500 col-span-full text-center py-12" data-testid="services-empty">{t("svcMarket.empty")}</p>
            )}
            {services.length > 0 && visible.length === 0 && (
              <p className="text-neutral-500 col-span-full text-center py-12" data-testid="services-search-empty">{t("svcMarket.searchEmpty")}</p>
            )}
            {visible.map((s) => (
              <button key={s.id} onClick={() => setDetail(s)} data-testid={`service-card-${s.id}`}
                className="tactile-card overflow-hidden flex flex-col text-left hover:border-[#8B5CF6]/40 transition-colors">
                <div className="aspect-video bg-[#0a0a0a] overflow-hidden">
                  {s.images?.[0] ? (
                    <img src={s.images[0]} alt={s.title} className="w-full h-full object-cover" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center"><Wrench className="w-10 h-10 text-neutral-700" /></div>
                  )}
                </div>
                <div className="p-4 flex-1 flex flex-col">
                  <div className="flex items-center justify-between gap-2">
                    <div className="micro-label text-neutral-500">{catName(s.category)}</div>
                    {s.owner_verified && (
                      <span data-testid={`service-verified-${s.id}`} title={t("svcMarket.verified")} className="inline-flex items-center gap-1 text-[0.6rem] uppercase tracking-wider px-2 py-0.5 border border-emerald-500/40 bg-emerald-500/10 text-emerald-300">
                        <BadgeCheck className="w-3 h-3" /> {t("svcMarket.verified")}
                      </span>
                    )}
                  </div>
                  <h3 className="font-display text-lg mt-1">{s.title}</h3>
                  <div className="text-xs text-neutral-400 mt-1">{s.owner_name}</div>
                  <div className="text-xs text-neutral-500 mt-1 flex items-center gap-1">
                    <MapPin className="w-3 h-3" /> {modalityLabel(s.modality)}{s.coverage_zone ? ` · ${s.coverage_zone}` : ""}
                  </div>
                  {s.next_slot ? (
                    <div className="text-[0.7rem] text-emerald-300/90 mt-1.5 flex items-center gap-1" data-testid={`service-nextslot-${s.id}`}>
                      <CalendarClock className="w-3 h-3" /> {t("svcMarket.nextSlot")}: {s.next_slot.date} · {s.next_slot.start}
                    </div>
                  ) : (s.availability?.length > 0 && (
                    <div className="text-[0.7rem] text-neutral-600 mt-1.5 flex items-center gap-1" data-testid={`service-noslot-${s.id}`}>
                      <CalendarClock className="w-3 h-3" /> {t("svcMarket.noUpcomingSlot")}
                    </div>
                  ))}
                  <div className="mt-auto pt-3 font-display text-lg text-[#8B5CF6]">{priceText(s)}</div>
                </div>
              </button>
            ))}
          </div>
        </>
      )}

      <Dialog open={!!detail} onOpenChange={(v) => !v && setDetail(null)}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[88vh] overflow-y-auto sm:max-w-xl" data-testid="service-detail-dialog">
          {detail && (
            <>
              <DialogHeader>
                <DialogTitle className="font-display flex items-center gap-2">
                  {detail.title}
                  {detail.owner_verified && <BadgeCheck className="w-5 h-5 text-emerald-400" />}
                </DialogTitle>
              </DialogHeader>
              <div className="space-y-4">
                {detail.images?.[0] && (
                  <img src={detail.images[0]} alt={detail.title} className="w-full aspect-video object-cover border border-white/10" />
                )}
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="text-sm text-neutral-400">{catName(detail.category)} · {modalityLabel(detail.modality)}</div>
                  <div className="font-display text-2xl text-[#8B5CF6]" data-testid="service-detail-price">{priceText(detail)}</div>
                </div>
                <div className="text-sm text-neutral-300">{t("svcMarket.by")} <span className="text-neutral-100">{detail.owner_name}</span>{detail.coverage_zone ? ` · ${detail.coverage_zone}` : ""}</div>
                {detail.description && <p className="text-sm text-neutral-300 whitespace-pre-line">{detail.description}</p>}

                <div className="grid sm:grid-cols-2 gap-3">
                  <div className="border border-white/10 p-3">
                    <div className="micro-label text-[#8B5CF6] mb-2 flex items-center gap-1"><Clock className="w-3.5 h-3.5" /> {t("svcMarket.detail.details")}</div>
                    <ul className="text-sm text-neutral-300 space-y-1">
                      {detail.duration_minutes > 0 && <li>{t("svcMarket.detail.duration", { min: detail.duration_minutes })}</li>}
                      {detail.capacity > 1 && <li>{t("svcMarket.detail.capacity", { n: detail.capacity })}</li>}
                      {detail.min_notice_hours > 0 && <li>{t("svcMarket.detail.minNotice", { h: detail.min_notice_hours })}</li>}
                      {depositText(detail) && <li>{depositText(detail)}</li>}
                    </ul>
                  </div>
                  <div className="border border-white/10 p-3">
                    <div className="micro-label text-[#8B5CF6] mb-2 flex items-center gap-1"><CreditCard className="w-3.5 h-3.5" /> {t("svcMarket.detail.payment")}</div>
                    <div className="text-sm text-neutral-300">
                      {(detail.payment_methods || []).map((m) => (m === "balance" ? t("svcMarket.detail.balanceUsdt") : t("svcMarket.detail.cash"))).join(" · ") || t("svcMarket.detail.balanceUsdt")}
                    </div>
                  </div>
                </div>

                {(detail.availability?.length > 0) && (
                  <div className="border border-white/10 p-3" data-testid="service-detail-availability">
                    <div className="micro-label text-[#8B5CF6] mb-2 flex items-center gap-1"><CalendarClock className="w-3.5 h-3.5" /> {t("svcMarket.detail.schedule")}</div>
                    <ul className="text-sm text-neutral-300 space-y-1">
                      {detail.availability.map((w, i) => (
                        <li key={i}>{t("svcMarket.weekdays", { returnObjects: true })[w.day]}: {w.start}–{w.end}</li>
                      ))}
                    </ul>
                    {detail.timezone && (
                      <div className="text-xs text-neutral-500 mt-2" data-testid="service-detail-timezone">{t("svcMarket.detail.timezone", { tz: detail.timezone })}</div>
                    )}
                  </div>
                )}

                {detail.inclusions && (
                  <div><div className="micro-label text-neutral-500 mb-1">{t("svcMarket.detail.includes")}</div><p className="text-sm text-neutral-300 whitespace-pre-line">{detail.inclusions}</p></div>
                )}
                {detail.exclusions && (
                  <div data-testid="service-detail-exclusions"><div className="micro-label text-neutral-500 mb-1">{t("svcMarket.detail.excludes")}</div><p className="text-sm text-neutral-300 whitespace-pre-line">{detail.exclusions}</p></div>
                )}
                {detail.requirements && (
                  <div><div className="micro-label text-neutral-500 mb-1">{t("svcMarket.detail.requirements")}</div><p className="text-sm text-neutral-300 whitespace-pre-line">{detail.requirements}</p></div>
                )}
                {detail.cancellation_policy && (
                  <div><div className="micro-label text-neutral-500 mb-1">{t("svcMarket.detail.cancellation")}</div><p className="text-sm text-neutral-300 whitespace-pre-line">{detail.cancellation_policy}</p></div>
                )}

                <BookingPanel service={detail} balance={balance} t={t} locale={dfLocale}
                  onBooked={() => { afterBooking(); setDetail(null); setTab("mine"); }} />
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ---------- Panel de reserva (calendario + horarios + cantidad + cobro) ----------
function BookingPanel({ service, balance, onBooked, t, locale }) {
  const [date, setDate] = useState(null);
  const [slots, setSlots] = useState([]);
  const [loadingSlots, setLoadingSlots] = useState(false);
  const [slot, setSlot] = useState(null);
  const [qty, setQty] = useState(1);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const isQuote = service.pricing_type === "quote";
  const unit = isQuote ? 0 : Number(service.price_usdt || 0);
  const total = Math.round(unit * Math.max(1, qty) * 100) / 100;
  const availDays = useMemo(
    () => new Set((service.availability || []).map((w) => w.day)), [service]);
  const blocked = useMemo(
    () => new Set(service.blocked_dates || []), [service]);
  const hasSchedule = (service.availability || []).length > 0;

  const disabledDate = (d) => {
    if (d < startOfToday()) return true;
    const ourDay = (d.getDay() + 6) % 7;         // JS 0=Dom → nuestro 0=Lun
    if (!availDays.has(ourDay)) return true;
    return blocked.has(toISODate(d));
  };

  useEffect(() => {
    if (!date) { setSlots([]); setSlot(null); return; }
    setLoadingSlots(true); setSlot(null);
    axios.get(`${API}/services/${service.id}/slots?date=${toISODate(date)}`, { withCredentials: true })
      .then((r) => setSlots(r.data?.slots || []))
      .catch(() => setSlots([]))
      .finally(() => setLoadingSlots(false));
  }, [date, service.id]);

  const confirm = async () => {
    if (!date || !slot) return;
    setBusy(true);
    try {
      await axios.post(`${API}/bookings`, {
        service_id: service.id, slot_date: toISODate(date),
        slot_start: slot, quantity: Math.max(1, qty), note,
      }, { withCredentials: true });
      toast.success(t("svcMarket.booking.success"));
      onBooked?.();
    } catch (e) {
      const d = e.response?.data?.detail;
      const msg = typeof d === "string" ? d : "";
      if (msg.toLowerCase().includes("insuficiente") || msg.toLowerCase().includes("insufficient")) {
        toast.error(t("svcMarket.booking.insufficient"));
      } else {
        toast.error(msg || t("svcMarket.booking.error"));
      }
    } finally { setBusy(false); }
  };

  if (!hasSchedule) return null;
  const canPay = !isQuote && total > balance;

  return (
    <div className="border border-[#8B5CF6]/30 bg-[#8B5CF6]/5 p-4 space-y-4" data-testid="booking-panel">
      <div className="micro-label text-[#8B5CF6] flex items-center gap-1"><CalendarClock className="w-3.5 h-3.5" /> {t("svcMarket.booking.book")}</div>

      <div>
        <div className="text-xs text-neutral-400 mb-2">{t("svcMarket.booking.pickDate")}</div>
        <div className="flex justify-center bg-[#0a0a0a] border border-white/10" data-testid="booking-calendar">
          <Calendar mode="single" selected={date} onSelect={setDate} disabled={disabledDate} fromDate={startOfToday()} locale={locale} weekStartsOn={1} />
        </div>
      </div>

      {date && (
        <div data-testid="booking-slots">
          <div className="text-xs text-neutral-400 mb-2">{t("svcMarket.booking.pickSlot")}</div>
          {loadingSlots ? (
            <div className="text-sm text-neutral-500 flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> …</div>
          ) : slots.length === 0 ? (
            <div className="text-sm text-neutral-500" data-testid="booking-no-slots">{t("svcMarket.booking.noSlots")}</div>
          ) : (
            <div className="flex flex-wrap gap-2">
              {slots.map((s) => (
                <button key={s.start} data-testid={`booking-slot-${s.start}`} onClick={() => setSlot(s.start)}
                  className={`px-3 py-1.5 text-sm border transition-colors ${slot === s.start ? "border-[#8B5CF6] bg-[#8B5CF6]/20 text-white" : "border-white/15 text-neutral-300 hover:border-[#8B5CF6]/50"}`}>
                  {s.start}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {!date && <div className="text-sm text-neutral-500">{t("svcMarket.booking.chooseDate")}</div>}

      {slot && (
        <>
          <div className="grid grid-cols-2 gap-3 items-end">
            <div>
              <div className="text-xs text-neutral-400 mb-1">{t("svcMarket.booking.quantity")}</div>
              <Input data-testid="booking-quantity" type="number" min="1" max="999" value={qty}
                onChange={(e) => setQty(Math.max(1, parseInt(e.target.value) || 1))}
                className="rounded-none bg-[#0a0a0a] border-white/10 font-mono h-10" />
            </div>
            {!isQuote && (
              <div className="text-right">
                <div className="text-xs text-neutral-400">{t("svcMarket.booking.total")}</div>
                <div className="font-display text-2xl text-[#8B5CF6]" data-testid="booking-total">{total} USDT</div>
              </div>
            )}
          </div>

          <div>
            <div className="text-xs text-neutral-400 mb-1">{t("svcMarket.booking.note")}</div>
            <Textarea data-testid="booking-note" value={note} onChange={(e) => setNote(e.target.value)} rows={2}
              className="rounded-none bg-[#0a0a0a] border-white/10" />
          </div>

          <div className="text-xs text-neutral-400 border-l-2 border-[#8B5CF6]/40 pl-3">
            {isQuote ? t("svcMarket.booking.quoteInfo") : t("svcMarket.booking.heldInfo")}
          </div>
          {!isQuote && (
            <div className="text-xs text-neutral-500" data-testid="booking-balance">{t("svcMarket.booking.yourBalance", { amount: balance.toLocaleString(undefined, { maximumFractionDigits: 2 }) })}</div>
          )}

          <Button data-testid="booking-confirm" onClick={confirm} disabled={busy || canPay}
            className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-11">
            {busy ? (<><Loader2 className="w-4 h-4 mr-2 animate-spin" /> {t("svcMarket.booking.booking")}</>)
              : canPay ? t("svcMarket.booking.insufficient")
              : isQuote ? t("svcMarket.booking.confirmQuote")
              : t("svcMarket.booking.confirm")}
          </Button>
        </>
      )}
    </div>
  );
}

// ---------- Mis reservas (cliente) ----------
function MyBookings({ bookings, onChanged, t }) {
  const cancel = async (b) => {
    if (!window.confirm(t("svcMarket.mine.cancelConfirm"))) return;
    try {
      await axios.post(`${API}/bookings/${b.id}/cancel`, {}, { withCredentials: true });
      toast.success(t("svcMarket.mine.cancelled"));
      onChanged?.();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
  };
  const canCancel = (b) =>
    ["pending", "accepted"].includes(b.status) &&
    (!b.slot_start_utc || new Date(b.slot_start_utc) > new Date());

  if (bookings.length === 0) {
    return <p className="text-neutral-500 text-center py-12 tactile-card" data-testid="svc-bookings-empty">{t("svcMarket.mine.none")}</p>;
  }
  return (
    <div className="space-y-3" data-testid="svc-bookings-list">
      {bookings.map((b) => (
        <div key={b.id} data-testid={`svc-booking-${b.id}`} className="tactile-card p-4 flex items-center justify-between gap-3 flex-wrap">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-display text-base truncate">{b.service_title}</span>
              <span className={`text-[0.6rem] uppercase tracking-wider px-2 py-0.5 border ${STATUS_BADGE[b.status] || ""}`} data-testid={`svc-booking-status-${b.id}`}>
                {t(`svcMarket.status.${b.status}`, b.status)}
              </span>
            </div>
            <div className="text-xs text-neutral-400 mt-1">{t("svcMarket.mine.when", { date: b.slot_date, start: b.slot_start, end: b.slot_end })}</div>
            <div className="text-xs text-neutral-500 mt-0.5">{b.company_name} · {b.quantity > 1 ? `${b.quantity}× · ` : ""}{b.amount_usdt > 0 ? `${b.amount_usdt} USDT` : t("svcMarket.price.quote")}</div>
            {b.status === "rejected" && b.reject_reason && (
              <div className="text-xs text-red-400 mt-1">{t("svcMarket.mine.rejectReason", { reason: b.reject_reason })}</div>
            )}
          </div>
          {canCancel(b) && (
            <Button data-testid={`svc-booking-cancel-${b.id}`} onClick={() => cancel(b)} variant="outline"
              className="border-white/15 text-neutral-300 hover:text-red-400 rounded-none h-9">
              {t("svcMarket.mine.cancel")}
            </Button>
          )}
        </div>
      ))}
    </div>
  );
}
