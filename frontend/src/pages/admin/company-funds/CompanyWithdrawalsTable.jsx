/**
 * iter87/iter277 — CompanyWithdrawalsTable → «Depósitos y retiros del fondo».
 *
 * Tabla UNIFICADA: retiros del fondo (con su flujo de estados) + depósitos
 * manuales de capital + retiros históricos hechos por ajuste (legado). El
 * botón «Ajuste manual» desapareció: las entradas van por «Depósito» y las
 * salidas por «Retiro», así ningún movimiento queda fuera de esta tabla.
 */
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  FileImage, Plus, Download, Search, FileDown, Banknote,
  ArrowDownCircle,
} from "lucide-react";

const STATUS_STYLES = {
  paid: "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  approved: "bg-[#8B5CF6]/10 text-[#8B5CF6] border-[#8B5CF6]/30",
  rejected: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30",
  pending: "bg-neutral-700/20 text-neutral-400 border-neutral-700/40",
};

const TYPE_STYLES = {
  withdrawal: "bg-[#8B5CF6]/10 text-[#A78BFA] border-[#8B5CF6]/30",
  deposit: "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  adjust_out: "bg-[#F59E0B]/10 text-[#F59E0B] border-[#F59E0B]/30",
};

export default function CompanyWithdrawalsTable({
  rows, total, page, setPage, isAdmin,
  createCurrencies, currencies,
  statusFilter, setStatusFilter,
  tipoFilter, setTipoFilter,
  beneficiaryQuery, setBeneficiaryQuery,
  onOpenDeposit, onOpenCreate, onOpenExport, onOpenClosingPdf, onOpenCashBox,
  onRequestStatus,
}) {
  const { t } = useTranslation();
  const STATUS_LABELS = {
    pending: t("admin.companyFunds.statusPending"),
    approved: t("admin.companyFunds.statusApproved"),
    paid: t("admin.companyFunds.statusPaid"),
    rejected: t("admin.companyFunds.statusRejected"),
  };
  const TYPE_LABELS = {
    withdrawal: t("admin.companyFunds.typeWithdrawal"),
    deposit: t("admin.companyFunds.typeDeposit"),
    adjust_out: t("admin.companyFunds.typeAdjustOut"),
  };
  const hasFilters = statusFilter !== "all" || tipoFilter !== "all"
    || beneficiaryQuery.trim() !== "";
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
            data-testid="open-cashbox-denominations"
            variant="outline"
            onClick={onOpenCashBox}
            className="rounded-none border-[#22C55E]/40 text-[#22C55E] hover:bg-[#22C55E]/10"
          >
            <Banknote className="w-4 h-4 mr-1" /> {t("admin.companyFunds.cashBoxBtn")}
          </Button>
          <Button
            data-testid="open-deposit-dialog"
            variant="outline"
            onClick={onOpenDeposit}
            disabled={currencies.length === 0}
            className="rounded-none border-[#22C55E]/40 text-[#22C55E] hover:bg-[#22C55E]/10"
          >
            <ArrowDownCircle className="w-4 h-4 mr-1" /> {t("admin.companyFunds.depositBtn")}
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

      {/* iter88/iter277 — filtros: tipo + estado + beneficiario. */}
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <div className="micro-label text-neutral-500 mb-1">
            {t("admin.companyFunds.filterTipo")}
          </div>
          <Select value={tipoFilter} onValueChange={setTipoFilter}>
            <SelectTrigger
              data-testid="cw-filter-tipo"
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-36"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
              <SelectItem value="all">{t("admin.companyFunds.filterAll")}</SelectItem>
              <SelectItem value="deposits">{t("admin.companyFunds.tipoDeposits")}</SelectItem>
              <SelectItem value="withdrawals">{t("admin.companyFunds.tipoWithdrawals")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
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
        <div className="flex-1 min-w-0 sm:min-w-[220px] max-w-md">
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
              setTipoFilter("all");
              setBeneficiaryQuery("");
            }}
            data-testid="cw-filter-clear"
            className="text-xs text-neutral-500 hover:text-[#8B5CF6] underline underline-offset-4 h-10"
          >
            {t("admin.companyFunds.filterClear")}
          </button>
        )}
        <div className="text-xs text-neutral-500 font-mono ml-auto h-10 flex items-end pb-2">
          {t("admin.companyFunds.showing", { n: rows.length, total })}
        </div>
      </div>

      <div className="tactile-card overflow-x-auto">
        <table className="w-full text-sm min-w-[980px]">
          <thead className="bg-[#0a0a0a] border-b border-white/10">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.companyFunds.colType")}</th>
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
            {rows.length === 0 && (
              <tr>
                <td colSpan="9" className="text-center text-neutral-500 py-8">
                  {t("admin.companyFunds.emptyWithdrawals")}
                </td>
              </tr>
            )}
            {rows.map((r) => r.kind === "withdrawal" ? (
              <WithdrawalRow
                key={r.key}
                w={r.data}
                isAdmin={isAdmin}
                typeLabel={TYPE_LABELS.withdrawal}
                statusLabel={STATUS_LABELS[r.data.status]}
                onRequestStatus={onRequestStatus}
                t={t}
              />
            ) : (
              <AdjustmentRow
                key={r.key}
                a={r.data}
                kind={r.kind}
                isAdmin={isAdmin}
                typeLabel={TYPE_LABELS[r.kind]}
                t={t}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* S07 — paginación del servidor: el historial completo es accesible. */}
      {(page > 0 || rows.length < total) && (
        <div className="flex items-center justify-end gap-2" data-testid="cw-pagination">
          <button
            type="button"
            data-testid="cw-page-prev"
            disabled={page === 0}
            onClick={() => setPage(Math.max(0, page - 1))}
            className="text-xs font-mono border border-white/15 px-3 py-1.5 disabled:opacity-30 disabled:cursor-default hover:border-[#8B5CF6]/60"
          >
            ‹
          </button>
          <span className="text-xs text-neutral-500 font-mono" data-testid="cw-page-indicator">
            {page + 1} / {Math.max(1, Math.ceil(total / 50))}
          </span>
          <button
            type="button"
            data-testid="cw-page-next"
            disabled={(page + 1) * 50 >= total}
            onClick={() => setPage(page + 1)}
            className="text-xs font-mono border border-white/15 px-3 py-1.5 disabled:opacity-30 disabled:cursor-default hover:border-[#8B5CF6]/60"
          >
            ›
          </button>
        </div>
      )}
    </>
  );
}

