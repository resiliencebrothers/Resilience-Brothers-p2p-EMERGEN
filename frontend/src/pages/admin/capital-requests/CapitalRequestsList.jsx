/**
 * iter86 — CapitalRequestsList
 *
 * Presentational grid + individual card renderer for capital requests.
 * Handles the STATUS_META colour dictionary, the empty state and the
 * progress bar for `disbursed` items.
 *
 * All side-effects (approve / reject / TOTP) delegate to callbacks that
 * come from useCapitalRequests.
 */
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import AdminPageHeader from "@/components/AdminPageHeader";
import { CheckCircle2, XCircle, Clock, HandCoins, Filter, Search } from "lucide-react";

const fmtNum = (n, d = 2) =>
  Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: d });
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString() : "—");

function useStatusMeta() {
  const { t } = useTranslation();
  return {
    pending:   { label: t("admin.capitalRequests.statusPending"),   cls: "text-amber-400 border-amber-500/40 bg-amber-500/5", icon: Clock },
    disbursed: { label: t("admin.capitalRequests.statusDisbursed"), cls: "text-[#8B5CF6] border-[#8B5CF6]/40 bg-[#8B5CF6]/5", icon: HandCoins },
    paid_off:  { label: t("admin.capitalRequests.statusPaidOff"),   cls: "text-emerald-400 border-emerald-500/40 bg-emerald-500/5", icon: CheckCircle2 },
    rejected:  { label: t("admin.capitalRequests.statusRejected"),  cls: "text-red-400 border-red-500/40 bg-red-500/5", icon: XCircle },
  };
}

