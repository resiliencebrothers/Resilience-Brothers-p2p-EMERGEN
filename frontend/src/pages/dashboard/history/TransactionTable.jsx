/**
 * iter83 — TransactionTable
 *
 * Renders the paginated ledger table + the row-detail modal.
 *
 * Jun 2026 restructure (owner request): the table now mirrors the Orders
 * table semantics — Par / Envías / Recibes columns — and each row carries a
 * unified TYPE: Intercambio (order / batch / payout rows), Conversión
 * (internal balance conversions), Retiro (withdrawals) and Depósito
 * (deposits). Currency pair labels render horizontally (nowrap).
 */
import { useState, useRef, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import CurrencyIcon from "@/components/CurrencyIcon";
import CurrencyPairIcon from "@/components/CurrencyPairIcon";
import {
  Receipt, ArrowDown, ArrowUp, ArrowRightLeft, Download, FileText, X,
} from "lucide-react";

// Unified movement kind resolver (owner semantics, Jun 2026):
//   exchange   → rows born from a P2P order / VIP batch (pair available)
//   conversion → internal balance conversion (Convertir Saldos)
//   deposit    → plain inbound movement
//   withdrawal → plain outbound movement
export function txKind(it) {
  if (it.direction === "conversion") return "conversion";
  if (["order", "order_payout", "vip_batch_item"].includes(it.ref_type)) return "exchange";
  return it.direction === "in" ? "deposit" : "withdrawal";
}

export function kindMeta(it, t) {
  const kind = txKind(it);
  if (kind === "exchange") {
    return { kind, color: "#8B5CF6", icon: ArrowRightLeft, label: t("myTransactions.table.kindExchange") };
  }
  if (kind === "conversion") {
    return { kind, color: "#8B5CF6", icon: ArrowRightLeft, label: t("myTransactions.table.conversion") };
  }
  if (kind === "deposit") {
    return { kind, color: "#22C55E", icon: ArrowDown, label: t("myTransactions.table.kindDeposit") };
  }
  return { kind, color: "#EF4444", icon: ArrowUp, label: t("myTransactions.table.kindWithdrawal") };
}

function hasPair(it) {
  return Boolean(it.from_code && it.to_code);
}

const fmt = (n, d = 4) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: d });

