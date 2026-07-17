import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Pagination } from "@/components/Pagination";
import MonthlyAuditReport from "@/pages/admin/audit/MonthlyAuditReport";
import { Download, FileText } from "lucide-react";

const ACTION_BADGE = {
  "order.approved": "bg-[#F59E0B]/10 text-[#F59E0B] border-[#F59E0B]/30",
  "order.rejected": "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30",
  "order.completed": "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  "order.pending": "bg-neutral-700/40 text-neutral-400 border-neutral-700",
  "rate.update": "bg-[#8B5CF6]/10 text-[#8B5CF6] border-[#8B5CF6]/30",
  "user.update": "bg-[#3B82F6]/10 text-[#3B82F6] border-[#3B82F6]/30",
  "settings.update": "bg-[#8B5CF6]/10 text-[#8B5CF6] border-[#8B5CF6]/30",
};

const PAGE_SIZE = 50;

export default function AdminAudit({ hideMonthly = false }) {
  const { t } = useTranslation();
  const [entries, setEntries] = useState([]);
  const [actionFilter, setActionFilter] = useState("all");
  const [actorFilter, setActorFilter] = useState("");
  const [sinceFilter, setSinceFilter] = useState("");
  const [untilFilter, setUntilFilter] = useState("");
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setPage(0);
  }, [actionFilter, actorFilter, sinceFilter, untilFilter]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit: PAGE_SIZE, offset: page * PAGE_SIZE };
      if (actionFilter !== "all") params.action = actionFilter;
      if (actorFilter) params.actor_id = actorFilter;
      if (sinceFilter) params.since = sinceFilter;
      if (untilFilter) params.until = untilFilter;
      const r = await axios.get(`${API}/admin/audit`, { params, withCredentials: true });
      setEntries(r.data);
      const headerTotal = Number(r.headers["x-total-count"]);
      setTotal(Number.isFinite(headerTotal) ? headerTotal : r.data.length);
    } catch (e) {
      toast.error(t("admin.audit.loadError"));
    } finally {
      setLoading(false);
    }
  }, [actionFilter, actorFilter, sinceFilter, untilFilter, page, t]);
  useEffect(() => { load(); }, [load]);

  const downloadExport = async (kind) => {
    try {
      const params = new URLSearchParams();
      if (actionFilter !== "all") params.set("action", actionFilter);
      if (actorFilter) params.set("actor_id", actorFilter);
      if (sinceFilter) params.set("since", sinceFilter);
      if (untilFilter) params.set("until", untilFilter);
      const url = `${API}/admin/audit/export.${kind}?${params.toString()}`;
      const r = await axios.get(url, { responseType: "blob", withCredentials: true });
      const blobUrl = URL.createObjectURL(new Blob([r.data], { type: r.headers["content-type"] }));
      const a = document.createElement("a");
      a.href = blobUrl;
      const ts = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
      a.download = `audit_log_${ts}.${kind}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(blobUrl);
      toast.success(t("admin.audit.exportedToast", { kind: kind.toUpperCase() }));
    } catch (e) {
      toast.error(t("admin.audit.exportError", { kind: kind.toUpperCase() }));
    }
  };

  const clearDates = () => { setSinceFilter(""); setUntilFilter(""); };

  return (
    <div className="space-y-6" data-testid="admin-audit">
      {!hideMonthly && <MonthlyAuditReport />}

      <div className="flex flex-wrap gap-3 items-end justify-between">
        <div className="flex flex-wrap gap-3 items-end">
          <div>
            <div className="micro-label text-neutral-500 mb-1">{t("admin.audit.filterAction")}</div>
            <Select value={actionFilter} onValueChange={setActionFilter}>
              <SelectTrigger data-testid="audit-action-filter" className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-52">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                <SelectItem value="all">{t("admin.audit.allActions")}</SelectItem>
                <SelectItem value="order.approved">{t("admin.audit.actionOrderApproved")}</SelectItem>
                <SelectItem value="order.rejected">{t("admin.audit.actionOrderRejected")}</SelectItem>
                <SelectItem value="order.completed">{t("admin.audit.actionOrderCompleted")}</SelectItem>
                <SelectItem value="rate.update">{t("admin.audit.actionRateUpdate")}</SelectItem>
                <SelectItem value="user.update">{t("admin.audit.actionUserUpdate")}</SelectItem>
                <SelectItem value="settings.update">{t("admin.audit.actionSettings")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <div className="micro-label text-neutral-500 mb-1">{t("admin.audit.actor")}</div>
            <Input
              data-testid="audit-actor-filter"
              value={actorFilter}
              onChange={(e) => setActorFilter(e.target.value)}
              placeholder={t("admin.audit.actorPh")}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-64 font-mono text-xs"
            />
          </div>
          <div>
            <div className="micro-label text-neutral-500 mb-1">{t("admin.audit.since")}</div>
            <Input
              type="date"
              data-testid="audit-since-filter"
              value={sinceFilter}
              onChange={(e) => setSinceFilter(e.target.value)}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-40 font-mono text-xs"
            />
          </div>
          <div>
            <div className="micro-label text-neutral-500 mb-1">{t("admin.audit.until")}</div>
            <Input
              type="date"
              data-testid="audit-until-filter"
              value={untilFilter}
              onChange={(e) => setUntilFilter(e.target.value)}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-40 font-mono text-xs"
            />
          </div>
          {(sinceFilter || untilFilter) && (
            <button
              data-testid="audit-clear-dates"
              onClick={clearDates}
              className="text-xs text-neutral-500 hover:text-[#8B5CF6] underline underline-offset-4 h-10"
            >
              {t("admin.audit.clearDates")}
            </button>
          )}
        </div>
        <div className="flex gap-2">
          <Button
            data-testid="audit-export-csv"
            onClick={() => downloadExport("csv")}
            className="rounded-none bg-transparent border border-white/15 hover:border-[#8B5CF6]/60 hover:bg-[#8B5CF6]/5 text-white h-10 px-4 font-mono text-xs uppercase tracking-wider"
          >
            <Download className="w-3.5 h-3.5 mr-2" /> CSV
          </Button>
          <Button
            data-testid="audit-export-pdf"
            onClick={() => downloadExport("pdf")}
            className="rounded-none bg-[#8B5CF6] hover:bg-[#8B5CF6]/90 text-white h-10 px-4 font-mono text-xs uppercase tracking-wider font-bold"
          >
            <FileText className="w-3.5 h-3.5 mr-2" /> PDF
          </Button>
        </div>
      </div>

      <div className="tactile-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-[#0a0a0a] border-b border-white/10">
              <tr className="text-left">
                <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.audit.colWhen")}</th>
                <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.audit.colWho")}</th>
                <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.audit.colRole")}</th>
                <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.audit.colPerms")}</th>
                <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.audit.colAction")}</th>
                <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.audit.colSummary")}</th>
                <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.audit.colEntity")}</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan="7" className="text-center text-neutral-500 py-8">{t("admin.audit.loading")}</td></tr>
              )}
              {!loading && entries.length === 0 && (
                <tr><td colSpan="7" className="text-center text-neutral-500 py-8">{t("admin.audit.empty")}</td></tr>
              )}
              {entries.map((e) => (
                <tr key={e.id} className="border-b border-white/5 hover:bg-white/5">
                  <td className="px-4 py-3 text-xs text-neutral-400 font-mono whitespace-nowrap">{new Date(e.created_at).toLocaleString()}</td>
                  <td className="px-4 py-3 text-xs">{e.actor_name || e.actor_email}</td>
                  <td className="px-4 py-3"><span className="text-[0.65rem] uppercase tracking-wider text-neutral-500">{e.actor_role}</span></td>
                  <td className="px-4 py-3">
                    <PermissionsCell effective={e.actor_permissions_effective} raw={e.actor_permissions} t={t} />
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs uppercase tracking-wider border px-2 py-0.5 font-mono ${ACTION_BADGE[e.action] || "bg-neutral-700/40 text-neutral-300 border-neutral-700"}`}>
                      {e.action}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm">{e.summary}</td>
                  <td className="px-4 py-3 text-xs font-mono text-neutral-500">{e.entity_id?.slice(0, 8) || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {total > 0 && (
        <Pagination
          page={page}
          total={total}
          pageSize={PAGE_SIZE}
          loading={loading}
          onPageChange={setPage}
          testidPrefix="audit-pagination"
        />
      )}
    </div>
  );
}


function PermissionsCell({ effective, raw, t }) {
  if (effective === "all") {
    return (
      <span className="inline-flex items-center px-2 py-0.5 text-[0.65rem] uppercase tracking-wider bg-emerald-500/10 text-emerald-300 border border-emerald-500/30"
            data-testid="audit-perms-admin">
        {t("admin.audit.permsAdmin")}
      </span>
    );
  }
  if (effective === "all_staff_default" || (Array.isArray(effective) && effective.length === 0)) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 text-[0.65rem] uppercase tracking-wider bg-neutral-500/10 text-neutral-400 border border-neutral-500/30"
            data-testid="audit-perms-open">
        {t("admin.audit.permsOpen")}
      </span>
    );
  }
  const codes = Array.isArray(effective) ? effective : (raw || []);
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 text-[0.65rem] uppercase tracking-wider bg-[#8B5CF6]/10 text-[#8B5CF6] border border-[#8B5CF6]/30 cursor-help"
      title={codes.join(" · ")}
      data-testid="audit-perms-scoped"
    >
      {codes.length} {codes.length === 1 ? t("admin.audit.permsOne") : t("admin.audit.permsMany")}
    </span>
  );
}
