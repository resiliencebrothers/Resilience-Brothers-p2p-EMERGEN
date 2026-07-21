/**
 * iter87 — CompanyWithdrawalsTable
 *
 * The bottom-of-page section header (title + 3 action buttons) plus the
 * withdrawals table. Only admins see the row-action buttons (approve /
 * paid / reject); staff members see the read-only table.
 */
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { FileImage, HandCoins, SlidersHorizontal, Plus, Download, Search, FileDown } from "lucide-react";

const STATUS_STYLES = {
  paid: "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  approved: "bg-[#8B5CF6]/10 text-[#8B5CF6] border-[#8B5CF6]/30",
  rejected: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30",
  pending: "bg-neutral-700/20 text-neutral-400 border-neutral-700/40",
};

export default function CompanyWithdrawalsTable({
  items, adjustments, isAdmin,
  createCurrencies, currencies,
  statusFilter, setStatusFilter,
  beneficiaryQuery, setBeneficiaryQuery,
  onOpenAdjustmentsHistory, onOpenAdjustment, onOpenCreate, onOpenExport, onOpenClosingPdf,
  onRequestStatus,
  rawTotal,
}) {
  const { t } = useTranslation();
  const STATUS_LABELS = {
    pending: t("admin.companyFunds.statusPending"),
    approved: t("admin.companyFunds.statusApproved"),
    paid: t("admin.companyFunds.statusPaid"),
    rejected: t("admin.companyFunds.statusRejected"),
  };
  const hasFilters = statusFilter !== "all" || beneficiaryQuery.trim() !== "";
  return (
    <>
      <div className="flex flex-wrap justify-between items-center gap-3">
        <h2 className="font-display text-xl">{t("admin.companyFunds.sectionTitle")}</h2>
        <div className="flex gap-2 flex-wrap">
          <Button
            data-testid="cw-export-csv-btn"
            onClick={onOpenExport}
            variant="outline"
            className="rounded-none border-white/20 hover:bg-white/5"
          >
            <Download className="w-4 h-4 mr-1" /> {t("admin.companyFunds.exportBtn")}
          </Button>
          <Button
            data-testid="company-closing-pdf-btn"
            onClick={onOpenClosingPdf}
            variant="outline"
            className="rounded-none border-[#8B5CF6]/60 text-[#A78BFA] hover:bg-[#8B5CF6]/10"
          >
            <FileDown className="w-4 h-4 mr-1" /> {t("admin.companyFunds.closingBtn")}
          </Button>
          <Button
            data-testid="open-adjustments-history"
            variant="outline"
            onClick={onOpenAdjustmentsHistory}
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
            onClick={onOpenAdjustment}
            disabled={currencies.length === 0}
            className="rounded-none border-white/20 hover:bg-white/5"
          >
            <SlidersHorizontal className="w-4 h-4 mr-1" /> {t("admin.companyFunds.manualAdjustment")}
          </Button>
          <Button
            data-testid="create-company-withdrawal"
            onClick={onOpenCreate}
            disabled={createCurrencies.length === 0}
            className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none"
          >
            <Plus className="w-4 h-4 mr-1" /> {t("admin.companyFunds.newWithdrawal")}
          </Button>
        </div>
      </div>

      {/* iter88 — Fund withdrawals filter row (status + beneficiary). */}
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <div className="micro-label text-neutral-500 mb-1">
            {t("admin.companyFunds.filterStatus")}
          </div>
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger
              data-testid="cw-filter-status"
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-40"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
              <SelectItem value="all">{t("admin.companyFunds.filterAll")}</SelectItem>
              <SelectItem value="pending">{STATUS_LABELS.pending}</SelectItem>
              <SelectItem value="approved">{STATUS_LABELS.approved}</SelectItem>
              <SelectItem value="paid">{STATUS_LABELS.paid}</SelectItem>
              <SelectItem value="rejected">{STATUS_LABELS.rejected}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex-1 min-w-[220px] max-w-md">
          <div className="micro-label text-neutral-500 mb-1">
            {t("admin.companyFunds.filterBeneficiary")}
          </div>
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-neutral-500 pointer-events-none" />
            <Input
              data-testid="cw-filter-beneficiary"
              value={beneficiaryQuery}
              onChange={(e) => setBeneficiaryQuery(e.target.value)}
              placeholder={t("admin.companyFunds.filterBeneficiaryPh")}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 pl-8 font-mono text-xs"
            />
          </div>
        </div>
        {hasFilters && (
          <button
            type="button"
            onClick={() => {
              setStatusFilter("all");
              setBeneficiaryQuery("");
            }}
            data-testid="cw-filter-clear"
            className="text-xs text-neutral-500 hover:text-[#8B5CF6] underline underline-offset-4 h-10"
          >
            {t("admin.companyFunds.filterClear")}
          </button>
        )}
        <div className="text-xs text-neutral-500 font-mono ml-auto h-10 flex items-end pb-2">
          {t("admin.companyFunds.showing", { n: items.length, total: rawTotal })}
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
              {isAdmin && <th className="px-4 py-3" />}
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr>
                <td colSpan="8" className="text-center text-neutral-500 py-8">
                  {t("admin.companyFunds.emptyWithdrawals")}
                </td>
              </tr>
            )}
            {items.map((w) => (
              <WithdrawalRow
                key={w.id}
                w={w}
                isAdmin={isAdmin}
                statusLabel={STATUS_LABELS[w.status]}
                onRequestStatus={onRequestStatus}
                t={t}
              />
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function WithdrawalRow({ w, isAdmin, statusLabel, onRequestStatus, t }) {
  return (
    <tr className="border-b border-white/5" data-testid={`company-withdrawal-row-${w.id}`}>
      <td className="px-4 py-3 font-mono text-[#8B5CF6]">
        {Number(w.amount).toLocaleString(undefined, { maximumFractionDigits: 2 })}
      </td>
      <td className="px-4 py-3 font-mono">{w.currency}</td>
      <td className="px-4 py-3 text-xs max-w-xs truncate">{w.beneficiary}</td>
      <td className="px-4 py-3 text-xs text-neutral-400 max-w-xs truncate">{w.concept || "—"}</td>
      <td className="px-4 py-3 text-xs">{w.authorized_by_name}</td>
      <td className="px-4 py-3">
        {w.invoice_image ? (
          <a
            href={w.invoice_image}
            target="_blank"
            rel="noreferrer"
            className="text-[#8B5CF6] hover:underline text-xs inline-flex items-center gap-1"
          >
            <FileImage className="w-3 h-3" /> {t("admin.companyFunds.seeInvoice")}
          </a>
        ) : <span className="text-neutral-600 text-xs">—</span>}
      </td>
      <td className="px-4 py-3">
        <span className={`text-xs uppercase border px-2 py-1 ${STATUS_STYLES[w.status]}`}>
          {statusLabel}
        </span>
      </td>
      {isAdmin && (
        <td className="px-4 py-3">
          {w.status !== "paid" && w.status !== "rejected" && (
            <div className="flex gap-1">
              <Button
                size="sm"
                onClick={() => onRequestStatus({ id: w.id, status: "approved" })}
                className="bg-[#8B5CF6] text-white rounded-none h-7 text-xs"
              >
                {t("admin.companyFunds.approve")}
              </Button>
              <Button
                size="sm"
                onClick={() => onRequestStatus({ id: w.id, status: "paid" })}
                className="bg-[#22C55E] text-black rounded-none h-7 text-xs"
              >
                {t("admin.companyFunds.paid")}
              </Button>
              <Button
                size="sm"
                onClick={() => onRequestStatus({ id: w.id, status: "rejected" })}
                className="bg-[#EF4444] text-white rounded-none h-7 text-xs"
              >
                ×
              </Button>
            </div>
          )}
        </td>
      )}
    </tr>
  );
}
