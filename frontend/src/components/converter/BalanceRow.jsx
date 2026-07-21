import { Button } from "@/components/ui/button";
import { ArrowRightLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import CurrencyIcon from "@/components/CurrencyIcon";

/**
 * iter55.29 — Extracted balance row for the converter card. Renders one
 * currency balance with the "Convertir" trigger.
 */
export function BalanceRow({ balance, onConvert }) {
  const { t } = useTranslation();
  const { currency, amount, usdt_equivalent } = balance;
  return (
    <div
      className="flex items-center justify-between border border-white/5 hover:border-[#8B5CF6]/30 transition-colors p-3"
      data-testid={`converter-row-${currency}`}
    >
      <div className="flex items-center gap-3">
        <CurrencyIcon code={currency} size="md" />
        <div>
          <div className="font-mono text-sm text-neutral-200">
            {Number(amount).toLocaleString(undefined, { maximumFractionDigits: 4 })}
            <span className="text-neutral-500 ml-1">{currency}</span>
          </div>
          {usdt_equivalent != null && currency !== "USDT" && (
            <div className="text-[0.65rem] text-neutral-600 font-mono mt-0.5">
              ≈ {usdt_equivalent.toLocaleString(undefined, { maximumFractionDigits: 2 })} USDT
            </div>
          )}
        </div>
      </div>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => onConvert(currency)}
        className="text-[#8B5CF6] hover:bg-[#8B5CF6]/10 rounded-none gap-1"
        data-testid={`converter-trigger-${currency}`}
      >
        <ArrowRightLeft className="w-3.5 h-3.5" />
        {t("balanceConverter.dialogTitle")}
      </Button>
    </div>
  );
}
