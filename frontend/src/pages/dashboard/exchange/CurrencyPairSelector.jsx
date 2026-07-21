import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export default function CurrencyPairSelector({
  currencies, receivableCurrencies, fromCode, toCode, amount,
  onFromChange, onToChange, onAmountChange,
}) {
  const { t } = useTranslation();
  // iter75 — Destination list is filtered against the source currency's
  // configured rate table (strict direct-rate only). Falls back to `currencies`
  // when the parent hasn't computed the receivable list yet (e.g. no source
  // picked). See ExchangeView for the whitelist logic.
  const toOptions = receivableCurrencies ?? currencies;
  const noDestinations = !!fromCode && toOptions.length === 0;
  return (
    <>
      <div className="grid md:grid-cols-2 gap-4">
        <CurrencySelect
          currencies={currencies}
          value={fromCode}
          onChange={onFromChange}
          label={t("exchange.from")}
          testid="from-currency-select"
        />
        <CurrencySelect
          currencies={toOptions}
          value={toCode}
          onChange={onToChange}
          label={t("exchange.to")}
          testid="to-currency-select"
          disabled={noDestinations}
          emptyLabel={noDestinations ? t("exchange.noReceivable") : undefined}
        />
      </div>
      {noDestinations && (
        <p
          data-testid="no-receivable-hint"
          className="text-[0.7rem] text-[#F59E0B] font-mono -mt-2"
        >
          {t("exchange.noReceivableHint", { code: fromCode })}
        </p>
      )}
      <div>
        <Label className="micro-label text-neutral-500">{t("exchange.amount")}</Label>
        <Input
          data-testid="amount-input"
          type="number"
          value={amount}
          onChange={(e) => onAmountChange(e.target.value)}
          placeholder="0.00"
          className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12 text-lg font-mono"
        />
      </div>
    </>
  );
}

function CurrencySelect({ currencies, value, onChange, label, testid, disabled, emptyLabel }) {
  const { t } = useTranslation();
  return (
    <div>
      <Label className="micro-label text-neutral-500">{label}</Label>
      <Select value={value} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger
          data-testid={testid}
          className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12 disabled:opacity-60"
        >
          <SelectValue placeholder={emptyLabel || t("exchange.selectCurrency")} />
        </SelectTrigger>
        <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
          {currencies.map((c) => (
            <SelectItem key={c.id || c.code} value={c.code} className="rounded-none">
              {c.code} — {c.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
