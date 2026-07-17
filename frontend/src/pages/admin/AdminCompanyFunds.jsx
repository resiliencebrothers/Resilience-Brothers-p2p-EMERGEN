import { useEffect, useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { useTranslation, Trans } from "react-i18next";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";
import AdminPageHeader from "@/components/AdminPageHeader";
import { Wallet, Plus, FileImage, SlidersHorizontal, HandCoins } from "lucide-react";
import { toast } from "sonner";
import AdjustmentDialog from "./company-funds/AdjustmentDialog";
import AdjustmentsHistoryDialog from "./company-funds/AdjustmentsHistoryDialog";

const STATUS_STYLES = {
  paid: "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  approved: "bg-[#8B5CF6]/10 text-[#8B5CF6] border-[#8B5CF6]/30",
  rejected: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30",
  pending: "bg-neutral-700/20 text-neutral-400 border-neutral-700/40",
};

export default function AdminCompanyFunds() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const STATUS_LABELS = {
    pending: t("admin.companyFunds.statusPending"),
    approved: t("admin.companyFunds.statusApproved"),
    paid: t("admin.companyFunds.statusPaid"),
    rejected: t("admin.companyFunds.statusRejected"),
  };
  const [funds, setFunds] = useState([]);
  const [items, setItems] = useState([]);
  const [adjustments, setAdjustments] = useState([]);
  const [currencies, setCurrencies] = useState([]);
  const [openCreate, setOpenCreate] = useState(false);
  const [openAdjustment, setOpenAdjustment] = useState(false);
  const [openAdjustmentsHistory, setOpenAdjustmentsHistory] = useState(false);
  const [form, setForm] = useState({ amount: "", currency: "", beneficiary: "", concept: "", note: "", invoice_image: "" });
  const [pendingSubmit, setPendingSubmit] = useState(false);
  const [pendingStatus, setPendingStatus] = useState(null);

  const load = async () => {
    try {
      const [f, l, a, c] = await Promise.all([
        axios.get(`${API}/admin/company-funds`, { withCredentials: true }),
        axios.get(`${API}/admin/company-withdrawals`, { withCredentials: true }),
        axios.get(`${API}/admin/company-funds/adjustments`, { withCredentials: true }),
        axios.get(`${API}/currencies`, { withCredentials: true }),
      ]);
      setFunds(f.data); setItems(l.data); setAdjustments(a.data); setCurrencies(c.data);
    } catch (e) { toast.error(t("admin.companyFunds.toastLoadError")); }
  };
  useEffect(() => { load(); }, []);

  const handleInvoiceUpload = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 4 * 1024 * 1024) return toast.error(t("admin.companyFunds.toastMax4"));
    const reader = new FileReader();
    reader.onload = () => setForm((f) => ({ ...f, invoice_image: reader.result }));
    reader.readAsDataURL(file);
  };

  const submitCreate = async (totpCode) => {
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
      setForm({ amount: "", currency: "", beneficiary: "", concept: "", note: "", invoice_image: "" });
      load();
    } catch (e) {
      if (!handleTotpError(e, navigate)) toast.error(e.response?.data?.detail || t("admin.common.genericError"));
    } finally { setPendingSubmit(false); }
  };

  const confirmStatusWithTotp = async (code) => {
    try {
      await axios.put(
        `${API}/admin/company-withdrawals/${pendingStatus.id}/status`,
        { status: pendingStatus.status, totp_code: code },
        { withCredentials: true }
      );
      toast.success(t("admin.companyFunds.toastStatus"));
      setPendingStatus(null); load();
    } catch (e) {
      if (!handleTotpError(e, navigate)) toast.error(e.response?.data?.detail || t("admin.common.genericError"));
    }
  };

  const scopeCurrencies = (user?.allowed_currencies || []);
  const fundCurrencies = funds.map(f => f.currency);
  const createCurrencies = !isAdmin && scopeCurrencies.length > 0
    ? fundCurrencies.filter(c => scopeCurrencies.includes(c))
    : fundCurrencies;

  return (
    <div data-testid="admin-company-funds" className="space-y-8">
      <AdminPageHeader
        eyebrow={t("admin.companyFunds.eyebrow")}
        title={t("admin.companyFunds.title")}
        subtitle={t("admin.companyFunds.subtitle")}
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-testid="fund-cards">
        {funds.length === 0 && <div className="col-span-full text-neutral-500 text-sm">{t("admin.companyFunds.empty")}</div>}
        {funds.map(f => (
          <div key={f.currency} className="tactile-card p-5" data-testid={`fund-${f.currency}`}>
            <Wallet className="w-4 h-4 text-[#8B5CF6] mb-2" />
            <div className="micro-label text-neutral-500">{f.currency}</div>
            <div
              className={`font-display text-2xl mt-1 ${
                f.balance >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"
              }`}
              data-testid={`fund-balance-${f.currency}`}
            >
              {f.balance.toLocaleString(undefined, { maximumFractionDigits: 2 })}
            </div>
            <div className="text-[0.65rem] text-neutral-500 mt-3 space-y-0.5 font-mono">
              <div>+ {t("admin.companyFunds.orders")}: {f.inflow.toLocaleString(undefined, { maximumFractionDigits: 2 })}</div>
              {f.manual_inflow > 0 && (
                <div className="text-[#22C55E]/80" data-testid={`fund-manual-in-${f.currency}`}>
                  + {t("admin.companyFunds.ownContribution")}: {f.manual_inflow.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </div>
              )}
              {(f.outflow_orders ?? 0) > 0 && (
                <div className="text-[#EF4444]/80" data-testid={`fund-order-out-${f.currency}`}>
                  − {t("admin.companyFunds.deliveredToClients")}: {f.outflow_orders.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </div>
              )}
              {(f.outflow_clients_vip ?? 0) > 0 && (
                <div data-testid={`fund-vip-out-${f.currency}`}>− {t("admin.companyFunds.vipWithdrawals")}: {f.outflow_clients_vip.toLocaleString(undefined, { maximumFractionDigits: 2 })}</div>
              )}
              {(f.outflow_clients_normal ?? 0) > 0 && (
                <div data-testid={`fund-normal-out-${f.currency}`}>− {t("admin.companyFunds.normalWithdrawals")}: {f.outflow_clients_normal.toLocaleString(undefined, { maximumFractionDigits: 2 })}</div>
              )}
              {(f.outflow_clients_vip == null && f.outflow_clients_normal == null && (f.outflow_clients ?? 0) > 0) && (
                <div>− {t("admin.companyFunds.clientWithdrawals")}: {f.outflow_clients.toLocaleString(undefined, { maximumFractionDigits: 2 })}</div>
              )}
              <div>− {t("admin.companyFunds.companyOutflow")}: {f.outflow_company.toLocaleString(undefined, { maximumFractionDigits: 2 })}</div>
              {f.manual_outflow > 0 && (
                <div className="text-[#EF4444]/80" data-testid={`fund-manual-out-${f.currency}`}>
                  − {t("admin.companyFunds.ownOutflow")}: {f.manual_outflow.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap justify-between items-center gap-3">
        <h2 className="font-display text-xl">{t("admin.companyFunds.sectionTitle")}</h2>
        <div className="flex gap-2 flex-wrap">
          <Button
            data-testid="open-adjustments-history"
            variant="outline"
            onClick={() => setOpenAdjustmentsHistory(true)}
            className="rounded-none border-white/20 hover:bg-white/5"
          >
            <HandCoins className="w-4 h-4 mr-1" />
            {t("admin.companyFunds.deposits")}
            {adjustments.length > 0 && (
              <span
                className="ml-2 text-[0.65rem] font-mono text-[#8B5CF6] bg-[#8B5CF6]/10 px-1.5 py-0.5"
                data-testid="adjustments-history-count"
              >
                {adjustments.length}
              </span>
            )}
          </Button>
          <Button
            data-testid="open-adjustment-dialog"
            variant="outline"
            onClick={() => setOpenAdjustment(true)}
            disabled={currencies.length === 0}
            className="rounded-none border-white/20 hover:bg-white/5"
          >
            <SlidersHorizontal className="w-4 h-4 mr-1" /> {t("admin.companyFunds.manualAdjustment")}
          </Button>
          <Button
            data-testid="create-company-withdrawal"
            onClick={() => setOpenCreate(true)}
            disabled={createCurrencies.length === 0}
            className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none"
          >
            <Plus className="w-4 h-4 mr-1" /> {t("admin.companyFunds.newWithdrawal")}
          </Button>
        </div>
      </div>

      <div className="tactile-card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-[#0a0a0a] border-b border-white/10">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.companyFunds.colAmount")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.companyFunds.colCurrency")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.companyFunds.colBeneficiary")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.companyFunds.colConcept")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.companyFunds.colAuthorized")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.companyFunds.colInvoice")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.companyFunds.colStatus")}</th>
              {isAdmin && <th className="px-4 py-3"></th>}
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan="8" className="text-center text-neutral-500 py-8">{t("admin.companyFunds.emptyWithdrawals")}</td></tr>}
            {items.map(w => (
              <tr key={w.id} className="border-b border-white/5" data-testid={`company-withdrawal-row-${w.id}`}>
                <td className="px-4 py-3 font-mono text-[#8B5CF6]">{w.amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                <td className="px-4 py-3 font-mono">{w.currency}</td>
                <td className="px-4 py-3 text-xs max-w-xs truncate">{w.beneficiary}</td>
                <td className="px-4 py-3 text-xs text-neutral-400 max-w-xs truncate">{w.concept || "—"}</td>
                <td className="px-4 py-3 text-xs">{w.authorized_by_name}</td>
                <td className="px-4 py-3">
                  {w.invoice_image ? (
                    <a href={w.invoice_image} target="_blank" rel="noreferrer" className="text-[#8B5CF6] hover:underline text-xs inline-flex items-center gap-1">
                      <FileImage className="w-3 h-3" /> {t("admin.companyFunds.seeInvoice")}
                    </a>
                  ) : <span className="text-neutral-600 text-xs">—</span>}
                </td>
                <td className="px-4 py-3">
                  <span className={`text-xs uppercase border px-2 py-1 ${STATUS_STYLES[w.status]}`}>
                    {STATUS_LABELS[w.status]}
                  </span>
                </td>
                {isAdmin && (
                  <td className="px-4 py-3">
                    {w.status !== "paid" && w.status !== "rejected" && (
                      <div className="flex gap-1">
                        <Button size="sm" onClick={() => setPendingStatus({ id: w.id, status: "approved" })} className="bg-[#8B5CF6] text-white rounded-none h-7 text-xs">{t("admin.companyFunds.approve")}</Button>
                        <Button size="sm" onClick={() => setPendingStatus({ id: w.id, status: "paid" })} className="bg-[#22C55E] text-black rounded-none h-7 text-xs">{t("admin.companyFunds.paid")}</Button>
                        <Button size="sm" onClick={() => setPendingStatus({ id: w.id, status: "rejected" })} className="bg-[#EF4444] text-white rounded-none h-7 text-xs">×</Button>
                      </div>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={openCreate} onOpenChange={setOpenCreate}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-display">{t("admin.companyFunds.dialogNewTitle")}</DialogTitle>
            <DialogDescription className="text-neutral-500 text-xs">
              <Trans
                i18nKey="admin.companyFunds.dialogNewSub"
                values={{ name: user?.name }}
                components={{ 1: <span className="font-mono text-white" /> }}
              />
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="micro-label text-neutral-500">{t("admin.companyFunds.currency")}</Label>
                <Select value={form.currency} onValueChange={(v) => setForm({ ...form, currency: v })}>
                  <SelectTrigger data-testid="company-form-currency" className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10"><SelectValue placeholder="Selecciona" /></SelectTrigger>
                  <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                    {createCurrencies.map(c => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="micro-label text-neutral-500">{t("admin.companyFunds.amount")}</Label>
                <Input data-testid="company-form-amount" type="number" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10 font-mono" />
              </div>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("admin.companyFunds.beneficiaryLabel")}</Label>
              <Input data-testid="company-form-beneficiary" value={form.beneficiary} onChange={(e) => setForm({ ...form, beneficiary: e.target.value })} placeholder={t("admin.companyFunds.beneficiaryPh")} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("admin.companyFunds.conceptLabel")}</Label>
              <Input data-testid="company-form-concept" value={form.concept} onChange={(e) => setForm({ ...form, concept: e.target.value })} placeholder={t("admin.companyFunds.conceptPh")} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("admin.companyFunds.note")}</Label>
              <Textarea data-testid="company-form-note" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} rows={2} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("admin.companyFunds.invoiceLabel")}</Label>
              <input data-testid="company-form-invoice" type="file" accept="image/*" onChange={handleInvoiceUpload} className="block mt-1 text-xs text-neutral-400" />
              {form.invoice_image && (
                <img src={form.invoice_image} alt="invoice" className="mt-2 max-h-32 border border-white/10" />
              )}
            </div>
            <Button
              data-testid="company-form-submit"
              disabled={pendingSubmit || !form.currency || !form.amount || !form.beneficiary}
              onClick={() => setPendingStatus({ submit: true })}
              className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none"
            >
              {t("admin.companyFunds.continueTotp")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <AdjustmentsHistoryDialog
        open={openAdjustmentsHistory}
        onOpenChange={setOpenAdjustmentsHistory}
        items={adjustments}
      />

      <AdjustmentDialog
        open={openAdjustment}
        onOpenChange={setOpenAdjustment}
        currencies={currencies.filter(c =>
          isAdmin || !user?.allowed_currencies?.length || user.allowed_currencies.includes(c.code)
        )}
        onCreated={load}
      />

      <TotpPromptDialog
        open={!!pendingStatus}
        title={pendingStatus?.submit ? t("admin.companyFunds.totpNewTitle") : t("admin.companyFunds.totpStatusTitle")}
        description={t("admin.companyFunds.totpDesc")}
        busy={pendingSubmit}
        onConfirm={(code) => {
          if (pendingStatus?.submit) submitCreate(code);
          else confirmStatusWithTotp(code);
        }}
        onCancel={() => setPendingStatus(null)}
      />
    </div>
  );
}
