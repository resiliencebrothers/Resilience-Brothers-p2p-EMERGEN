/**
 * iter87 — useCompanyFunds
 *
 * Data hook for the admin Company Funds page. Owns:
 *   • The 4-way parallel load (funds, withdrawals, adjustments, currencies).
 *   • The "new withdrawal" form state + invoice upload + submit.
 *   • The `pendingStatus` state that drives the TOTP prompt for both
 *     status-changes and the initial create flow (`submit: true` marker).
 *   • Adjustment history + manual-adjustment dialog open flags.
 *
 * Scope helpers `scopeCurrencies` / `createCurrencies` are computed here
 * so the presentation module doesn't reach into AuthContext directly.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { handleTotpError } from "@/components/TotpPromptDialog";

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
  const [openAdjustmentsHistory, setOpenAdjustmentsHistory] = useState(false);

  const [form, setForm] = useState(emptyForm);
  const [pendingSubmit, setPendingSubmit] = useState(false);
  const [pendingStatus, setPendingStatus] = useState(null);
  // iter88 — Client-side filters for the Fund withdrawals table.
  const [statusFilter, setStatusFilter] = useState("all");
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

  const confirmStatusWithTotp = useCallback(async (code) => {
    try {
      await axios.put(
        `${API}/admin/company-withdrawals/${pendingStatus.id}/status`,
        { status: pendingStatus.status, totp_code: code },
        { withCredentials: true },
      );
      toast.success(t("admin.companyFunds.toastStatus"));
      setPendingStatus(null);
      load();
    } catch (e) {
      if (!handleTotpError(e, navigate)) {
        toast.error(e.response?.data?.detail || t("admin.common.genericError"));
      }
    }
  }, [pendingStatus, navigate, load, t]);

  const scopeCurrencies = user?.allowed_currencies || [];
  const fundCurrencies = funds.map((f) => f.currency);
  const createCurrencies = !isAdmin && scopeCurrencies.length > 0
    ? fundCurrencies.filter((c) => scopeCurrencies.includes(c))
    : fundCurrencies;
  const adjustmentCurrencies = currencies.filter(
    (c) => isAdmin || !scopeCurrencies.length || scopeCurrencies.includes(c.code),
  );

  // iter88 — Filter the withdrawals table client-side by status + beneficiary
  // substring (case-insensitive). Runs over the already-loaded list.
  const filteredItems = useMemo(() => {
    const needle = beneficiaryQuery.trim().toLowerCase();
    return items.filter((w) => {
      if (statusFilter !== "all" && w.status !== statusFilter) return false;
      if (needle && !(w.beneficiary || "").toLowerCase().includes(needle)) return false;
      return true;
    });
  }, [items, statusFilter, beneficiaryQuery]);

  return {
    isAdmin,
    funds, items, filteredItems, adjustments, currencies,
    statusFilter, setStatusFilter,
    beneficiaryQuery, setBeneficiaryQuery,
    openCreate, setOpenCreate,
    openAdjustment, setOpenAdjustment,
    openAdjustmentsHistory, setOpenAdjustmentsHistory,
    exportOpen, setExportOpen,
    closingOpen, setClosingOpen,
    form, setForm,
    pendingSubmit, pendingStatus, setPendingStatus,
    createCurrencies, adjustmentCurrencies,
    load, handleInvoiceUpload, submitCreate, confirmStatusWithTotp,
  };
}
