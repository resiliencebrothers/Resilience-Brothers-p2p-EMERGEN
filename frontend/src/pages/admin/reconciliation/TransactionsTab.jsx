import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Check, X as XIcon, Link2, EyeOff, Search, Undo2, RotateCcw, AlertTriangle, RefreshCw } from "lucide-react";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { TopScrollTable } from "@/components/TopScrollTable";

const STATUS_META = {
  manual_review: "border-amber-500/50 bg-amber-500/10 text-amber-400",
  unmatched: "border-white/20 bg-white/5 text-neutral-300",
  auto_matched: "border-emerald-500/50 bg-emerald-500/10 text-emerald-400",
  manual_matched: "border-emerald-500/50 bg-emerald-500/10 text-emerald-300",
  duplicate: "border-red-500/40 bg-red-500/10 text-red-400",
  ignored: "border-white/10 bg-white/[0.02] text-neutral-500",
};

const FILTERS = ["manual_review", "unmatched", "auto_matched", "manual_matched", "duplicate", "ignored"];

const ScoreBar = ({ score }) => {
  const s = Math.max(0, Math.min(100, Number(score || 0)));
  const tone = s >= 90 ? "bg-emerald-500" : s >= 50 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2 min-w-[90px]">
      <div className="h-1.5 w-14 bg-white/10 overflow-hidden">
        <div className={`h-full ${tone}`} style={{ width: `${s}%` }} />
      </div>
      <span className="font-mono text-xs text-neutral-300">{s}</span>
    </div>
  );
};

const BreakdownChips = ({ b, t }) => {
  if (!b) return null;
  const items = [
    [t("reconciliation.breakdown.amount"), b.amount_score],
    [t("reconciliation.breakdown.currency"), b.currency_score],
    [`${t("reconciliation.breakdown.name")}${b.name_similarity != null ? ` ${(b.name_similarity * 100).toFixed(0)}%` : ""}`, b.name_score],
    [t("reconciliation.breakdown.surname"), b.surname_score],
    [`${t("reconciliation.breakdown.date")}${b.date_difference_days != null ? ` ±${b.date_difference_days}d` : ""}`, b.date_score],
  ];
  return (
    <div className="flex flex-wrap gap-1 mt-1.5" data-testid="recon-breakdown-chips">
      {items.map(([label, pts]) => (
        <span
          key={label}
          className={`text-[10px] font-mono px-1.5 py-0.5 border ${
            (pts || 0) > 0
              ? "border-emerald-500/30 text-emerald-400 bg-emerald-500/5"
              : "border-white/10 text-neutral-600"
          }`}
        >
          {label} +{pts ?? 0}
        </span>
      ))}
      {(b.reference_score || 0) > 0 && (
        <span className="text-[10px] font-mono px-1.5 py-0.5 border border-sky-500/40 text-sky-300 bg-sky-500/10">
          {t("reconciliation.breakdown.referenceBonus")} ✓
        </span>
      )}
      <span className="text-[10px] font-mono px-1.5 py-0.5 border border-violet-500/40 text-violet-300 bg-violet-500/10">
        {t("reconciliation.breakdown.total")} {b.total}
      </span>
    </div>
  );
};

const CandidateRow = ({ c, onConfirm, busy, t }) => (
  <div className="border border-white/10 bg-white/[0.02] p-3 flex items-center justify-between gap-3 flex-wrap">
    <div className="text-sm min-w-0">
      <div className="text-white flex items-center gap-2 flex-wrap">
        {c.kind === "vip_batch_item" && (
          <span className="text-[10px] uppercase tracking-wider border border-violet-500/50 bg-violet-500/10 text-violet-300 px-1.5 py-0.5">
            {t("reconciliation.tx.batchItem")}
          </span>
        )}
        <span>{c.order_user_name || c.order_sender_name || "—"}</span>
        {c.order_user_name && c.order_sender_name && c.order_sender_name !== c.order_user_name && (
          <span className="text-neutral-500"> · {t("reconciliation.tx.sender")}: {c.order_sender_name}</span>
        )}
      </div>
      <div className="text-xs text-neutral-500 font-mono">
        {c.order_id?.slice(0, 8)} · {Number(c.order_amount).toLocaleString()} · {String(c.order_created_at || "").slice(0, 10)}
        {c.order_payment_reference ? ` · ${t("reconciliation.tx.refLabel")} ${c.order_payment_reference}` : ""}
        {c.payment_account_label ? ` · ${c.payment_account_label}` : ""}
      </div>
      <BreakdownChips b={c.breakdown} t={t} />
    </div>
    <div className="flex items-center gap-3">
      <ScoreBar score={c.score} />
      <Button
        size="sm"
        data-testid={`recon-confirm-candidate-${c.order_id}`}
        disabled={busy}
        onClick={() => onConfirm(c.order_id)}
        className="rounded-none bg-emerald-600 hover:bg-emerald-500 text-white h-8"
      >
        <Check className="w-3.5 h-3.5 mr-1" /> {t("reconciliation.tx.confirm")}
      </Button>
    </div>
  </div>
);

