import { useTranslation } from "react-i18next";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { getDeliveryValidator } from "@/services/delivery_validators";

/**
 * Delivery method + delivery-details editor. For crypto deliveries also
 * shows the mandatory chain selector because BEP20/ERC20/POLYGON share the
 * same 0x address format.
 */
export default function DeliverySection({
  toCurr,
  deliveryOptions,
  deliveryMethod, onDeliveryMethodChange,
  deliveryDetails, onDeliveryDetailsChange,
  cryptoNetwork, onCryptoNetworkChange,
}) {
  const { t } = useTranslation();
  return (
    <>
      <DeliveryMethodPicker
        toCurr={toCurr}
        deliveryOptions={deliveryOptions}
        deliveryMethod={deliveryMethod}
        onDeliveryMethodChange={onDeliveryMethodChange}
      />
      {deliveryMethod !== "accumulate" && (
        <DeliveryDetailsBlock
          toCurr={toCurr}
          deliveryMethod={deliveryMethod}
          deliveryDetails={deliveryDetails}
          onDeliveryDetailsChange={onDeliveryDetailsChange}
          cryptoNetwork={cryptoNetwork}
          onCryptoNetworkChange={onCryptoNetworkChange}
        />
      )}
    </>
  );
}

function DeliveryMethodPicker({ toCurr, deliveryOptions, deliveryMethod, onDeliveryMethodChange }) {
  const { t } = useTranslation();
  const hasCash = deliveryOptions.some((o) => o.value === "cash");
  const hasAccumulate = deliveryOptions.some((o) => o.value === "accumulate");
  const hasTransfer = deliveryOptions.some((o) => o.value === "transfer");
  return (
    <div>
      <Label className="micro-label text-neutral-500">{t("exchange.selectMethodLabel")}</Label>
      <Select
        value={deliveryMethod}
        onValueChange={onDeliveryMethodChange}
        disabled={!toCurr}
      >
        <SelectTrigger
          data-testid="delivery-method-select"
          className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12"
        >
          <SelectValue placeholder={toCurr ? t("exchange.selectMethod") : t("exchange.selectCurrency")} />
        </SelectTrigger>
        <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
          {deliveryOptions.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
          ))}
        </SelectContent>
      </Select>
      {toCurr?.type === "crypto" && (
        <p className="text-[0.65rem] text-neutral-600 mt-2">
          Como recibes {toCurr.code} (cripto), solo se envía a tu wallet. La entrega física no aplica.
        </p>
      )}
      {toCurr?.type !== "crypto" && deliveryOptions.length > 0 && !hasCash && !hasAccumulate && (
        <p className="text-[0.65rem] text-neutral-600 mt-2">
          Esta moneda ({toCurr?.name || toCurr?.code}) se entrega únicamente por transferencia bancaria.
        </p>
      )}
      {toCurr?.type !== "crypto" && deliveryOptions.length > 0 && !hasTransfer && hasCash && (
        <p className="text-[0.65rem] text-neutral-600 mt-2">
          Esta moneda ({toCurr?.name || toCurr?.code}) se entrega únicamente en efectivo.
        </p>
      )}
    </div>
  );
}

