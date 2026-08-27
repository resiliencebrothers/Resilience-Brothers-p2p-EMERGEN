import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";
import { UNASSIGNED } from "@/components/FundAccountSelect";
import AdminPageHeader from "@/components/AdminPageHeader";
import { toast } from "sonner";
import WithdrawalsFilters from "./withdrawals/WithdrawalsFilters";
import { useLiveRefresh } from "@/hooks/useLiveStream";
import WithdrawalsTable from "./withdrawals/WithdrawalsTable";
import RedemptionsTable from "./withdrawals/RedemptionsTable";
import WithdrawalDialog from "./withdrawals/WithdrawalDialog";

export default function AdminWithdrawals() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const statusLabel = (status, method) => {
    if (method === "cash") {
      return ({
        paid: t("admin.common.delivered"),
        approved: t("admin.common.inProgress"),
        pending: t("admin.common.pending"),
        rejected: t("admin.common.rejected"),
        cancelled: t("admin.common.cancelled"),
      })[status] || status;
    }
    return ({
      paid: t("admin.common.paid"),
      approved: t("admin.common.confirmed"),
      pending: t("admin.common.pending"),
      rejected: t("admin.common.rejected"),
      cancelled: t("admin.common.cancelled"),
    })[status] || status;
  };

  const [items, setItems] = useState([]);
  const [redemptions, setRedemptions] = useState([]);
  const [open, setOpen] = useState(null);
  const [note, setNote] = useState("");
  const [payoutProof, setPayoutProof] = useState("");
  const [payoutHash, setPayoutHash] = useState("");
  const [paidFromAccount, setPaidFromAccount] = useState(UNASSIGNED);
  const [pendingStatus, setPendingStatus] = useState(null);
  const [statusFilter, setStatusFilter] = useState("all");
  const [currencyFilter, setCurrencyFilter] = useState("all");
  const [currencies, setCurrencies] = useState([]);
  const [userInput, setUserInput] = useState("");
  const [userQuery, setUserQuery] = useState("");
  // iter198 — courier fee per km for cash withdrawals.
  const [courierKm, setCourierKm] = useState("");
  const [courierMuni, setCourierMuni] = useState("");
  const [pendingCourier, setPendingCourier] = useState(false);
  // iter198 — courier fee for marketplace redemptions ({id, km} or null).
  const [pendingRedFee, setPendingRedFee] = useState(null);

  useEffect(() => {
    const id = setTimeout(() => setUserQuery(userInput.trim()), 300);
    return () => clearTimeout(id);
  }, [userInput]);

  useEffect(() => {
    axios.get(`${API}/currencies`).then((r) => setCurrencies(r.data || [])).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    const params = {};
    if (statusFilter !== "all") params.status = statusFilter;
    if (currencyFilter !== "all") params.currency = currencyFilter;
    if (userQuery) params.user_q = userQuery;
    const [w, r] = await Promise.all([
      axios.get(`${API}/admin/withdrawals`, { params, withCredentials: true }),
      axios.get(`${API}/admin/redemptions`, { withCredentials: true }),
    ]);
    setItems(w.data);
    setRedemptions(r.data);
  }, [statusFilter, currencyFilter, userQuery]);
  useEffect(() => { load(); }, [load]);
  // iter159 — new/updated withdrawals appear without F5.
  useLiveRefresh(load, ["withdrawal_created", "withdrawal_status_changed"], 800);

  const openDialog = (w) => {
    setOpen(w);
    setNote(w.admin_note || "");
    setPayoutProof(w.payout_proof_image || "");
    setPayoutHash(w.payout_tx_hash || "");
    setPaidFromAccount(w.paid_from_account_id || UNASSIGNED);
    setCourierKm(
      Number(w.courier_km || 0) > 0
        ? String(w.courier_km)
        : Number(w.courier_quote_km || 0) > 0
          ? String(w.courier_quote_km)
          : ""
    );
  };

  const handleProofUpload = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 4 * 1024 * 1024) { toast.error(t("admin.withdrawals.toastMax4")); return; }
    const reader = new FileReader();
    reader.onload = () => setPayoutProof(reader.result);
    reader.readAsDataURL(f);
  };

  const confirmWithTotp = async (code) => {
    try {
      const body = { status: pendingStatus, admin_note: note, totp_code: code };
      if (payoutProof && payoutProof !== open.payout_proof_image) body.payout_proof_image = payoutProof;
      if (payoutHash && payoutHash !== open.payout_tx_hash) body.payout_tx_hash = payoutHash;
      if (pendingStatus === "paid" && paidFromAccount !== UNASSIGNED) body.paid_from_account_id = paidFromAccount;
      await axios.put(`${API}/admin/withdrawals/${open.id}/status`, body, { withCredentials: true });
      toast.success(t("admin.withdrawals.toastUpdated"));
      setPendingStatus(null); setOpen(null); setNote("");
      setPayoutProof(""); setPayoutHash(""); setPaidFromAccount(UNASSIGNED);
      load();
    } catch (e) {
      if (!handleTotpError(e, navigate)) toast.error(e.response?.data?.detail || t("admin.withdrawals.toastGenericError"));
    }
  };

  const askChange = (status) => {
    if (status === "paid" && open?.method === "transfer" && !payoutProof) {
      toast.error(t("admin.withdrawals.askProofTransfer"));
      return;
    }
    if (status === "paid" && open?.method === "crypto" && !payoutProof && !payoutHash) {
      toast.error(t("admin.withdrawals.askProofCrypto"));
      return;
    }
    setPendingStatus(status);
  };

  const confirmCourierWithTotp = async (code) => {
    try {
      // iter211 — si el staff eligió municipio, se cobra su tarifa fija.
      const body = courierMuni
        ? { municipality: courierMuni, totp_code: code }
        : { km: parseFloat(courierKm || "0") || 0, totp_code: code };
      const r = await axios.post(
        `${API}/admin/withdrawals/${open.id}/courier-fee`,
        body,
        { withCredentials: true },
      );
      toast.success(t("admin.withdrawals.courier.toastApplied"));
      setPendingCourier(false);
      setCourierMuni("");
      setOpen(r.data);
      load();
    } catch (e) {
      if (!handleTotpError(e, navigate)) {
        const d = e.response?.data?.detail;
        toast.error(typeof d === "string" ? d : d?.message || t("admin.withdrawals.toastGenericError"));
      }
    }
  };

  const confirmRedFeeWithTotp = async (code) => {
    try {
      await axios.post(
        `${API}/admin/redemptions/${pendingRedFee.id}/courier-fee`,
        { km: pendingRedFee.km, totp_code: code },
        { withCredentials: true },
      );
      toast.success(t("admin.withdrawals.courier.toastApplied"));
      setPendingRedFee(null);
      load();
    } catch (e) {
      if (!handleTotpError(e, navigate)) {
        const d = e.response?.data?.detail;
        toast.error(typeof d === "string" ? d : d?.message || t("admin.withdrawals.toastGenericError"));
      }
    }
  };

  const createDelivery = async (kind, refId) => {
    try {
      await axios.post(`${API}/admin/deliveries`, { kind, ref_id: refId },
        { withCredentials: true });
      toast.success(t("admin.withdrawals.deliveryCreated"));
    } catch (e) {
      const d = e.response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Error");
    }
  };

  const updateRedemption = async (id, status) => {
    await axios.put(`${API}/admin/redemptions/${id}/status`, { status }, { withCredentials: true });
    toast.success(t("admin.withdrawals.toastRedemption"));
    load();
  };

  return (
    <div data-testid="admin-withdrawals" className="space-y-8">
      <AdminPageHeader
        eyebrow={t("admin.withdrawals.eyebrow")}
        title={t("admin.withdrawals.title")}
        testid="admin-withdrawals-header"
      />

      <div>
        <h2 className="font-display text-xl mb-3">{t("admin.withdrawals.sectionWithdrawals")}</h2>
        <WithdrawalsFilters
          userInput={userInput}
          onUserInputChange={setUserInput}
          statusFilter={statusFilter}
          onStatusFilterChange={setStatusFilter}
          currencyFilter={currencyFilter}
          onCurrencyFilterChange={setCurrencyFilter}
          currencies={currencies}
          resultCount={items.length}
        />
        <WithdrawalsTable items={items} statusLabel={statusLabel} onManage={openDialog} />
      </div>

      <div>
        <h2 className="font-display text-xl mb-3">{t("admin.withdrawals.sectionRedemptions")}</h2>
        <RedemptionsTable
          redemptions={redemptions}
          onUpdateStatus={updateRedemption}
          onSetCourierFee={(id, km) => setPendingRedFee({ id, km })}
          onCreateDelivery={(r) => createDelivery("redemption", r.id)}
        />
      </div>

      <WithdrawalDialog
        open={open}
        onClose={() => setOpen(null)}
        note={note}
        onNoteChange={setNote}
        payoutProof={payoutProof}
        onPayoutProofChange={setPayoutProof}
        payoutHash={payoutHash}
        onPayoutHashChange={setPayoutHash}
        paidFromAccount={paidFromAccount}
        onPaidFromAccountChange={setPaidFromAccount}
        statusLabel={statusLabel}
        onProofUpload={handleProofUpload}
        onAskChange={askChange}
        courierKm={courierKm}
        onCourierKmChange={setCourierKm}
        courierMuni={courierMuni}
        onCourierMuniChange={setCourierMuni}
        onApplyCourier={() => setPendingCourier(true)}
        onCreateDelivery={createDelivery}
      />

      <TotpPromptDialog
        open={!!pendingStatus}
        title={t("admin.withdrawals.totpTitle", { status: pendingStatus ?? "" })}
        description={t("admin.withdrawals.totpDescription")}
        onConfirm={confirmWithTotp}
        onCancel={() => setPendingStatus(null)}
      />

      <TotpPromptDialog
        open={pendingCourier}
        title={t("admin.withdrawals.courier.totpTitle")}
        description={t("admin.withdrawals.totpDescription")}
        onConfirm={confirmCourierWithTotp}
        onCancel={() => setPendingCourier(false)}
      />

      <TotpPromptDialog
        open={!!pendingRedFee}
        title={t("admin.withdrawals.courier.totpTitle")}
        description={t("admin.withdrawals.totpDescription")}
        onConfirm={confirmRedFeeWithTotp}
        onCancel={() => setPendingRedFee(null)}
      />
    </div>
  );
}
