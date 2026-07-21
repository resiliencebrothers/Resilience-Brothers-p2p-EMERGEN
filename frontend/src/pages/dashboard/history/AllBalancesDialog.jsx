/**
 * iter84 — AllBalancesDialog
 *
 * Modal that shows the user's full wallet in a single scrollable list.
 * The History section's balance summary widget already renders the top
 * 8 positive balances inline; this dialog is the "see all" expansion.
 *
 * Layout per row: currency icon · code + name · amount · USDT equivalent.
 * Sorted by USDT equivalent (descending) so the biggest positions show
 * up first. Zero balances are hidden.
 */
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import CurrencyIcon from "@/components/CurrencyIcon";
import { Wallet } from "lucide-react";

export default function AllBalancesDialog({ open, onOpenChange, balanceSummary }) {
  const { t } = useTranslation();
  const rows = useMemo(() => {
    const list = (balanceSummary?.balances || [])
      .filter((b) => Number(b.amount) > 0)
      .map((b) => ({
        currency: b.currency,
        amount: Number(b.amount),
        usdt: Number(b.usdt_equivalent || 0),
      }));
    list.sort((a, b) => b.usdt - a.usdt);
    return list;
  }, [balanceSummary]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="all-balances-dialog"
        className="bg-[#0c0c0c] border border-white/10 text-white max-w-xl rounded-none max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-white">
            <Wallet className="w-5 h-5 text-[#8B5CF6]" />
            {t("myTransactions.allBalances.title")}
            <span className="ml-auto font-mono text-sm text-neutral-500">
              {rows.length}
            </span>
          </DialogTitle>
          <DialogDescription className="text-neutral-500 text-xs">
            {t("myTransactions.allBalances.subtitle")}
          </DialogDescription>
        </DialogHeader>

        <div className="text-right border-b border-white/5 pb-3 mb-1">
          <div className="micro-label text-neutral-500 mb-0.5">
            {t("myTransactions.allBalances.totalLabel")}
          </div>
          <div className="font-mono text-2xl text-[#8B5CF6]">
            {Number(balanceSummary?.total_usdt || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
            <span className="text-sm text-neutral-500 ml-2">USDT</span>
          </div>
        </div>

        {rows.length === 0 ? (
          <div className="text-center text-sm text-neutral-500 py-8" data-testid="all-balances-empty">
            {t("myTransactions.allBalances.empty")}
          </div>
        ) : (
          <div className="divide-y divide-white/5">
            {rows.map((r) => (
              <div
                key={r.currency}
                className="flex items-center justify-between py-2.5 gap-3"
                data-testid={`all-balances-row-${r.currency}`}
              >
                <div className="flex items-center gap-3">
                  <CurrencyIcon code={r.currency} size="md" />
                  <div>
                    <div className="text-sm font-semibold text-white">{r.currency}</div>
                    <div className="text-[0.65rem] text-neutral-600 font-mono">
                      ≈ {r.usdt.toLocaleString(undefined, { maximumFractionDigits: 2 })} USDT
                    </div>
                  </div>
                </div>
                <div className="font-mono text-sm text-neutral-200">
                  {r.amount.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                </div>
              </div>
            ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
