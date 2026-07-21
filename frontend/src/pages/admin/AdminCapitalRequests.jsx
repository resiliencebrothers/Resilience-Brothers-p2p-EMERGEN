/**
 * iter86 — AdminCapitalRequests (container)
 *
 * Composition-only shell. Data comes from `useCapitalRequests`, rendering
 * from `CapitalRequestsList` + `ApproveCapitalDialog` + `RejectCapitalDialog`.
 *
 * Behaviour is byte-identical to the pre-refactor 364-line version.
 */
import { useTranslation } from "react-i18next";
import TotpPromptDialog from "@/components/TotpPromptDialog";
import { useCapitalRequests } from "@/pages/admin/capital-requests/useCapitalRequests";
import CapitalRequestsList from "@/pages/admin/capital-requests/CapitalRequestsList";
import {
  ApproveCapitalDialog, RejectCapitalDialog,
} from "@/pages/admin/capital-requests/CapitalRequestDialogs";

export default function AdminCapitalRequests() {
  const { t } = useTranslation();
  const cr = useCapitalRequests();

  return (
    <div className="space-y-4" data-testid="admin-capital-requests">
      <CapitalRequestsList
        items={cr.filteredItems}
        statusFilter={cr.statusFilter}
        setStatusFilter={cr.setStatusFilter}
        clientQuery={cr.clientQuery}
        setClientQuery={cr.setClientQuery}
        loading={cr.loading}
        onApprove={cr.openApprove}
        onReject={cr.openReject}
      />

      <ApproveCapitalDialog
        approving={cr.approving}
        setApproving={cr.setApproving}
        discountPct={cr.discountPct}
        setDiscountPct={cr.setDiscountPct}
        adminNotes={cr.adminNotes}
        setAdminNotes={cr.setAdminNotes}
        busy={cr.busy}
        onSubmit={cr.submitApprove}
      />

      <RejectCapitalDialog
        rejecting={cr.rejecting}
        setRejecting={cr.setRejecting}
        rejectReason={cr.rejectReason}
        setRejectReason={cr.setRejectReason}
        busy={cr.busy}
        onSubmit={cr.submitReject}
      />

      <TotpPromptDialog
        open={!!cr.pendingTotp}
        title={t("admin.capitalRequests.totpTitle")}
        description={t("admin.capitalRequests.totpDescription")}
        onConfirm={(code) => {
          if (cr.pendingTotp?.kind === "approve") cr.submitApprove(code);
          else if (cr.pendingTotp?.kind === "reject") cr.submitReject(code);
        }}
        onCancel={() => cr.setPendingTotp(null)}
      />
    </div>
  );
}
