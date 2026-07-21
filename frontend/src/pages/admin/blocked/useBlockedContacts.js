/**
 * iter85 — useBlockedContacts
 *
 * Data hook for the admin Blocked Contacts page. Owns the paginated fetch
 * (search-aware), the single-block create dialog state + submit, and the
 * remove flow. Extracted from the original AdminBlockedContacts.jsx.
 */
import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { API } from "@/App";

export const emptyForm = { phone: "", email: "", name: "", reason: "", notes: "" };

export function useBlockedContacts() {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/admin/blocked-contacts`, {
        params: { q: q || undefined, limit: 100 },
        withCredentials: true,
      });
      setItems(r.data.items);
      setTotal(r.data.total);
    } catch (e) {
      toast.error(e.response?.data?.detail || t("admin.blocked.loadError"));
    } finally {
      setLoading(false);
    }
  }, [q, t]);

  useEffect(() => { load(); }, [load]);

  const submit = useCallback(async () => {
    if (!form.phone && !form.email) {
      toast.error(t("admin.blocked.needPhoneOrEmail"));
      return;
    }
    if (!form.reason.trim()) {
      toast.error(t("admin.blocked.needReason"));
      return;
    }
    setSaving(true);
    try {
      await axios.post(
        `${API}/admin/blocked-contacts`,
        {
          phone: form.phone || null,
          email: form.email || null,
          name: form.name || null,
          reason: form.reason.trim(),
          notes: form.notes || null,
        },
        { withCredentials: true },
      );
      toast.success(t("admin.blocked.blockedToast"));
      setForm(emptyForm);
      setOpen(false);
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("admin.common.genericError"));
    } finally {
      setSaving(false);
    }
  }, [form, load, t]);

  const remove = useCallback(async (id) => {
    if (!window.confirm(t("admin.blocked.removeConfirm"))) return;
    try {
      await axios.delete(`${API}/admin/blocked-contacts/${id}`, { withCredentials: true });
      toast.success(t("admin.blocked.removeToast"));
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("admin.common.genericError"));
    }
  }, [load, t]);

  const openBlockDialog = useCallback(() => {
    setForm(emptyForm);
    setOpen(true);
  }, []);

  return {
    items, total, q, setQ, loading,
    open, setOpen, form, setForm, saving,
    load, submit, remove, openBlockDialog,
  };
}
