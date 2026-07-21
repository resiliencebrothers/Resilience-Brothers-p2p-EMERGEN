/**
 * iter84 — AdminSecurity (container)
 *
 * Composition-only shell for the admin Security page. Delegates data
 * fetching to `useSecurityAudit` + `useCloudflareBlocks` and rendering
 * to `SecurityAuditPanels` + `CloudflareBlocklist`.
 *
 * Behaviour is byte-identical to the pre-refactor 511-line version.
 */
import { useTranslation, Trans } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Shield, RefreshCw } from "lucide-react";
import { useSecurityAudit } from "@/pages/admin/security/useSecurityAudit";
import { useCloudflareBlocks } from "@/pages/admin/security/useCloudflareBlocks";
import SecurityAuditPanels from "@/pages/admin/security/SecurityAuditPanels";
import CloudflareBlocklist from "@/pages/admin/security/CloudflareBlocklist";

export default function AdminSecurity() {
  const { t } = useTranslation();
  const audit = useSecurityAudit();
  const cf = useCloudflareBlocks();

  if (audit.loading) {
    return <div className="text-sm text-neutral-500">{t("admin.security.loading")}</div>;
  }
  if (!audit.data) return null;

  return (
    <div data-testid="admin-security-page" className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl flex items-center gap-2">
            <Shield className="w-7 h-7 text-[#8B5CF6]" /> {t("admin.security.title")}
          </h1>
          <p className="text-sm text-neutral-400 mt-1">
            <Trans
              i18nKey="admin.security.window"
              values={{
                days: audit.data.window_days,
                ts: audit.data.generated_at?.slice(0, 16).replace("T", " "),
              }}
              components={{ 1: <span className="text-white" /> }}
            />
          </p>
        </div>
        <Button
          data-testid="security-refresh-btn"
          onClick={audit.load}
          size="sm"
          variant="outline"
          className="border-white/10 text-neutral-300 hover:bg-white/5"
        >
          <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> {t("admin.security.reload")}
        </Button>
      </div>

      <SecurityAuditPanels
        data={audit.data}
        revoking={audit.revoking}
        onRevokeSessions={audit.revokeSessions}
      />

      <CloudflareBlocklist
        cfData={cf.cfData}
        cfLoading={cf.cfLoading}
        cfDialogOpen={cf.cfDialogOpen}
        setCfDialogOpen={cf.setCfDialogOpen}
        cfForm={cf.cfForm}
        setCfForm={cf.setCfForm}
        cfSubmitting={cf.cfSubmitting}
        cfDeleting={cf.cfDeleting}
        loadCloudflare={cf.loadCloudflare}
        submitCfBlock={cf.submitCfBlock}
        deleteCfBlock={cf.deleteCfBlock}
      />
    </div>
  );
}
