/**
 * iter85 — useBlockedImport
 *
 * Data hook for the bulk-import dialog. Handles textarea state, the
 * POST /admin/blocked-contacts/bulk-import call, the result payload
 * (imported / skipped / invalid / affected_active_accounts) and the
 * dialog open/reset lifecycle.
 */
import { useCallback, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { API } from "@/App";

export function useBlockedImport({ onSuccess }) {
  const { t } = useTranslation();
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState("");
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState(null);

  const openImportDialog = useCallback(() => {
    setImportText("");
    setImportResult(null);
    setImportOpen(true);
  }, []);

  const resetImport = useCallback(() => {
    setImportText("");
    setImportResult(null);
    setImportOpen(false);
  }, []);

  const submitBulkImport = useCallback(async () => {
    if (!importText.trim()) {
      toast.error(t("admin.blocked.importPaste"));
      return;
    }
    setImporting(true);
    setImportResult(null);
    try {
      const r = await axios.post(
        `${API}/admin/blocked-contacts/bulk-import`,
        { text: importText },
        { withCredentials: true },
      );
      setImportResult(r.data);
      if (r.data.imported_count > 0) {
        toast.success(t("admin.blocked.importedToast", { n: r.data.imported_count }));
      } else if (r.data.skipped_count > 0) {
        toast.info(t("admin.blocked.allDuplicates"));
      } else {
        toast.warning(t("admin.blocked.noValidPhones"));
      }
      if (onSuccess) onSuccess();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("admin.blocked.importError"));
    } finally {
      setImporting(false);
    }
  }, [importText, onSuccess, t]);

  return {
    importOpen, importText, importing, importResult,
    setImportOpen, setImportText,
    openImportDialog, resetImport, submitBulkImport,
  };
}