function DeliveryDetailsBlock({
  toCurr, deliveryMethod, deliveryDetails, onDeliveryDetailsChange,
  cryptoNetwork, onCryptoNetworkChange,
}) {
  const { t } = useTranslation();
  const validator = getDeliveryValidator(toCurr?.code, deliveryMethod, toCurr?.type);
  const feedback = validator?.validate?.(deliveryDetails, { code: toCurr?.code });
  const isCrypto = deliveryMethod === "crypto" || toCurr?.type === "crypto";
  return (
    <div>
      <Label className="micro-label text-neutral-500">
        {deliveryMethod === "transfer" && t("exchange.helperTransfer")}
        {deliveryMethod === "cash" && t("exchange.helperCash")}
        {deliveryMethod === "crypto" && t("exchange.helperCrypto")}
      </Label>

      {validator?.hint ? (
        <p
          data-testid={`delivery-hint-${toCurr?.code}-${deliveryMethod}`}
          className="mt-2 text-[0.7rem] text-[#8B5CF6]/90 font-mono flex items-center gap-1.5"
        >
          <span className="opacity-70">{validator.icon}</span>
          {validator.hint}
        </p>
      ) : (
        <p className="mt-2 text-[0.7rem] text-neutral-500">{t("exchange.detailsHelperGeneric")}</p>
      )}

      <Textarea
        data-testid="delivery-details-input"
        value={deliveryDetails}
        onChange={(e) => onDeliveryDetailsChange(e.target.value)}
        rows={3}
        placeholder={validator?.example || ""}
        className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 font-mono text-sm"
      />

      {isCrypto && (
        <CryptoNetworkPicker
          cryptoNetwork={cryptoNetwork}
          onCryptoNetworkChange={onCryptoNetworkChange}
          onDeliveryDetailsChange={onDeliveryDetailsChange}
        />
      )}

      {feedback && (
        <p
          data-testid="delivery-validation-feedback"
          className={`mt-1.5 text-[0.7rem] font-mono ${feedback.ok ? "text-[#22C55E]" : "text-[#EF4444]"}`}
        >
          {feedback.feedback}
        </p>
      )}

      <p className="mt-2 text-[0.7rem] text-neutral-500 leading-relaxed">
        {t("exchange.accuracyWarning")}
      </p>
    </div>
  );
}

// iter55.12 — Explicit chain selector for crypto: BEP20/ERC20 addresses
// look identical (0x...) but sending to the wrong chain loses funds.
function CryptoNetworkPicker({ cryptoNetwork, onCryptoNetworkChange, onDeliveryDetailsChange }) {
  const { t } = useTranslation();
  const handleChange = (v) => {
    onCryptoNetworkChange(v);
    // Inject/replace the "Red: X" line inside deliveryDetails
    onDeliveryDetailsChange((current) => {
      const lines = current.split("\n").filter((l) => !/^\s*Red:/i.test(l));
      const stripped = lines.join("\n").trimEnd();
      return stripped ? `${stripped}\nRed: ${v}` : `Red: ${v}`;
    });
  };
  return (
    <div className="mt-3">
      <Label className="micro-label text-neutral-500 flex items-center gap-2">
        <span className="text-[#EF4444]">*</span> Red / cadena
        <span className="text-[0.6rem] text-neutral-600 normal-case tracking-normal">(obligatorio)</span>
      </Label>
      <Select value={cryptoNetwork} onValueChange={handleChange}>
        <SelectTrigger
          data-testid="crypto-network-select"
          className="rounded-none mt-1.5 bg-[#0a0a0a] border-white/10 h-10"
        >
          <SelectValue placeholder={t("exchange.selectDestNetwork")} />
        </SelectTrigger>
        <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
          <SelectItem value="BEP20">
            BEP20 · Binance Smart Chain <span className="text-[0.65rem] text-[#8B5CF6] ml-1">(recomendada)</span>
          </SelectItem>
          <SelectItem value="TRC20">TRC20 · Tron</SelectItem>
          <SelectItem value="ERC20">ERC20 · Ethereum</SelectItem>
          <SelectItem value="POLYGON">POLYGON · Matic</SelectItem>
          <SelectItem value="SOLANA">Solana</SelectItem>
          <SelectItem value="BTC">Bitcoin (nativa)</SelectItem>
        </SelectContent>
      </Select>
      <p className="mt-1.5 text-[0.65rem] text-neutral-500 leading-relaxed">
        Enviar a la red equivocada resulta en pérdida total de los fondos.
        Verifica que tu wallet acepte esta red antes de confirmar.
      </p>
    </div>
  );
}
