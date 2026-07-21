import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { ArrowRightLeft } from "lucide-react";
import { ConvertPreview } from "@/components/converter/ConvertPreview";
import CurrencyIcon from "@/components/CurrencyIcon";

/**
 * Conversion modal. Fully controlled by BalanceConverterCard: it owns
 * `fromCode`, `toCode`, `amount`, all preview numbers, and `submit`.
 * This component is presentational.
 */
export default function ConvertDialog({
  open, onOpenChange,
  isVip,
  fromCode, toCode, amount,
  onToCodeChange, onAmountChange, onMax,
  currencies, positive,
  previewRate, previewNet,
  feeUsdt, minSourceUsdt, belowMinSource, previewSourceUsdt,
  insufficientUsdtForFee, usdtBalance,
  busy, onSubmit,
}) {
  const { t } = useTranslation();
  const balance = positive.find((x) => x.currency === fromCode)?.amount || 0;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#111] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2" data-testid="converter-dialog-title">
            {t("balanceConverter.dialogTitle")}
            <span className="inline-flex items-center gap-1">
              <CurrencyIcon code={fromCode} size="sm" />
              {fromCode}
            </span>
            <ArrowRightLeft className="w-4 h-4 text-[#8B5CF6]" />
            <span className="inline-flex items-center gap-1">
              <CurrencyIcon code={toCode} size="sm" />
              {toCode}
            </span>
          </DialogTitle>
          <DialogDescription className="text-neutral-400 text-xs">
            {t("balanceConverter.dialogDescription", {
              tier: isVip ? "VIP" : t("balanceConverter.tierStandard"),
              fee: feeUsdt.toFixed(2),
              min: minSourceUsdt.toFixed(2),
            })}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 pt-4">
          <div>
            <Label className="micro-label text-neutral-500">{t("balanceConverter.toCurrencyLabel")}</Label>
            <Select value={toCode} onValueChange={onToCodeChange}>
              <SelectTrigger
                data-testid="converter-to-code"
                className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12"
              >
                <SelectValue placeholder={t("balanceConverter.selectDestination")} />
              </SelectTrigger>
              <SelectContent className="bg-[#111] border-white/10 text-white">
                {currencies
                  .filter((c) => c.code !== fromCode && c.is_convertible_to !== false)
                  .map((c) => (
                    <SelectItem
                      key={c.code}
                      value={c.code}
                      data-testid={`converter-to-option-${c.code}`}
                    >
                      {c.code} · {c.name}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="micro-label text-neutral-500">
              {t("balanceConverter.amountOfLabel", { code: fromCode })}
            </Label>
            <div className="flex items-center gap-2 mt-2">
              <Input
                data-testid="converter-amount"
                type="number"
                min="0"
                step="any"
                value={amount}
                onChange={(e) => onAmountChange(e.target.value)}
                className="rounded-none bg-[#0a0a0a] border-white/10 h-12 font-mono"
              />
              <Button
                variant="ghost"
                className="text-xs text-[#8B5CF6] h-12 rounded-none px-3 hover:bg-[#8B5CF6]/10"
                onClick={onMax}
                data-testid="converter-max"
              >{t("balanceConverter.maxBtn")}</Button>
            </div>
            {fromCode && (
              <div className="text-[0.65rem] text-neutral-500 mt-1 font-mono">
                {t("balanceConverter.availableBalance", {
                  amount: Number(balance).toLocaleString(undefined, { maximumFractionDigits: 4 }),
                  code: fromCode,
                })}
              </div>
            )}
          </div>
          <ConvertPreview
            fromCode={fromCode}
            toCode={toCode}
            previewRate={previewRate}
            previewNet={previewNet}
            feeUsdt={feeUsdt}
            belowMinSource={belowMinSource}
            minSourceUsdt={minSourceUsdt}
            previewSourceUsdt={previewSourceUsdt}
          />
          {insufficientUsdtForFee && (
            <div
              className="border border-[#EF4444]/40 bg-[#EF4444]/5 p-3 text-xs text-[#EF4444] leading-relaxed"
              data-testid="converter-insufficient-usdt-fee"
            >
              {fromCode === "USDT"
                ? t("balanceConverter.insufficientUsdtSelf", {
                    balance: usdtBalance.toFixed(4),
                    fee: feeUsdt.toFixed(2),
                  })
                : t("balanceConverter.insufficientUsdtOther", {
                    balance: usdtBalance.toFixed(4),
                    fee: feeUsdt.toFixed(2),
                  })}
            </div>
          )}
          <Button
            data-testid="confirm-converter"
            onClick={onSubmit}
            disabled={busy || !amount || previewRate === null || belowMinSource || insufficientUsdtForFee}
            className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-12 flex items-center justify-center gap-2 disabled:opacity-50"
          >
            <ArrowRightLeft className="w-4 h-4" />
            {busy ? t("balanceConverter.convertingBtn") : t("balanceConverter.confirmBtn")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
