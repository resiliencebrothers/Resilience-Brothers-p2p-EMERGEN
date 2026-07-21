/**
 * iter86 — Capital-request dialogs
 *
 * Two named exports: `ApproveCapitalDialog` (discount + admin notes)
 * and `RejectCapitalDialog` (rejection reason). Both are presentation-
 * only components — all state and submit logic live in the parent hook
 * `useCapitalRequests`.
 */
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";

const fmtNum = (n, d = 2) =>
  Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: d });

export function ApproveCapitalDialog({
  approving, setApproving,
  discountPct, setDiscountPct,
  adminNotes, setAdminNotes,
  busy, onSubmit,
}) {
  const { t } = useTranslation();
  return (
    <Dialog open={!!approving} onOpenChange={(o) => !o && setApproving(null)}>
      <DialogContent className="bg-[#0c0c0c] border border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("admin.capitalRequests.approveDialog")}</DialogTitle>
        </DialogHeader>
        {approving && (
          <div className="space-y-4">
            <div className="border border-white/10 bg-[#0a0a0a] p-3 text-sm">
              <div>
                {t("admin.capitalRequests.client")}{" "}
                <strong>{approving.user_name}</strong> ({approving.user_email})
              </div>
              <div className="mt-1">
                {t("admin.capitalRequests.amountLabel")}{" "}
                <strong className="tabular-nums">
                  {fmtNum(approving.amount, 2)} {approving.currency_code}
                </strong>
              </div>
              <div className="mt-1 text-xs text-neutral-500">{approving.reason}</div>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">
                {t("admin.capitalRequests.discountLabel")}
              </Label>
              <Input
                data-testid="cr-approve-discount"
                type="number" min="1" max="100"
                value={discountPct}
                onChange={(e) => setDiscountPct(e.target.value)}
                className="rounded-none bg-[#0a0a0a] border-white/10 h-11 mt-1 font-mono"
              />
              <div className="text-[0.65rem] text-neutral-500 mt-1">
                {t("admin.capitalRequests.discountHelper", { code: approving.currency_code })}
              </div>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">
                {t("admin.capitalRequests.adminNotesLabel")}
              </Label>
              <Textarea
                data-testid="cr-approve-notes"
                value={adminNotes}
                onChange={(e) => setAdminNotes(e.target.value)}
                maxLength={500}
                className="rounded-none bg-[#0a0a0a] border-white/10 mt-1"
              />
            </div>
          </div>
        )}
        <DialogFooter>
          <Button
            onClick={() => setApproving(null)}
            className="rounded-none bg-transparent border border-white/15 text-white"
          >
            {t("admin.capitalRequests.cancel")}
          </Button>
          <Button
            data-testid="cr-approve-confirm"
            onClick={() => onSubmit()}
            disabled={busy}
            className="rounded-none bg-emerald-600 hover:bg-emerald-500 text-white font-bold"
          >
            {t("admin.capitalRequests.disburse")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function RejectCapitalDialog({
  rejecting, setRejecting,
  rejectReason, setRejectReason,
  busy, onSubmit,
}) {
  const { t } = useTranslation();
  return (
    <Dialog open={!!rejecting} onOpenChange={(o) => !o && setRejecting(null)}>
      <DialogContent className="bg-[#0c0c0c] border border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("admin.capitalRequests.rejectDialog")}</DialogTitle>
        </DialogHeader>
        {rejecting && (
          <div className="space-y-4">
            <div className="border border-white/10 bg-[#0a0a0a] p-3 text-sm">
              <div>
                {t("admin.capitalRequests.client")}{" "}
                <strong>{rejecting.user_name}</strong>
              </div>
              <div className="mt-1">
                {t("admin.capitalRequests.amountLabel")}{" "}
                <strong className="tabular-nums">
                  {fmtNum(rejecting.amount, 2)} {rejecting.currency_code}
                </strong>
              </div>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">
                {t("admin.capitalRequests.rejectReasonLabel")}
              </Label>
              <Textarea
                data-testid="cr-reject-reason"
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                minLength={5}
                maxLength={500}
                className="rounded-none bg-[#0a0a0a] border-white/10 mt-1"
                placeholder={t("admin.capitalRequests.rejectReasonPh")}
              />
            </div>
          </div>
        )}
        <DialogFooter>
          <Button
            onClick={() => setRejecting(null)}
            className="rounded-none bg-transparent border border-white/15 text-white"
          >
            {t("admin.capitalRequests.cancel")}
          </Button>
          <Button
            data-testid="cr-reject-confirm"
            onClick={() => onSubmit()}
            disabled={busy}
            className="rounded-none bg-red-600 hover:bg-red-500 text-white font-bold"
          >
            {t("admin.capitalRequests.rejectBtn")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
