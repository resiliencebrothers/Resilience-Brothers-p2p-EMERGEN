import { useEffect, useState, useCallback, useRef } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { ArrowUpCircle, ArrowDownCircle, ArrowRightLeft, Check, X as XIcon, Clock, Eye, Search } from "lucide-react";
import { useLiveRefresh } from "@/hooks/useLiveStream";
import { TopScrollTable } from "@/components/TopScrollTable";
import CopyableText from "@/components/CopyableText";

// iter171 — coalesce SSE bursts (new_vip_batch + vip_batch_item_decision)
// into a single refetch to prevent the queue from getting stuck in
// "Cargando..." when many orders arrive at once.
const LIVE_EVENTS = ["new_vip_batch", "vip_batch_item_decision"];

/**
 * iter110 · Phase 1 — Admin queue for VIP batch items.
 *
 * Flat "items pending" view (grouped visually by direction).
 * Requires the standard `orders` permission (same as classic order queue).
 */
export default function AdminVipBatchItems({ onChanged }) {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [statusFilter, setStatusFilter] = useState("pending");
  const [loading, setLoading] = useState(true);
  const [rejecting, setRejecting] = useState(null);
  const [viewing, setViewing] = useState(null);
  const [pairFilter, setPairFilter] = useState("all");
  const [pairCounts, setPairCounts] = useState([]);
  // iter189 — search by VIP name/email, holder or card + created date range.
  const [search, setSearch] = useState("");
  const [searchDebounced, setSearchDebounced] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  useEffect(() => {
    const id = setTimeout(() => setSearchDebounced(search), 400);
    return () => clearTimeout(id);
  }, [search]);
  // iter171 — abort in-flight request when a newer one starts so stale
  // responses can never overwrite fresh data or leave `loading=true`.
  const abortRef = useRef(null);
  const initialLoadRef = useRef(true);

  const load = useCallback(async () => {
    if (abortRef.current) {
      try { abortRef.current.abort(); } catch (_) { /* ignore */ }
    }
    const controller = new AbortController();
    abortRef.current = controller;
    if (initialLoadRef.current) setLoading(true);
    try {
      const r = await axios.get(`${API}/admin/vip-batches`, {
        params: {
          status: statusFilter,
          limit: 300,
          ...(pairFilter !== "all" ? { pair: pairFilter } : {}),
          ...(searchDebounced.trim() ? { q: searchDebounced.trim() } : {}),
          ...(dateFrom ? { date_from: dateFrom } : {}),
          ...(dateTo ? { date_to: dateTo } : {}),
        },
        withCredentials: true,
        signal: controller.signal,
        timeout: 30000,
      });
      setItems(r.data?.items || []);
      setPairCounts(r.data?.pair_counts || []);
      onChanged?.();
    } catch (err) {
      if (axios.isCancel(err) || err?.code === "ERR_CANCELED") return;
      toast.error(err?.response?.data?.detail || t("adminVipBatches.loadError"));
    } finally {
      if (abortRef.current === controller) {
        setLoading(false);
        initialLoadRef.current = false;
        abortRef.current = null;
      }
    }
  }, [statusFilter, pairFilter, searchDebounced, dateFrom, dateTo, t, onChanged]);

  useEffect(() => { load(); }, [load]);
  useLiveRefresh(load, LIVE_EVENTS);

  useEffect(() => () => {
    if (abortRef.current) {
      try { abortRef.current.abort(); } catch (_) { /* ignore */ }
    }
  }, []);

  const approve = async (id) => {
    try {
      await axios.post(`${API}/admin/vip-batches/items/${id}/approve`, {}, { withCredentials: true });
      toast.success(t("adminVipBatches.approvedToast"));
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("adminVipBatches.actionError"));
    }
  };

  return (
    <div className="space-y-4" data-testid="admin-vip-batches">
      <div className="flex items-center gap-2 flex-wrap">
        {["pending", "approved", "rejected"].map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setStatusFilter(s)}
            data-testid={`vip-batches-filter-${s}`}
            className={`text-xs uppercase tracking-widest px-3 py-1.5 border font-mono transition-colors ${
              statusFilter === s
                ? "bg-[#8B5CF6]/10 border-[#8B5CF6] text-[#8B5CF6]"
                : "bg-transparent border-white/10 text-neutral-400 hover:border-white/30"
            }`}
          >
            {t(`adminVipBatches.filter.${s}`)}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-2 flex-wrap" data-testid="vip-batches-search-row">
        <div className="relative flex-1 min-w-[220px] max-w-md">
          <Search className="w-4 h-4 text-neutral-500 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
          <Input
            data-testid="vip-batches-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("adminVipBatches.searchPh")}
            className="rounded-none bg-[#0a0a0a] border-white/10 h-9 pl-9 text-sm"
          />
        </div>
        <label className="flex items-center gap-1.5 text-[0.65rem] uppercase tracking-widest text-neutral-500">
          {t("adminVipBatches.dateFrom")}
          <input
            type="date"
            data-testid="vip-batches-date-from"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="bg-[#0a0a0a] border border-white/10 text-neutral-300 text-xs px-2 py-1.5 font-mono [color-scheme:dark]"
          />
        </label>
        <label className="flex items-center gap-1.5 text-[0.65rem] uppercase tracking-widest text-neutral-500">
          {t("adminVipBatches.dateTo")}
          <input
            type="date"
            data-testid="vip-batches-date-to"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="bg-[#0a0a0a] border border-white/10 text-neutral-300 text-xs px-2 py-1.5 font-mono [color-scheme:dark]"
          />
        </label>
        {(search || dateFrom || dateTo) && (
          <button
            type="button"
            data-testid="vip-batches-clear-filters"
            onClick={() => { setSearch(""); setDateFrom(""); setDateTo(""); }}
            className="text-[0.65rem] uppercase tracking-widest text-[#8B5CF6] hover:text-[#A78BFA] font-semibold"
          >
            {t("adminVipBatches.clearFilters")}
          </button>
        )}
      </div>

      <PairFilterChips
        pairCounts={pairCounts}
        pairFilter={pairFilter}
        onSelect={setPairFilter}
      />

      <div className="tactile-card overflow-hidden">
        <TopScrollTable deps={[items, loading]} maxHeightClass="max-h-[65vh]" testid="vip-batches">
          <table className="w-full text-sm min-w-[900px]">
            <thead className="border-b border-white/10 bg-[#0a0a0a] sticky top-0 z-10">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminVipBatches.colVip")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminVipBatches.colDirection")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminVipBatches.colHolder")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("adminVipBatches.colAmount")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 whitespace-nowrap">{t("adminVipBatches.colCreated")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminVipBatches.colStatus")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminVipBatches.colActions")}</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan="7" className="text-center text-neutral-500 py-8">{t("admin.common.loadingEllipsis")}</td></tr>
            )}
            {!loading && items.length === 0 && (
              <tr><td colSpan="7" className="text-center text-neutral-500 py-8" data-testid="admin-vip-batches-empty">
                {t("adminVipBatches.empty")}
              </td></tr>
            )}
            {!loading && items.map((it) => (
              <tr key={it.id} className="border-b border-white/5" data-testid={`vip-item-row-${it.id}`}>
                <td className="px-4 py-3">
                  <div className="text-white text-xs truncate max-w-[140px]">{it.vip_name || "—"}</div>
                  <div className="text-[0.6rem] text-neutral-500 font-mono">{it.vip_user_id.slice(-8)}</div>
                </td>
                <td className="px-4 py-3">
                  <DirBadge direction={it.direction} item={it} />
                </td>
                <td className="px-4 py-3 text-white">{it.holder_name}</td>
                <td className="px-4 py-3 font-mono text-white text-right">
                  {Number(it.amount).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  <span className="text-[0.6rem] text-neutral-500 ml-1">{it.from_code || it.currency}</span>
                  {it.amount_to != null && it.to_code && (
                    <div className="text-[0.65rem] text-emerald-400" data-testid={`vip-item-credit-${it.id}`}>
                      → {Number(it.amount_to).toLocaleString(undefined, { maximumFractionDigits: 4 })} {it.to_code}
                    </div>
                  )}
                  {it.payment_account_label && (
                    <div className="text-[0.6rem] text-neutral-500 font-normal" data-testid={`vip-item-account-${it.id}`}>
                      {it.payment_account_label}
                    </div>
                  )}
                </td>
                <td className="px-4 py-3 text-xs text-neutral-500 whitespace-nowrap">
                  {new Date(it.created_at).toLocaleString()}
                </td>
                <td className="px-4 py-3">
                  <ItemPill status={it.status} />
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setViewing(it)}
                      data-testid={`vip-item-view-${it.id}`}
                      title={t("adminVipBatches.viewDetails")}
                      className="text-neutral-400 hover:text-[#8B5CF6] transition-colors"
                    >
                      <Eye className="w-4 h-4" />
                    </button>
                    {it.status === "pending" ? (
                      <div className="flex gap-2">
                        <Button
                          onClick={() => approve(it.id)}
                          data-testid={`vip-item-approve-${it.id}`}
                          className="rounded-none bg-emerald-500 hover:bg-emerald-400 text-black h-8 px-3 text-xs font-semibold"
                        >
                          <Check className="w-3 h-3 mr-1" /> {t("adminVipBatches.approve")}
                        </Button>
                        <Button
                          onClick={() => setRejecting(it)}
                          data-testid={`vip-item-reject-${it.id}`}
                          variant="ghost"
                          className="rounded-none border border-[#EF4444]/40 text-[#EF4444] hover:bg-[#EF4444]/10 h-8 px-3 text-xs"
                        >
                          <XIcon className="w-3 h-3 mr-1" /> {t("adminVipBatches.reject")}
                        </Button>
                      </div>
                    ) : (
                      <span className="text-xs text-neutral-500">
                        {it.margin_usdt != null && it.status === "approved" ? (
                          <span className="text-emerald-400" data-testid={`vip-item-margin-${it.id}`}>
                            {t("adminVipBatches.marginLabel")}: {Number(it.margin_usdt) >= 0 ? "+" : ""}{Number(it.margin_usdt).toFixed(2)} USDT
                          </span>
                        ) : it.balance_delta_usdt != null ? (
                          `${it.direction === "credit" ? "+" : "-"}$${Number(it.balance_delta_usdt).toFixed(2)} USDT`
                        ) : "—"}
                      </span>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
          </table>
        </TopScrollTable>
      </div>

      <RejectDialog
        open={!!rejecting}
        item={rejecting}
        onClose={() => setRejecting(null)}
        onDone={() => { setRejecting(null); load(); }}
      />

      <DetailsDialog
        open={!!viewing}
        item={viewing}
        onClose={() => setViewing(null)}
      />
    </div>
  );
}


function DetailRow({ label, value, mono = true, tone = "text-white", testid, copyable = false, copyValue, copyToast, copyTestid }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1.5 border-b border-white/5">
      <span className="micro-label text-neutral-500 shrink-0">{label}</span>
      {copyable ? (
        <span className={`text-sm text-right break-all ${tone} inline-flex items-center justify-end min-w-0 max-w-full`} data-testid={testid}>
          <CopyableText
            value={copyValue ?? value}
            monospace={mono}
            toastMessage={copyToast}
            testid={copyTestid}
          />
        </span>
      ) : (
        <span className={`text-sm text-right break-all ${mono ? "font-mono" : ""} ${tone}`} data-testid={testid}>
          {value}
        </span>
      )}
    </div>
  );
}


function DetailsDialog({ open, item, onClose }) {
  const { t } = useTranslation();
  if (!item) return null;
  const fmt = (n, d = 2) => Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: 4 });
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent
        data-testid="vip-item-details-dialog"
        className="bg-[#0c0c0c] border border-white/10 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="font-mono text-base">
            {t("adminVipBatches.detailsTitle", { id: item.id.slice(-8) })}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-0.5">
          <DetailRow label={t("adminVipBatches.dClient")} value={item.vip_name || "—"} mono={false} testid="vip-item-detail-client" />
          <DetailRow label={t("adminVipBatches.dEmail")} value={item.vip_email || "—"} testid="vip-item-detail-email" />
          <DetailRow
            label={item.to_code ? t("adminVipBatches.dPair") : t("adminVipBatches.colDirection")}
            value={item.to_code ? `${item.from_code} → ${item.to_code}` : t(`vipBatches.direction.${item.direction}`)}
            tone="text-[#A78BFA]"
          />
          <DetailRow
            label={t("adminVipBatches.dHolder")}
            value={item.holder_name}
            mono={false}
            testid="vip-item-detail-holder"
            copyable
            copyValue={item.holder_name}
            copyToast={t("adminVipBatches.copiedHolder")}
            copyTestid="vip-item-detail-holder-copy"
          />
          {item.card_number && (
            <DetailRow
              label={t("adminVipBatches.dCard")}
              value={item.card_number}
              tone="text-[#22C55E]"
              testid="vip-item-detail-card"
              copyable
              copyValue={item.card_number.replace(/\s+/g, "")}
              copyToast={t("adminVipBatches.copiedCard")}
              copyTestid="vip-item-detail-card-copy"
            />
          )}
          <DetailRow
            label={t("adminVipBatches.dSends")}
            value={`${fmt(item.amount)} ${item.from_code || item.currency}`}
            testid="vip-item-detail-sends"
            copyable
            copyValue={String(item.amount)}
            copyToast={t("adminVipBatches.copiedAmount")}
            copyTestid="vip-item-detail-sends-copy"
          />
          {item.payment_account_label && (
            <DetailRow
              label={t("adminVipBatches.dPayAccount")}
              value={item.payment_account_label}
              mono={false}
              tone="text-emerald-400"
              testid="vip-item-detail-account"
            />
          )}
          {item.payment_account_details && (
            <DetailRow
              label={t("adminVipBatches.dPayAccountDetails")}
              value={item.payment_account_details}
              testid="vip-item-detail-account-details"
              copyable
              copyValue={item.payment_account_details}
              copyToast={t("adminVipBatches.copiedAccount")}
              copyTestid="vip-item-detail-account-copy"
            />
          )}
          {item.amount_to != null && item.to_code && (
            <DetailRow label={t("adminVipBatches.dReceives")} value={`${fmt(item.amount_to)} ${item.to_code}`} tone="text-emerald-400" testid="vip-item-detail-receives" />
          )}
          {item.rate_applied != null && (
            <DetailRow label={t("adminVipBatches.dRate")} value={fmt(item.rate_applied, 0)} tone="text-[#8B5CF6]" testid="vip-item-detail-rate" />
          )}
          {item.real_rate_applied != null && (
            <DetailRow label={t("adminVipBatches.dRealRate")} value={fmt(item.real_rate_applied, 0)} />
          )}
          {item.margin_usdt != null && item.status === "approved" && (
            <DetailRow
              label={t("adminVipBatches.dMargin")}
              value={`${Number(item.margin_usdt) >= 0 ? "+" : ""}${Number(item.margin_usdt).toFixed(2)} USDT`}
              tone={Number(item.margin_usdt) >= 0 ? "text-emerald-400" : "text-[#EF4444]"}
            />
          )}
          <div className="flex items-start justify-between gap-4 py-1.5 border-b border-white/5">
            <span className="micro-label text-neutral-500 shrink-0">{t("adminVipBatches.colStatus")}</span>
            <ItemPill status={item.status} />
          </div>
          {item.admin_note && (
            <DetailRow label={t("adminVipBatches.dAdminNote")} value={item.admin_note} mono={false} tone="text-amber-300" />
          )}
          <DetailRow label={t("adminVipBatches.colCreated")} value={new Date(item.created_at).toLocaleString()} />
          {item.reviewed_at && (
            <DetailRow label={t("adminVipBatches.dReviewed")} value={new Date(item.reviewed_at).toLocaleString()} />
          )}
          {item.reviewed_by_name && (
            <DetailRow label={t("adminVipBatches.dReviewedBy")} value={item.reviewed_by_name} mono={false} />
          )}
          <DetailRow label={t("adminVipBatches.dBatch")} value={item.batch_id.slice(-8)} tone="text-neutral-400" />
        </div>
        <div className="flex justify-end pt-3 border-t border-white/5 mt-2">
          <Button
            variant="ghost"
            onClick={onClose}
            data-testid="vip-item-details-close"
            className="rounded-none border border-white/10 text-neutral-300 hover:text-white"
          >
            {t("common.close", "Cerrar")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}


function PairFilterChips({ pairCounts, pairFilter, onSelect }) {
  const { t } = useTranslation();
  const total = pairCounts.reduce((acc, p) => acc + p.count, 0);
  const chips = [...pairCounts];
  if (pairFilter !== "all" && !chips.some((p) => p.pair === pairFilter)) {
    chips.push({ pair: pairFilter, label: pairFilter.replace("->", "→"), count: 0 });
  }
  const base = "inline-flex items-center gap-1.5 text-[0.65rem] uppercase tracking-widest px-2.5 py-1 border font-mono transition-colors";
  const active = "bg-[#8B5CF6]/10 border-[#8B5CF6] text-[#A78BFA]";
  const idle = "bg-transparent border-white/10 text-neutral-400 hover:border-white/30";
  return (
    <div className="flex items-center gap-2 flex-wrap" data-testid="vip-batches-pair-chips">
      <span className="micro-label text-neutral-600 mr-1">{t("adminVipBatches.pairFilterLabel")}</span>
      <button
        type="button"
        onClick={() => onSelect("all")}
        data-testid="vip-batches-pair-all"
        className={`${base} ${pairFilter === "all" ? active : idle}`}
      >
        {t("adminVipBatches.pairAll")}
        <span className="text-neutral-500">{total}</span>
      </button>
      {chips.map((p) => (
        <button
          key={p.pair}
          type="button"
          onClick={() => onSelect(p.pair)}
          data-testid={`vip-batches-pair-${p.pair.replace("->", "-")}`}
          className={`${base} ${pairFilter === p.pair ? active : idle}`}
        >
          <ArrowRightLeft className="w-3 h-3" />
          {p.label || t("adminVipBatches.pairLegacy")}
          <span className={p.count > 0 ? "text-[#8B5CF6] font-bold" : "text-neutral-600"}>{p.count}</span>
        </button>
      ))}
    </div>
  );
}


function DirBadge({ direction, item }) {
  const { t } = useTranslation();
  if (item?.to_code) {
    return (
      <span
        className="inline-flex items-center gap-1 text-[0.6rem] uppercase tracking-widest px-2 py-1 border font-mono border-[#8B5CF6]/40 bg-[#8B5CF6]/10 text-[#A78BFA]"
        data-testid={`vip-item-pair-${item.id}`}
      >
        <ArrowRightLeft className="w-3 h-3" />
        {item.from_code}→{item.to_code}
      </span>
    );
  }
  const isCredit = direction === "credit";
  const Icon = isCredit ? ArrowUpCircle : ArrowDownCircle;
  const cls = isCredit
    ? "border-emerald-500/40 bg-emerald-500/5 text-emerald-400"
    : "border-[#EF4444]/40 bg-[#EF4444]/10 text-[#EF4444]";
  return (
    <span className={`inline-flex items-center gap-1 text-[0.6rem] uppercase tracking-widest px-2 py-1 border font-mono ${cls}`}>
      <Icon className="w-3 h-3" />
      {t(`vipBatches.direction.${direction}`)}
    </span>
  );
}


function ItemPill({ status }) {
  const { t } = useTranslation();
  const map = {
    pending:  { cls: "border-amber-500/40 bg-amber-500/5 text-amber-400", Icon: Clock },
    approved: { cls: "border-emerald-500/40 bg-emerald-500/5 text-emerald-400", Icon: Check },
    rejected: { cls: "border-[#EF4444]/40 bg-[#EF4444]/10 text-[#EF4444]", Icon: XIcon },
  }[status] || {};
  const Icon = map.Icon || Clock;
  return (
    <span className={`inline-flex items-center gap-1 text-[0.6rem] uppercase tracking-widest px-1.5 py-0.5 border font-mono ${map.cls || ""}`}>
      <Icon className="w-3 h-3" />
      {t(`vipBatches.status.item.${status}`, status)}
    </span>
  );
}


function RejectDialog({ open, item, onClose, onDone }) {
  const { t } = useTranslation();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (open) setNote(""); }, [open]);

  const submit = async () => {
    if (!item) return;
    setBusy(true);
    try {
      await axios.post(
        `${API}/admin/vip-batches/items/${item.id}/reject`,
        { admin_note: note.trim() },
        { withCredentials: true },
      );
      toast.success(t("adminVipBatches.rejectedToast"));
      onDone?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("adminVipBatches.actionError"));
    } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent
        data-testid="vip-item-reject-dialog"
        className="bg-[#0c0c0c] border border-[#EF4444]/30 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle>{t("adminVipBatches.rejectDialogTitle")}</DialogTitle>
        </DialogHeader>
        <p className="text-xs text-neutral-400">
          {t("adminVipBatches.rejectDialogBody", { holder: item?.holder_name || "" })}
        </p>
        <textarea
          data-testid="vip-item-reject-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
          maxLength={300}
          placeholder={t("adminVipBatches.rejectPlaceholder")}
          className="w-full mt-3 bg-black/40 border border-white/10 rounded-none px-3 py-2 text-sm text-white placeholder:text-neutral-600 focus:border-[#EF4444]/50 focus:outline-none"
        />
        <div className="flex justify-end gap-2 pt-3 border-t border-white/5 mt-2">
          <Button variant="ghost" onClick={onClose} className="rounded-none text-neutral-400">
            {t("common.cancel")}
          </Button>
          <Button
            onClick={submit}
            disabled={busy}
            data-testid="vip-item-reject-confirm"
            className="rounded-none bg-[#EF4444] hover:bg-[#F87171] text-white disabled:opacity-40"
          >
            {t("adminVipBatches.reject")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
