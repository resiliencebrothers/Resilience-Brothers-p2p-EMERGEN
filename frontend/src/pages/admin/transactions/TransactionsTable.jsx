import { ArrowDown, ArrowUp } from "lucide-react";
import { useTranslation } from "react-i18next";
import { OriginBadge } from "./OriginBadge";

export function TransactionsTable({ items, loading, onRowClick }) {
  const { t } = useTranslation();
  const tx = (k) => t(`admin.transactions.${k}`);
  return (
    <div className="tactile-card overflow-hidden">
      <div className="overflow-x-auto overflow-y-auto max-h-[70vh]" data-testid="transactions-table-scroll">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10 border-b border-white/10 bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-3 py-3 micro-label text-neutral-500">{tx("colDate")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{tx("colType")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{tx("colOrigin")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{tx("colCurrency")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500 text-right">{tx("colAmount")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{tx("colHolder")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{tx("colAccount")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{tx("colClient")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{tx("colMethod")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{tx("colStatus")}</th>
              <th className="px-3 py-3 micro-label text-neutral-500">{tx("colRef")}</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan="11" className="text-center text-neutral-500 py-8">
                  {tx("loading")}
                </td>
              </tr>
            )}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan="11" className="text-center text-neutral-500 py-8">
                  {tx("empty")}
                </td>
              </tr>
            )}
            {items.map((it) => (
              <tr
                key={`${it.ref_type}-${it.ref_id}`}
                data-testid={`tx-row-${it.ref_id}`}
                onClick={() => onRowClick(it)}
                className="border-b border-white/5 hover:bg-[#8B5CF6]/5 cursor-pointer transition-colors"
              >
                <td className="px-3 py-2 font-mono text-xs text-neutral-400">
                  {new Date(it.created_at).toLocaleString()}
                </td>
                <td className="px-3 py-2">
                  {it.direction === "in" ? (
                    <span className="inline-flex items-center gap-1 text-[#22C55E] text-xs font-bold uppercase">
                      <ArrowDown className="w-3 h-3" /> {tx("in")}
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-[#EF4444] text-xs font-bold uppercase">
                      <ArrowUp className="w-3 h-3" /> {tx("out")}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <OriginBadge refType={it.ref_type} testid={`tx-origin-${it.ref_id}`} />
                </td>
                <td className="px-3 py-2 font-mono text-[#8B5CF6]">{it.currency}</td>
                <td className="px-3 py-2 font-mono text-right">{it.amount.toLocaleString()}</td>
                <td className="px-3 py-2">
                  {it.holder_name || <span className="text-neutral-600">—</span>}
                </td>
                <td className="px-3 py-2 text-xs" data-testid={`tx-account-${it.ref_id}`}>
                  {it.payment_account_label ? (
                    <span className="text-emerald-400">{it.payment_account_label}</span>
                  ) : (it.direction === "in" && (it.ref_type === "deposit" || it.ref_type === "order")) ? (
                    <span className="text-amber-500/80">{tx("accountMissingShort")}</span>
                  ) : (
                    <span className="text-neutral-600">—</span>
                  )}
                </td>
                <td className="px-3 py-2 text-neutral-400">{it.client_name}</td>
                <td className="px-3 py-2 text-xs uppercase text-neutral-500">{it.method}</td>
                <td className="px-3 py-2 text-xs uppercase text-neutral-500">{it.status}</td>
                <td className="px-3 py-2 font-mono text-xs text-neutral-600">
                  {it.ref_id?.slice(0, 6)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
