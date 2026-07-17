import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useTranslation, Trans } from "react-i18next";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Ban, Plus, Trash2, Search, Upload, CheckCircle2, AlertTriangle, SkipForward } from "lucide-react";
import { toast } from "sonner";

const emptyForm = { phone: "", email: "", name: "", reason: "", notes: "" };

export default function AdminBlockedContacts() {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState("");
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState(null);

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
    } finally { setLoading(false); }
  }, [q, t]);

  useEffect(() => { load(); }, [load]);

  const submit = async () => {
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
      await axios.post(`${API}/admin/blocked-contacts`,
        { phone: form.phone || null, email: form.email || null,
          name: form.name || null,
          reason: form.reason.trim(), notes: form.notes || null },
        { withCredentials: true },
      );
      toast.success(t("admin.blocked.blockedToast"));
      setForm(emptyForm); setOpen(false); load();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("admin.common.genericError"));
    } finally { setSaving(false); }
  };

  const remove = async (id) => {
    if (!window.confirm(t("admin.blocked.removeConfirm"))) return;
    try {
      await axios.delete(`${API}/admin/blocked-contacts/${id}`, { withCredentials: true });
      toast.success(t("admin.blocked.removeToast")); load();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("admin.common.genericError"));
    }
  };

  const submitBulkImport = async () => {
    if (!importText.trim()) {
      toast.error(t("admin.blocked.importPaste"));
      return;
    }
    setImporting(true);
    setImportResult(null);
    try {
      const r = await axios.post(`${API}/admin/blocked-contacts/bulk-import`,
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
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("admin.blocked.importError"));
    } finally { setImporting(false); }
  };

  const resetImport = () => {
    setImportText("");
    setImportResult(null);
    setImportOpen(false);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="font-display text-3xl flex items-center gap-2"><Ban className="w-7 h-7 text-[#EF4444]" /> {t("admin.blocked.title")}</h1>
          <p className="text-xs text-neutral-500 mt-1">{t("admin.blocked.subtitle")}</p>
        </div>
        <div className="flex gap-2">
          <Button data-testid="bulk-import-blocked-btn"
            onClick={() => { setImportText(""); setImportResult(null); setImportOpen(true); }}
            variant="outline"
            className="border-white/20 hover:border-[#8B5CF6] hover:bg-[#8B5CF6]/10 text-white rounded-none">
            <Upload className="w-4 h-4 mr-1" /> {t("admin.blocked.importList")}
          </Button>
          <Button data-testid="add-blocked-contact-btn"
            onClick={() => { setForm(emptyForm); setOpen(true); }}
            className="bg-[#EF4444] hover:bg-[#DC2626] text-white rounded-none">
            <Plus className="w-4 h-4 mr-1" /> {t("admin.blocked.blockContact")}
          </Button>
        </div>
      </div>

      <div className="tactile-card p-3 flex items-center gap-2">
        <Search className="w-4 h-4 text-neutral-500 ml-2" />
        <Input
          data-testid="blocked-contacts-search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("admin.blocked.searchPh")}
          className="rounded-none bg-transparent border-none focus-visible:ring-0 h-9"
        />
        <span className="text-xs text-neutral-500 mr-2 font-mono">{total} {t("admin.blocked.total")}</span>
      </div>

      <div className="tactile-card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="border-b border-white/10 bg-[#0F0F0F]">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.blocked.colPhone")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.blocked.colName")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.blocked.colEmail")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.blocked.colReason")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.blocked.colBlockedBy")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.blocked.colDate")}</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan="7" className="text-center text-neutral-500 py-8">{t("admin.common.loadingEllipsis")}</td></tr>}
            {!loading && items.length === 0 && <tr><td colSpan="7" className="text-center text-neutral-500 py-8">{t("admin.blocked.empty")}</td></tr>}
            {items.map((c) => (
              <tr key={c.id} data-testid={`blocked-row-${c.id}`} className="border-b border-white/5 hover:bg-white/[0.02]">
                <td className="px-4 py-3 font-mono text-neutral-300">{c.phone || <span className="text-neutral-600">—</span>}</td>
                <td className="px-4 py-3 text-neutral-300 text-xs">{c.name || <span className="text-neutral-600">—</span>}</td>
                <td className="px-4 py-3 text-neutral-300 text-xs break-all">{c.email || <span className="text-neutral-600">—</span>}</td>
                <td className="px-4 py-3 text-neutral-400 text-xs max-w-xs">
                  <div className="line-clamp-2 whitespace-pre-line">{c.reason}</div>
                  {c.notes && <div className="text-[0.65rem] text-neutral-600 mt-1 line-clamp-1">{c.notes}</div>}
                </td>
                <td className="px-4 py-3 text-xs text-neutral-500 break-all">{c.created_by_email}</td>
                <td className="px-4 py-3 text-xs text-neutral-500">{new Date(c.created_at).toLocaleDateString()}</td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => remove(c.id)}
                    data-testid={`unblock-${c.id}`}
                    title={t("admin.blocked.removeConfirm")}
                    className="text-neutral-400 hover:text-[#22C55E]"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent data-testid="block-contact-dialog" className="bg-[#14101F] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-display text-2xl">{t("admin.blocked.blockDialogTitle")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label className="micro-label text-neutral-500">{t("admin.blocked.phoneLabel")}</Label>
              <Input
                data-testid="block-phone-input"
                value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
                placeholder="+5350123456"
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono"
              />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("admin.blocked.nameLabel")}</Label>
              <Input
                data-testid="block-name-input"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder={t("admin.blocked.namePh")}
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"
              />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("admin.blocked.emailLabel")}</Label>
              <Input
                data-testid="block-email-input"
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder={t("admin.blocked.emailPh")}
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"
              />
            </div>
            <p className="text-[0.65rem] text-neutral-600 -mt-2">{t("admin.blocked.atLeastOne")}</p>
            <div>
              <Label className="micro-label text-neutral-500">{t("admin.blocked.reasonLabel")}</Label>
              <Input
                data-testid="block-reason-input"
                required
                value={form.reason}
                onChange={(e) => setForm({ ...form, reason: e.target.value })}
                placeholder={t("admin.blocked.reasonPh")}
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"
              />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("admin.blocked.notesLabel")}</Label>
              <Textarea
                data-testid="block-notes-input"
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                placeholder={t("admin.blocked.notesPh")}
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 min-h-[80px]"
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" onClick={() => setOpen(false)} className="rounded-none">{t("admin.blocked.cancel")}</Button>
              <Button
                data-testid="block-submit"
                onClick={submit}
                disabled={saving}
                className="bg-[#EF4444] hover:bg-[#DC2626] text-white rounded-none"
              >
                {saving ? t("admin.blocked.blocking") : t("admin.blocked.block")}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={importOpen} onOpenChange={(o) => { if (!o) resetImport(); else setImportOpen(true); }}>
        <DialogContent data-testid="bulk-import-dialog" className="bg-[#14101F] border-white/10 text-white rounded-none max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-display text-2xl flex items-center gap-2">
              <Upload className="w-6 h-6 text-[#8B5CF6]" /> {t("admin.blocked.importDialogTitle")}
            </DialogTitle>
            <DialogDescription className="text-neutral-500 text-xs">
              {t("admin.blocked.importDesc")}
            </DialogDescription>
          </DialogHeader>
          {!importResult ? (
            <div className="space-y-4">
              <div className="bg-[#0F0F0F] border border-white/5 p-3 text-[0.7rem] text-neutral-500 font-mono leading-relaxed">
                <div className="text-[0.65rem] text-neutral-400 mb-2 font-sans uppercase tracking-wider">{t("admin.blocked.exampleTitle")}</div>
                Estafador ❌️<br />
                +5359804084<br />
                +5356455618<br />
                📌Son la misma persona<br />
                📌Se hace pasar por Remesero<br />
                <br />
                Juan Pérez<br />
                +1-305-555-1234<br />
                📌Estafó $500 en venta USDT
              </div>
              <div>
                <Label className="micro-label text-neutral-500">{t("admin.blocked.importListLabel")}</Label>
                <Textarea
                  data-testid="bulk-import-textarea"
                  value={importText}
                  onChange={(e) => setImportText(e.target.value)}
                  placeholder={t("admin.blocked.importPh")}
                  className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 min-h-[280px] font-mono text-xs"
                />
              </div>
              <div className="flex justify-between items-center pt-2">
                <span className="text-[0.65rem] text-neutral-600">
                  {t("admin.blocked.importFooter")}
                </span>
                <div className="flex gap-2">
                  <Button variant="ghost" onClick={resetImport} className="rounded-none">{t("admin.blocked.cancel")}</Button>
                  <Button
                    data-testid="bulk-import-submit"
                    onClick={submitBulkImport}
                    disabled={importing || !importText.trim()}
                    className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none"
                  >
                    {importing ? t("admin.blocked.importing") : t("admin.blocked.importBtn")}
                  </Button>
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-4" data-testid="bulk-import-result">
              <div className="grid grid-cols-3 gap-2">
                <div className="tactile-card p-4 text-center">
                  <CheckCircle2 className="w-6 h-6 mx-auto text-[#22C55E] mb-1" />
                  <div className="font-display text-2xl text-[#22C55E]" data-testid="import-count-imported">{importResult.imported_count}</div>
                  <div className="text-[0.65rem] uppercase tracking-wider text-neutral-500">{t("admin.blocked.imported")}</div>
                </div>
                <div className="tactile-card p-4 text-center">
                  <SkipForward className="w-6 h-6 mx-auto text-[#8B5CF6] mb-1" />
                  <div className="font-display text-2xl text-[#8B5CF6]" data-testid="import-count-skipped">{importResult.skipped_count}</div>
                  <div className="text-[0.65rem] uppercase tracking-wider text-neutral-500">{t("admin.blocked.skipped")}</div>
                </div>
                <div className="tactile-card p-4 text-center">
                  <AlertTriangle className="w-6 h-6 mx-auto text-[#EF4444] mb-1" />
                  <div className="font-display text-2xl text-[#EF4444]" data-testid="import-count-invalid">{importResult.invalid_count}</div>
                  <div className="text-[0.65rem] uppercase tracking-wider text-neutral-500">{t("admin.blocked.invalid")}</div>
                </div>
              </div>
              {importResult.affected_active_accounts > 0 && (
                <div className="border-l-2 border-[#8B5CF6] bg-[#8B5CF6]/5 p-3 text-xs text-[#FEF3C7]">
                  <Trans
                    i18nKey="admin.blocked.importAffected"
                    values={{ n: importResult.affected_active_accounts }}
                    components={{ 1: <span className="font-semibold" />, 2: <strong /> }}
                  />
                </div>
              )}
              {importResult.invalid?.length > 0 && (
                <div>
                  <div className="text-xs uppercase tracking-wider text-neutral-500 mb-1">{t("admin.blocked.invalidEntriesTitle")}</div>
                  <div className="bg-[#0F0F0F] border border-[#EF4444]/30 p-2 max-h-32 overflow-y-auto text-xs font-mono">
                    {importResult.invalid.map((it) => (
                      <div key={`${it.phone}-${it.reason}`} className="text-neutral-400">• <span className="text-[#EF4444]">{it.phone}</span> — {it.reason}</div>
                    ))}
                  </div>
                </div>
              )}
              <div className="flex justify-end pt-2">
                <Button
                  data-testid="bulk-import-close"
                  onClick={resetImport}
                  className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none"
                >
                  {t("admin.blocked.closeBtn")}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
