/**
 * iter84 — useSecurityAudit
 *
 * Data hook for the AdminSecurity page. Owns the `/admin/security/audit`
 * fetch + the per-user session-revoke action. Keeps `data`, `loading`
 * and per-user `revoking` state.
 *
 * Extracted from the original AdminSecurity.jsx to isolate data-plane
 * concerns from presentation.
 */
import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { API } from "@/App";

export function useSecurityAudit() {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [revoking, setRevoking] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/admin/security/audit`, { withCredentials: true });
      setData(r.data);
    } catch (e) {
      const detail = e.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : t("admin.security.loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { load(); }, [load]);

  const revokeSessions = useCallback(async (userId, email) => {
    if (!window.confirm(t("admin.security.revokeConfirm", { email }))) return;
    setRevoking(userId);
    try {
      const r = await axios.post(
        `${API}/admin/security/sessions/${userId}/revoke`,
        {},
        { withCredentials: true },
      );
      toast.success(t("admin.security.sessionsRevokedToast", { n: r.data.revoked, email }));
      await load();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("admin.common.genericError"));
    } finally {
      setRevoking(null);
    }
  }, [t, load]);

  return { data, loading, revoking, load, revokeSessions };
}
