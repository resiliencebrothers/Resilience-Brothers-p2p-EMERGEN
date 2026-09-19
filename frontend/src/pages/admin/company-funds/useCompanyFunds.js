/**
 * iter87/iter277 — useCompanyFunds
 *
 * Data hook for the admin Company Funds page. Owns:
 *   • The 4-way parallel load (funds, withdrawals, adjustments, currencies).
 *   • The unified «Depósitos y retiros» rows (withdrawals + adjustments).
 *   • The "new withdrawal" form state + invoice upload + submit.
 *   • The `pendingStatus` state that drives the TOTP prompt for both
 *     status-changes and the initial create flow (`submit: true` marker).
 *   • iter277 — pay-in-cash support: account options (with method) and the
 *     bill breakdown that travels with the "paid" transition.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { handleTotpError } from "@/components/TotpPromptDialog";
import { UNASSIGNED } from "@/components/FundAccountSelect";
import { useLiveRefresh } from "@/hooks/useLiveStream";

// iter159 — company funds move whenever balances/orders/withdrawals change.
const CF_LIVE_EVENTS = [
  "ledger_changed", "order_status_changed",
  "withdrawal_status_changed", "daily_autoclose",
];

const emptyForm = {
  amount: "", currency: "", beneficiary: "",
  concept: "", note: "", invoice_image: "",
};

export function useCompanyFunds() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const [funds, setFunds] = useState([]);
  const [items, setItems] = useState([]);
  const [adjustments, setAdjustments] = useState([]);
  const [currencies, setCurrencies] = useState([]);

  const [openCreate, setOpenCreate] = useState(false);
  const [openAdjustment, setOpenAdjustment] = useState(false);

  const [form, setForm] = useState(emptyForm);
  const [pendingSubmit, setPendingSubmit] = useState(false);
  const [pendingStatus, setPendingStatus] = useState(null);
  // iter194 — optional "paid from account" attribution when marking a
  // company withdrawal as paid (feeds the per-account fund breakdown).
  const [paidFromAccount, setPaidFromAccount] = useState(UNASSIGNED);
  // iter277 — cuentas (con método) del prompt de pago + desglose de billetes
  // cuando la cuenta elegida es de efectivo.
  const [payOptions, setPayOptions] = useState([]);
  const [payDenoms, setPayDenoms] = useState({});
  // iter88/iter277 — client-side filters for the unified table.
  const [statusFilter, setStatusFilter] = useState("all");
  const [tipoFilter, setTipoFilter] = useState("all");
  const [beneficiaryQuery, setBeneficiaryQuery] = useState("");
  // iter88 — CSV export dialog state.
  const [exportOpen, setExportOpen] = useState(false);
  // iter91 — separate flag for the investor closing PDF dialog.
  const [closingOpen, setClosingOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const [f, l, a, c] = await Promise.all([
        axios.get(`${API}/admin/company-funds`, { withCredentials: true }),
        axios.get(`${API}/admin/company-withdrawals`, { withCredentials: true }),
        axios.get(`${API}/admin/company-funds/adjustments`, { withCredentials: true }),
        axios.get(`${API}/currencies`, { withCredentials: true }),
      ]);
      setFunds(f.data);
      setItems(l.data);
      setAdjustments(a.data);
      setCurrencies(c.data);
    } catch {
      toast.error(t("admin.companyFunds.toastLoadError"));
    }
  }, [t]);
  useEffect(() => { load(); }, [load]);
  useLiveRefresh(load, CF_LIVE_EVENTS);

  // iter277 — opciones de cuenta (con método) para el prompt de pago.
  useEffect(() => {
    const cur = pendingStatus?.status === "paid" ? pendingStatus.currency : null;
    if (!cur) { setPayOptions([]); return undefined; }
    let alive = true;
    axios
      .get(`${API}/admin/fund-accounts/options`, {
        params: { currency: cur }, withCredentials: true,
      })
      .then((r) => { if (alive) setPayOptions(r.data || []); })
      .catch(() => { if (alive) setPayOptions([]); });
    return () => { alive = false; };
  }, [pendingStatus]);

  const payAccountMethod =
    payOptions.find((o) => o.id === paidFromAccount)?.method || null;

  const handleInvoiceUpload = useCallback((e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 4 * 1024 * 1024) {
      toast.error(t("admin.companyFunds.toastMax4"));
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setForm((f) => ({ ...f, invoice_image: reader.result }));
    reader.readAsDataURL(file);
  }, [t]);

  const submitCreate = useCallback(async (totpCode) => {
    setPendingSubmit(true);
    try {
      const body = {
        amount: parseFloat(form.amount),
        currency: form.currency,
        beneficiary: form.beneficiary,
        concept: form.concept,
        note: form.note,
        invoice_image: form.invoice_image,
        totp_code: totpCode,
      };
      await axios.post(`${API}/admin/company-withdrawals`, body, { withCredentials: true });
      toast.success(t("admin.companyFunds.toastCreated"));
      setOpenCreate(false);
      setForm(emptyForm);
      load();
    } catch (e) {
      if (!handleTotpError(e, navigate)) {
        toast.error(e.response?.data?.detail || t("admin.common.genericError"));
      }
    } finally {
      setPendingSubmit(false);
    }
  }, [form, load, navigate, t]);

  const requestStatus = useCallback((p) => {
    setPaidFromAccount(UNASSIGNED);
    setPayDenoms({});
    setPendingStatus(p);
  }, []);

  const confirmStatusWithTotp = useCallback(async (code) => {
    try {
      const body = { status: pendingStatus.status, totp_code: code };
      if (pendingStatus.status === "paid" && paidFromAccount !== UNASSIGNED) {
        body.paid_from_account_id = paidFromAccount;
        // iter277 — pago en efectivo: el desglose de billetes debe sumar el
        // monto exacto (validado también en el backend).
        if (payAccountMethod === "cash") {
          const clean = {};
          let total = 0;
          Object.entries(payDenoms).forEach(([d, q]) => {
            const n = parseInt(q, 10);
            if (n > 0) { clean[d] = n; total += (parseInt(d, 10) || 0) * n; }
          });
          const amount = Number(pendingStatus.amount || 0);
          if (Math.abs(total - amount) > 0.01) {
            toast.error(t("admin.companyFunds.payDenomsMismatch", {
              total: total.toLocaleString(),
              amount: amount.toLocaleString(),
              currency: pendingStatus.currency,
            }));
            return;
          }
          body.denominations = clean;
        }
      }
      await axios.put(
        `${API}/admin/company-withdrawals/${pendingStatus.id}/status`,
        body,
        { withCredentials: true },
      );
      toast.success(t("admin.companyFunds.toastStatus"));
      setPendingStatus(null);
      setPaidFromAccount(UNASSIGNED);
      setPayDenoms({});
      load();
    } catch (e) {
      if (!handleTotpError(e, navigate)) {
        toast.error(e.response?.data?.detail || t("admin.common.genericError"));
      }
    }
  }, [pendingStatus, paidFromAccount, payAccountMethod, payDenoms, navigate, load, t]);

  const scopeCurrencies = user?.allowed_currencies || [];
  const fundCurrencies = funds.map((f) => f.currency);
  const createCurrencies = !isAdmin && scopeCurrencies.length > 0
    ? fundCurrencies.filter((c) => scopeCurrencies.includes(c))
    : fundCurrencies;
  const adjustmentCurrencies = currencies.filter(
    (c) => isAdmin || !scopeCurrencies.length || scopeCurrencies.includes(c.code),
  );

  // iter277 — tabla unificada: retiros del fondo + depósitos manuales +
  // retiros históricos por ajuste (legado), ordenados por fecha.
  const mergedRows = useMemo(() => {
    const rows = [
      ...items.map((w) => ({
        kind: "withdrawal", key: `w-${w.id}`,
        created_at: w.created_at || "", data: w,
      })),
      ...adjustments.map((a) => ({
        kind: a.adjustment_type === "inflow" ? "deposit" : "adjust_out",
        key: `a-${a.id}`, created_at: a.created_at || "", data: a,
      })),
    ];
    rows.sort((x, y) => y.created_at.localeCompare(x.created_at));
    return rows;
  }, [items, adjustments]);

  const filteredItems = useMemo(() => {
    const needle = beneficiaryQuery.trim().toLowerCase();
    return mergedRows.filter((r) => {
      if (tipoFilter === "deposits" && r.kind !== "deposit") return false;
      if (tipoFilter === "withdrawals" && r.kind === "deposit") return false;
      if (statusFilter !== "all"
          && (r.kind !== "withdrawal" || r.data.status !== statusFilter)) {
        return false;
      }
      if (needle) {
        const who = (r.kind === "withdrawal"
          ? r.data.beneficiary : r.data.source_name) || "";
        if (!who.toLowerCase().includes(needle)) return false;
      }
      return true;
    });
  }, [mergedRows, tipoFilter, statusFilter, beneficiaryQuery]);

  return {
    isAdmin,
    funds, items, filteredItems, mergedRows, adjustments, currencies,
    statusFilter, setStatusFilter,
    tipoFilter, setTipoFilter,
    beneficiaryQuery, setBeneficiaryQuery,
    openCreate, setOpenCreate,
    openAdjustment, setOpenAdjustment,
    exportOpen, setExportOpen,
    closingOpen, setClosingOpen,
    form, setForm,
    pendingSubmit, pendingStatus, setPendingStatus,
    requestStatus, paidFromAccount, setPaidFromAccount,
    payOptions, payAccountMethod, payDenoms, setPayDenoms,
    createCurrencies, adjustmentCurrencies,
    load, handleInvoiceUpload, submitCreate, confirmStatusWithTotp,
  };
}