function WithdrawalRow({ w, isAdmin, typeLabel, statusLabel, onRequestStatus, t }) {
  return (
    <tr className="border-b border-white/5" data-testid={`company-withdrawal-row-${w.id}`}>
      <td className="px-4 py-3">
        <span className={`text-[0.65rem] uppercase border px-2 py-1 whitespace-nowrap ${TYPE_STYLES.withdrawal}`}>
          {typeLabel}
        </span>
      </td>
      <td className="px-4 py-3 font-mono text-[#8B5CF6]">
        −{Number(w.amount).toLocaleString(undefined, { maximumFractionDigits: 2 })}
      </td>
      <td translate="no" className="notranslate px-4 py-3 font-mono">{w.currency}</td>
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
                onClick={() => onRequestStatus({ id: w.id, status: "approved", currency: w.currency, amount: w.amount })}
                className="bg-[#8B5CF6] text-white rounded-none h-7 text-xs"
              >
                {t("admin.companyFunds.approve")}
              </Button>
              <Button
                size="sm"
                onClick={() => onRequestStatus({ id: w.id, status: "paid", currency: w.currency, amount: w.amount })}
                className="bg-[#22C55E] text-black rounded-none h-7 text-xs"
              >
                {t("admin.companyFunds.paid")}
              </Button>
              <Button
                size="sm"
                onClick={() => onRequestStatus({ id: w.id, status: "rejected", currency: w.currency, amount: w.amount })}
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

// iter277 — fila de depósito / retiro-por-ajuste (solo lectura: ya afectó el
// balance al registrarse).
function AdjustmentRow({ a, kind, isAdmin, typeLabel, t }) {
  const isDeposit = kind === "deposit";
  const methodLabel = {
    cash: t("admin.companyFunds.methodCash"),
    transfer: t("admin.companyFunds.methodTransfer"),
    crypto: t("admin.companyFunds.methodCrypto"),
  }[a.method] || a.method;
  return (
    <tr className="border-b border-white/5" data-testid={`fund-movement-row-${a.id}`}>
      <td className="px-4 py-3">
        <span className={`text-[0.65rem] uppercase border px-2 py-1 whitespace-nowrap ${TYPE_STYLES[kind]}`}>
          {typeLabel}
        </span>
      </td>
      <td className={`px-4 py-3 font-mono ${isDeposit ? "text-[#22C55E]" : "text-[#F59E0B]"}`}>
        {isDeposit ? "+" : "−"}{Number(a.amount).toLocaleString(undefined, { maximumFractionDigits: 2 })}
      </td>
      <td translate="no" className="notranslate px-4 py-3 font-mono">{a.currency}</td>
      <td className="px-4 py-3 text-xs max-w-xs truncate">{a.source_name}</td>
      <td className="px-4 py-3 text-xs text-neutral-400 max-w-xs truncate">
        {[methodLabel, a.account_label || null, a.note || null]
          .filter(Boolean).join(" · ")}
      </td>
      <td className="px-4 py-3 text-xs">{a.actor_name || a.actor_email}</td>
      <td className="px-4 py-3"><span className="text-neutral-600 text-xs">—</span></td>
      <td className="px-4 py-3">
        <span className="text-xs uppercase border px-2 py-1 bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30">
          {t("admin.companyFunds.statusRecorded")}
        </span>
      </td>
      {isAdmin && <td className="px-4 py-3" />}
    </tr>
  );
}
