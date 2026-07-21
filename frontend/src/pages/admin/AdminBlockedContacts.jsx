/**
 * iter85 — AdminBlockedContacts (container)
 *
 * Composition-only shell for the admin Blocked Contacts page. Data lives
 * in `useBlockedContacts` (fetch + single-block CRUD) and `useBlockedImport`
 * (bulk-import lifecycle). Presentation is `BlockedContactsTable`,
 * `BlockContactDialog` and `BulkImportDialog`.
 *
 * Behaviour is byte-identical to the pre-refactor 368-line version.
 */
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Ban, Plus, Upload } from "lucide-react";
import { useBlockedContacts } from "@/pages/admin/blocked/useBlockedContacts";
import { useBlockedImport } from "@/pages/admin/blocked/useBlockedImport";
import BlockedContactsTable from "@/pages/admin/blocked/BlockedContactsTable";
import BlockContactDialog from "@/pages/admin/blocked/BlockContactDialog";
import BulkImportDialog from "@/pages/admin/blocked/BulkImportDialog";

export default function AdminBlockedContacts() {
  const { t } = useTranslation();
  const bc = useBlockedContacts();
  const imp = useBlockedImport({ onSuccess: bc.load });

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="font-display text-3xl flex items-center gap-2">
            <Ban className="w-7 h-7 text-[#EF4444]" /> {t("admin.blocked.title")}
          </h1>
          <p className="text-xs text-neutral-500 mt-1">{t("admin.blocked.subtitle")}</p>
        </div>
        <div className="flex gap-2">
          <Button
            data-testid="bulk-import-blocked-btn"
            onClick={imp.openImportDialog}
            variant="outline"
            className="border-white/20 hover:border-[#8B5CF6] hover:bg-[#8B5CF6]/10 text-white rounded-none"
          >
            <Upload className="w-4 h-4 mr-1" /> {t("admin.blocked.importList")}
          </Button>
          <Button
            data-testid="add-blocked-contact-btn"
            onClick={bc.openBlockDialog}
            className="bg-[#EF4444] hover:bg-[#DC2626] text-white rounded-none"
          >
            <Plus className="w-4 h-4 mr-1" /> {t("admin.blocked.blockContact")}
          </Button>
        </div>
      </div>

      <BlockedContactsTable
        items={bc.items}
        total={bc.total}
        q={bc.q}
        setQ={bc.setQ}
        loading={bc.loading}
        onRemove={bc.remove}
      />

      <BlockContactDialog
        open={bc.open}
        setOpen={bc.setOpen}
        form={bc.form}
        setForm={bc.setForm}
        saving={bc.saving}
        onSubmit={bc.submit}
      />

      <BulkImportDialog
        importOpen={imp.importOpen}
        setImportOpen={imp.setImportOpen}
        importText={imp.importText}
        setImportText={imp.setImportText}
        importing={imp.importing}
        importResult={imp.importResult}
        onSubmit={imp.submitBulkImport}
        onReset={imp.resetImport}
      />
    </div>
  );
}