const EMPTY_FLT = { q: "", dateFrom: "", dateTo: "", amountMin: "", amountMax: "", scoreMin: "" };

export default function TransactionsTab({ onChanged, currency }) {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [statusFilter, setStatusFilter] = useState("manual_review");
  const [flt, setFlt] = useState(EMPTY_FLT);
  const [fltDebounced, setFltDebounced] = useState(EMPTY_FLT);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState(null);
  const [linking, setLinking] = useState(null);
  const [rollback, setRollback] = useState(null);
  // iter190 — ignore-with-note dialog ("quién ignoró")
  const [ignoring, setIgnoring] = useState(null);
  const [ignoreNote, setIgnoreNote] = useState("");
  const [rollbackReason, setRollbackReason] = useState("");
  const [orderQ, setOrderQ] = useState("");
  const [orderResults, setOrderResults] = useState([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const id = setTimeout(() => setFltDebounced(flt), 400);
    return () => clearTimeout(id);
  }, [flt]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { status: statusFilter, limit: 300 };
      if (currency) params.currency = currency;
      if (fltDebounced.q) params.q = fltDebounced.q;
      if (fltDebounced.dateFrom) params.date_from = fltDebounced.dateFrom;
      if (fltDebounced.dateTo) params.date_to = fltDebounced.dateTo;
      if (fltDebounced.amountMin) params.amount_min = fltDebounced.amountMin;
      if (fltDebounced.amountMax) params.amount_max = fltDebounced.amountMax;
      if (fltDebounced.scoreMin) params.score_min = fltDebounced.scoreMin;
      const r = await axios.get(`${API}/admin/reconciliation/transactions`, {
        params, withCredentials: true,
      });
      setItems(r.data?.items || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Error");
    } finally { setLoading(false); }
  }, [statusFilter, fltDebounced, currency]);

  useEffect(() => { load(); }, [load]);

  const act = async (txId, action, body = {}) => {
    setBusy(true);
    try {
      await axios.post(`${API}/admin/reconciliation/transactions/${txId}/${action}`, body, { withCredentials: true });
      toast.success(t(`reconciliation.tx.${action}Ok`));
      setDetail(null); setLinking(null); setRollback(null); setRollbackReason("");
      setIgnoring(null); setIgnoreNote("");
      load(); onChanged?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Error");
    } finally { setBusy(false); }
  };

  const searchOrders = useCallback(async (tx, q) => {
    try {
      const r = await axios.get(`${API}/admin/reconciliation/orders-search`, {
        params: { currency: tx.currency, q: q || undefined }, withCredentials: true,
      });
      setOrderResults(r.data?.items || []);
    } catch (err) {
      setOrderResults([]);
      toast.error(err?.response?.data?.detail || "Error");
    }
  }, []);

  useEffect(() => {
    if (!linking) return;
    const id = setTimeout(() => searchOrders(linking, orderQ), 300);
    return () => clearTimeout(id);
  }, [linking, orderQ, searchOrders]);

  const runRematch = async () => {
    setBusy(true);
    try {
      const r = await axios.post(`${API}/admin/reconciliation/rematch`,
        currency ? { currency } : {}, { withCredentials: true });
      const d = r.data || {};
      toast.success(t("reconciliation.tx.rematchDone", {
        auto: d.auto ?? 0, review: d.review ?? 0, unmatched: d.unmatched ?? 0,
      }));
      load();
      onChanged?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Error");
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-4" data-testid="reconciliation-transactions-tab">
      <div className="flex items-center gap-2 flex-wrap justify-between">
        <div className="flex items-center gap-2 flex-wrap">
          {FILTERS.map((s) => (
            <button
              key={s}
              type="button"
              data-testid={`recon-filter-${s}`}
              onClick={() => setStatusFilter(s)}
              className={`text-xs uppercase tracking-widest px-3 py-1.5 border font-mono transition-colors ${
                statusFilter === s
                  ? "bg-violet-500/10 border-violet-500 text-violet-300"
                  : "bg-transparent border-white/10 text-neutral-400 hover:border-white/30"
              }`}
            >
              {t(`reconciliation.filter.${s}`)}
            </button>
          ))}
        </div>
        <Button
          data-testid="recon-rematch-btn"
          onClick={runRematch}
          disabled={busy}
          className="rounded-none bg-violet-600 hover:bg-violet-500 text-white h-8 text-xs"
        >
          <RefreshCw className={`w-3.5 h-3.5 mr-2 ${busy ? "animate-spin" : ""}`} />
          {t("reconciliation.tx.rematch")}
        </Button>
      </div>

      <div className="flex items-end gap-2 flex-wrap" data-testid="recon-adv-filters">
        <Input
          data-testid="recon-flt-q"
          value={flt.q}
          onChange={(e) => setFlt((f) => ({ ...f, q: e.target.value }))}
          placeholder={t("reconciliation.advFilters.q")}
          className="w-64 h-8 rounded-none bg-white/5 border-white/10 text-sm"
        />
        <label className="text-[10px] uppercase tracking-wider text-neutral-500 flex flex-col gap-1">
          {t("reconciliation.advFilters.dateFrom")}
          <Input data-testid="recon-flt-date-from" type="date" value={flt.dateFrom}
            onChange={(e) => setFlt((f) => ({ ...f, dateFrom: e.target.value }))}
            className="w-36 h-8 rounded-none bg-white/5 border-white/10 text-sm" />
        </label>
        <label className="text-[10px] uppercase tracking-wider text-neutral-500 flex flex-col gap-1">
          {t("reconciliation.advFilters.dateTo")}
          <Input data-testid="recon-flt-date-to" type="date" value={flt.dateTo}
            onChange={(e) => setFlt((f) => ({ ...f, dateTo: e.target.value }))}
            className="w-36 h-8 rounded-none bg-white/5 border-white/10 text-sm" />
        </label>
        <Input
          data-testid="recon-flt-amount-min" type="number" value={flt.amountMin}
          onChange={(e) => setFlt((f) => ({ ...f, amountMin: e.target.value }))}
          placeholder={t("reconciliation.advFilters.amountMin")}
          className="w-28 h-8 rounded-none bg-white/5 border-white/10 text-sm"
        />
        <Input
          data-testid="recon-flt-amount-max" type="number" value={flt.amountMax}
          onChange={(e) => setFlt((f) => ({ ...f, amountMax: e.target.value }))}
          placeholder={t("reconciliation.advFilters.amountMax")}
          className="w-28 h-8 rounded-none bg-white/5 border-white/10 text-sm"
        />
        <Input
          data-testid="recon-flt-score-min" type="number" value={flt.scoreMin}
          onChange={(e) => setFlt((f) => ({ ...f, scoreMin: e.target.value }))}
          placeholder={t("reconciliation.advFilters.scoreMin")}
          className="w-24 h-8 rounded-none bg-white/5 border-white/10 text-sm"
        />
        {Object.values(flt).some(Boolean) && (
          <Button
            data-testid="recon-flt-clear"
            variant="ghost"
            onClick={() => setFlt(EMPTY_FLT)}
            className="h-8 rounded-none text-xs text-neutral-400 hover:text-white"
          >
            {t("reconciliation.advFilters.clear")}
          </Button>
        )}
      </div>

      <div className="tactile-card p-0 overflow-hidden">
        {loading ? (
          <div className="p-6 text-sm text-neutral-500 animate-pulse">…</div>
        ) : items.length === 0 ? (
          <div className="p-6 text-sm text-neutral-500" data-testid="recon-tx-empty">
            {t("reconciliation.tx.empty")}
          </div>
        ) : (
          <TopScrollTable
            testid="recon-tx"
            deps={[items]}
            maxHeightClass="max-h-[70vh]"
          >
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-neutral-500 text-xs uppercase tracking-wider">
                  <th className="px-3 py-2">{t("reconciliation.tx.date")}</th>
                  <th className="px-3 py-2">{t("reconciliation.tx.sender")}</th>
                  <th className="px-3 py-2">{t("reconciliation.tx.description")}</th>
                  <th className="px-3 py-2 text-right">{t("reconciliation.tx.amount")}</th>
                  <th className="px-3 py-2">{t("reconciliation.tx.method")}</th>
                  <th className="px-3 py-2">{t("reconciliation.tx.score")}</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {items.map((tx) => (
                  <tr key={tx.id} className="border-t border-white/5 align-top" data-testid={`recon-tx-row-${tx.id}`}>
                    <td className="px-3 py-2.5 font-mono text-xs whitespace-nowrap">{tx.transaction_date}</td>
                    <td className="px-3 py-2.5">
                      {tx.sender_name || "—"}
                      {tx.status === "ignored" && (
                        <div
                          className="text-[11px] text-neutral-500 mt-1 leading-relaxed"
                          data-testid={`recon-ignored-meta-${tx.id}`}
                        >
                          <EyeOff className="w-3 h-3 inline mr-1 align-[-1px]" />
                          {tx.ignored_reason === "debit"
                            ? t("reconciliation.tx.ignoredAuto")
                            : t("reconciliation.tx.ignoredBy", {
                                name: tx.reviewed_by_name || tx.reviewed_by || "—",
                                date: String(tx.reviewed_at || "").slice(0, 16).replace("T", " "),
                              })}
                          {tx.review_note && (
                            <span className="text-neutral-300 italic"> · «{tx.review_note}»</span>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-neutral-400 max-w-[260px] truncate" title={tx.description || ""}>
                      {tx.description || tx.reference || "—"}
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono whitespace-nowrap text-white">
                      {Number(tx.amount).toLocaleString(undefined, { minimumFractionDigits: 2 })}{" "}
                      <span className="text-neutral-500 text-xs">{tx.currency}</span>
                    </td>
                    <td className="px-3 py-2.5 text-xs text-neutral-400">{tx.payment_method || "—"}</td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-1.5">
                        {tx.confidence_score != null ? <ScoreBar score={tx.confidence_score} /> : "—"}
                        {tx.review_flag && (
                          <span
                            title={t(`reconciliation.tx.${tx.review_flag}`)}
                            data-testid={`recon-flag-${tx.id}`}
                            className="inline-flex items-center gap-1 text-[10px] uppercase border border-orange-500/40 bg-orange-500/10 text-orange-400 px-1.5 py-0.5"
                          >
                            <AlertTriangle className="w-3 h-3" />
                            {t(`reconciliation.tx.${tx.review_flag}Short`)}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-1.5 justify-end">
                        {tx.status === "manual_review" && (
                          <Button size="sm" variant="outline"
                            data-testid={`recon-review-btn-${tx.id}`}
                            onClick={() => setDetail(tx)}
                            className="rounded-none h-7 text-xs border-amber-500/40 text-amber-400 hover:bg-amber-500/10">
                            {t("reconciliation.tx.review")} ({(tx.candidates || []).length})
                          </Button>
                        )}
                        {["manual_review", "unmatched"].includes(tx.status) && (
                          <>
                            <Button size="sm" variant="outline"
                              data-testid={`recon-link-btn-${tx.id}`}
                              onClick={() => { setLinking(tx); setOrderQ(""); }}
                              className="rounded-none h-7 text-xs border-white/10 text-neutral-300 hover:bg-white/5">
                              <Link2 className="w-3 h-3 mr-1" /> {t("reconciliation.tx.link")}
                            </Button>
                            <Button size="sm" variant="outline"
                              data-testid={`recon-ignore-btn-${tx.id}`}
                              disabled={busy}
                              onClick={() => { setIgnoring(tx); setIgnoreNote(""); }}
                              className="rounded-none h-7 text-xs border-white/10 text-neutral-500 hover:bg-white/5">
                              <EyeOff className="w-3 h-3" />
                            </Button>
                          </>
                        )}
                        {tx.status === "ignored" && (
                          <Button size="sm" variant="outline"
                            data-testid={`recon-restore-btn-${tx.id}`}
                            disabled={busy}
                            onClick={() => act(tx.id, "restore")}
                            className="rounded-none h-7 text-xs border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10">
                            <RotateCcw className="w-3 h-3 mr-1" /> {t("reconciliation.tx.restore")}
                          </Button>
                        )}
                        {["auto_matched", "manual_matched"].includes(tx.status) && (
                          <>
                            <span className="text-xs font-mono text-emerald-400">
                              {t("reconciliation.tx.order")} {String(tx.matched_order_id || "").slice(0, 8)}
                            </span>
                            <Button size="sm" variant="outline"
                              data-testid={`recon-rollback-btn-${tx.id}`}
                              onClick={() => setRollback(tx)}
                              className="rounded-none h-7 text-xs border-red-500/30 text-red-400 hover:bg-red-500/10">
                              <Undo2 className="w-3 h-3 mr-1" /> {t("reconciliation.tx.rollback")}
                            </Button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TopScrollTable>
        )}
      </div>

      {/* Candidates review dialog */}
      <Dialog open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="bg-[#0d0d0d] border-white/10 max-w-xl max-h-[85vh] overflow-y-auto" data-testid="recon-candidates-dialog">
          <DialogHeader>
            <DialogTitle>{t("reconciliation.tx.candidatesTitle")}</DialogTitle>
            <DialogDescription className="sr-only">{t("reconciliation.tx.candidatesTitle")}</DialogDescription>
          </DialogHeader>
          {detail && (
            <div className="space-y-3">
              <div className="text-xs text-neutral-400 font-mono border border-white/10 bg-white/[0.02] p-2.5">
                {detail.transaction_date} · {detail.sender_name || "—"} ·{" "}
                {Number(detail.amount).toLocaleString()} {detail.currency}
                {detail.description ? ` · ${detail.description.slice(0, 80)}` : ""}
              </div>
              {detail.status === "manual_review" && (detail.auto_block_reasons || []).length > 0 && (
                <div
                  className="text-xs border border-amber-500/30 bg-amber-500/5 text-amber-300 p-2.5"
                  data-testid="recon-block-reasons"
                >
                  <span className="text-amber-400 font-medium">
                    {t("reconciliation.tx.blockTitle")}:{" "}
                  </span>
                  {detail.auto_block_reasons.map((r) => t(`reconciliation.block.${r}`)).join(" · ")}
                </div>
              )}
              {(detail.candidates || []).map((c) => (
                <CandidateRow key={c.order_id} c={c} busy={busy} t={t}
                  onConfirm={(orderId) => act(detail.id, "confirm", { order_id: orderId })} />
              ))}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1">
                <Button variant="outline" disabled={busy}
                  data-testid="recon-reject-suggestions-btn"
                  onClick={() => act(detail.id, "reject")}
                  className="rounded-none border-red-500/40 text-red-400 hover:bg-red-500/10 w-full">
                  <XIcon className="w-4 h-4 mr-2" /> {t("reconciliation.tx.rejectAll")}
                </Button>
                <Button variant="outline" disabled={busy}
                  data-testid="recon-ignore-from-dialog-btn"
                  onClick={() => { setIgnoring(detail); setIgnoreNote(""); setDetail(null); }}
                  className="rounded-none border-white/20 text-neutral-300 hover:bg-white/5 w-full">
                  <EyeOff className="w-4 h-4 mr-2" /> {t("reconciliation.tx.ignoreFromDialog")}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* iter190 — ignore-with-note dialog (quién ignoró) */}
      <Dialog open={!!ignoring} onOpenChange={(o) => { if (!o) { setIgnoring(null); setIgnoreNote(""); } }}>
        <DialogContent className="bg-[#0d0d0d] border-white/10 max-w-md max-h-[85vh] overflow-y-auto" data-testid="recon-ignore-dialog">
          <DialogHeader>
            <DialogTitle>{t("reconciliation.tx.ignoreDialogTitle")}</DialogTitle>
            <DialogDescription className="sr-only">{t("reconciliation.tx.ignoreDialogTitle")}</DialogDescription>
          </DialogHeader>
          {ignoring && (
            <div className="space-y-3">
              <p className="text-sm text-neutral-400">
                {ignoring.sender_name || "—"} ·{" "}
                <span className="font-mono text-white">
                  {Number(ignoring.amount).toLocaleString(undefined, { minimumFractionDigits: 2 })} {ignoring.currency}
                </span>
              </p>
              <div>
                <label className="text-[0.65rem] uppercase tracking-widest text-neutral-500">
                  {t("reconciliation.tx.ignoreNoteLabel")}
                </label>
                <Input
                  data-testid="recon-ignore-note"
                  value={ignoreNote}
                  onChange={(e) => setIgnoreNote(e.target.value)}
                  placeholder={t("reconciliation.tx.ignoreNotePh")}
                  maxLength={200}
                  className="rounded-none bg-[#0a0a0a] border-white/10 mt-1.5"
                />
              </div>
              <Button
                data-testid="recon-ignore-confirm"
                disabled={busy}
                onClick={() => act(ignoring.id, "ignore", { note: ignoreNote.trim() })}
                className="rounded-none bg-white/10 hover:bg-white/20 text-white w-full"
              >
                <EyeOff className="w-4 h-4 mr-2" /> {t("reconciliation.tx.ignoreConfirm")}
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Rollback dialog (§25 — reason mandatory) */}
      <Dialog open={!!rollback} onOpenChange={(o) => { if (!o) { setRollback(null); setRollbackReason(""); } }}>
        <DialogContent className="bg-[#0d0d0d] border-white/10 max-w-md max-h-[85vh] overflow-y-auto" data-testid="recon-rollback-dialog">
          <DialogHeader>
            <DialogTitle>{t("reconciliation.tx.rollbackTitle")}</DialogTitle>
            <DialogDescription className="sr-only">{t("reconciliation.tx.rollbackHint")}</DialogDescription>
          </DialogHeader>
          {rollback && (
            <div className="space-y-3">
              <p className="text-sm text-neutral-400">{t("reconciliation.tx.rollbackHint")}</p>
              <Input
                data-testid="recon-rollback-reason"
                value={rollbackReason}
                onChange={(e) => setRollbackReason(e.target.value)}
                placeholder={t("reconciliation.tx.rollbackReasonPh")}
                className="rounded-none bg-[#0a0a0a] border-white/10"
              />
              <Button
                data-testid="recon-rollback-confirm"
                disabled={busy || rollbackReason.trim().length < 5}
                onClick={() => act(rollback.id, "rollback", { reason: rollbackReason.trim() })}
                className="rounded-none bg-red-600 hover:bg-red-500 text-white w-full"
              >
                <Undo2 className="w-4 h-4 mr-2" /> {t("reconciliation.tx.rollback")}
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Manual link dialog */}
      <Dialog open={!!linking} onOpenChange={(o) => !o && setLinking(null)}>
        <DialogContent className="bg-[#0d0d0d] border-white/10 max-w-xl max-h-[85vh] overflow-y-auto" data-testid="recon-link-dialog">
          <DialogHeader>
            <DialogTitle>{t("reconciliation.tx.linkTitle")}</DialogTitle>
            <DialogDescription className="sr-only">{t("reconciliation.tx.linkSearchPh")}</DialogDescription>
          </DialogHeader>
          {linking && (
            <div className="space-y-3">
              <div className="relative">
                <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
                <Input
                  data-testid="recon-order-search"
                  value={orderQ}
                  onChange={(e) => setOrderQ(e.target.value)}
                  placeholder={t("reconciliation.tx.linkSearchPh")}
                  className="rounded-none bg-[#0a0a0a] border-white/10 pl-9"
                />
              </div>
              <div className="max-h-72 overflow-y-auto space-y-2">
                {orderResults.length === 0 && (
                  <p className="text-sm text-neutral-500">{t("reconciliation.tx.noOrders")}</p>
                )}
                {orderResults.map((o) => (
                  <div key={o.id} className="border border-white/10 bg-white/[0.02] p-3 flex items-center justify-between gap-3">
                    <div className="text-sm">
                      <div className="text-white flex items-center gap-2 flex-wrap">
                        {o.kind === "vip_batch_item" && (
                          <span className="text-[10px] uppercase tracking-wider border border-violet-500/50 bg-violet-500/10 text-violet-300 px-1.5 py-0.5">
                            {t("reconciliation.tx.batchItem")}
                          </span>
                        )}
                        <span>{o.user_name}</span>
                        {o.sender_name && o.sender_name !== o.user_name && (
                          <span className="text-neutral-500"> · {o.sender_name}</span>
                        )}
                      </div>
                      <div className="text-xs text-neutral-500 font-mono">
                        {o.id.slice(0, 8)} · {Number(o.amount_from).toLocaleString()} {o.from_code}{o.to_code ? ` → ${o.to_code}` : ""} · {String(o.created_at).slice(0, 10)}
                      </div>
                    </div>
                    <Button size="sm" disabled={busy}
                      data-testid={`recon-link-order-${o.id}`}
                      onClick={() => act(linking.id, "confirm", { order_id: o.id })}
                      className="rounded-none bg-emerald-600 hover:bg-emerald-500 text-white h-8">
                      <Check className="w-3.5 h-3.5 mr-1" /> {t("reconciliation.tx.confirm")}
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
