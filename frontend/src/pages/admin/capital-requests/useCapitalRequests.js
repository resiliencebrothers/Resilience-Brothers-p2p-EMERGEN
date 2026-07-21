/**
 * iter86 — useCapitalRequests
 *
 * Data hook for the admin Capital Requests page. Owns:
 *   • The filtered fetch of `/admin/capital-requests`.
 *   • The approve dialog state (discountPct + adminNotes) and submit.
 *   • The reject dialog state (rejectReason) and submit.
 *   • The TOTP re-prompt lifecycle (`pendingTotp`) shared by both flows.
 *   • The `busy` flag while a submit is in flight.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { handleTotpError } from "@/components/TotpPromptDialog";

const fmtNum = (n, d = 2) =>
  Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: d });

export function useCapitalRequests() {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [statusFilter, setStatusFilter] = useState("all");
  // iter87 — client-side search filter (name / email). Debounced only via
  // React's batching — the list is bounded by pagination so a simple
  // includes() sweep is fine.
  const [clientQuery, setClientQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [approving, setApproving] = useState(null);
  const [rejecting, setRejecting] = useState(null);
  const [discountPct, setDiscountPct] = useState("30");
  const [adminNotes, setAdminNotes] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const [pendingTotp, setPendingTotp] = useState(null);
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

  const openApprove = useCallback((item) => {
    setApproving(item);
    setDiscountPct("30");
    setAdminNotes("");
  }, []);

  const openReject = useCallback((item) => {
    setRejecting(item);
    setRejectReason("");
  }, []);

  const submitApprove = useCallback(async (totp) => {
    if (!approving) return;
    const pct = Number(discountPct);
    if (Number.isNaN(pct) || pct < 1 || pct > 100) {
      toast.error(t("admin.capitalRequests.discountInvalid"));
      return;
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
        }),
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
  }, [approving, discountPct, adminNotes, load, t]);

  const submitReject = useCallback(async (totp) => {
    if (!rejecting) return;
    if (rejectReason.trim().length < 5) {
      toast.error(t("admin.capitalRequests.rejectReasonInvalid"));
      return;
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
  }, [rejecting, rejectReason, load, t]);

  // iter87 — Case-insensitive substring match against user_name + user_email.
  // Runs client-side over the already-filtered-by-status list.
  const filteredItems = useMemo(() => {
    const needle = clientQuery.trim().toLowerCase();
    if (!needle) return items;
    return items.filter((cr) => {
      const name = (cr.user_name || "").toLowerCase();
      const email = (cr.user_email || "").toLowerCase();
      return name.includes(needle) || email.includes(needle);
    });
  }, [items, clientQuery]);

  return {
    items, statusFilter, setStatusFilter, loading,
    // iter87 — client filter (name/email search) exposed to the presentation layer
    clientQuery, setClientQuery, filteredItems,
    approving, setApproving, discountPct, setDiscountPct, adminNotes, setAdminNotes,
    rejecting, setRejecting, rejectReason, setRejectReason,
    pendingTotp, setPendingTotp, busy,
    openApprove, openReject, submitApprove, submitReject, load,
  };
}