export default function CapitalRequestsList({
  items, statusFilter, setStatusFilter,
  clientQuery, setClientQuery,
  loading, onApprove, onReject,
}) {
  const { t } = useTranslation();
  const STATUS_META = useStatusMeta();

  const header = (
    <AdminPageHeader
      eyebrow={t("admin.capitalRequests.eyebrow")}
      title={t("admin.capitalRequests.title")}
      subtitle={t("admin.capitalRequests.subtitle")}
      actions={
        <div className="flex items-center gap-2 flex-wrap">
          {/* iter87 — Search by client name/email. */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-neutral-500 pointer-events-none" />
            <Input
              data-testid="cr-filter-client"
              value={clientQuery}
              onChange={(e) => setClientQuery(e.target.value)}
              placeholder={t("admin.capitalRequests.searchClientPh")}
              className="w-56 rounded-none bg-[#0a0a0a] border-white/10 h-10 pl-8 font-mono text-xs"
            />
            {clientQuery && (
              <button
                type="button"
                onClick={() => setClientQuery("")}
                data-testid="cr-filter-client-clear"
                title={t("admin.capitalRequests.searchClear")}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-neutral-500 hover:text-white"
              >
                ×
              </button>
            )}
          </div>
          <Filter className="w-4 h-4 text-neutral-500" />
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger
              className="w-44 rounded-none bg-[#0a0a0a] border-white/10 h-10"
              data-testid="cr-filter-status"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
              <SelectItem value="all">{t("admin.capitalRequests.allFilter")}</SelectItem>
              <SelectItem value="pending">{t("admin.capitalRequests.pendingFilter")}</SelectItem>
              <SelectItem value="disbursed">{t("admin.capitalRequests.disbursedFilter")}</SelectItem>
              <SelectItem value="paid_off">{t("admin.capitalRequests.paidOffFilter")}</SelectItem>
              <SelectItem value="rejected">{t("admin.capitalRequests.rejectedFilter")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      }
    />
  );

  if (loading) {
    return (
      <>
        {header}
        <div className="text-neutral-500 p-6">{t("admin.capitalRequests.loading")}</div>
      </>
    );
  }
  if (items.length === 0) {
    const isFiltered = statusFilter !== "all" || (clientQuery && clientQuery.trim() !== "");
    return (
      <>
        {header}
        <div className="tactile-card p-10 text-center text-neutral-500" data-testid="cr-empty">
          {isFiltered
            ? t("admin.capitalRequests.emptyFiltered")
            : t("admin.capitalRequests.empty")}
        </div>
      </>
    );
  }
  return (
    <>
      {header}
      <div className="space-y-3">
        {items.map((cr) => (
          <CapitalRequestCard
            key={cr.id}
            cr={cr}
            meta={STATUS_META[cr.status] || STATUS_META.pending}
            onApprove={onApprove}
            onReject={onReject}
            t={t}
          />
        ))}
      </div>
    </>
  );
}

function CapitalRequestCard({ cr, meta, onApprove, onReject, t }) {
  const StatusIcon = meta.icon;
  const paidPct = cr.debt_original
    ? Math.round(((cr.debt_original - (cr.debt_remaining || 0)) / cr.debt_original) * 100)
    : 0;
  return (
    <div className="tactile-card p-5" data-testid={`cr-item-${cr.id}`}>
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex-1 min-w-[260px]">
          <div className="flex items-center gap-2 mb-1">
            <span className={`text-[0.65rem] uppercase tracking-widest border px-2 py-0.5 flex items-center gap-1 ${meta.cls}`}>
              <StatusIcon className="w-3 h-3" /> {meta.label}
            </span>
            <span className="text-neutral-500 text-xs">{fmtDate(cr.created_at)}</span>
          </div>
          <div className="font-display text-xl">
            {cr.user_name || t("admin.capitalRequests.noName")}
            <span className="text-sm text-neutral-500 ml-2 font-mono">
              {cr.user_email}
            </span>
          </div>
          <div className="text-sm text-neutral-300 mt-2 leading-relaxed max-w-xl">
            {cr.reason}
          </div>
          {cr.status === "rejected" && cr.reject_reason && (
            <div className="mt-2 text-xs text-red-400">
              {t("admin.capitalRequests.rejectReason", { reason: cr.reject_reason })}
            </div>
          )}
          {cr.status === "disbursed" && cr.admin_notes && (
            <div className="mt-2 text-xs text-neutral-500">
              {t("admin.capitalRequests.adminNotes", { notes: cr.admin_notes })}
            </div>
          )}
        </div>
        <div className="text-right">
          <div className="micro-label text-neutral-500">
            {t("admin.capitalRequests.amountRequested")}
          </div>
          <div className="font-display text-2xl tabular-nums">
            {fmtNum(cr.amount, 2)}
            <span className="text-sm text-neutral-500"> {cr.currency_code}</span>
          </div>
          {cr.status === "disbursed" && (
            <>
              <div className="mt-2 text-xs text-neutral-500">
                {t("admin.capitalRequests.remaining")}{" "}
                <span className="text-red-400 tabular-nums">
                  {fmtNum(cr.debt_remaining, 2)} {cr.currency_code}
                </span>
              </div>
              <div className="mt-1 text-[0.65rem] text-[#8B5CF6]">
                {t("admin.capitalRequests.discountPerOrder", { pct: cr.discount_pct })}
              </div>
            </>
          )}
        </div>
      </div>

      {cr.status === "disbursed" && (
        <div className="mt-4">
          <div className="h-1.5 bg-white/5">
            <div className="h-full bg-emerald-500 transition-all" style={{ width: `${paidPct}%` }} />
          </div>
          <div className="text-[0.65rem] text-neutral-500 mt-1 uppercase tracking-widest">
            {t("admin.capitalRequests.paidPct", { pct: paidPct, n: (cr.repayment_events || []).length })}
          </div>
        </div>
      )}

      {cr.status === "pending" && (
        <div className="flex gap-2 mt-4">
          <Button
            data-testid={`cr-approve-${cr.id}`}
            onClick={() => onApprove(cr)}
            className="rounded-none bg-emerald-600 hover:bg-emerald-500 text-white h-9 px-4 text-xs uppercase tracking-wider font-bold"
          >
            <CheckCircle2 className="w-4 h-4 mr-1.5" /> {t("admin.capitalRequests.approve")}
          </Button>
          <Button
            data-testid={`cr-reject-${cr.id}`}
            onClick={() => onReject(cr)}
            className="rounded-none bg-red-600 hover:bg-red-500 text-white h-9 px-4 text-xs uppercase tracking-wider font-bold"
          >
            <XCircle className="w-4 h-4 mr-1.5" /> {t("admin.capitalRequests.reject")}
          </Button>
        </div>
      )}
    </div>
  );
}