export default function TransactionTable({ items, loading, hasFilters }) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState(null);

  // iter84 — Owner request (Feb 2026): horizontal scrollbar mirrored at the
  // top of the table so users notice it, plus a proper vertical scroll on the
  // table body (not the whole viewport). Columns reordered to Par-first and
  // Fecha-last so trading identity is the leading data point.
  //
  // We render a *custom* top scrollbar (visible on every browser incl. mobile
  // where native scrollbars are auto-hidden) with a draggable purple thumb.
  // Body scroll and top scrollbar stay in sync bidirectionally.
  const bodyScrollRef = useRef(null);
  const tableRef = useRef(null);
  const trackRef = useRef(null);
  const [contentWidth, setContentWidth] = useState(0);
  const [viewportWidth, setViewportWidth] = useState(0);
  const [thumbLeft, setThumbLeft] = useState(0);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    const measure = () => {
      if (tableRef.current && bodyScrollRef.current) {
        setContentWidth(tableRef.current.scrollWidth);
        setViewportWidth(bodyScrollRef.current.clientWidth);
      }
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [items, loading]);

  const overflow = Math.max(0, contentWidth - viewportWidth);
  const hasOverflow = overflow > 4;
  const trackW = viewportWidth || 0;
  const thumbW = hasOverflow ? Math.max(40, (trackW * trackW) / (contentWidth || 1)) : 0;
  const maxThumbLeft = Math.max(0, trackW - thumbW);

  const onBodyScroll = useCallback(() => {
    const body = bodyScrollRef.current;
    if (!body) return;
    const ratio = overflow > 0 ? body.scrollLeft / overflow : 0;
    setThumbLeft(ratio * maxThumbLeft);
  }, [overflow, maxThumbLeft]);

  const scrollToThumb = useCallback((nextLeft) => {
    const clamped = Math.max(0, Math.min(maxThumbLeft, nextLeft));
    setThumbLeft(clamped);
    const body = bodyScrollRef.current;
    if (body && maxThumbLeft > 0) {
      body.scrollLeft = (clamped / maxThumbLeft) * overflow;
    }
  }, [maxThumbLeft, overflow]);

  // Drag handlers on the custom thumb (mouse + touch)
  useEffect(() => {
    if (!dragging) return;
    const state = { startX: dragging.startX, startLeft: dragging.startLeft };
    const onMove = (e) => {
      const clientX = e.touches ? e.touches[0].clientX : e.clientX;
      scrollToThumb(state.startLeft + (clientX - state.startX));
    };
    const onUp = () => setDragging(false);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    window.addEventListener("touchmove", onMove, { passive: false });
    window.addEventListener("touchend", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      window.removeEventListener("touchmove", onMove);
      window.removeEventListener("touchend", onUp);
    };
  }, [dragging, scrollToThumb]);

  const onThumbDown = (e) => {
    e.preventDefault();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    setDragging({ startX: clientX, startLeft: thumbLeft });
  };

  const onTrackClick = (e) => {
    if (!trackRef.current) return;
    const rect = trackRef.current.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    // Center the thumb around the click position
    scrollToThumb(clickX - thumbW / 2);
  };

  return (
    <>
      <div className="tactile-card overflow-hidden" data-testid="my-tx-table-wrapper">
        {/* Custom horizontal scrollbar mirrored on top of the table */}
        {hasOverflow && (
          <div
            ref={trackRef}
            onClick={onTrackClick}
            className="relative h-3 bg-[#0a0a0a] border-b border-[#8B5CF6]/20 cursor-pointer select-none"
            data-testid="my-tx-top-scrollbar"
            aria-hidden="true"
          >
            <div
              onMouseDown={onThumbDown}
              onTouchStart={onThumbDown}
              onClick={(e) => e.stopPropagation()}
              className="absolute top-0.5 bottom-0.5 rounded-full bg-[#8B5CF6] hover:bg-[#A78BFA] transition-colors cursor-grab active:cursor-grabbing shadow-[0_0_8px_rgba(139,92,246,0.5)]"
              style={{ left: `${thumbLeft}px`, width: `${thumbW}px` }}
              data-testid="my-tx-top-scrollbar-thumb"
            />
          </div>
        )}
        {/* Actual scrollable body: vertical scroll bound to the table, not the page */}
        <div
          ref={bodyScrollRef}
          onScroll={onBodyScroll}
          className="tx-body-scroll overflow-x-auto overflow-y-auto max-h-[70vh]"
          data-testid="my-tx-body-scroll"
        >
          <table ref={tableRef} className="w-full text-sm">
            <thead className="border-b border-white/10 bg-[#0a0a0a] sticky top-0 z-10">
              <tr className="text-left">
                <th className="px-3 py-3 micro-label text-neutral-500">{t("myTransactions.table.pair")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500">{t("myTransactions.table.type")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500 text-right">{t("myTransactions.table.sends")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500 text-right">{t("myTransactions.table.receives")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500">{t("myTransactions.table.status")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500">{t("myTransactions.table.date")}</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan="6" className="text-center text-neutral-500 py-8">
                    {t("myTransactions.table.loading")}
                  </td>
                </tr>
              )}
              {!loading && items.length === 0 && (
                <tr>
                  <td colSpan="6" className="text-center text-neutral-500 py-8">
                    {hasFilters ? t("myTransactions.table.emptyFiltered") : t("myTransactions.table.empty")}
                  </td>
                </tr>
              )}
              {items.map((it) => (
                <TransactionRow key={`${it.ref_type}-${it.ref_id}`} it={it} onSelect={setSelected} t={t} />
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <Dialog open={!!selected} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent
          data-testid="my-tx-modal"
          className="bg-[#0c0c0c] border border-white/10 text-white max-w-2xl rounded-none max-h-[85vh] overflow-y-auto"
        >
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-white">
              <Receipt className="w-5 h-5 text-[#8B5CF6]" />
              {t("myTransactions.detail.title")}
              {selected && (() => {
                const meta = kindMeta(selected, t);
                const Icon = meta.icon;
                return (
                  <span
                    className="ml-2 text-xs font-bold uppercase flex items-center gap-1"
                    style={{ color: meta.color }}
                  >
                    <Icon className="w-3 h-3" /> {meta.label}
                  </span>
                );
              })()}
            </DialogTitle>
          </DialogHeader>
          {selected && <TransactionDetail selected={selected} t={t} />}
        </DialogContent>
      </Dialog>
    </>
  );
}

function TransactionRow({ it, onSelect, t }) {
  const meta = kindMeta(it, t);
  const Icon = meta.icon;
  const pair = hasPair(it);
  const isConversion = meta.kind === "conversion";
  const showFlow = pair && (isConversion || meta.kind === "exchange");
  return (
    <tr
      data-testid={`my-tx-row-${it.ref_id}`}
      data-direction={it.direction}
      onClick={() => onSelect(it)}
      className="border-b border-white/5 hover:bg-[#8B5CF6]/5 cursor-pointer transition-colors"
    >
      <td className="px-3 py-2 whitespace-nowrap">
        {showFlow ? (
          <CurrencyPairIcon from={it.from_code} to={it.to_code} size="sm" showLabel className="text-xs" />
        ) : (
          <span className="inline-flex items-center gap-1.5 font-mono text-[#8B5CF6] whitespace-nowrap">
            <CurrencyIcon code={it.currency} size="sm" />
            {it.currency}
          </span>
        )}
      </td>
      <td className="px-3 py-2 whitespace-nowrap">
        <span
          className="inline-flex items-center gap-1 text-xs font-bold uppercase"
          style={{ color: meta.color }}
        >
          <Icon className="w-3 h-3" /> {meta.label}
        </span>
        {meta.kind === "exchange" && it.direction === "in" && (
          <div className="mt-0.5">
            <span className="inline-flex items-center px-1.5 py-0.5 text-[0.6rem] uppercase tracking-wider bg-[#22C55E]/10 text-[#22C55E] border border-[#22C55E]/30 font-mono">
              {t("myTransactions.table.in")}
            </span>
          </div>
        )}
        {meta.kind === "exchange" && it.direction === "out" && (
          <div className="mt-0.5">
            <span className="inline-flex items-center px-1.5 py-0.5 text-[0.6rem] uppercase tracking-wider bg-[#EF4444]/10 text-[#EF4444] border border-[#EF4444]/30 font-mono">
              {t("myTransactions.table.out")}
            </span>
          </div>
        )}
        {isConversion && it.conversion_subtype === "small_balance" && (
          <div className="mt-0.5">
            <span
              className="inline-flex items-center px-1.5 py-0.5 text-[0.6rem] uppercase tracking-wider bg-[#F59E0B]/10 text-[#F59E0B] border border-[#F59E0B]/30 font-mono"
              data-testid={`my-tx-subtype-small-${it.ref_id}`}
            >
              {t("myTransactions.table.subtypeSmall")}
            </span>
          </div>
        )}
      </td>
      <td className="px-3 py-2 font-mono text-right whitespace-nowrap">
        {showFlow ? (
          <span className="text-neutral-300">{fmt(it.amount_from ?? it.amount)} {it.from_code}</span>
        ) : meta.kind === "withdrawal" ? (
          <span className="text-[#EF4444]">-{fmt(it.amount)} {it.currency}</span>
        ) : (
          <span className="text-neutral-600">—</span>
        )}
      </td>
      <td className="px-3 py-2 font-mono text-right whitespace-nowrap">
        {showFlow ? (
          <span className="text-[#8B5CF6]">{fmt(it.amount_to)} {it.to_code}</span>
        ) : meta.kind === "deposit" ? (
          <span className="text-[#22C55E]">+{fmt(it.amount)} {it.currency}</span>
        ) : (
          <span className="text-neutral-600">—</span>
        )}
      </td>
      <td className="px-3 py-2 text-xs uppercase text-neutral-500 whitespace-nowrap">{it.status}</td>
      <td className="px-3 py-2 font-mono text-xs text-neutral-400 whitespace-nowrap">
        {new Date(it.created_at).toLocaleString()}
      </td>
    </tr>
  );
}

function TransactionDetail({ selected, t }) {
  const meta = kindMeta(selected, t);
  const pair = hasPair(selected) && meta.kind === "exchange";
  return (
    <div className="space-y-4 text-sm">
      {selected.direction === "conversion" ? (
        <ConversionDetailBlock selected={selected} t={t} />
      ) : (
        <div className="grid grid-cols-2 gap-3 border border-white/5 p-4 bg-[#0a0a0a]">
          {pair ? (
            <>
              <div className="col-span-2">
                <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.table.pair")}</div>
                <CurrencyPairIcon from={selected.from_code} to={selected.to_code} size="md" showLabel />
              </div>
              <div>
                <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.table.sends")}</div>
                <div className="font-mono text-lg">{fmt(selected.amount_from)} {selected.from_code}</div>
              </div>
              <div>
                <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.table.receives")}</div>
                <div className="font-mono text-lg text-[#8B5CF6]">{fmt(selected.amount_to)} {selected.to_code}</div>
              </div>
            </>
          ) : (
            <>
              <div>
                <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.detail.currency")}</div>
                <div className="font-mono text-[#8B5CF6] text-lg flex items-center gap-2">
                  <CurrencyIcon code={selected.currency} size="md" />
                  {selected.currency}
                </div>
              </div>
              <div>
                <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.detail.amount")}</div>
                <div className="font-mono text-xl">{selected.amount.toLocaleString()}</div>
              </div>
            </>
          )}
          <div>
            <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.detail.holder")}</div>
            <div className="font-medium">{selected.holder_name || "—"}</div>
          </div>
          <div>
            <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.detail.method")}</div>
            <div className="uppercase text-xs">
              {selected.ref_type === "vip_batch_item"
                ? t("myTransactions.table.methodBatch")
                : selected.method}
            </div>
          </div>
          <div>
            <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.detail.status")}</div>
            <div className="uppercase text-xs text-[#22C55E]">{selected.status}</div>
          </div>
          <div>
            <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.detail.date")}</div>
            <div className="font-mono text-xs">{new Date(selected.created_at).toLocaleString()}</div>
          </div>
          <div className="col-span-2">
            <div className="micro-label text-neutral-500 mb-1">
              {selected.ref_type === "withdrawal" ? t("myTransactions.detail.withdrawalId") : t("myTransactions.detail.orderId")}
            </div>
            <div className="font-mono text-xs text-neutral-400">{selected.ref_id}</div>
          </div>
        </div>
      )}
      {selected.delivery_details && selected.direction !== "conversion" && (
        <div className="border border-white/5 p-4 bg-[#0a0a0a]">
          <div className="micro-label text-neutral-500 mb-2">
            {selected.direction === "in" ? t("myTransactions.detail.senderData") : t("myTransactions.detail.recipientData")}
          </div>
          <div className="text-sm whitespace-pre-wrap font-mono text-neutral-300">
            {selected.delivery_details}
          </div>
        </div>
      )}
      {selected.direction !== "conversion"
        && (selected.method === "crypto" || selected.crypto_network)
        && selected.payout_tx_hash && (
        <PayoutTxBlock selected={selected} t={t} />
      )}
      {(selected.direction === "in" || selected.ref_type === "order_payout")
        && selected.proof_image && selected.proof_image.trim() && (
        <div>
          <div className="micro-label text-neutral-500 mb-2">
            {selected.ref_type === "order_payout"
              ? t("myTransactions.detail.payoutProof")
              : t("myTransactions.detail.proof")}
          </div>
          <a
            href={selected.proof_image}
            target="_blank"
            rel="noreferrer"
            className="block border border-white/10 bg-[#0a0a0a] p-2"
          >
            <img
              src={selected.proof_image}
              alt={t("myTransactions.detail.proof")}
              className="w-full max-h-96 object-contain bg-black"
              onError={(e) => { e.currentTarget.style.display = "none"; }}
            />
          </a>
        </div>
      )}
      {selected.direction === "out" && selected.ref_type !== "order_payout" && (
        <div className="border border-dashed border-white/10 p-4 text-center text-xs text-neutral-500">
          <X className="w-4 h-4 inline mr-1" /> {t("myTransactions.detail.outflowsHaveNoProof")}
        </div>
      )}
    </div>
  );
}

function PayoutTxBlock({ selected, t }) {
  return (
    <div
      className="border border-[#8B5CF6]/30 bg-[#8B5CF6]/5 p-4"
      data-testid="my-tx-payout-tx-block"
    >
      {selected.crypto_network && (
        <div className="flex items-center gap-2 mb-2">
          <span className="micro-label text-neutral-500">
            {t("myTransactions.detail.cryptoNetwork")}
          </span>
          <span
            data-testid="my-tx-payout-network"
            className="inline-flex items-center px-1.5 py-0.5 text-[0.7rem] uppercase tracking-wider bg-[#8B5CF6]/10 text-[#8B5CF6] border border-[#8B5CF6]/30 font-mono"
          >
            {selected.crypto_network}
          </span>
        </div>
      )}
      <div className="micro-label text-neutral-500 mb-1.5">
        {t("myTransactions.detail.txHashLabel")}
      </div>
      <div className="flex items-start gap-2">
        <code
          data-testid="my-tx-payout-hash"
          className="flex-1 text-xs font-mono text-neutral-200 break-all"
        >
          {selected.payout_tx_hash}
        </code>
        <button
          type="button"
          onClick={() => {
            navigator.clipboard.writeText(selected.payout_tx_hash);
            toast.success(t("common.copied"));
          }}
          data-testid="my-tx-payout-hash-copy"
          className="shrink-0 text-[#8B5CF6] hover:text-[#A78BFA] p-1"
          title={t("common.copied")}
        >
          <FileText className="w-3.5 h-3.5" />
        </button>
      </div>
      {selected.explorer_url && (
        <a
          href={selected.explorer_url}
          target="_blank"
          rel="noopener noreferrer"
          data-testid="my-tx-payout-explorer"
          className="mt-2 inline-flex items-center gap-1.5 text-xs text-[#8B5CF6] hover:text-[#A78BFA] hover:underline"
        >
          <Download className="w-3 h-3 rotate-180" /> {t("myTransactions.detail.viewOnExplorer")}
        </a>
      )}
    </div>
  );
}

function ConversionDetailBlock({ selected, t }) {
  const isSmall = selected.conversion_subtype === "small_balance";
  return (
    <div className="border border-[#8B5CF6]/20 bg-[#8B5CF6]/5 p-4 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="micro-label text-[#8B5CF6]">
          {t("myTransactions.detail.conversionTitle")}
        </div>
        <span
          className={
            "inline-flex items-center px-2 py-0.5 text-[0.65rem] uppercase tracking-wider font-mono border "
            + (isSmall
              ? "bg-[#F59E0B]/10 text-[#F59E0B] border-[#F59E0B]/30"
              : "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30")
          }
          data-testid="my-tx-conversion-subtype"
        >
          {isSmall
            ? t("myTransactions.detail.subtypeSmall")
            : t("myTransactions.detail.subtypeNormal")}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.detail.from")}</div>
          <div className="font-mono text-lg flex items-center gap-2">
            <CurrencyIcon code={selected.from_code} size="md" />
            <div>
              <div>{Number(selected.amount_from || 0).toLocaleString(undefined, { maximumFractionDigits: 4 })}</div>
              <div className="text-[0.65rem] text-neutral-500">{selected.from_code}</div>
            </div>
          </div>
        </div>
        <div>
          <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.detail.to")}</div>
          <div className="font-mono text-lg flex items-center gap-2">
            <CurrencyIcon code={selected.to_code} size="md" />
            <div>
              <div className="text-[#8B5CF6]">
                {Number(selected.amount_to || 0).toLocaleString(undefined, { maximumFractionDigits: 4 })}
              </div>
              <div className="text-[0.65rem] text-neutral-500">{selected.to_code}</div>
            </div>
          </div>
        </div>
        <div>
          <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.detail.rate")}</div>
          <div className="font-mono text-xs text-neutral-300">
            1 {selected.from_code} ≈ {Number(selected.rate || 0).toFixed(6)} {selected.to_code}
          </div>
        </div>
        <div>
          <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.detail.fee")}</div>
          <div className="font-mono text-sm text-[#EF4444]">
            −{Number(selected.usdt_fee || 0).toFixed(2)} USDT
          </div>
        </div>
        <div>
          <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.detail.date")}</div>
          <div className="font-mono text-xs">{new Date(selected.created_at).toLocaleString()}</div>
        </div>
        <div>
          <div className="micro-label text-neutral-500 mb-1">
            {t("myTransactions.detail.sourceUsdtValue")}
          </div>
          <div className="font-mono text-xs text-neutral-400">
            ≈ {Number(selected.amount_from_usdt || 0).toFixed(4)} USDT
          </div>
        </div>
      </div>
    </div>
  );
}
