import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { History } from "lucide-react";

/**
 * iter55.29 — Extracted from VipView. Modal that shows the drill-down of
 * orders that credited a specific currency to the client's balance.
 */
export function VipLedgerDialog({ open, onOpenChange, currency, bucket }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="bg-[#111] border-white/10 text-white rounded-none max-w-2xl max-h-[80vh] overflow-y-auto"
        data-testid="ledger-dialog"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <History className="w-5 h-5 text-[#8B5CF6]" />
            Órdenes que acreditaron {currency}
          </DialogTitle>
        </DialogHeader>
        <div className="pt-2 space-y-3" data-testid={`ledger-orders-${currency}`}>
          {(!bucket || bucket.orders.length === 0) ? (
            <p className="text-sm text-neutral-500">
              No hay órdenes registradas para esta moneda.
            </p>
          ) : (
            <>
              <div className="border border-[#8B5CF6]/30 bg-[#8B5CF6]/5 p-3 flex justify-between items-baseline">
                <span className="text-xs text-neutral-400">Total acreditado:</span>
                <span className="font-mono text-lg text-[#8B5CF6]">
                  {bucket.total.toLocaleString(undefined, { maximumFractionDigits: 4 })} {currency}
                </span>
              </div>
              {bucket.orders.map((o) => (
                <LedgerOrderRow key={o.id} order={o} />
              ))}
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}


function LedgerOrderRow({ order: o }) {
  return (
    <div
      className="border border-white/10 p-3 text-sm"
      data-testid={`ledger-order-${o.id}`}
    >
      <div className="flex justify-between items-start gap-2 flex-wrap">
        <div>
          <div className="font-mono">
            +{Number(o.amount_to).toLocaleString(undefined, { maximumFractionDigits: 4 })} {o.to_code}
          </div>
          <div className="text-xs text-neutral-500 mt-0.5">
            desde {Number(o.amount_from).toLocaleString(undefined, { maximumFractionDigits: 2 })} {o.from_code}
            {o.sender_name && (
              <span className="text-neutral-600"> · {o.sender_name}</span>
            )}
          </div>
        </div>
        <div className="text-right">
          <span className="text-[0.65rem] uppercase tracking-wider text-[#22C55E]">
            {o.status}
          </span>
          <div className="text-[0.65rem] text-neutral-600 mt-0.5">
            {new Date(o.accumulated_at || o.created_at).toLocaleString()}
          </div>
        </div>
      </div>
      <div className="text-[0.6rem] text-neutral-700 font-mono mt-2">
        ID: {o.id}
      </div>
    </div>
  );
}
