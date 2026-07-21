import { Trans, useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Check, Loader2 } from "lucide-react";

/**
 * Batch-approve bar for pending/needs_more_info rows.
 * Shows only when there is at least one actionable row.
 */
export default function KYCBatchBar({
  actionableItems, batchIds, onBatchIdsChange,
  bulkRunning, onBulkApprove,
}) {
  const { t } = useTranslation();
  if (actionableItems.length === 0) return null;

  const checked =
    batchIds.size > 0 && batchIds.size === actionableItems.length
      ? true
      : batchIds.size > 0 ? "indeterminate" : false;

  return (
    <div
      className="flex items-center gap-3 border border-white/10 bg-black/30 px-4 py-2 text-sm"
      data-testid="kyc-batch-bar"
    >
      <Checkbox
        data-testid="kyc-batch-select-all"
        checked={checked}
        onCheckedChange={(v) => {
          if (v) onBatchIdsChange(new Set(actionableItems.map((it) => it.id)));
          else onBatchIdsChange(new Set());
        }}
      />
      <span className="text-neutral-400">
        {batchIds.size > 0 ? (
          <Trans
            i18nKey="admin.kycAdmin.batchSelected"
            values={{ count: batchIds.size }}
            components={{ 1: <span className="text-white font-mono" /> }}
          />
        ) : (
          t("admin.kycAdmin.batchSelectHint")
        )}
      </span>
      <div className="ml-auto flex items-center gap-2">
        {batchIds.size > 0 && (
          <Button
            data-testid="kyc-clear-batch-btn"
            variant="outline"
            size="sm"
            onClick={() => onBatchIdsChange(new Set())}
            className="border-white/10 text-neutral-400 hover:bg-white/5 h-8"
          >
            {t("admin.kycAdmin.batchClear")}
          </Button>
        )}
        <Button
          data-testid="kyc-bulk-approve-btn"
          size="sm"
          onClick={onBulkApprove}
          disabled={batchIds.size === 0 || bulkRunning}
          className="bg-emerald-500 text-black hover:bg-emerald-500/90 h-8 disabled:opacity-40"
        >
          {bulkRunning ? (
            <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
          ) : (
            <Check className="w-3.5 h-3.5 mr-1.5" />
          )}
          {t("admin.kycAdmin.batchApprove", {
            label: batchIds.size > 0
              ? t("admin.kycAdmin.batchApproveMany", { count: batchIds.size })
              : t("admin.kycAdmin.batchApproveOne"),
          })}
        </Button>
      </div>
    </div>
  );
}
