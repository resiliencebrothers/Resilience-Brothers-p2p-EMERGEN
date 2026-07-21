/**
 * iter83 — TransactionTable
 *
 * Renders the paginated ledger table + the row-detail modal. Owns the
 * "selected row" local state because it's a purely UI concern that lives
 * and dies with the table (no upstream state consumer).
 *
 * Extracted from the original MyTransactions.jsx (iter78/iter79) with
 * behaviour-preserving edits only — CSS classes, testids, dialog wiring
 * and copy are byte-identical.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import CurrencyIcon from "@/components/CurrencyIcon";
import {
  Receipt, ArrowDown, ArrowUp, ArrowRightLeft, Download, FileText, X,
} from "lucide-react";

// Row-style resolver. Keeps colour + icon + label together per direction.
export function directionMeta(direction, t) {
  if (direction === "in") {
    return { color: "#22C55E", icon: ArrowDown, label: t("myTransactions.table.in") };
  }
  if (direction === "out") {
    return { color: "#EF4444", icon: ArrowUp, label: t("myTransactions.table.out") };
  }
  return { color: "#8B5CF6", icon: ArrowRightLeft, label: t("myTransactions.table.conversion") };
}

export default function TransactionTable({ items, loading, hasFilters }) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState(null);

  return (
    <>
      <div className="tactile-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-white/10 bg-[#0a0a0a]">
              <tr className="text-left">
                <th className="px-3 py-3 micro-label text-neutral-500">{t("myTransactions.table.date")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500">{t("myTransactions.table.type")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500">{t("myTransactions.table.currency")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500 text-right">{t("myTransactions.table.amount")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500">{t("myTransactions.table.holder")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500">{t("myTransactions.table.method")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500">{t("myTransactions.table.status")}</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan="7" className="text-center text-neutral-500 py-8">
                    {t("myTransactions.table.loading")}
                  </td>
                </tr>
              )}
              {!loading && items.length === 0 && (
                <tr>
                  <td colSpan="7" className="text-center text-neutral-500 py-8">
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
                const meta = directionMeta(selected.direction, t);
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
  const meta = directionMeta(it.direction, t);
  const Icon = meta.icon;
  const isConversion = it.direction === "conversion";
  return (
    <tr
      data-testid={`my-tx-row-${it.ref_id}`}
      data-direction={it.direction}
      onClick={() => onSelect(it)}
      className="border-b border-white/5 hover:bg-[#8B5CF6]/5 cursor-pointer transition-colors"
    >
      <td className="px-3 py-2 font-mono text-xs text-neutral-400">
        {new Date(it.created_at).toLocaleString()}
      </td>
      <td className="px-3 py-2">
        <span
          className="inline-flex items-center gap-1 text-xs font-bold uppercase"
          style={{ color: meta.color }}
        >
          <Icon className="w-3 h-3" /> {meta.label}
        </span>
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
      <td className="px-3 py-2">
        {isConversion ? (
          <span className="inline-flex items-center gap-1 font-mono text-xs">
            <CurrencyIcon code={it.from_code} size="sm" />
            <span className="text-neutral-300">{it.from_code}</span>
            <ArrowRightLeft className="w-3 h-3 text-[#8B5CF6] mx-0.5" />
            <CurrencyIcon code={it.to_code} size="sm" />
            <span className="text-neutral-300">{it.to_code}</span>
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 font-mono text-[#8B5CF6]">
            <CurrencyIcon code={it.currency} size="sm" />
            {it.currency}
          </span>
        )}
      </td>
      <td className="px-3 py-2 font-mono text-right">
        {isConversion ? (
          <span className="text-neutral-300">
            {Number(it.amount_from || it.amount).toLocaleString(undefined, { maximumFractionDigits: 4 })}
            <span className="text-neutral-600 mx-1">→</span>
            <span className="text-[#8B5CF6]">
              {Number(it.amount_to || 0).toLocaleString(undefined, { maximumFractionDigits: 4 })}
            </span>
          </span>
        ) : it.amount.toLocaleString()}
      </td>
      <td className="px-3 py-2">{it.holder_name || "—"}</td>
      <td className="px-3 py-2 text-xs uppercase text-neutral-500">
        {isConversion ? t("myTransactions.table.methodSelfConvert") : it.method}
      </td>
      <td className="px-3 py-2 text-xs uppercase text-neutral-500">{it.status}</td>
    </tr>
  );
}

function TransactionDetail({ selected, t }) {
  return (
    <div className="space-y-4 text-sm">
      {selected.direction === "conversion" ? (
        <ConversionDetailBlock selected={selected} t={t} />
      ) : (
        <div className="grid grid-cols-2 gap-3 border border-white/5 p-4 bg-[#0a0a0a]">
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
          <div>
            <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.detail.holder")}</div>
            <div className="font-medium">{selected.holder_name || "—"}</div>
          </div>
          <div>
            <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.detail.method")}</div>
            <div className="uppercase text-xs">{selected.method}</div>
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
