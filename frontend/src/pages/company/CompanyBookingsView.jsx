import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { CalendarCheck, Check, X, Clock, User, Wallet, TrendingUp, Star, MessageSquare, CornerDownRight, Loader2 } from "lucide-react";
import { toast } from "sonner";

// Reservas recibidas por la Empresa (Fase 2). La empresa acepta o rechaza cada
// turno; al rechazar (o si no decide a tiempo) el cliente recibe el reembolso
// automático en USDT. El dinero se libera a la empresa DESPUÉS de la cita.
const STATUS_BADGE = {
  pending: "bg-amber-500/10 text-amber-300 border-amber-500/30",
  accepted: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  rejected: "bg-red-500/10 text-red-400 border-red-500/30",
  cancelled: "bg-neutral-500/10 text-neutral-300 border-neutral-500/30",
  expired: "bg-orange-500/10 text-orange-300 border-orange-500/30",
  settled: "bg-sky-500/10 text-sky-300 border-sky-500/30",
};
const FILTERS = [
  { v: "", k: "filterAll" }, { v: "pending", k: "filterPending" },
  { v: "accepted", k: "filterAccepted" }, { v: "settled", k: "filterSettled" },
  { v: "rejected", k: "filterRejected" }, { v: "cancelled", k: "filterCancelled" },
  { v: "expired", k: "filterExpired" },
];

