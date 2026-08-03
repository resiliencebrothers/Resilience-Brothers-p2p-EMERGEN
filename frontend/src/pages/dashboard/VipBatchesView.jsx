import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import {
  Layers, Plus, ArrowUpCircle, ArrowDownCircle, ArrowRightLeft, TrendingUp,
  TrendingDown, Clock, Check, X as XIcon, FileText,
} from "lucide-react";
import { useLiveEvent } from "@/hooks/useLiveStream";
import { MovementsHistory } from "./vip/VipLedgerOps";

/**
 * iter110 · Phase 1 — VIP batch operations view.
 *
 * Landing at `/dashboard/batches` (VIP-only). Shows:
 *   1. Balance card (positive / negative / net in USDT).
 *   2. List of open + recent closed batches.
 *   3. "Nuevo lote" dialog.
 *   4. Batch detail sheet: table of items, add-row-inline, close.
 *
 * Live refresh via SSE `vip_batch_item_decision`.
 */
export default function VipBatchesView() {
  const { t } = useTranslation();
  const [balance, setBalance] = useState(null);
  const [batches, setBatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [openBatch, setOpenBatch] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const [bal, list] = await Promise.all([
        axios.get(`${API}/vip/balance`, { withCredentials: true }),
        axios.get(`${API}/vip/batches`, { params: { limit: 20 }, withCredentials: true }),
      ]);
      setBalance(bal.data);
      setBatches(list.data?.items || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("vipBatches.loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { refresh(); }, [refresh]);
  useLiveEvent("vip_batch_item_decision", refresh);

  return (
    <div className="space-y-6" data-testid="vip-batches-view">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <div className="micro-label text-neutral-500">{t("vipBatches.eyebrow")}</div>
          <h1 className="text-3xl font-display mt-1">{t("vipBatches.title")}</h1>
        </div>
        <Button
          onClick={() => setCreating(true)}
          data-testid="new-batch-btn"
          className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white h-10 px-4 text-xs uppercase tracking-widest font-semibold"
        >
          <Plus className="w-4 h-4 mr-2" /> {t("vipBatches.newBatch")}
        </Button>
      </div>

      <BalanceCard balance={balance} loading={loading} />

      <section className="space-y-3">
        <div className="micro-label text-neutral-500">{t("vipBatches.recentBatches")}</div>
        {loading && (
          <div className="text-sm text-neutral-500 py-8 text-center">
            {t("admin.common.loadingEllipsis")}
          </div>
        )}
        {!loading && batches.length === 0 && (
          <div
            className="text-sm text-neutral-500 py-10 text-center border border-white/5 bg-black/20"
            data-testid="batches-empty"
          >
            {t("vipBatches.empty")}
          </div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {batches.map((b) => (
            <BatchRow key={b.id} batch={b} onOpen={() => setOpenBatch(b)} />
          ))}
        </div>
      </section>

      <MovementsHistory />

      <CreateBatchDialog
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(b) => { setCreating(false); setOpenBatch(b); refresh(); }}
      />
      <BatchDetailDialog
        batch={openBatch}
        onClose={() => setOpenBatch(null)}
        onChanged={refresh}
      />
    </div>
  );
}


function BalanceCard({ balance, loading }) {
  const { t } = useTranslation();
  if (loading) return null;
  const negative = balance?.negative_usdt || 0;

  return (
    <div className="space-y-3">
      <div
        className="border border-[#8B5CF6]/25 bg-[#8B5CF6]/5 p-4 text-xs text-neutral-300 leading-relaxed"
        data-testid="batches-credit-info"
      >
        <TrendingUp className="w-4 h-4 text-[#A78BFA] inline mr-2" />
        {t("vipBatches.creditedInfo")}
      </div>
      {negative > 0 && (
        <div className="tactile-card p-6 flex items-center gap-4" data-testid="balance-negative">
          <TrendingDown className="w-6 h-6 text-[#EF4444] shrink-0" />
          <div>
            <div className="micro-label text-neutral-500">{t("vipBatches.legacyDebt")}</div>
            <div className="text-2xl font-mono text-[#EF4444]">
              ${negative.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              <span className="text-[0.65rem] text-neutral-500 ml-2">USDT</span>
            </div>
            <div className="text-[0.7rem] text-neutral-500 mt-1">{t("vipBatches.legacyDebtHint")}</div>
          </div>
        </div>
      )}
    </div>
  );
}


function BatchRow({ batch, onOpen }) {
  const { t } = useTranslation();
  const isPair = !!batch.to_code;
  const dirIcon = batch.direction === "credit" ? ArrowUpCircle : ArrowDownCircle;
  const dirColor = batch.direction === "credit" ? "text-emerald-400" : "text-[#EF4444]";
  const DirIcon = isPair ? ArrowRightLeft : dirIcon;
  return (
    <button
      type="button"
      onClick={onOpen}
      data-testid={`batch-row-${batch.id}`}
      className="tactile-card p-4 text-left hover:border-[#8B5CF6]/50 transition-colors flex items-center gap-4"
    >
      <DirIcon className={`w-6 h-6 shrink-0 ${isPair ? "text-[#8B5CF6]" : dirColor}`} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          {isPair ? (
            <span className="text-sm font-mono font-semibold text-white" data-testid={`batch-pair-${batch.id}`}>
              {batch.from_code} → {batch.to_code}
            </span>
          ) : (
            <>
              <span className="text-sm font-semibold text-white">
                {t(`vipBatches.direction.${batch.direction}`)}
              </span>
              <span className="micro-label text-neutral-500">·</span>
              <span className="text-sm font-mono text-white">{batch.currency}</span>
            </>
          )}
          <StatusPill status={batch.status} kind="batch" />
        </div>
        <div className="text-[0.65rem] text-neutral-500 mt-1 font-mono">
          {batch.items_approved || 0}✓ · {batch.items_pending || 0}⧗ · {batch.items_rejected || 0}✗
        </div>
      </div>
      <div className="text-right shrink-0">
        <div className="text-[0.65rem] text-neutral-500">
          {new Date(batch.created_at).toLocaleDateString()}
        </div>
        <div className="text-xs text-white font-mono mt-0.5">
          ${(batch.amount_approved || 0).toLocaleString()}
        </div>
      </div>
    </button>
  );
}


function StatusPill({ status, kind = "item" }) {
  const { t } = useTranslation();
  const map = {
    open:     { cls: "border-emerald-500/40 bg-emerald-500/5 text-emerald-400", Icon: FileText },
    closed:   { cls: "border-white/10 bg-white/5 text-neutral-400", Icon: Check },
    pending:  { cls: "border-amber-500/40 bg-amber-500/5 text-amber-400", Icon: Clock },
    approved: { cls: "border-emerald-500/40 bg-emerald-500/5 text-emerald-400", Icon: Check },
    rejected: { cls: "border-[#EF4444]/40 bg-[#EF4444]/10 text-[#EF4444]", Icon: XIcon },
  }[status] || {};
  const Icon = map.Icon || Layers;
  return (
    <span className={`inline-flex items-center gap-1 text-[0.6rem] uppercase tracking-widest px-1.5 py-0.5 border font-mono ${map.cls || ""}`}>
      <Icon className="w-3 h-3" />
      {t(`vipBatches.status.${kind}.${status}`, status)}
    </span>
  );
}


function CreateBatchDialog({ open, onClose, onCreated }) {
  const { t } = useTranslation();
  const [pairs, setPairs] = useState([]);
  const [pairsLoading, setPairsLoading] = useState(false);
  const [pairKey, setPairKey] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setPairKey(""); setNote("");
    setPairsLoading(true);
    axios.get(`${API}/vip/batch-pairs`, { withCredentials: true })
      .then((r) => {
        const items = r.data?.items || [];
        setPairs(items);
        if (items.length > 0) setPairKey(items[0].pair);
      })
      .catch(() => setPairs([]))
      .finally(() => setPairsLoading(false));
  }, [open]);

  const selected = pairs.find((p) => p.pair === pairKey);

  const submit = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      const r = await axios.post(
        `${API}/vip/batches`,
        { from_code: selected.from_code, to_code: selected.to_code, note: note.trim() || null },
        { withCredentials: true },
      );
      toast.success(t("vipBatches.batchCreated"));
      onCreated?.(r.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("vipBatches.actionError"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent
        data-testid="new-batch-dialog"
        className="bg-[#0c0c0c] border border-[#8B5CF6]/30 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle>{t("vipBatches.newBatchTitle")}</DialogTitle>
          <DialogDescription className="text-xs text-neutral-400 leading-relaxed">
            {t("vipBatches.newBatchBody")}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 mt-2">
          <div>
            <Label className="micro-label text-neutral-500">
              {t("vipBatches.pairLabel")}
            </Label>
            <Select value={pairKey} onValueChange={setPairKey}>
              <SelectTrigger data-testid="batch-pair" className="rounded-none bg-black/40 border-white/10 text-white h-10 mt-1">
                <SelectValue placeholder={pairsLoading ? "…" : t("vipBatches.pairPlaceholder")} />
              </SelectTrigger>
              <SelectContent className="bg-[#0c0c0c] border border-white/10 rounded-none max-h-72">
                {pairs.map((p) => (
                  <SelectItem key={p.pair} value={p.pair} className="rounded-none">
                    {p.from_code} → {p.to_code}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {!pairsLoading && pairs.length === 0 && (
              <p className="text-xs text-amber-400 mt-2" data-testid="batch-no-pairs">
                {t("vipBatches.noPairs")}
              </p>
            )}
            {selected && (
              <div
                className="mt-2 border border-[#8B5CF6]/25 bg-[#8B5CF6]/5 px-3 py-2 text-xs text-neutral-300 font-mono"
                data-testid="batch-rate-hint"
              >
                {t("vipBatches.rateVipHint", {
                  from: selected.from_code,
                  rate: selected.rate_vip,
                  to: selected.to_code,
                })}
              </div>
            )}
          </div>

          <div>
            <Label htmlFor="batch-note" className="micro-label text-neutral-500">
              {t("vipBatches.noteLabel")}
            </Label>
            <Input
              id="batch-note"
              data-testid="batch-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={t("vipBatches.notePlaceholder")}
              maxLength={200}
              className="rounded-none bg-black/40 border-white/10 text-white h-10 mt-1"
            />
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-3 border-t border-white/5 mt-4">
          <Button variant="ghost" onClick={onClose} className="rounded-none text-neutral-400 hover:text-white">
            {t("common.cancel")}
          </Button>
          <Button
            onClick={submit}
            disabled={busy || !selected}
            data-testid="batch-create-submit"
            className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white disabled:opacity-40"
          >
            {t("vipBatches.createBatch")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}


function BatchDetailDialog({ batch, onClose, onChanged }) {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [holder, setHolder] = useState("");
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [current, setCurrent] = useState(batch);

  const loadDetail = useCallback(async () => {
    if (!batch?.id) return;
    try {
      const r = await axios.get(`${API}/vip/batches/${batch.id}`, { withCredentials: true });
      setCurrent(r.data.batch);
      setItems(r.data.items || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("vipBatches.loadError"));
    }
  }, [batch?.id, t]);

  useEffect(() => {
    if (batch) { setCurrent(batch); loadDetail(); }
    else { setItems([]); setHolder(""); setAmount(""); }
  }, [batch, loadDetail]);

  useLiveEvent(batch ? "vip_batch_item_decision" : null, loadDetail);

  if (!batch) return null;
  const isOpen = current?.status === "open";
  const isPair = !!current?.to_code;
  const previewRate = current?.current_rate_vip || current?.rate_vip || null;
  const previewTo = isPair && previewRate && amount
    ? Number(amount) * previewRate
    : null;

  const addItem = async () => {
    if (!holder.trim() || !amount) return;
    setBusy(true);
    try {
      await axios.post(
        `${API}/vip/batches/${batch.id}/items`,
        { items: [{ holder_name: holder.trim(), amount: Number(amount) }] },
        { withCredentials: true },
      );
      toast.success(t("vipBatches.itemAdded"));
      setHolder(""); setAmount("");
      await loadDetail();
      onChanged?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("vipBatches.actionError"));
    } finally { setBusy(false); }
  };

  const closeBatch = async () => {
    if (!confirm(t("vipBatches.confirmClose"))) return;
    setBusy(true);
    try {
      await axios.post(`${API}/vip/batches/${batch.id}/close`, {}, { withCredentials: true });
      toast.success(t("vipBatches.batchClosed"));
      await loadDetail();
      onChanged?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("vipBatches.actionError"));
    } finally { setBusy(false); }
  };

  return (
    <Dialog open={!!batch} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent
        data-testid="batch-detail-dialog"
        className="bg-[#0c0c0c] border border-[#8B5CF6]/30 text-white rounded-none max-w-2xl max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Layers className="w-5 h-5 text-[#8B5CF6]" />
            {t(`vipBatches.direction.${current?.direction}`)} — {current?.currency}
            {current?.status && <StatusPill status={current.status} kind="batch" />}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {t("vipBatches.creditedInfo")}
          </DialogDescription>
        </DialogHeader>

        {isOpen && (
          <div className="border border-white/5 bg-black/30 p-3">
            <div className="micro-label text-neutral-500 mb-2">{t("vipBatches.addRow")}</div>
            <div className="grid grid-cols-1 sm:grid-cols-[1fr_140px_auto] gap-2">
              <Input
                data-testid="new-item-holder"
                value={holder}
                onChange={(e) => setHolder(e.target.value)}
                placeholder={t("vipBatches.holderPlaceholder")}
                maxLength={120}
                className="rounded-none bg-black/40 border-white/10 text-white h-10"
              />
              <Input
                data-testid="new-item-amount"
                type="number"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="0.00"
                min="0.01"
                step="0.01"
                className="rounded-none bg-black/40 border-white/10 text-white h-10 font-mono"
              />
              <Button
                onClick={addItem}
                disabled={busy || !holder.trim() || !amount}
                data-testid="add-item-btn"
                className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white h-10 disabled:opacity-40"
              >
                <Plus className="w-4 h-4 mr-1" /> {t("vipBatches.addItem")}
              </Button>
            </div>
            {previewTo != null && previewTo > 0 && (
              <div className="text-[0.7rem] text-emerald-400 font-mono mt-2" data-testid="item-receive-preview">
                {t("vipBatches.estReceive", {
                  amount: previewTo.toLocaleString(undefined, { maximumFractionDigits: 4 }),
                  to: current.to_code,
                })}
              </div>
            )}
          </div>
        )}

        <div className="border border-white/5 max-h-[45vh] overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="bg-[#0a0a0a] border-b border-white/10">
              <tr className="text-left">
                <th className="px-3 py-2 micro-label text-neutral-500">{t("vipBatches.colHolder")}</th>
                <th className="px-3 py-2 micro-label text-neutral-500 text-right">{t("vipBatches.colAmount")}</th>
                {isPair && (
                  <th className="px-3 py-2 micro-label text-neutral-500 text-right">{t("vipBatches.colReceive")}</th>
                )}
                <th className="px-3 py-2 micro-label text-neutral-500">{t("vipBatches.colStatus")}</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && (
                <tr>
                  <td colSpan={isPair ? 4 : 3} className="text-center text-neutral-500 py-6" data-testid="batch-items-empty">
                    {t("vipBatches.itemsEmpty")}
                  </td>
                </tr>
              )}
              {items.map((it) => (
                <tr key={it.id} className="border-b border-white/5" data-testid={`item-row-${it.id}`}>
                  <td className="px-3 py-2 text-white">{it.holder_name}</td>
                  <td className="px-3 py-2 font-mono text-white text-right">
                    {Number(it.amount).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    <span className="text-[0.6rem] text-neutral-500 ml-1">{it.from_code || it.currency}</span>
                  </td>
                  {isPair && (
                    <td className="px-3 py-2 font-mono text-emerald-400 text-right" data-testid={`item-receive-${it.id}`}>
                      {it.amount_to != null
                        ? Number(it.amount_to).toLocaleString(undefined, { maximumFractionDigits: 4 })
                        : "—"}
                      <span className="text-[0.6rem] text-neutral-500 ml-1">{it.to_code}</span>
                    </td>
                  )}
                  <td className="px-3 py-2">
                    <StatusPill status={it.status} kind="item" />
                    {it.admin_note && (
                      <div className="text-[0.65rem] italic text-neutral-500 mt-0.5">{it.admin_note}</div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex justify-between items-center gap-2 pt-3 border-t border-white/5 mt-2">
          {isOpen ? (
            <Button
              variant="ghost"
              onClick={closeBatch}
              disabled={busy}
              data-testid="batch-close-btn"
              className="rounded-none border border-white/10 text-neutral-300 hover:bg-white/5 text-xs"
            >
              {t("vipBatches.closeBatch")}
            </Button>
          ) : (
            <span className="text-xs text-neutral-500">
              {t("vipBatches.batchClosedInfo")}
            </span>
          )}
          <Button variant="ghost" onClick={onClose} className="rounded-none text-neutral-400 hover:text-white">
            {t("common.close")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
