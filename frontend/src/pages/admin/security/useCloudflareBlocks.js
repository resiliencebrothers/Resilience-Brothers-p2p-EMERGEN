/**
 * iter84 — useCloudflareBlocks
 *
 * Data hook for the Cloudflare IP-blocklist panel. Owns the CF fetch,
 * the create dialog (form + submit), and the delete flow. All CF-specific
 * state was previously interleaved with the audit state in AdminSecurity.jsx.
 */
import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { API } from "@/App";

export function useCloudflareBlocks() {
  const { t } = useTranslation();
  const [cfData, setCfData] = useState(null);
  const [cfLoading, setCfLoading] = useState(true);
  const [cfDialogOpen, setCfDialogOpen] = useState(false);
  const [cfForm, setCfForm] = useState({ ip: "", notes: "" });
  const [cfSubmitting, setCfSubmitting] = useState(false);
  const [cfDeleting, setCfDeleting] = useState(null);

  const loadCloudflare = useCallback(async () => {
    setCfLoading(true);
    try {
      const r = await axios.get(`${API}/admin/security/cloudflare/blocks`, { withCredentials: true });
      setCfData(r.data);
    } catch (e) {
      const detail = e.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : t("admin.security.cfLoadError"));
    } finally {
      setCfLoading(false);
    }
  }, [t]);

  useEffect(() => { loadCloudflare(); }, [loadCloudflare]);

  const submitCfBlock = useCallback(async () => {
    const ip = cfForm.ip.trim();
    if (!ip) {
      toast.error(t("admin.security.ipRequired"));
      return;
    }
    setCfSubmitting(true);
    try {
      const r = await axios.post(
        `${API}/admin/security/cloudflare/blocks`,
        { ip, notes: cfForm.notes.trim() },
        { withCredentials: true },
      );
      if (r.data?.already_blocked) {
        toast.info(t("admin.security.cfAlready", { ip }));
      } else if (r.data?.cf_ok) {
        toast.success(t("admin.security.cfBoth", { ip }));
      } else if (r.data?.created) {
        toast.success(t("admin.security.cfAppOnly", { ip }));
      } else {
        toast.warning(t("admin.security.cfFailed", { reason: r.data?.reason || "revisa logs" }));
      }
      setCfDialogOpen(false);
      setCfForm({ ip: "", notes: "" });
      await loadCloudflare();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("admin.security.cfCreateError"));
    } finally {
      setCfSubmitting(false);
    }
  }, [cfForm, loadCloudflare, t]);

  const deleteCfBlock = useCallback(async (blockId, ip) => {
    if (!window.confirm(t("admin.security.unblockConfirm", { ip }))) return;
    setCfDeleting(blockId);
    try {
      await axios.delete(
        `${API}/admin/security/cloudflare/blocks/${blockId}`,
        { withCredentials: true },
      );
      toast.success(t("admin.security.cfDelSuccess", { ip }));
      await loadCloudflare();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("admin.security.cfDelError"));
    } finally {
      setCfDeleting(null);
    }
  }, [loadCloudflare, t]);

  return {
    cfData, cfLoading, cfDialogOpen, cfForm, cfSubmitting, cfDeleting,
    setCfDialogOpen, setCfForm,
    loadCloudflare, submitCfBlock, deleteCfBlock,
  };
}
