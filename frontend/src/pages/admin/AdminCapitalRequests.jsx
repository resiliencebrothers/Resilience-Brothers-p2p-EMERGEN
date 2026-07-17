import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";
import AdminPageHeader from "@/components/AdminPageHeader";
import { CheckCircle2, XCircle, Clock, HandCoins, Filter } from "lucide-react";

const fmtNum = (n, d = 2) =>
  Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: d });
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString() : "—");

export default function AdminCapitalRequests() {
  const { t } = useTranslation();

  const STATUS_META = {
    pending:   { label: t("admin.capitalRequests.statusPending"),   cls: "text-amber-400 border-amber-500/40 bg-amber-500/5", icon: Clock },
    disbursed: { label: t("admin.capitalRequests.statusDisbursed"), cls: "text-[#8B5CF6] border-[#8B5CF6]/40 bg-[#8B5CF6]/5", icon: HandCoins },
    paid_off:  { label: t("admin.capitalRequests.statusPaidOff"),   cls: "text-emerald-400 border-emerald-500/40 bg-emerald-500/5", icon: CheckCircle2 },
    rejected:  { label: t("admin.capitalRequests.statusRejected"),  cls: "text-red-400 border-red-500/40 bg-red-500/5", icon: XCircle },
  };

  const [items, setItems] = useState([]);
  const [statusFilter, setStatusFilter] = useState("all");
  const [loading, setLoading] = useState(false);
  const [approving, setApproving] = useState(null); // {id, amount, currency, user_name}
  const [rejecting, setRejecting] = useState(null);
  const [discountPct, setDiscountPct] = useState("30");
  const [adminNotes, setAdminNotes] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const [pendingTotp, setPendingTotp] = useState(null); // {kind, payload}
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (statusFilter !== "all") params.status = statusFilter;
      const r = await axios.get(`${API}/admin/capital-requests`, {
        params, withCredentials: true,
      });
      setItems(r.data || []);
    } catch (e) {
      toast.error(e.response?.data?.detail || t("admin.capitalRequests.loadError"));
    } finally {
      setLoading(false);
    }
  }, [statusFilter, t]);

  useEffect(() => { load(); }, [load]);

  const openApprove = (item) => {
    setApproving(item);
    setDiscountPct("30");
    setAdminNotes("");
  };
  const openReject = (item) => {
    setRejecting(item);
    setRejectReason("");
  };

  const submitApprove = async (totp) => {
    if (!approving) return;
    const pct = Number(discountPct);
    if (isNaN(pct) || pct < 1 || pct > 100) {
      return toast.error(t("admin.capitalRequests.discountInvalid"));
    }
    setBusy(true);
    try {
      await axios.post(
        `${API}/admin/capital-requests/${approving.id}/approve`,
        { discount_pct: pct, admin_notes: adminNotes, totp_code: totp },
        { withCredentials: true },
      );
      toast.success(
        t("admin.capitalRequests.disbursedToast", {
          amount: fmtNum(approving.amount, 2),
          code: approving.currency_code,
          who: approving.user_name || approving.user_email,
          pct,
        })
      );
      setApproving(null);
      setPendingTotp(null);
      load();
    } catch (e) {
      if (!handleTotpError(e, () => setPendingTotp({ kind: "approve" }))) {
        toast.error(e.response?.data?.detail || t("admin.capitalRequests.approveError"));
      }
    } finally {
      setBusy(false);
    }
  };

  const submitReject = async (totp) => {
    if (!rejecting) return;
    if (rejectReason.trim().length < 5) {
      return toast.error(t("admin.capitalRequests.rejectReasonInvalid"));
    }
    setBusy(true);
    try {
      await axios.post(
        `${API}/admin/capital-requests/${rejecting.id}/reject`,
        { reject_reason: rejectReason.trim(), totp_code: totp },
        { withCredentials: true },
      );
      toast.success(t("admin.capitalRequests.rejectedToast"));
      setRejecting(null);
      setPendingTotp(null);
      load();
    } catch (e) {
      if (!handleTotpError(e, () => setPendingTotp({ kind: "reject" }))) {
        toast.error(e.response?.data?.detail || t("admin.capitalRequests.rejectError"));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4" data-testid="admin-capital-requests">
      <AdminPageHeader
        eyebrow={t("admin.capitalRequests.eyebrow")}
        title={t("admin.capitalRequests.title")}
        subtitle={t("admin.capitalRequests.subtitle")}
        actions={
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-neutral-500" />
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-44 rounded-none bg-[#0a0a0a] border-white/10 h-10" data-testid="cr-filter-status">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                <SelectItem value="all">{t("admin.capitalRequests.allFilter")}</SelectItem>
                <SelectItem value="pending">{t("admin.capitalRequests.pendingFilter")}</SelectItem>
                <SelectItem value="disbursed">{t("admin.capitalRequests.disbursedFilter")}</SelectItem>
                <SelectItem value="paid_off">{t("admin.capitalRequests.paidOffFilter")}</SelectItem>
                <SelectItem value="rejected">{t("admin.capitalRequests.rejectedFilter")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
        }
      />

      {loading ? (
        <div className="text-neutral-500 p-6">{t("admin.capitalRequests.loading")}</div>
      ) : items.length === 0 ? (
        <div className="tactile-card p-10 text-center text-neutral-500" data-testid="cr-empty">
          {t("admin.capitalRequests.empty")}
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((cr) => {
            const meta = STATUS_META[cr.status] || STATUS_META.pending;
            const StatusIcon = meta.icon;
            const paidPct = cr.debt_original
              ? Math.round(((cr.debt_original - (cr.debt_remaining || 0)) / cr.debt_original) * 100)
              : 0;
            return (
              <div
                key={cr.id}
                className="tactile-card p-5"
                data-testid={`cr-item-${cr.id}`}
              >
                <div className="flex items-start justify-between gap-4 flex-wrap">
                  <div className="flex-1 min-w-[260px]">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`text-[0.65rem] uppercase tracking-widest border px-2 py-0.5 flex items-center gap-1 ${meta.cls}`}>
                        <StatusIcon className="w-3 h-3" /> {meta.label}
                      </span>
                      <span className="text-neutral-500 text-xs">
                        {fmtDate(cr.created_at)}
                      </span>
                    </div>
                    <div className="font-display text-xl">
                      {cr.user_name || t("admin.capitalRequests.noName")}
                      <span className="text-sm text-neutral-500 ml-2 font-mono">
                        {cr.user_email}
                      </span>
                    </div>
                    <div className="text-sm text-neutral-300 mt-2 leading-relaxed max-w-xl">
                      {cr.reason}
                    </div>
                    {cr.status === "rejected" && cr.reject_reason && (
                      <div className="mt-2 text-xs text-red-400">
                        {t("admin.capitalRequests.rejectReason", { reason: cr.reject_reason })}
                      </div>
                    )}
                    {cr.status === "disbursed" && cr.admin_notes && (
                      <div className="mt-2 text-xs text-neutral-500">
                        {t("admin.capitalRequests.adminNotes", { notes: cr.admin_notes })}
                      </div>
                    )}
                  </div>
                  <div className="text-right">
                    <div className="micro-label text-neutral-500">{t("admin.capitalRequests.amountRequested")}</div>
                    <div className="font-display text-2xl tabular-nums">
                      {fmtNum(cr.amount, 2)} <span className="text-sm text-neutral-500">{cr.currency_code}</span>
                    </div>
                    {cr.status === "disbursed" && (
                      <>
                        <div className="mt-2 text-xs text-neutral-500">
                          {t("admin.capitalRequests.remaining")} <span className="text-red-400 tabular-nums">{fmtNum(cr.debt_remaining, 2)} {cr.currency_code}</span>
                        </div>
                        <div className="mt-1 text-[0.65rem] text-[#8B5CF6]">
                          {t("admin.capitalRequests.discountPerOrder", { pct: cr.discount_pct })}
                        </div>
                      </>
                    )}
                  </div>
                </div>

                {cr.status === "disbursed" && (
                  <div className="mt-4">
                    <div className="h-1.5 bg-white/5">
                      <div
                        className="h-full bg-emerald-500 transition-all"
                        style={{ width: `${paidPct}%` }}
                      />
                    </div>
                    <div className="text-[0.65rem] text-neutral-500 mt-1 uppercase tracking-widest">
                      {t("admin.capitalRequests.paidPct", { pct: paidPct, n: (cr.repayment_events || []).length })}
                    </div>
                  </div>
                )}

                {cr.status === "pending" && (
                  <div className="flex gap-2 mt-4">
                    <Button
                      data-testid={`cr-approve-${cr.id}`}
                      onClick={() => openApprove(cr)}
                      className="rounded-none bg-emerald-600 hover:bg-emerald-500 text-white h-9 px-4 text-xs uppercase tracking-wider font-bold"
                    >
                      <CheckCircle2 className="w-4 h-4 mr-1.5" /> {t("admin.capitalRequests.approve")}
                    </Button>
                    <Button
                      data-testid={`cr-reject-${cr.id}`}
                      onClick={() => openReject(cr)}
                      className="rounded-none bg-red-600 hover:bg-red-500 text-white h-9 px-4 text-xs uppercase tracking-wider font-bold"
                    >
                      <XCircle className="w-4 h-4 mr-1.5" /> {t("admin.capitalRequests.reject")}
                    </Button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* APPROVE DIALOG */}
      <Dialog open={!!approving} onOpenChange={(o) => !o && setApproving(null)}>
        <DialogContent className="bg-[#0c0c0c] border border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("admin.capitalRequests.approveDialog")}</DialogTitle>
          </DialogHeader>
          {approving && (
            <div className="space-y-4">
              <div className="border border-white/10 bg-[#0a0a0a] p-3 text-sm">
                <div>{t("admin.capitalRequests.client")} <strong>{approving.user_name}</strong> ({approving.user_email})</div>
                <div className="mt-1">{t("admin.capitalRequests.amountLabel")} <strong className="tabular-nums">{fmtNum(approving.amount, 2)} {approving.currency_code}</strong></div>
                <div className="mt-1 text-xs text-neutral-500">{approving.reason}</div>
              </div>
              <div>
                <Label className="micro-label text-neutral-500">{t("admin.capitalRequests.discountLabel")}</Label>
                <Input
                  data-testid="cr-approve-discount"
                  type="number"
                  min="1" max="100"
                  value={discountPct}
                  onChange={(e) => setDiscountPct(e.target.value)}
                  className="rounded-none bg-[#0a0a0a] border-white/10 h-11 mt-1 font-mono"
                />
                <div className="text-[0.65rem] text-neutral-500 mt-1">
                  {t("admin.capitalRequests.discountHelper", { code: approving.currency_code })}
                </div>
              </div>
              <div>
                <Label className="micro-label text-neutral-500">{t("admin.capitalRequests.adminNotesLabel")}</Label>
                <Textarea
                  data-testid="cr-approve-notes"
                  value={adminNotes}
                  onChange={(e) => setAdminNotes(e.target.value)}
                  maxLength={500}
                  className="rounded-none bg-[#0a0a0a] border-white/10 mt-1"
                />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button onClick={() => setApproving(null)} className="rounded-none bg-transparent border border-white/15 text-white">{t("admin.capitalRequests.cancel")}</Button>
            <Button
              data-testid="cr-approve-confirm"
              onClick={() => submitApprove()}
              disabled={busy}
              className="rounded-none bg-emerald-600 hover:bg-emerald-500 text-white font-bold"
            >
              {t("admin.capitalRequests.disburse")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* REJECT DIALOG */}
      <Dialog open={!!rejecting} onOpenChange={(o) => !o && setRejecting(null)}>
        <DialogContent className="bg-[#0c0c0c] border border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("admin.capitalRequests.rejectDialog")}</DialogTitle>
          </DialogHeader>
          {rejecting && (
            <div className="space-y-4">
              <div className="border border-white/10 bg-[#0a0a0a] p-3 text-sm">
                <div>{t("admin.capitalRequests.client")} <strong>{rejecting.user_name}</strong></div>
                <div className="mt-1">{t("admin.capitalRequests.amountLabel")} <strong className="tabular-nums">{fmtNum(rejecting.amount, 2)} {rejecting.currency_code}</strong></div>
              </div>
              <div>
                <Label className="micro-label text-neutral-500">{t("admin.capitalRequests.rejectReasonLabel")}</Label>
                <Textarea
                  data-testid="cr-reject-reason"
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  minLength={5}
                  maxLength={500}
                  className="rounded-none bg-[#0a0a0a] border-white/10 mt-1"
                  placeholder={t("admin.capitalRequests.rejectReasonPh")}
                />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button onClick={() => setRejecting(null)} className="rounded-none bg-transparent border border-white/15 text-white">{t("admin.capitalRequests.cancel")}</Button>
            <Button
              data-testid="cr-reject-confirm"
              onClick={() => submitReject()}
              disabled={busy}
              className="rounded-none bg-red-600 hover:bg-red-500 text-white font-bold"
            >
              {t("admin.capitalRequests.rejectBtn")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <TotpPromptDialog
        open={!!pendingTotp}
        title={t("admin.capitalRequests.totpTitle")}
        description={t("admin.capitalRequests.totpDescription")}
        onConfirm={(code) => {
          if (pendingTotp?.kind === "approve") submitApprove(code);
          else if (pendingTotp?.kind === "reject") submitReject(code);
        }}
        onCancel={() => setPendingTotp(null)}
      />
    </div>
  );
}
