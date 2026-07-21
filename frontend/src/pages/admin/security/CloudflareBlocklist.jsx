/**
 * iter84 — CloudflareBlocklist
 *
 * Rendering of the Cloudflare IP-blocklist panel: status pills header,
 * reload + "block IP" buttons, table of active/pending/deleted blocks
 * and the create-block dialog.
 *
 * Uses `useCloudflareBlocks` for all state/side-effects so this module
 * is purely presentational.
 */
import { useTranslation, Trans } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Cloud, RefreshCw, Plus, Trash2 } from "lucide-react";
import { Panel, Empty } from "./SecurityUiPrimitives";

function statusStyle(status) {
  const map = {
    active: "border border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
    pending_create: "border border-[#8B5CF6]/40 bg-[#8B5CF6]/10 text-[#FEF3C7]",
    pending_delete: "border border-[#8B5CF6]/40 bg-[#8B5CF6]/10 text-[#FEF3C7]",
    deleted: "border border-neutral-500/40 bg-neutral-500/10 text-neutral-400",
    failed: "border border-[#EF4444]/40 bg-[#EF4444]/10 text-[#FEE2E2]",
  };
  return map[status] || "border border-neutral-500/40 bg-neutral-500/10 text-neutral-400";
}

export default function CloudflareBlocklist({
  cfData, cfLoading,
  cfDialogOpen, setCfDialogOpen,
  cfForm, setCfForm,
  cfSubmitting, cfDeleting,
  loadCloudflare, submitCfBlock, deleteCfBlock,
}) {
  const { t } = useTranslation();
  return (
    <>
      <Panel
        icon={Cloud}
        title={t("admin.security.blocklistTitle")}
        subtitle={t("admin.security.blocklistDesc")}
      >
        <div className="mb-3 flex flex-wrap items-center gap-3 text-[0.7rem]">
          <span className="px-2 py-1 border border-emerald-500/40 bg-emerald-500/10 text-emerald-300">
            {t("admin.security.enforceAppOk")}
          </span>
          <span className={`px-2 py-1 border ${cfData?.configured ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300" : "border-neutral-500/40 bg-neutral-500/10 text-neutral-400"}`}>
            {cfData?.configured ? t("admin.security.cfConfigured") : t("admin.security.cfNotConfigured")}
          </span>
          <span className={`px-2 py-1 border ${cfData?.auto_block_enabled ? "border-[#8B5CF6]/40 bg-[#8B5CF6]/10 text-[#FEF3C7]" : "border-neutral-500/40 bg-neutral-500/10 text-neutral-400"}`}>
            {cfData?.auto_block_enabled ? t("admin.security.autoBlockOn") : t("admin.security.autoBlockOff")}
          </span>
          <div className="ml-auto flex gap-2">
            <Button
              data-testid="cf-refresh-btn"
              onClick={loadCloudflare}
              size="sm"
              variant="outline"
              className="border-white/10 text-neutral-300 hover:bg-white/5"
            >
              <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> {t("admin.security.reload")}
            </Button>
            <Button
              data-testid="cf-add-block-btn"
              onClick={() => setCfDialogOpen(true)}
              size="sm"
              className="bg-[#8B5CF6] text-white hover:bg-[#8B5CF6]/90"
            >
              <Plus className="w-3.5 h-3.5 mr-1.5" /> {t("admin.security.blockIp")}
            </Button>
          </div>
        </div>

        {cfLoading && <div className="text-xs text-neutral-500">{t("admin.security.loadingBlocklist")}</div>}
        {!cfLoading && cfData?.items?.length === 0 && <Empty text={t("admin.security.noBlocks")} />}
        {!cfLoading && cfData?.items?.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs" data-testid="cf-blocks-table">
              <thead>
                <tr className="text-[0.6rem] uppercase tracking-wider text-neutral-500 border-b border-white/5">
                  <th className="text-left py-2 pr-3 font-semibold">{t("admin.security.colIp")}</th>
                  <th className="text-left py-2 pr-3 font-semibold">{t("admin.security.colStatus")}</th>
                  <th className="text-left py-2 pr-3 font-semibold">{t("admin.security.colSource")}</th>
                  <th className="text-left py-2 pr-3 font-semibold">{t("admin.security.colNotes")}</th>
                  <th className="text-left py-2 pr-3 font-semibold">{t("admin.security.colCreated")}</th>
                  <th className="text-left py-2 pr-3 font-semibold">{t("admin.security.colAction")}</th>
                </tr>
              </thead>
              <tbody>
                {cfData.items.map((b) => (
                  <tr key={b.id} className="border-b border-white/5" data-testid={`cf-block-row-${b.id}`}>
                    <td className="py-1.5 pr-3 text-white font-mono text-[0.7rem]">{b.ip}</td>
                    <td className="py-1.5 pr-3">
                      <span className={`px-1.5 py-0.5 text-[0.6rem] uppercase font-bold ${statusStyle(b.status)}`}>
                        {b.status}
                      </span>
                    </td>
                    <td className="py-1.5 pr-3 text-neutral-400 text-[0.7rem]">{b.source}</td>
                    <td className="py-1.5 pr-3 text-neutral-400 text-[0.7rem] max-w-xs truncate" title={b.notes}>
                      {b.notes || "-"}
                    </td>
                    <td className="py-1.5 pr-3 text-neutral-400 font-mono text-[0.7rem]">
                      {b.created_at?.slice(0, 16).replace("T", " ")}
                    </td>
                    <td className="py-1.5 pr-3">
                      {b.status === "active" || b.status === "failed" ? (
                        <Button
                          data-testid={`cf-unblock-btn-${b.id}`}
                          size="sm"
                          variant="outline"
                          onClick={() => deleteCfBlock(b.id, b.ip)}
                          disabled={cfDeleting === b.id}
                          className="bg-[#EF4444]/10 border-[#EF4444]/40 text-[#EF4444] hover:bg-[#EF4444]/20 h-6 px-2 text-[0.65rem]"
                        >
                          <Trash2 className="w-3 h-3 mr-1" /> {t("admin.security.unblock")}
                        </Button>
                      ) : (
                        <span className="text-neutral-600 text-[0.65rem] italic">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Dialog open={cfDialogOpen} onOpenChange={setCfDialogOpen}>
        <DialogContent
          data-testid="cf-block-dialog"
          className="bg-neutral-950 border-white/10 max-h-[85vh] overflow-y-auto"
        >
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-white">
              <Cloud className="w-5 h-5 text-[#8B5CF6]" /> {t("admin.security.cfDialogTitle")}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="text-[0.7rem] uppercase tracking-wider text-neutral-500">IP</label>
              <Input
                data-testid="cf-block-ip-input"
                placeholder={t("admin.security.ipPlaceholder")}
                value={cfForm.ip}
                onChange={(e) => setCfForm({ ...cfForm, ip: e.target.value })}
                className="bg-black/40 border-white/10 text-white font-mono"
              />
            </div>
            <div>
              <label className="text-[0.7rem] uppercase tracking-wider text-neutral-500">
                {t("admin.security.notesOptional")}
              </label>
              <Textarea
                data-testid="cf-block-notes-input"
                placeholder={t("admin.security.notesPlaceholder")}
                value={cfForm.notes}
                onChange={(e) => setCfForm({ ...cfForm, notes: e.target.value })}
                className="bg-black/40 border-white/10 text-white text-sm"
                rows={2}
              />
            </div>
            {!cfData?.configured && (
              <div className="text-[0.7rem] text-blue-300 border border-blue-500/30 bg-blue-500/5 px-3 py-2">
                <Trans
                  i18nKey="admin.security.cfDialogInfo"
                  components={{ 1: <strong />, 2: <code />, 3: <code /> }}
                />
              </div>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setCfDialogOpen(false)}
              className="border-white/10 text-neutral-300 hover:bg-white/5"
            >
              {t("admin.common.cancel")}
            </Button>
            <Button
              data-testid="cf-block-submit-btn"
              onClick={submitCfBlock}
              disabled={cfSubmitting || !cfForm.ip.trim()}
              className="bg-[#EF4444] text-white hover:bg-[#EF4444]/90"
            >
              {cfSubmitting ? t("admin.security.cfSubmitting") : t("admin.security.cfSubmit")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
