/**
 * iter87 — AdminCompanyFunds (container)
 *
 * Composition-only shell. Data + side-effects live in `useCompanyFunds`.
 * Presentation is `FundCards`, `CompanyWithdrawalsTable`, `NewWithdrawalDialog`,
 * `AdjustmentDialog` and `AdjustmentsHistoryDialog`.
 *
 * Behaviour is byte-identical to the pre-refactor 346-line version.
 */
import { useTranslation } from "react-i18next";
import TotpPromptDialog from "@/components/TotpPromptDialog";
import AdminPageHeader from "@/components/AdminPageHeader";
import AdjustmentDialog from "./company-funds/AdjustmentDialog";
import AdjustmentsHistoryDialog from "./company-funds/AdjustmentsHistoryDialog";
import FundCards from "@/pages/admin/company-funds/FundCards";
import CompanyWithdrawalsTable from "@/pages/admin/company-funds/CompanyWithdrawalsTable";
import NewWithdrawalDialog from "@/pages/admin/company-funds/NewWithdrawalDialog";
import ExportCsvDialog from "@/pages/admin/company-funds/ExportCsvDialog";
import CompanyClosingPdfDialog from "@/pages/admin/company-funds/CompanyClosingPdfDialog";
import { useCompanyFunds } from "@/pages/admin/company-funds/useCompanyFunds";

export default function AdminCompanyFunds() {
  const { t } = useTranslation();
  const cf = useCompanyFunds();

  return (
    <div data-testid="admin-company-funds" className="space-y-8">
      <AdminPageHeader
        eyebrow={t("admin.companyFunds.eyebrow")}
        title={t("admin.companyFunds.title")}
        subtitle={t("admin.companyFunds.subtitle")}
      />

      <FundCards funds={cf.funds} />

      <CompanyWithdrawalsTable
        items={cf.filteredItems}
        rawTotal={cf.items.length}
        adjustments={cf.adjustments}
        isAdmin={cf.isAdmin}
        createCurrencies={cf.createCurrencies}
        currencies={cf.currencies}
        statusFilter={cf.statusFilter}
        setStatusFilter={cf.setStatusFilter}
        beneficiaryQuery={cf.beneficiaryQuery}
        setBeneficiaryQuery={cf.setBeneficiaryQuery}
        onOpenAdjustmentsHistory={() => cf.setOpenAdjustmentsHistory(true)}
        onOpenAdjustment={() => cf.setOpenAdjustment(true)}
        onOpenCreate={() => cf.setOpenCreate(true)}
        onOpenExport={() => cf.setExportOpen(true)}
        onOpenClosingPdf={() => cf.setClosingOpen(true)}
        onRequestStatus={cf.setPendingStatus}
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
      />

      <AdjustmentsHistoryDialog
        open={cf.openAdjustmentsHistory}
        onOpenChange={cf.setOpenAdjustmentsHistory}
        items={cf.adjustments}
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
      />
    </div>
  );
}
