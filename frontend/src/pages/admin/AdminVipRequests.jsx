import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Crown, Check, X, Clock, TrendingUp, CreditCard } from "lucide-react";
import { useLiveEvent } from "@/hooks/useLiveStream";
import AdminPageHeader from "@/components/AdminPageHeader";

/**
 * iter109 — Admin queue for VIP upgrade requests.
 *
 * Tab embedded inside AdminUsersHub (`/admin/users?tab=vip-requests`).
 * Requires `vip_requests` permission (admin auto-passes).
 *
 * Actions:
 *   - Approve → user.role becomes VIP (backend handles atomically).
 *   - Reject  → opens sub-dialog to capture admin_note (optional).
 *
 * Auto-refreshes on SSE events + 60s polling fallback.
 */
export default function AdminVipRequests() {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [statusFilter, setStatusFilter] = useState("pending");
  const [loading, setLoading] = useState(true);
  const [rejecting, setRejecting] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/admin/vip-requests`, {
        params: statusFilter !== "all" ? { status: statusFilter } : {},
        withCredentials: true,
      });
      setItems(r.data?.items || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("adminVipRequests.loadError"));
    } finally {
      setLoading(false);
    }
  }, [statusFilter, t]);

  useEffect(() => { load(); }, [load]);
  useLiveEvent("vip_request_created", load);
  useLiveEvent("vip_request_updated", load);

  const approve = async (id) => {
    try {
      await axios.post(`${API}/admin/vip-requests/${id}/approve`, {}, { withCredentials: true });
      toast.success(t("adminVipRequests.approvedToast"));
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("adminVipRequests.actionError"));
    }
  };

  return (
    <div className="space-y-4" data-testid="admin-vip-requests">
      <AdminPageHeader
        eyebrow={t("adminVipRequests.eyebrow")}
        title={t("adminVipRequests.title")}
        testid="admin-vip-requests-header"
      />

      <div className="flex items-center gap-2 flex-wrap">
        {["pending", "approved", "rejected", "all"].map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setStatusFilter(s)}
            data-testid={`vip-requests-filter-${s}`}
            className={`text-xs uppercase tracking-widest px-3 py-1.5 border font-mono transition-colors ${
              statusFilter === s
                ? "bg-[#8B5CF6]/10 border-[#8B5CF6] text-[#8B5CF6]"
                : "bg-transparent border-white/10 text-neutral-400 hover:border-white/30"
            }`}
          >
            {t(`adminVipRequests.filter.${s}`)}
          </button>
        ))}
      </div>

      <div className="tactile-card overflow-x-auto">
        <table className="w-full text-sm min-w-[900px]">
          <thead className="border-b border-white/10 bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminVipRequests.colUser")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminVipRequests.colVolume")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminVipRequests.colMethod")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminVipRequests.colMessage")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 whitespace-nowrap">{t("adminVipRequests.colCreated")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminVipRequests.colStatus")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminVipRequests.colActions")}</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan="7" className="text-center text-neutral-500 py-8">
                  {t("admin.common.loadingEllipsis")}
                </td>
              </tr>
            )}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan="7" className="text-center text-neutral-500 py-8" data-testid="admin-vip-requests-empty">
                  {t("adminVipRequests.empty")}
                </td>
              </tr>
            )}
            {!loading && items.map((it) => (
              <tr
                key={it.id}
                className="border-b border-white/5"
                data-testid={`vip-request-row-${it.id}`}
              >
                <td className="px-4 py-3">
                  <div className="text-white">{it.user_name || "—"}</div>
                  <div className="text-xs text-neutral-500">{it.user_email}</div>
                </td>
                <td className="px-4 py-3 text-white font-mono text-sm">
                  <span className="inline-flex items-center gap-1">
                    <TrendingUp className="w-3 h-3 text-emerald-400" />
                    ${Number(it.estimated_monthly_volume_usd).toLocaleString()}
                  </span>
                </td>
                <td className="px-4 py-3 text-xs text-neutral-300">
                  <span className="inline-flex items-center gap-1">
                    <CreditCard className="w-3 h-3 text-neutral-500" />
                    {t(`vipRequest.method.${it.preferred_payment_method}`, it.preferred_payment_method)}
                  </span>
                </td>
                <td className="px-4 py-3 text-xs text-neutral-400 max-w-xs">
                  <div className="line-clamp-3">{it.message}</div>
                </td>
                <td className="px-4 py-3 text-xs text-neutral-500 whitespace-nowrap">
                  {new Date(it.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3">
                  <StatusPill status={it.status} />
                </td>
                <td className="px-4 py-3">
                  {it.status === "pending" ? (
                    <div className="flex gap-2">
                      <Button
                        onClick={() => approve(it.id)}
                        data-testid={`vip-approve-${it.id}`}
                        className="rounded-none bg-emerald-500 hover:bg-emerald-400 text-black h-8 px-3 text-xs font-semibold"
                      >
                        <Check className="w-3 h-3 mr-1" /> {t("adminVipRequests.approve")}
                      </Button>
                      <Button
                        onClick={() => setRejecting(it)}
                        data-testid={`vip-reject-${it.id}`}
                        variant="ghost"
                        className="rounded-none border border-[#EF4444]/40 text-[#EF4444] hover:bg-[#EF4444]/10 h-8 px-3 text-xs"
                      >
                        <X className="w-3 h-3 mr-1" /> {t("adminVipRequests.reject")}
                      </Button>
                    </div>
                  ) : (
                    <span className="text-xs text-neutral-500">
                      {it.reviewed_at ? new Date(it.reviewed_at).toLocaleDateString() : "—"}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <RejectDialog
        open={!!rejecting}
        request={rejecting}
        onClose={() => setRejecting(null)}
        onDone={() => { setRejecting(null); load(); }}
      />
    </div>
  );
}


function StatusPill({ status }) {
  const { t } = useTranslation();
  const meta = {
    pending:  { cls: "bg-amber-500/10 text-amber-400 border-amber-500/30", Icon: Clock },
    approved: { cls: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30", Icon: Check },
    rejected: { cls: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30", Icon: X },
  }[status] || {};
  const Icon = meta.Icon || Crown;
  return (
    <span className={`inline-flex items-center gap-1 text-[0.65rem] uppercase tracking-widest border px-2 py-1 font-mono ${meta.cls || ""}`}>
      <Icon className="w-3 h-3" />
      {t(`vipRequest.status.${status}`, status)}
    </span>
  );
}


function RejectDialog({ open, request, onClose, onDone }) {
  const { t } = useTranslation();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (open) setNote(""); }, [open]);

  const submit = async () => {
    if (!request) return;
    setBusy(true);
    try {
      await axios.post(
        `${API}/admin/vip-requests/${request.id}/reject`,
        { admin_note: note.trim() },
        { withCredentials: true },
      );
      toast.success(t("adminVipRequests.rejectedToast"));
      onDone?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("adminVipRequests.actionError"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent
        data-testid="vip-reject-dialog"
        className="bg-[#0c0c0c] border border-[#EF4444]/30 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle>{t("adminVipRequests.rejectDialogTitle")}</DialogTitle>
        </DialogHeader>
        <p className="text-xs text-neutral-400">
          {t("adminVipRequests.rejectDialogBody", {
            name: request?.user_name || request?.user_email || "",
          })}
        </p>
        <textarea
          data-testid="vip-reject-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={4}
          maxLength={500}
          placeholder={t("adminVipRequests.rejectDialogPlaceholder")}
          className="w-full mt-3 bg-black/40 border border-white/10 rounded-none px-3 py-2 text-sm text-white placeholder:text-neutral-600 focus:border-[#EF4444]/50 focus:outline-none"
        />
        <div className="flex justify-end gap-2 pt-3 border-t border-white/5 mt-2">
          <Button variant="ghost" onClick={onClose} className="rounded-none text-neutral-400">
            {t("common.cancel")}
          </Button>
          <Button
            onClick={submit}
            disabled={busy}
            data-testid="vip-reject-confirm"
            className="rounded-none bg-[#EF4444] hover:bg-[#F87171] text-white disabled:opacity-40"
          >
            {t("adminVipRequests.reject")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
