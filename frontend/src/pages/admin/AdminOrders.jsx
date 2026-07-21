import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Pagination } from "@/components/Pagination";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";
import AdminPageHeader from "@/components/AdminPageHeader";
import { toast } from "sonner";
import OrdersFilters from "./orders/OrdersFilters";
import OrdersTable from "./orders/OrdersTable";
import OrderDetailDialog from "./orders/OrderDetailDialog";

const PAGE_SIZE = 50;

const STATUS_KEYS = {
  pending: "admin.orders.statusPending",
  requires_double_approval: "admin.orders.statusDoubleApproval",
  approved: "admin.orders.statusApproved",
  completed: "admin.orders.statusCompleted",
  rejected: "admin.orders.statusRejected",
};

export default function AdminOrders() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { user: currentUser } = useAuth();
  const isAdmin = currentUser?.role === "admin";

  const [orders, setOrders] = useState([]);
  const [filter, setFilter] = useState("all");
  const [userQuery, setUserQuery] = useState("");
  const [userInput, setUserInput] = useState("");
  const [currencyFilter, setCurrencyFilter] = useState("all");
  const [currencies, setCurrencies] = useState([]);
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(null);
  const [note, setNote] = useState("");
  const [payoutProof, setPayoutProof] = useState("");
  const [payoutHash, setPayoutHash] = useState("");
  const [pendingStatus, setPendingStatus] = useState(null); // status waiting for 2FA (low-margin orders)

  useEffect(() => { setPage(0); }, [filter, userQuery, currencyFilter]);

  // Debounce user query input
  useEffect(() => {
    const id = setTimeout(() => setUserQuery(userInput.trim()), 300);
    return () => clearTimeout(id);
  }, [userInput]);

  // Load currencies once for the filter dropdown
  useEffect(() => {
    axios.get(`${API}/currencies`).then((r) => setCurrencies(r.data || [])).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit: PAGE_SIZE, offset: page * PAGE_SIZE };
      if (filter !== "all") params.status = filter;
      if (userQuery) params.user_q = userQuery;
      if (currencyFilter !== "all") params.currency = currencyFilter;
      const r = await axios.get(`${API}/admin/orders`, { params, withCredentials: true });
      setOrders(r.data);
      const totalHeader = Number(r.headers["x-total-count"]);
      setTotal(Number.isFinite(totalHeader) ? totalHeader : r.data.length);
    } catch (e) {
      toast.error(t("admin.orders.loadError"));
    } finally {
      setLoading(false);
    }
  }, [filter, page, userQuery, currencyFilter, t]);
  useEffect(() => { load(); }, [load]);

  const openOrder = (o) => {
    setOpen(o);
    setNote(o.admin_note || "");
    setPayoutProof(o.payout_proof_image || "");
    setPayoutHash(o.payout_tx_hash || "");
  };

  const handlePayoutUpload = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 4 * 1024 * 1024) { toast.error(t("admin.orders.toastMax4")); return; }
    const reader = new FileReader();
    reader.onload = () => setPayoutProof(reader.result);
    reader.readAsDataURL(f);
  };

  const updateStatus = async (status, totpCode = null) => {
    if (!open) return;
    const body = { status, admin_note: note };
    if (totpCode) body.totp_code = totpCode;
    // Only send payout fields when they changed — saves bandwidth on small status flips.
    if (payoutProof && payoutProof !== open.payout_proof_image) body.payout_proof_image = payoutProof;
    if (payoutHash && payoutHash !== open.payout_tx_hash) body.payout_tx_hash = payoutHash;
    try {
      await axios.put(`${API}/admin/orders/${open.id}/status`, body, { withCredentials: true });
      toast.success(t("admin.orders.toastUpdated", { status: t(STATUS_KEYS[status] || "admin.orders.statusApproved") }));
      setOpen(null); setNote(""); setPayoutProof(""); setPayoutHash(""); setPendingStatus(null); load();
    } catch (e) {
      const detail = e.response?.data?.detail;
      const code = typeof detail === "object" ? detail?.code : null;
      // Server requires step-up 2FA → open prompt
      if (code === "TOTP_CODE_REQUIRED" || code === "TOTP_INVALID") {
        if (code === "TOTP_INVALID") toast.error(detail?.message || t("admin.orders.toastInvalidTotp"));
        setPendingStatus(status);
        return;
      }
      if (!handleTotpError(e, navigate)) toast.error(detail?.message || detail || t("admin.common.genericError"));
    }
  };

  return (
    <div data-testid="admin-orders" className="space-y-4">
      <AdminPageHeader
        eyebrow={t("admin.orders.eyebrow")}
        title={t("admin.orders.title")}
        testid="admin-orders-header"
      />

      <OrdersFilters
        filter={filter}
        onFilterChange={setFilter}
        userInput={userInput}
        onUserInputChange={setUserInput}
        currencyFilter={currencyFilter}
        onCurrencyFilterChange={setCurrencyFilter}
        currencies={currencies}
        total={total}
      />

      <OrdersTable orders={orders} loading={loading} onOpenOrder={openOrder} />

      <Pagination
        page={page}
        total={total}
        pageSize={PAGE_SIZE}
        loading={loading}
        onPageChange={setPage}
        testidPrefix="orders-pagination"
      />

      <OrderDetailDialog
        open={open}
        isAdmin={isAdmin}
        note={note}
        onNoteChange={setNote}
        payoutProof={payoutProof}
        onPayoutProofChange={setPayoutProof}
        payoutHash={payoutHash}
        onPayoutHashChange={setPayoutHash}
        onClose={() => setOpen(null)}
        onUpdateStatus={updateStatus}
        onPayoutUpload={handlePayoutUpload}
      />

      <TotpPromptDialog
        open={!!pendingStatus}
        title={t("admin.orders.totpTitle")}
        description={t("admin.orders.totpDescription")}
        onConfirm={(code) => updateStatus(pendingStatus, code)}
        onCancel={() => setPendingStatus(null)}
      />
    </div>
  );
}
