import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Calendar } from "@/components/ui/calendar";
import { es as dfEs, enUS as dfEn } from "date-fns/locale";
import { Wrench, Plus, Edit2, Trash2, Send, Pause, Play, Clock, MapPin, CalendarClock, X } from "lucide-react";
import { toast } from "sonner";

// Catálogo de SERVICIOS de la Empresa (Fase 1). El formulario captura ya la
// configuración de calendario (ventanas de disponibilidad, fechas bloqueadas)
// y de pago (tipo de precio, anticipo, métodos) que la siguiente fase usará
// para reservas y cobros. Flujo: borrador → pendiente → (admin) publicado.
const MODALITY = ["local", "domicilio", "remoto", "alquiler"];
const PRICING = ["fixed", "hourly", "daily", "per_person", "quote"];
const STATUS_BADGE = {
  draft: "bg-neutral-500/10 text-neutral-300 border-neutral-500/30",
  pending: "bg-amber-500/10 text-amber-300 border-amber-500/30",
  published: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  rejected: "bg-red-500/10 text-red-400 border-red-500/30",
  paused: "bg-sky-500/10 text-sky-300 border-sky-500/30",
};

const emptyForm = {
  title: "", category: "otros", description: "", image_url: "",
  modality: "local", pricing_type: "fixed", price_usdt: "",
  deposit_type: "none", deposit_value: "",
  duration_minutes: "60", min_notice_hours: "0", capacity: "1",
  coverage_zone: "", cancellation_policy: "",
  requirements: "", inclusions: "", exclusions: "",
  payment_methods: ["balance"], availability: [], blocked_dates: [],
};

const effStatus = (s) => (s.status === "published" && !s.is_active ? "paused" : s.status);
const toISODate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const startOfToday = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; };

