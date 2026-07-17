import { useEffect, useRef, useState, useCallback } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";
import CopyableText from "@/components/CopyableText";
import CashDetailsTable, { parseCashDetails } from "@/components/CashDetailsTable";
import ExplorerLink from "@/components/ExplorerLink";
import AdminPageHeader from "@/components/AdminPageHeader";
import { validateCryptoHash, findNetwork } from "@/services/cryptoValidators";
import { toast } from "sonner";
import { Search } from "lucide-react";

const STATUS_STYLES = {
  paid: "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  approved: "bg-[#8B5CF6]/10 text-[#8B5CF6] border-[#8B5CF6]/30",
  rejected: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30",
  pending: "bg-neutral-700/20 text-neutral-400 border-neutral-700/40",
};

export default function AdminWithdrawals() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const STATUS_LABEL = (status, method) => {
    if (method === "cash") {
      return ({
        paid: t("admin.common.delivered"),
        approved: t("admin.common.inProgress"),
        pending: t("admin.common.pending"),
        rejected: t("admin.common.rejected"),
      })[status] || status;
    }
    return ({
      paid: t("admin.common.paid"),
      approved: t("admin.common.confirmed"),
      pending: t("admin.common.pending"),
      rejected: t("admin.common.rejected"),
    })[status] || status;
  };
  const [items, setItems] = useState([]);
  const [redemptions, setRedemptions] = useState([]);
  const [open, setOpen] = useState(null);
  const [note, setNote] = useState("");
  const [payoutProof, setPayoutProof] = useState(""); // base64 preview
  const [payoutHash, setPayoutHash] = useState("");
  const fileRef = useRef(null);
  const [pendingStatus, setPendingStatus] = useState(null); // status awaiting 2FA
  const [statusFilter, setStatusFilter] = useState("all");
  const [currencyFilter, setCurrencyFilter] = useState("all");
  const [currencies, setCurrencies] = useState([]);
  const [userInput, setUserInput] = useState("");
  const [userQuery, setUserQuery] = useState("");

  // Debounced user query
  useEffect(() => {
    const t = setTimeout(() => setUserQuery(userInput.trim()), 300);
    return () => clearTimeout(t);
  }, [userInput]);

  // Load currencies once
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
    setItems(w.data); setRedemptions(r.data);
  }, [statusFilter, currencyFilter, userQuery]);
  useEffect(() => { load(); }, [load]);

  const openDialog = (w) => {
    setOpen(w);
    setNote(w.admin_note || "");
    setPayoutProof(w.payout_proof_image || "");
    setPayoutHash(w.payout_tx_hash || "");
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
      await axios.put(
        `${API}/admin/withdrawals/${open.id}/status`,
        body,
        { withCredentials: true }
      );
      toast.success(t("admin.withdrawals.toastUpdated"));
      setPendingStatus(null); setOpen(null); setNote("");
      setPayoutProof(""); setPayoutHash("");
      load();
    } catch (e) {
      if (!handleTotpError(e, navigate)) toast.error(e.response?.data?.detail || t("admin.withdrawals.toastGenericError"));
    }
  };

  const askChange = (status) => {
    // For "paid" require proof up front (UX hint — backend also enforces)
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

  const updateR = async (id, status) => {
    await axios.put(`${API}/admin/redemptions/${id}/status`, { status }, { withCredentials: true });
    toast.success(t("admin.withdrawals.toastRedemption")); load();
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
        <div className="flex flex-wrap gap-2 mb-3 items-end">
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500 pointer-events-none" />
            <Input
              data-testid="withdrawals-user-search"
              value={userInput}
              onChange={(e) => setUserInput(e.target.value)}
              placeholder={t("admin.withdrawals.searchPlaceholder")}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-9 w-60 pl-9 text-xs"
            />
          </div>
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger data-testid="withdrawals-status-filter" className="rounded-none bg-[#0a0a0a] border-white/10 h-9 w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
              <SelectItem value="all">{t("admin.withdrawals.allStatuses")}</SelectItem>
              <SelectItem value="pending">{t("admin.common.pending")}</SelectItem>
              <SelectItem value="approved">{t("admin.withdrawals.statusConfirmedInProgress")}</SelectItem>
              <SelectItem value="paid">{t("admin.withdrawals.statusPaidDelivered")}</SelectItem>
              <SelectItem value="rejected">{t("admin.common.rejected")}</SelectItem>
            </SelectContent>
          </Select>
          <Select value={currencyFilter} onValueChange={setCurrencyFilter}>
            <SelectTrigger data-testid="withdrawals-currency-filter" className="rounded-none bg-[#0a0a0a] border-white/10 h-9 w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
              <SelectItem value="all">{t("admin.withdrawals.allCurrencies")}</SelectItem>
              {currencies.map((c) => (
                <SelectItem key={c.id || c.code} value={c.code}>{c.code}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          {(userInput || statusFilter !== "all" || currencyFilter !== "all") && (
            <button
              data-testid="withdrawals-clear-filters"
              onClick={() => { setUserInput(""); setStatusFilter("all"); setCurrencyFilter("all"); }}
              className="text-xs text-neutral-500 hover:text-[#8B5CF6] underline underline-offset-4 h-9"
            >
              {t("admin.common.clear")}
            </button>
          )}
          <div className="ml-auto text-xs text-neutral-500" data-testid="withdrawals-result-count">
            {items.length} {items.length === 1 ? t("admin.withdrawals.resultOne") : t("admin.withdrawals.resultMany")}
          </div>
        </div>
        <div className="tactile-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="border-b border-white/10 bg-[#0a0a0a]">
              <tr className="text-left">
                <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colUser")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colAmount")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colCurrency")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colMethod")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colDetails")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colStatus")}</th>
                <th className="px-3 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && <tr><td colSpan="7" className="text-center text-neutral-500 py-6">{t("admin.withdrawals.empty")}</td></tr>}
              {items.map(w => (
                <tr key={w.id} className="border-b border-white/5">
                  <td className="px-3 py-3">{w.user_name}</td>
                  <td className="px-3 py-3 font-mono text-[#8B5CF6]">{w.amount_usd}</td>
                  <td className="px-3 py-3 font-mono">{w.currency || "USD"}</td>
                  <td className="px-3 py-3">
                    <span>{w.method}</span>
                    {w.method === "crypto" && w.crypto_network && (
                      <span
                        data-testid={`withdrawal-network-${w.id}`}
                        className="ml-2 inline-flex items-center px-1.5 py-0.5 text-[0.6rem] uppercase tracking-wider bg-[#8B5CF6]/10 text-[#8B5CF6] border border-[#8B5CF6]/30 font-mono"
                      >
                        {w.crypto_network}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-3 text-xs max-w-xs truncate">{w.details}</td>
                  <td className="px-3 py-3">
                    <span className={`text-xs uppercase tracking-wider border px-2 py-1 ${STATUS_STYLES[w.status] || STATUS_STYLES.pending}`}>
                      {STATUS_LABEL(w.status, w.method)}
                    </span>
                  </td>
                  <td className="px-3 py-3">
                    <Button size="sm" onClick={() => openDialog(w)} className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none h-8" data-testid={`manage-withdrawal-${w.id}`}>{t("admin.withdrawals.manage")}</Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <h2 className="font-display text-xl mb-3">{t("admin.withdrawals.sectionRedemptions")}</h2>
        <div className="tactile-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="border-b border-white/10 bg-[#0a0a0a]">
              <tr className="text-left">
                <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colUser")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colProduct")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colQty")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colTotal")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colAddress")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colStatus")}</th>
                <th className="px-3 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {redemptions.length === 0 && <tr><td colSpan="7" className="text-center text-neutral-500 py-6">{t("admin.withdrawals.emptyRedemptions")}</td></tr>}
              {redemptions.map(r => (
                <tr key={r.id} className="border-b border-white/5">
                  <td className="px-3 py-3">{r.user_name}</td>
                  <td className="px-3 py-3">{r.product_name}</td>
                  <td className="px-3 py-3 font-mono">{r.quantity}</td>
                  <td className="px-3 py-3 font-mono text-[#8B5CF6]">${r.total_usd}</td>
                  <td className="px-3 py-3 text-xs max-w-xs truncate">{r.delivery_address}</td>
                  <td className="px-3 py-3 text-xs uppercase">{r.status}</td>
                  <td className="px-3 py-3">
                    <div className="flex gap-1">
                      <Button size="sm" onClick={() => updateR(r.id, "approved")} className="bg-[#22C55E] text-black rounded-none h-7 text-xs">✓</Button>
                      <Button size="sm" onClick={() => updateR(r.id, "delivered")} className="bg-[#8B5CF6] text-white rounded-none h-7 text-xs">⇪</Button>
                      <Button size="sm" onClick={() => updateR(r.id, "rejected")} className="bg-[#EF4444] text-white rounded-none h-7 text-xs">✕</Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <Dialog open={!!open} onOpenChange={() => setOpen(null)}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-display">{t("admin.withdrawals.dialogTitle", { id: open?.id?.slice(0,8) })}</DialogTitle>
            <DialogDescription className="text-neutral-500 text-xs">
              {t("admin.withdrawals.dialogDesc")}
            </DialogDescription>
          </DialogHeader>
          {open && (
            <div className="space-y-4">
              <div className="font-mono text-sm space-y-1">
                <div><span className="text-neutral-500">{t("admin.withdrawals.fClient")}</span> {open.user_name}</div>
                <div><span className="text-neutral-500">{t("admin.withdrawals.fAmount")}</span> {open.amount_usd} {open.currency || "USD"}</div>
                <div><span className="text-neutral-500">{t("admin.withdrawals.fMethod")}</span> {open.method}</div>
                {open.method === "crypto" && open.crypto_network && (
                  <div data-testid="withdrawal-modal-network">
                    <span className="text-neutral-500">{t("admin.withdrawals.fNetwork")}</span>{" "}
                    <span className="inline-flex items-center px-1.5 py-0.5 text-[0.7rem] uppercase tracking-wider bg-[#8B5CF6]/10 text-[#8B5CF6] border border-[#8B5CF6]/30 font-mono ml-1">
                      {open.crypto_network}
                    </span>
                  </div>
                )}
                <div className="flex items-start gap-2 flex-wrap">
                  <span className="text-neutral-500 flex-shrink-0">
                    {open.method === "crypto" ? t("admin.withdrawals.fWallet") : t("admin.withdrawals.fDetails")}
                  </span>
                  {open.method === "cash" && parseCashDetails(open.details) ? (
                    <div className="flex-1 min-w-0 space-y-2">
                      <CashDetailsTable details={open.details} />
                      <CopyableText
                        value={open.details}
                        label={t("admin.withdrawals.copyFullBlock")}
                        toastMessage={t("admin.withdrawals.copyDetailsToast")}
                        testid="withdrawal-copy-details"
                      />
                    </div>
                  ) : (
                    <CopyableText
                      value={open.details}
                      label={open.method === "crypto" ? t("admin.withdrawals.copyWallet") : t("admin.withdrawals.copyDetails")}
                      toastMessage={open.method === "crypto" ? t("admin.withdrawals.copyWalletToast") : t("admin.withdrawals.copyDetailsToast")}
                      testid="withdrawal-copy-details"
                    />
                  )}
                </div>
                <div className="flex items-start gap-2 flex-wrap">
                  <span className="text-neutral-500 flex-shrink-0">{t("admin.withdrawals.fBeneficiary")}</span>
                  {open.beneficiary_name ? (
                    <CopyableText
                      value={open.beneficiary_name}
                      label={t("admin.withdrawals.copyBeneficiary")}
                      toastMessage={t("admin.withdrawals.copyBeneficiaryToast")}
                      testid="withdrawal-copy-beneficiary"
                      monospace={false}
                    />
                  ) : (
                    <span>—</span>
                  )}
                </div>
                <div><span className="text-neutral-500">{t("admin.withdrawals.fStatus")}</span> <span className="uppercase tracking-wider">{STATUS_LABEL(open.status, open.method)}</span></div>
              </div>
              <Textarea value={note} onChange={e => setNote(e.target.value)} placeholder={t("admin.withdrawals.notePlaceholder")} rows={2} className="rounded-none bg-[#0a0a0a] border-white/10" />

              <div className="border border-white/10 p-3 space-y-3 bg-[#0a0a0a]/50">
                <div className="micro-label text-[#8B5CF6]">
                  {open.method === "crypto"
                    ? t("admin.withdrawals.payoutTxHash")
                    : t("admin.withdrawals.payoutEvidence")}
                </div>
                {open.method === "crypto" ? (
                  <div>
                    <Input
                      data-testid="payout-tx-hash"
                      value={payoutHash}
                      onChange={(e) => setPayoutHash(e.target.value)}
                      placeholder={
                        open.crypto_network
                          ? findNetwork(open.crypto_network).hashPlaceholder
                          : t("admin.withdrawals.hashPlaceholder")
                      }
                      className="rounded-none bg-[#0a0a0a] border-white/10 h-11 font-mono text-xs"
                    />
                    {payoutHash && open.crypto_network && (
                      validateCryptoHash(payoutHash, open.crypto_network) ? (
                        <p
                          data-testid="payout-hash-match-ok"
                          className="text-[0.7rem] text-[#22C55E] mt-1.5 flex items-center gap-1.5"
                        >
                          <span aria-hidden>✓</span>
                          <span>{t("withdraw.networkMatchOk")} <strong>{findNetwork(open.crypto_network).label}</strong></span>
                        </p>
                      ) : (
                        <p
                          data-testid="payout-hash-mismatch"
                          className="text-[0.7rem] text-[#EF4444] mt-1.5 flex items-start gap-1.5 leading-relaxed"
                        >
                          <span aria-hidden className="mt-0.5">⚠</span>
                          <span>
                            <strong>{t("withdraw.networkMismatch")} {findNetwork(open.crypto_network).label}</strong>. {t("withdraw.networkMismatchHint")}
                          </span>
                        </p>
                      )
                    )}
                    {open.payout_tx_hash && (
                      <div className="mt-2 flex items-center flex-wrap gap-2">
                        <ExplorerLink
                          network={open.crypto_network}
                          txHash={open.payout_tx_hash}
                          testid="admin-withdrawal-explorer-link"
                        />
                        <span className="text-[0.65rem] text-neutral-500">
                          {t("admin.withdrawals.explorerHint")}
                        </span>
                      </div>
                    )}
                    <p className="text-[0.65rem] text-neutral-500 mt-2 leading-relaxed">
                      {t("admin.withdrawals.hashHelper")}
                    </p>
                  </div>
                ) : (
                  <div>
                    <label className="micro-label text-neutral-500">
                      {t("admin.withdrawals.captureLabel")}
                    </label>
                    <input
                      ref={fileRef}
                      data-testid="payout-proof-input"
                      type="file"
                      accept="image/*"
                      onChange={handleProofUpload}
                      className="block mt-1 text-xs text-neutral-400"
                    />
                    {payoutProof && (
                      <div className="mt-2">
                        <img src={payoutProof} alt="proof" className="max-h-40 border border-white/10" data-testid="payout-proof-preview" />
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div className="grid grid-cols-3 gap-2">
                <Button data-testid="withdrawal-approve" onClick={() => askChange("approved")} className="bg-[#22C55E] text-black rounded-none">
                  {open.method === "cash" ? t("admin.withdrawals.approveInProgress") : t("admin.withdrawals.approveConfirm")}
                </Button>
                <Button data-testid="withdrawal-pay" onClick={() => askChange("paid")} className="bg-[#8B5CF6] text-white rounded-none">
                  {open.method === "cash" ? t("admin.withdrawals.payDelivered") : t("admin.withdrawals.payPaid")}
                </Button>
                <Button data-testid="withdrawal-reject" onClick={() => askChange("rejected")} className="bg-[#EF4444] text-white rounded-none">{t("admin.withdrawals.reject")}</Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <TotpPromptDialog
        open={!!pendingStatus}
        title={t("admin.withdrawals.totpTitle", { status: pendingStatus ?? "" })}
        description={t("admin.withdrawals.totpDescription")}
        onConfirm={confirmWithTotp}
        onCancel={() => setPendingStatus(null)}
      />
    </div>
  );
}