export default function CompanyBookingsView({ onChanged }) {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [earnings, setEarnings] = useState(null);
  const [filter, setFilter] = useState("");
  const [rejecting, setRejecting] = useState(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    const q = filter ? `?status=${filter}` : "";
    axios.get(`${API}/company/bookings${q}`, { withCredentials: true })
      .then((r) => setItems(r.data)).catch(() => {});
    axios.get(`${API}/company/bookings/earnings`, { withCredentials: true })
      .then((r) => setEarnings(r.data)).catch(() => {});
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  const accept = async (b) => {
    setBusy(true);
    try {
      await axios.post(`${API}/company/bookings/${b.id}/accept`, {}, { withCredentials: true });
      toast.success(t("company.bookings.acceptedToast"));
      load(); onChanged?.();
    } catch (e) { toast.error(e.response?.data?.detail || t("company.bookings.genericError")); }
    finally { setBusy(false); }
  };

  const doReject = async () => {
    if (!rejecting) return;
    setBusy(true);
    try {
      await axios.post(`${API}/company/bookings/${rejecting.id}/reject`, { reason },
        { withCredentials: true });
      toast.success(t("company.bookings.rejectedToast"));
      setRejecting(null); setReason("");
      load(); onChanged?.();
    } catch (e) { toast.error(e.response?.data?.detail || t("company.bookings.genericError")); }
    finally { setBusy(false); }
  };

  const pendingCount = items.filter((b) => b.status === "pending").length;

  return (
    <div className="space-y-6" data-testid="company-bookings-view">
      <div>
        <div className="micro-label text-[#8B5CF6] mb-2">{t("company.bookings.sectionLabel")}</div>
        <h2 className="font-display text-2xl flex items-center gap-3">
          <CalendarCheck className="w-6 h-6 text-[#8B5CF6]" /> {t("company.bookings.title")}
          {pendingCount > 0 && <span className="text-sm bg-amber-500/15 text-amber-300 px-2 py-0.5 rounded-full">{t("company.bookings.pendingBadge", { count: pendingCount })}</span>}
        </h2>
      </div>

      <div className="border-l-4 border-[#8B5CF6] bg-[#8B5CF6]/5 px-4 py-3 text-sm text-neutral-300" data-testid="company-bookings-note">
        {t("company.bookings.note")}
      </div>

      {earnings && (
        <div className="tactile-card p-4" data-testid="company-earnings-panel">
          <div className="micro-label text-[#8B5CF6] mb-3 flex items-center gap-1"><Wallet className="w-3.5 h-3.5" /> {t("company.bookings.earningsTitle")}</div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="border border-white/10 p-3">
              <div className="text-xs text-neutral-400">{t("company.bookings.heldLabel")}</div>
              <div className="font-display text-2xl text-amber-300" data-testid="earnings-held">{earnings.held_pending} USDT</div>
              <div className="text-[0.7rem] text-neutral-500 mt-1">{t("company.bookings.heldHint")}</div>
            </div>
            <div className="border border-white/10 p-3">
              <div className="text-xs text-neutral-400">{t("company.bookings.upcomingLabel")}</div>
              <div className="font-display text-2xl text-emerald-400" data-testid="earnings-upcoming">{earnings.upcoming_release} USDT</div>
              <div className="text-[0.7rem] text-neutral-500 mt-1">{t("company.bookings.upcomingHint")}</div>
            </div>
            <div className="border border-white/10 p-3">
              <div className="text-xs text-neutral-400">{t("company.bookings.settledLabel")}</div>
              <div className="font-display text-2xl text-sky-300" data-testid="earnings-settled">{earnings.settled_total} USDT</div>
              <div className="text-[0.7rem] text-neutral-500 mt-1">{t("company.bookings.settledHint")}</div>
            </div>
          </div>
          {earnings.upcoming?.length > 0 && (
            <div className="mt-4">
              <div className="text-xs text-neutral-400 mb-2 flex items-center gap-1"><TrendingUp className="w-3.5 h-3.5 text-emerald-400" /> {t("company.bookings.scheduleTitle")}</div>
              <ul className="space-y-1.5" data-testid="earnings-schedule">
                {earnings.upcoming.map((u) => (
                  <li key={u.id} className="flex items-center justify-between gap-3 text-sm border-b border-white/5 pb-1.5 last:border-0">
                    <span className="text-neutral-300 truncate">{u.slot_date} · {u.slot_start} · <span className="text-neutral-500">{u.service_title}</span></span>
                    <span className="font-mono text-emerald-300 shrink-0">{u.amount_usdt} USDT</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      <div className="flex gap-2 flex-wrap">
        {FILTERS.map((f) => (
          <button key={f.v || "all"} data-testid={`company-bookings-filter-${f.v || "all"}`} onClick={() => setFilter(f.v)}
            className={`px-3 py-1 text-xs uppercase tracking-wider border transition-colors ${filter === f.v ? "border-[#8B5CF6] text-[#8B5CF6] bg-[#8B5CF6]/10" : "border-white/10 text-neutral-400 hover:text-white"}`}>
            {t(`company.bookings.${f.k}`)}
          </button>
        ))}
      </div>

      {items.length === 0 && (
        <p className="text-neutral-500 text-center py-12 tactile-card" data-testid="company-bookings-empty">
          {filter ? t("company.bookings.emptyFiltered") : t("company.bookings.empty")}
        </p>
      )}

      <div className="space-y-3">
        {items.map((b) => (
          <div key={b.id} data-testid={`company-booking-${b.id}`} className="tactile-card p-4 flex items-start justify-between gap-3 flex-wrap">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-display text-base truncate">{b.service_title}</span>
                <span className={`text-[0.6rem] uppercase tracking-wider px-2 py-0.5 border ${STATUS_BADGE[b.status] || ""}`} data-testid={`company-booking-status-${b.id}`}>
                  {t(`company.bookings.status.${b.status}`, { defaultValue: b.status })}
                </span>
              </div>
              <div className="text-xs text-neutral-400 mt-1 flex items-center gap-1">
                <Clock className="w-3 h-3" /> {b.slot_date} · {b.slot_start}–{b.slot_end}
              </div>
              <div className="text-xs text-neutral-400 mt-0.5 flex items-center gap-1">
                <User className="w-3 h-3" /> {b.customer_name || t("company.bookings.customerFallback")}
              </div>
              <div className="text-xs text-neutral-500 mt-0.5">
                {b.quantity > 1 ? `${b.quantity}× · ` : ""}{b.amount_usdt > 0 ? `${b.amount_usdt} USDT` : t("company.bookings.toBudget")}
              </div>
              {b.remainder_usdt > 0 && ["pending", "accepted", "settled"].includes(b.status) && (
                <div className="text-[0.7rem] text-emerald-300/80 mt-0.5" data-testid={`company-booking-deposit-${b.id}`}>
                  {t("company.bookings.depositLinePre")} {b.deposit_usdt} {t("company.bookings.depositLineMid")} {b.remainder_usdt} {t("company.bookings.depositLineUnit")} {b.status === "settled" ? t("company.bookings.tailReleased") : t("company.bookings.tailFrozen")}
                </div>
              )}
              {b.note && <div className="text-xs text-neutral-400 mt-1 italic">“{b.note}”</div>}
            </div>
            {b.status === "pending" && (
              <div className="flex gap-2">
                <Button data-testid={`company-booking-accept-${b.id}`} onClick={() => accept(b)} disabled={busy}
                  className="bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 rounded-none h-9">
                  <Check className="w-4 h-4 mr-1" /> {t("company.bookings.accept")}
                </Button>
                <Button data-testid={`company-booking-reject-${b.id}`} onClick={() => { setRejecting(b); setReason(""); }} disabled={busy}
                  variant="outline" className="border-white/15 text-neutral-300 hover:text-red-400 rounded-none h-9">
                  <X className="w-4 h-4 mr-1" /> {t("company.bookings.reject")}
                </Button>
              </div>
            )}
          </div>
        ))}
      </div>

      <Dialog open={!!rejecting} onOpenChange={(v) => !v && setRejecting(null)}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto sm:max-w-md" data-testid="company-booking-reject-dialog">
          <DialogHeader><DialogTitle className="font-display">{t("company.bookings.rejectDialogTitle")}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <p className="text-sm text-neutral-300">
              {rejecting?.amount_usdt > 0
                ? t("company.bookings.rejectBodyWithAmount", { amount: rejecting.amount_usdt })
                : t("company.bookings.rejectBodyNoAmount")}
            </p>
            <Textarea data-testid="company-booking-reject-reason" value={reason} onChange={(e) => setReason(e.target.value)} rows={3}
              placeholder={t("company.bookings.rejectPlaceholder")} className="rounded-none bg-[#0a0a0a] border-white/10" />
            <div className="flex gap-2">
              <Button data-testid="company-booking-reject-cancel" onClick={() => setRejecting(null)} variant="outline"
                className="flex-1 border-white/15 text-neutral-200 rounded-none h-10">{t("company.bookings.cancelBtn")}</Button>
              <Button data-testid="company-booking-reject-confirm" onClick={doReject} disabled={busy}
                className="flex-1 bg-red-500/80 hover:bg-red-500 text-white font-semibold rounded-none h-10">
                {busy ? t("company.bookings.saving") : t("company.bookings.rejectConfirm")}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <CompanyReviews />
    </div>
  );
}

// ---------- Reseñas de clientes: la empresa responde públicamente ----------
function CompanyReviews() {
  const { t } = useTranslation();
  const [reviews, setReviews] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [savingId, setSavingId] = useState(null);

  const load = useCallback(() => {
    axios.get(`${API}/company/reviews`, { withCredentials: true })
      .then((r) => setReviews(r.data || [])).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async (rv) => {
    const text = (drafts[rv.id] ?? "").trim();
    if (!text) return;
    setSavingId(rv.id);
    try {
      await axios.post(`${API}/company/reviews/${rv.id}/response`, { response: text },
        { withCredentials: true });
      toast.success(t("company.bookings.replyPublished"));
      setDrafts((d) => { const n = { ...d }; delete n[rv.id]; return n; });
      load();
    } catch (e) { toast.error(e.response?.data?.detail || t("company.bookings.genericError")); }
    finally { setSavingId(null); }
  };

  return (
    <div data-testid="company-reviews-section">
      <h3 className="font-display text-xl flex items-center gap-2 mt-2">
        <MessageSquare className="w-5 h-5 text-[#8B5CF6]" /> {t("company.bookings.reviewsTitle")}
        {reviews.length > 0 && <span className="text-sm text-neutral-500">· {reviews.length}</span>}
      </h3>
      <p className="text-sm text-neutral-400 mt-1 mb-3">{t("company.bookings.reviewsSubtitle")}</p>

      {reviews.length === 0 ? (
        <p className="text-neutral-500 text-center py-10 tactile-card" data-testid="company-reviews-empty">
          {t("company.bookings.reviewsEmpty")}
        </p>
      ) : (
        <div className="space-y-3">
          {reviews.map((rv) => (
            <div key={rv.id} data-testid={`company-review-${rv.id}`} className="tactile-card p-4">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center gap-0.5">
                    {[1, 2, 3, 4, 5].map((n) => (
                      <Star key={n} className={`w-3.5 h-3.5 ${n <= Math.round(rv.rating) ? "fill-amber-400 text-amber-400" : "text-neutral-600"}`} />
                    ))}
                  </span>
                  <span className="text-xs text-neutral-300">{rv.customer_name}</span>
                </div>
                <span className="text-[0.7rem] text-neutral-500">{rv.service_title}</span>
              </div>
              {rv.comment && <p className="text-sm text-neutral-300 mt-1.5 whitespace-pre-line">{rv.comment}</p>}

              {rv.company_response ? (
                <div className="mt-2.5 ml-3 border-l-2 border-[#8B5CF6]/40 pl-3" data-testid={`company-review-reply-${rv.id}`}>
                  <div className="text-[0.65rem] uppercase tracking-wider text-[#A78BFA] flex items-center gap-1">
                    <CornerDownRight className="w-3 h-3" /> {t("company.bookings.yourResponse")}
                  </div>
                  <p className="text-sm text-neutral-300 mt-0.5 whitespace-pre-line">{rv.company_response}</p>
                  <button data-testid={`company-review-edit-${rv.id}`} onClick={() => setDrafts((d) => ({ ...d, [rv.id]: rv.company_response }))}
                    className="text-[0.7rem] text-neutral-500 hover:text-[#A78BFA] mt-1">{t("company.bookings.editReply")}</button>
                </div>
              ) : null}

              {(drafts[rv.id] !== undefined || !rv.company_response) && (
                <div className="mt-2.5 space-y-2">
                  <Textarea data-testid={`company-review-input-${rv.id}`} rows={2}
                    value={drafts[rv.id] ?? ""} onChange={(e) => setDrafts((d) => ({ ...d, [rv.id]: e.target.value }))}
                    placeholder={t("company.bookings.replyPlaceholder")} className="rounded-none bg-[#0a0a0a] border-white/10" />
                  <Button data-testid={`company-review-save-${rv.id}`} onClick={() => save(rv)} disabled={savingId === rv.id || !(drafts[rv.id] ?? "").trim()}
                    className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-semibold rounded-none h-9">
                    {savingId === rv.id ? (<><Loader2 className="w-4 h-4 mr-1 animate-spin" /> {t("company.bookings.saving")}</>) : (rv.company_response ? t("company.bookings.saveChanges") : t("company.bookings.reply"))}
                  </Button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