export default function CompanyServicesView({ onChanged }) {
  const { t, i18n } = useTranslation();
  const [items, setItems] = useState([]);
  const [categories, setCategories] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);
  const WD = t("company.services.weekdays", { returnObjects: true });
  const dfLocale = (i18n.language || "es").split("-")[0] === "en" ? dfEn : dfEs;

  const load = useCallback(() => {
    axios.get(`${API}/company/services`, { withCredentials: true })
      .then((r) => setItems(r.data)).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    axios.get(`${API}/service-categories`, { withCredentials: true })
      .then((r) => setCategories(r.data)).catch(() => {});
  }, [load]);

  const catName = (slug) => categories.find((c) => c.slug === slug)?.name || slug;

  const onImageFile = (file) => {
    if (!file) return;
    if (file.size > 4 * 1024 * 1024) return toast.error(t("company.services.imageTooLarge"));
    const reader = new FileReader();
    reader.onload = () => setForm((f) => ({ ...f, image_url: reader.result }));
    reader.readAsDataURL(file);
  };

  const togglePayment = (m) => setForm((f) => ({
    ...f,
    payment_methods: f.payment_methods.includes(m)
      ? f.payment_methods.filter((x) => x !== m)
      : [...f.payment_methods, m],
  }));

  const addWindow = () => setForm((f) => ({
    ...f, availability: [...f.availability, { day: 0, start: "09:00", end: "17:00" }],
  }));
  const updWindow = (i, patch) => setForm((f) => ({
    ...f, availability: f.availability.map((w, idx) => (idx === i ? { ...w, ...patch } : w)),
  }));
  const rmWindow = (i) => setForm((f) => ({
    ...f, availability: f.availability.filter((_, idx) => idx !== i),
  }));

  const setBlocked = (dates) => setForm((f) => ({
    ...f, blocked_dates: [...new Set((dates || []).map(toISODate))].sort(),
  }));
  const rmBlocked = (d) => setForm((f) => ({
    ...f, blocked_dates: f.blocked_dates.filter((x) => x !== d),
  }));

  const buildPayload = () => ({
    title: form.title.trim(),
    category: form.category || "otros",
    description: form.description,
    images: form.image_url ? [form.image_url] : [],
    modality: form.modality,
    pricing_type: form.pricing_type,
    price_usdt: form.pricing_type === "quote" ? 0 : (parseFloat(form.price_usdt) || 0),
    deposit_type: form.deposit_type,
    deposit_value: parseFloat(form.deposit_value) || 0,
    duration_minutes: parseInt(form.duration_minutes) || 0,
    min_notice_hours: parseInt(form.min_notice_hours) || 0,
    capacity: Math.max(1, parseInt(form.capacity) || 1),
    coverage_zone: form.coverage_zone.trim(),
    cancellation_policy: form.cancellation_policy.trim(),
    requirements: form.requirements.trim(),
    inclusions: form.inclusions.trim(),
    exclusions: form.exclusions.trim(),
    payment_methods: form.payment_methods.length ? form.payment_methods : ["balance"],
    availability: form.availability,
    blocked_dates: form.blocked_dates,
  });

  const validate = () => {
    if (!form.title || form.title.trim().length < 2) {
      toast.error(t("company.services.titleRequired")); return false;
    }
    if (form.pricing_type !== "quote" && !(parseFloat(form.price_usdt) > 0)) {
      toast.error(t("company.services.priceRequired")); return false;
    }
    return true;
  };

  const save = async (submit) => {
    if (!validate()) return;
    setBusy(true);
    try {
      if (editing) {
        await axios.put(`${API}/company/services/${editing.id}`, buildPayload(),
          { withCredentials: true });
        toast.success(t("company.services.updated"));
      } else {
        await axios.post(`${API}/company/services`, { ...buildPayload(), submit },
          { withCredentials: true });
        toast.success(submit ? t("company.services.sentReview") : t("company.services.draftSaved"));
      }
      setOpen(false); setEditing(null); setForm(emptyForm);
      load(); onChanged?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("company.services.saveFailed"));
    } finally { setBusy(false); }
  };

  const openEdit = (s) => {
    setEditing(s);
    setForm({
      ...emptyForm, ...s,
      image_url: (s.images && s.images[0]) || "",
      price_usdt: String(s.price_usdt ?? ""),
      deposit_value: String(s.deposit_value ?? ""),
      duration_minutes: String(s.duration_minutes ?? "60"),
      min_notice_hours: String(s.min_notice_hours ?? "0"),
      capacity: String(s.capacity ?? "1"),
      payment_methods: s.payment_methods || ["balance"],
      availability: s.availability || [],
      blocked_dates: s.blocked_dates || [],
    });
    setOpen(true);
  };

  const act = async (s, action) => {
    try {
      await axios.post(`${API}/company/services/${s.id}/${action}`, {}, { withCredentials: true });
      toast.success(
        action === "submit" ? t("company.services.sentReviewShort")
          : action === "pause" ? t("company.services.paused") : t("company.services.reactivated"));
      load(); onChanged?.();
    } catch (e) { toast.error(e.response?.data?.detail || t("company.services.genericError")); }
  };

  const remove = async (s) => {
    if (!window.confirm(t("company.services.confirmDelete", { title: s.title }))) return;
    try {
      await axios.delete(`${API}/company/services/${s.id}`, { withCredentials: true });
      toast.success(t("company.services.deleted"));
      load(); onChanged?.();
    } catch (e) { toast.error(e.response?.data?.detail || t("company.services.deleteFailed")); }
  };

  const priceText = (s) => {
    if (s.pricing_type === "quote") return t("company.services.pricing.quote");
    const hasUnit = ["hourly", "daily", "per_person"].includes(s.pricing_type);
    const unit = hasUnit ? t(`company.services.priceUnit.${s.pricing_type}`) : "";
    return `${s.price_usdt} USDT${unit}`;
  };

  return (
    <div className="space-y-6" data-testid="company-services-view">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="micro-label text-[#8B5CF6] mb-2">{t("company.services.sectionLabel")}</div>
          <h2 className="font-display text-2xl flex items-center gap-3">
            <Wrench className="w-6 h-6 text-[#8B5CF6]" /> {t("company.services.title")}
          </h2>
        </div>
        <Button data-testid="company-service-new-btn"
          onClick={() => { setEditing(null); setForm(emptyForm); setOpen(true); }}
          className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-semibold rounded-none">
          <Plus className="w-4 h-4 mr-1" /> {t("company.services.newBtn")}
        </Button>
      </div>

      <div className="border-l-4 border-[#8B5CF6] bg-[#8B5CF6]/5 px-4 py-3 text-sm text-neutral-300" data-testid="company-services-note">
        {t("company.services.notePre")}<span className="text-[#8B5CF6]">{t("company.services.noteServicesTab")}</span>{t("company.services.noteMid")}<span className="text-[#8B5CF6]">{t("company.services.noteBookingsTab")}</span>{t("company.services.notePost")}
      </div>

      {items.length === 0 && (
        <p className="text-neutral-500 text-center py-12 tactile-card" data-testid="company-services-empty">
          {t("company.services.empty")}
        </p>
      )}

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map((s) => {
          const st = effStatus(s);
          return (
            <div key={s.id} className="tactile-card overflow-hidden flex flex-col" data-testid={`company-service-${s.id}`}>
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
                  <span className={`text-[0.6rem] uppercase tracking-wider px-2 py-0.5 border ${STATUS_BADGE[st] || ""}`} data-testid={`company-service-status-${s.id}`}>
                    {t(`company.services.status.${st}`, { defaultValue: st })}
                  </span>
                </div>
                <h3 className="font-display text-lg mt-1">{s.title}</h3>
                <div className="text-xs text-neutral-500 mt-1 flex items-center gap-1">
                  <MapPin className="w-3 h-3" /> {t(`company.services.modality.${s.modality}`, { defaultValue: s.modality })}
                  {s.coverage_zone ? ` · ${s.coverage_zone}` : ""}
                </div>
                {s.status === "rejected" && s.rejection_reason && (
                  <div className="text-xs text-red-400 mt-1" data-testid={`company-service-reason-${s.id}`}>{t("company.services.rejectionPrefix")} {s.rejection_reason}</div>
                )}
                <div className="mt-auto pt-3 flex items-center justify-between">
                  <div className="font-display text-lg text-[#8B5CF6]">{priceText(s)}</div>
                  <div className="flex gap-2">
                    {(s.status === "draft" || s.status === "rejected") && (
                      <button data-testid={`company-service-submit-${s.id}`} onClick={() => act(s, "submit")}
                        className="text-neutral-400 hover:text-emerald-400" title={t("company.services.submitTitle")}><Send className="w-4 h-4" /></button>
                    )}
                    {s.status === "published" && (
                      s.is_active ? (
                        <button data-testid={`company-service-pause-${s.id}`} onClick={() => act(s, "pause")}
                          className="text-neutral-400 hover:text-sky-300" title={t("company.services.pauseTitle")}><Pause className="w-4 h-4" /></button>
                      ) : (
                        <button data-testid={`company-service-unpause-${s.id}`} onClick={() => act(s, "unpause")}
                          className="text-neutral-400 hover:text-emerald-400" title={t("company.services.unpauseTitle")}><Play className="w-4 h-4" /></button>
                      )
                    )}
                    <button data-testid={`company-service-edit-${s.id}`} onClick={() => openEdit(s)}
                      className="text-neutral-400 hover:text-[#8B5CF6]" title={t("company.services.editTitle")}><Edit2 className="w-4 h-4" /></button>
                    <button data-testid={`company-service-delete-${s.id}`} onClick={() => remove(s)}
                      className="text-neutral-400 hover:text-[#EF4444]" title={t("company.services.deleteTitle")}><Trash2 className="w-4 h-4" /></button>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[88vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle className="font-display">{editing ? t("company.services.dialogEditTitle") : t("company.services.dialogNewTitle")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label className="micro-label text-neutral-500">{t("company.services.titleLabel")}</Label>
              <Input data-testid="service-title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="micro-label text-neutral-500">{t("company.services.categoryLabel")}</Label>
                <Select value={form.category} onValueChange={(v) => setForm({ ...form, category: v })}>
                  <SelectTrigger data-testid="service-category" className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"><SelectValue /></SelectTrigger>
                  <SelectContent className="bg-[#1A1730] border-white/10 text-white">
                    {categories.map((c) => (
                      <SelectItem key={c.slug} value={c.slug} data-testid={`service-category-${c.slug}`}>{c.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="micro-label text-neutral-500">{t("company.services.modalityLabel")}</Label>
                <Select value={form.modality} onValueChange={(v) => setForm({ ...form, modality: v })}>
                  <SelectTrigger data-testid="service-modality" className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"><SelectValue /></SelectTrigger>
                  <SelectContent className="bg-[#1A1730] border-white/10 text-white">
                    {MODALITY.map((m) => (
                      <SelectItem key={m} value={m} data-testid={`service-modality-${m}`}>{t(`company.services.modality.${m}`)}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("company.services.descLabel")}</Label>
              <Textarea data-testid="service-description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows={3} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("company.services.imageLabel")}</Label>
              <input data-testid="service-image" type="file" accept="image/*" onChange={(e) => onImageFile(e.target.files?.[0])}
                className="mt-1 block w-full text-xs text-neutral-400 file:mr-3 file:px-3 file:py-2 file:border-0 file:bg-[#8B5CF6] file:text-white file:text-xs" />
              {form.image_url && <img src={form.image_url} alt="preview" className="mt-2 h-24 object-cover border border-white/10" />}
            </div>

            {/* Precio y pago */}
            <div className="border-t border-white/10 pt-3">
              <div className="micro-label text-[#8B5CF6] mb-2 flex items-center gap-1"><Clock className="w-3.5 h-3.5" /> {t("company.services.priceSection")}</div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="micro-label text-neutral-500">{t("company.services.pricingTypeLabel")}</Label>
                  <Select value={form.pricing_type} onValueChange={(v) => setForm({ ...form, pricing_type: v })}>
                    <SelectTrigger data-testid="service-pricing-type" className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"><SelectValue /></SelectTrigger>
                    <SelectContent className="bg-[#1A1730] border-white/10 text-white">
                      {PRICING.map((p) => (
                        <SelectItem key={p} value={p} data-testid={`service-pricing-${p}`}>{t(`company.services.pricing.${p}`)}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                {form.pricing_type !== "quote" && (
                  <div>
                    <Label className="micro-label text-neutral-500">{t("company.services.priceLabel")}</Label>
                    <Input data-testid="service-price" type="number" step="any" min="0" value={form.price_usdt} onChange={(e) => setForm({ ...form, price_usdt: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
                  </div>
                )}
              </div>
              <div className="grid grid-cols-2 gap-3 mt-3">
                <div>
                  <Label className="micro-label text-neutral-500">{t("company.services.depositLabel")}</Label>
                  <Select value={form.deposit_type} onValueChange={(v) => setForm({ ...form, deposit_type: v })}>
                    <SelectTrigger data-testid="service-deposit-type" className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"><SelectValue /></SelectTrigger>
                    <SelectContent className="bg-[#1A1730] border-white/10 text-white">
                      <SelectItem value="none" data-testid="service-deposit-none">{t("company.services.depositNone")}</SelectItem>
                      <SelectItem value="percent" data-testid="service-deposit-percent">{t("company.services.depositPercent")}</SelectItem>
                      <SelectItem value="fixed" data-testid="service-deposit-fixed">{t("company.services.depositFixed")}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                {form.deposit_type !== "none" && (
                  <div>
                    <Label className="micro-label text-neutral-500">{form.deposit_type === "percent" ? t("company.services.depositPercentLabel") : t("company.services.depositFixedLabel")}</Label>
                    <Input data-testid="service-deposit-value" type="number" step="any" min="0" value={form.deposit_value} onChange={(e) => setForm({ ...form, deposit_value: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
                  </div>
                )}
              </div>
              <div className="mt-3">
                <Label className="micro-label text-neutral-500">{t("company.services.paymentMethodsLabel")}</Label>
                <div className="flex gap-4 mt-2">
                  <label htmlFor="pay-balance" className="flex items-center gap-2 text-sm text-neutral-300 cursor-pointer">
                    <Checkbox id="pay-balance" data-testid="service-pay-balance" checked={form.payment_methods.includes("balance")} onCheckedChange={() => togglePayment("balance")}
                      className="border-white/30 data-[state=checked]:bg-[#8B5CF6] data-[state=checked]:border-[#8B5CF6]" /> {t("company.services.payBalance")}
                  </label>
                  <label htmlFor="pay-cash" className="flex items-center gap-2 text-sm text-neutral-300 cursor-pointer">
                    <Checkbox id="pay-cash" data-testid="service-pay-cash" checked={form.payment_methods.includes("cash")} onCheckedChange={() => togglePayment("cash")}
                      className="border-white/30 data-[state=checked]:bg-[#8B5CF6] data-[state=checked]:border-[#8B5CF6]" /> {t("company.services.payCash")}
                  </label>
                </div>
              </div>
            </div>

            {/* Calendario */}
            <div className="border-t border-white/10 pt-3">
              <div className="micro-label text-[#8B5CF6] mb-2 flex items-center gap-1"><CalendarClock className="w-3.5 h-3.5" /> {t("company.services.availabilitySection")}</div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <Label className="micro-label text-neutral-500">{t("company.services.durationLabel")}</Label>
                  <Input data-testid="service-duration" type="number" min="0" value={form.duration_minutes} onChange={(e) => setForm({ ...form, duration_minutes: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
                </div>
                <div>
                  <Label className="micro-label text-neutral-500">{t("company.services.minNoticeLabel")}</Label>
                  <Input data-testid="service-min-notice" type="number" min="0" value={form.min_notice_hours} onChange={(e) => setForm({ ...form, min_notice_hours: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
                </div>
                <div>
                  <Label className="micro-label text-neutral-500">{t("company.services.capacityLabel")}</Label>
                  <Input data-testid="service-capacity" type="number" min="1" value={form.capacity} onChange={(e) => setForm({ ...form, capacity: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
                </div>
              </div>
              <div className="mt-3 space-y-2" data-testid="service-availability-list">
                {form.availability.map((w, i) => (
                  <div key={i} className="flex items-center gap-2" data-testid={`service-window-${i}`}>
                    <select value={w.day} data-testid={`service-window-day-${i}`} onChange={(e) => updWindow(i, { day: parseInt(e.target.value) })}
                      className="h-9 bg-[#0a0a0a] border border-white/10 text-sm px-2 text-white flex-1">
                      {WD.map((d, idx) => <option key={idx} value={idx}>{d}</option>)}
                    </select>
                    <Input type="time" data-testid={`service-window-start-${i}`} value={w.start} onChange={(e) => updWindow(i, { start: e.target.value })} className="rounded-none bg-[#0a0a0a] border-white/10 h-9 w-[110px]" />
                    <span className="text-neutral-500">–</span>
                    <Input type="time" data-testid={`service-window-end-${i}`} value={w.end} onChange={(e) => updWindow(i, { end: e.target.value })} className="rounded-none bg-[#0a0a0a] border-white/10 h-9 w-[110px]" />
                    <button data-testid={`service-window-remove-${i}`} onClick={() => rmWindow(i)} className="text-neutral-500 hover:text-[#EF4444]"><X className="w-4 h-4" /></button>
                  </div>
                ))}
                <Button type="button" variant="outline" data-testid="service-add-window"
                  onClick={addWindow} className="border-white/15 text-neutral-300 hover:text-white rounded-none h-9">
                  <Plus className="w-4 h-4 mr-1" /> {t("company.services.addWindow")}
                </Button>
              </div>
              <div className="mt-3">
                <Label className="micro-label text-neutral-500">{t("company.services.blockedLabel")}</Label>
                <p className="text-xs text-neutral-500 mt-1">{t("company.services.blockedHint")}</p>
                <div className="mt-2 inline-flex bg-[#0a0a0a] border border-white/10" data-testid="service-blocked-calendar">
                  <Calendar mode="multiple" selected={form.blocked_dates.map((d) => new Date(d + "T00:00:00"))}
                    onSelect={setBlocked} fromDate={startOfToday()} locale={dfLocale} weekStartsOn={1} />
                </div>
                {form.blocked_dates.length > 0 && (
                  <div className="flex flex-wrap gap-2 mt-2">
                    {form.blocked_dates.map((d) => (
                      <span key={d} data-testid={`service-blocked-${d}`} className="inline-flex items-center gap-1 text-xs bg-white/5 border border-white/10 px-2 py-1">
                        {d}
                        <button type="button" onClick={() => rmBlocked(d)} className="text-neutral-500 hover:text-[#EF4444]"><X className="w-3 h-3" /></button>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Condiciones */}
            <div className="border-t border-white/10 pt-3 space-y-3">
              <div>
                <Label className="micro-label text-neutral-500">{t("company.services.zoneLabel")}</Label>
                <Input data-testid="service-zone" value={form.coverage_zone} onChange={(e) => setForm({ ...form, coverage_zone: e.target.value })} placeholder={t("company.services.zonePlaceholder")} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
              <div>
                <Label className="micro-label text-neutral-500">{t("company.services.inclusionsLabel")}</Label>
                <Textarea data-testid="service-inclusions" value={form.inclusions} onChange={(e) => setForm({ ...form, inclusions: e.target.value })} rows={2} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
              <div>
                <Label className="micro-label text-neutral-500">{t("company.services.requirementsLabel")}</Label>
                <Textarea data-testid="service-requirements" value={form.requirements} onChange={(e) => setForm({ ...form, requirements: e.target.value })} rows={2} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
              <div>
                <Label className="micro-label text-neutral-500">{t("company.services.cancellationLabel")}</Label>
                <Textarea data-testid="service-cancellation" value={form.cancellation_policy} onChange={(e) => setForm({ ...form, cancellation_policy: e.target.value })} rows={2} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
            </div>

            <div className="flex gap-2 pt-2">
              {!editing && (
                <Button data-testid="service-save-draft" onClick={() => save(false)} disabled={busy}
                  variant="outline" className="flex-1 border-white/15 text-neutral-200 hover:text-white rounded-none h-11">
                  {t("company.services.saveDraft")}
                </Button>
              )}
              <Button data-testid="service-save-submit" onClick={() => save(editing ? null : true)} disabled={busy}
                className="flex-1 bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-11">
                {busy ? t("company.services.saving") : editing ? t("company.services.saveChanges") : t("company.services.submitReview")}
              </Button>
            </div>
            {!editing && <p className="text-xs text-neutral-500">{t("company.services.pendingHint")}</p>}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
