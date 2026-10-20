import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Building2, Check, X, Clock, Hash, MapPin, Phone, FileText } from "lucide-react";
import { useLiveEvent } from "@/hooks/useLiveStream";
import AdminPageHeader from "@/components/AdminPageHeader";

// Etiquetas de documentos del KYB Empresa (orden fijo).
const DOC_LABELS = {
  operating_license: "Licencia operativa",
  legal_rep_id: "ID representante legal",
  tax_certificate: "Certificado fiscal",
};

/**
 * Cola admin de solicitudes del Programa Empresas.
 * Tab dentro de AdminUsersHub (`/admin/users?tab=company-kyb`).
 * Requiere permiso `company_requests` (el admin pasa siempre).
 *
 * Aprobar → crea una cuenta Empresa NUEVA e independiente (el backend lo
 * hace de forma atómica). Rechazar → captura una nota opcional.
 */
export default function AdminCompanyRequests() {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [statusFilter, setStatusFilter] = useState("pending");
  const [loading, setLoading] = useState(true);
  const [rejecting, setRejecting] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/admin/company-requests`, {
        params: statusFilter !== "all" ? { status: statusFilter } : {},
        withCredentials: true,
      });
      setItems(r.data?.items || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("adminCompanyRequests.loadError"));
    } finally {
      setLoading(false);
    }
  }, [statusFilter, t]);

  useEffect(() => { load(); }, [load]);
  useLiveEvent("company_request_created", load);
  useLiveEvent("company_request_updated", load);

  const approve = async (id) => {
    setBusyId(id);
    try {
      await axios.post(`${API}/admin/company-requests/${id}/approve`, {}, { withCredentials: true });
      toast.success(t("adminCompanyRequests.approvedToast"));
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("adminCompanyRequests.actionError"));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-4" data-testid="admin-company-requests">
      <AdminPageHeader
        eyebrow={t("adminCompanyRequests.eyebrow")}
        title={t("adminCompanyRequests.title")}
        testid="admin-company-requests-header"
      />

      <div className="flex items-center gap-2 flex-wrap">
        {["pending", "approved", "rejected", "all"].map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setStatusFilter(s)}
            data-testid={`company-requests-filter-${s}`}
            className={`text-xs uppercase tracking-widest px-3 py-1.5 border font-mono transition-colors ${
              statusFilter === s
                ? "bg-[#8B5CF6]/10 border-[#8B5CF6] text-[#8B5CF6]"
                : "bg-transparent border-white/10 text-neutral-400 hover:border-white/30"
            }`}
          >
            {t(`adminCompanyRequests.filter.${s}`)}
          </button>
        ))}
      </div>

      <div className="tactile-card overflow-x-auto">
        <table className="w-full text-sm min-w-[980px]">
          <thead className="border-b border-white/10 bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminCompanyRequests.colRequester")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminCompanyRequests.colCompany")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminCompanyRequests.colAccount")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminCompanyRequests.colDetails")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminCompanyRequests.colDocuments")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 whitespace-nowrap">{t("adminCompanyRequests.colCreated")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminCompanyRequests.colStatus")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminCompanyRequests.colActions")}</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan="8" className="text-center text-neutral-500 py-8">
                {t("admin.common.loadingEllipsis")}
              </td></tr>
            )}
            {!loading && items.length === 0 && (
              <tr><td colSpan="8" className="text-center text-neutral-500 py-8" data-testid="admin-company-requests-empty">
                {t("adminCompanyRequests.empty")}
              </td></tr>
            )}
            {!loading && items.map((it) => (
              <tr key={it.id} className="border-b border-white/5" data-testid={`company-request-row-${it.id}`}>
                <td className="px-4 py-3">
                  <div className="text-white">{it.user_name || "—"}</div>
                  <div className="text-xs text-neutral-500">{it.user_email}</div>
                </td>
                <td className="px-4 py-3">
                  <div className="text-white inline-flex items-center gap-1">
                    <Building2 className="w-3 h-3 text-[#8B5CF6]" />
                    {it.company_name}
                  </div>
                  <div className="text-xs text-neutral-500 inline-flex items-center gap-1 mt-0.5">
                    <Hash className="w-3 h-3" /> {it.tax_id}
                  </div>
                </td>
                <td className="px-4 py-3 text-xs">
                  <div className="text-neutral-200 font-mono">{it.account_email}</div>
                  <div className="text-neutral-500 inline-flex items-center gap-1 mt-0.5">
                    <Phone className="w-3 h-3" /> {it.company_phone}
                  </div>
                </td>
                <td className="px-4 py-3 text-xs text-neutral-400 max-w-xs">
                  <div className="inline-flex items-start gap-1">
                    <MapPin className="w-3 h-3 mt-0.5 shrink-0" />
                    <span className="line-clamp-3">{it.address}</span>
                  </div>
                </td>
                <td className="px-4 py-3 text-xs">
                  {(it.documents || []).length === 0 ? (
                    <span className="text-neutral-600">—</span>
                  ) : (
                    <div className="flex flex-col gap-1">
                      {it.documents.map((d) => (
                        <a
                          key={d.doc_type}
                          href={d.ref}
                          target="_blank"
                          rel="noreferrer"
                          data-testid={`company-doc-${it.id}-${d.doc_type}`}
                          className="inline-flex items-center gap-1 text-[#8B5CF6] hover:underline"
                        >
                          <FileText className="w-3 h-3 shrink-0" />
                          {DOC_LABELS[d.doc_type] || d.doc_type}
                        </a>
                      ))}
                    </div>
                  )}
                </td>
                <td className="px-4 py-3 text-xs text-neutral-500 whitespace-nowrap">
                  {new Date(it.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3"><StatusPill status={it.status} /></td>
                <td className="px-4 py-3">
                  {it.status === "pending" ? (
                    <div className="flex gap-2">
                      <Button
                        onClick={() => approve(it.id)}
                        disabled={busyId === it.id}
                        data-testid={`company-approve-${it.id}`}
                        className="rounded-none bg-emerald-500 hover:bg-emerald-400 text-black h-8 px-3 text-xs font-semibold disabled:opacity-40"
                      >
                        <Check className="w-3 h-3 mr-1" /> {t("adminCompanyRequests.approve")}
                      </Button>
                      <Button
                        onClick={() => setRejecting(it)}
                        data-testid={`company-reject-${it.id}`}
                        variant="ghost"
                        className="rounded-none border border-[#EF4444]/40 text-[#EF4444] hover:bg-[#EF4444]/10 h-8 px-3 text-xs"
                      >
                        <X className="w-3 h-3 mr-1" /> {t("adminCompanyRequests.reject")}
                      </Button>
                    </div>
                  ) : (
                    <span className="text-xs text-neutral-500">
                      {it.reviewed_at ? new Date(it.reviewed_at).toLocaleDateString() : "—"}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <RejectDialog
        open={!!rejecting}
        request={rejecting}
        onClose={() => setRejecting(null)}
        onDone={() => { setRejecting(null); load(); }}
      />
    </div>
  );
}


function StatusPill({ status }) {
  const { t } = useTranslation();
  const meta = {
    pending:  { cls: "bg-[#8B5CF6]/10 text-[#A78BFA] border-[#8B5CF6]/30", Icon: Clock },
    approved: { cls: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30", Icon: Check },
    rejected: { cls: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30", Icon: X },
  }[status] || {};
  const Icon = meta.Icon || Building2;
  return (
    <span className={`inline-flex items-center gap-1 text-[0.65rem] uppercase tracking-widest border px-2 py-1 font-mono ${meta.cls || ""}`}>
      <Icon className="w-3 h-3" />
      {t(`companyRequest.status.${status}`, status)}
    </span>
  );
}


function RejectDialog({ open, request, onClose, onDone }) {
  const { t } = useTranslation();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (open) setNote(""); }, [open]);

  const submit = async () => {
    if (!request) return;
    setBusy(true);
    try {
      await axios.post(
        `${API}/admin/company-requests/${request.id}/reject`,
        { admin_note: note.trim() },
        { withCredentials: true },
      );
      toast.success(t("adminCompanyRequests.rejectedToast"));
      onDone?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("adminCompanyRequests.actionError"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent
        data-testid="company-reject-dialog"
        className="bg-[#0c0c0c] border border-[#EF4444]/30 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle>{t("adminCompanyRequests.rejectDialogTitle")}</DialogTitle>
        </DialogHeader>
        <p className="text-xs text-neutral-400">
          {t(request?.requester_anonymous
            ? "adminCompanyRequests.rejectDialogBodyAnon"
            : "adminCompanyRequests.rejectDialogBody", {
            name: request?.company_name || request?.user_email || "",
          })}
        </p>
        <textarea
          data-testid="company-reject-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={4}
          maxLength={500}
          placeholder={t("adminCompanyRequests.rejectDialogPlaceholder")}
          className="w-full mt-3 bg-black/40 border border-white/10 rounded-none px-3 py-2 text-sm text-white placeholder:text-neutral-600 focus:border-[#EF4444]/50 focus:outline-none"
        />
        <div className="flex justify-end gap-2 pt-3 border-t border-white/5 mt-2">
          <Button variant="ghost" onClick={onClose} className="rounded-none text-neutral-400">
            {t("common.cancel")}
          </Button>
          <Button
            onClick={submit}
            disabled={busy}
            data-testid="company-reject-confirm"
            className="rounded-none bg-[#EF4444] hover:bg-[#F87171] text-white disabled:opacity-40"
          >
            {t("adminCompanyRequests.reject")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
