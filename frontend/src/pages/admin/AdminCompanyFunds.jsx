/**
 * iter87/iter277 — AdminCompanyFunds (container)
 *
 * Composition-only shell. Data + side-effects live in `useCompanyFunds`.
 * Presentation is `FundCards`, `CompanyWithdrawalsTable` (tabla unificada de
 * depósitos y retiros), `NewWithdrawalDialog` y `AdjustmentDialog` (depósito).
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { Scale } from "lucide-react";
import { Button } from "@/components/ui/button";
import TotpPromptDialog from "@/components/TotpPromptDialog";
import FundAccountSelect from "@/components/FundAccountSelect";
import AdminPageHeader from "@/components/AdminPageHeader";
import AdjustmentDialog from "./company-funds/AdjustmentDialog";
import CashBoxDenominationsDialog from "./company-funds/CashBoxDenominationsDialog";
import FundCards from "@/pages/admin/company-funds/FundCards";
import BatchesTodayCard from "@/pages/admin/company-funds/BatchesTodayCard";
import TotalUsdtCard from "@/pages/admin/company-funds/TotalUsdtCard";
import CompanyWithdrawalsTable from "@/pages/admin/company-funds/CompanyWithdrawalsTable";
import NewWithdrawalDialog from "@/pages/admin/company-funds/NewWithdrawalDialog";
import PayCashBills from "@/pages/admin/company-funds/PayCashBills";
import ExportCsvDialog from "@/pages/admin/company-funds/ExportCsvDialog";
import CompanyClosingPdfDialog from "@/pages/admin/company-funds/CompanyClosingPdfDialog";
import { useCompanyFunds } from "@/pages/admin/company-funds/useCompanyFunds";

export default function AdminCompanyFunds() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const cf = useCompanyFunds();
  const [cashBoxOpen, setCashBoxOpen] = useState(false);

  return (
    <div data-testid="admin-company-funds" className="space-y-8">
      <AdminPageHeader
        eyebrow={t("admin.companyFunds.eyebrow")}
        title={t("admin.companyFunds.title")}
        subtitle={t("admin.companyFunds.subtitle")}
        actions={
          <Button
            data-testid="open-client-debts-btn"
            onClick={() => navigate("/admin/company-funds/client-debts")}
            className="border border-[#8B5CF6]/40 bg-[#8B5CF6]/10 text-[#c4b5fd] hover:bg-[#8B5CF6]/20 rounded-none"
          >
            <Scale className="w-4 h-4 mr-2" /> {t("admin.clientDebts.open")}
          </Button>
        }
      />

      <TotalUsdtCard />

      <BatchesTodayCard />

      <FundCards funds={cf.funds} />

      <CompanyWithdrawalsTable
        rows={cf.moveRows}
        total={cf.moveTotal}
        page={cf.movePage}
        setPage={cf.setMovePage}
        isAdmin={cf.isAdmin}
        createCurrencies={cf.createCurrencies}
        currencies={cf.currencies}
        statusFilter={cf.statusFilter}
        setStatusFilter={cf.setStatusFilter}
        tipoFilter={cf.tipoFilter}
        setTipoFilter={cf.setTipoFilter}
        beneficiaryQuery={cf.beneficiaryQuery}
        setBeneficiaryQuery={cf.setBeneficiaryQuery}
        onOpenDeposit={() => cf.setOpenAdjustment(true)}
        onOpenCashBox={() => setCashBoxOpen(true)}
        onOpenCreate={() => cf.setOpenCreate(true)}
        onOpenExport={() => cf.setExportOpen(true)}
        onOpenClosingPdf={() => cf.setClosingOpen(true)}
        onRequestStatus={cf.requestStatus}
      />

      <ExportCsvDialog
        open={cf.exportOpen}
        onOpenChange={cf.setExportOpen}
      />

      <CompanyClosingPdfDialog
        open={cf.closingOpen}
        onOpenChange={cf.setClosingOpen}
      />

      <NewWithdrawalDialog
        open={cf.openCreate}
        onOpenChange={cf.setOpenCreate}
        form={cf.form}
        setForm={cf.setForm}
        createCurrencies={cf.createCurrencies}
        onInvoiceUpload={cf.handleInvoiceUpload}
        pendingSubmit={cf.pendingSubmit}
        onContinueTotp={() => cf.setPendingStatus({ submit: true })}
        isAdmin={cf.isAdmin}
        payNow={cf.payNow}
        setPayNow={cf.setPayNow}
        createAccount={cf.createAccount}
        setCreateAccount={cf.setCreateAccount}
        createAccountMethod={cf.createAccountMethod}
        createDenoms={cf.createDenoms}
        setCreateDenoms={cf.setCreateDenoms}
      />

      <CashBoxDenominationsDialog
        open={cashBoxOpen}
        onOpenChange={setCashBoxOpen}
      />

      <AdjustmentDialog
        open={cf.openAdjustment}
        onOpenChange={cf.setOpenAdjustment}
        currencies={cf.adjustmentCurrencies}
        onCreated={cf.load}
      />

      <TotpPromptDialog
        open={!!cf.pendingStatus}
        title={cf.pendingStatus?.submit
          ? t("admin.companyFunds.totpNewTitle")
          : t("admin.companyFunds.totpStatusTitle")}
        description={t("admin.companyFunds.totpDesc")}
        busy={cf.pendingSubmit}
        onConfirm={(code) => {
          if (cf.pendingStatus?.submit) cf.submitCreate(code);
          else cf.confirmStatusWithTotp(code);
        }}
        onCancel={() => cf.setPendingStatus(null)}
      >
        {cf.pendingStatus?.status === "paid" && cf.pendingStatus?.currency && (
          <div className="space-y-3">
            <FundAccountSelect
              currency={cf.pendingStatus.currency}
              value={cf.paidFromAccount}
              onChange={cf.setPaidFromAccount}
              label={t("admin.companyFunds.paidFromAccount")}
              unassignedLabel={t("admin.companyFunds.unassigned")}
              testId="cw-paid-from-account"
              autoMode
            />
            {cf.payAccountMethod === "cash" && (
              <PayCashBills
                currency={cf.pendingStatus.currency}
                amount={Number(cf.pendingStatus.amount || 0)}
                counts={cf.payDenoms}
                onChange={cf.setPayDenoms}
                t={t}
              />
            )}
          </div>
        )}
      </TotpPromptDialog>
    </div>
  );
}
