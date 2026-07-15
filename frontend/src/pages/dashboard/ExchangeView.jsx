import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { useTranslation } from "react-i18next";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { getDeliveryValidator } from "@/services/delivery_validators";
import { ArrowRight, Upload, Copy, CheckCircle2 } from "lucide-react";
import VerificationGateBanner from "@/components/VerificationGateBanner";
import { extractDetailMessage } from "@/utils/apiErrors";

export default function ExchangeView() {
  const { user } = useAuth();
  const { t } = useTranslation();
  const [currencies, setCurrencies] = useState([]);
  const [rates, setRates] = useState([]);
  const [fromCode, setFromCode] = useState("");
  const [toCode, setToCode] = useState("");
  const [amount, setAmount] = useState("");
  const [deliveryMethod, setDeliveryMethod] = useState("transfer");
  const [deliveryDetails, setDeliveryDetails] = useState("");
  // iter55.12 — For crypto delivery we require an explicit chain selection
  // because BEP20/ERC20/POLYGON share the same 0x address format and sending
  // to the wrong chain loses funds. The value is auto-injected into
  // `deliveryDetails` as a "Red: XXX" line.
  const [cryptoNetwork, setCryptoNetwork] = useState("");
  const [senderName, setSenderName] = useState("");
  const [proofImage, setProofImage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(null);
  const [copied, setCopied] = useState(false);
  const [allowedMethods, setAllowedMethods] = useState([]);

  const isVip = user?.role === "vip" || user?.role === "admin";
  const isStaff = user?.role === "admin" || user?.role === "employee";

  // Static one-shot load on mount — API/axios are stable module imports
  useEffect(() => {
    axios.get(`${API}/currencies`).then(r => setCurrencies(r.data.filter(c => c.is_active)));
    axios.get(`${API}/rates`).then(r => setRates(r.data));
  }, []);

  // Fetch valid delivery methods for the chosen destination currency from the
  // backend source-of-truth (iter43). Replaces the previous JS-side heuristic
  // that had to be kept in sync with services/delivery_rules.py by hand.
  useEffect(() => {
    if (!toCode) { setAllowedMethods([]); return; }
    let cancelled = false;
    axios.get(`${API}/currencies/${encodeURIComponent(toCode)}/delivery-methods`)
      .then(r => { if (!cancelled) setAllowedMethods(r.data.allowed || []); })
      .catch(() => { if (!cancelled) setAllowedMethods([]); });
    return () => { cancelled = true; };
  }, [toCode]);

  const selectedRate = useMemo(() => {
    return rates.find(r => r.from_code === fromCode && r.to_code === toCode);
  }, [rates, fromCode, toCode]);

  const fromCurr = currencies.find(c => c.code === fromCode);
  const toCurr = currencies.find(c => c.code === toCode);

  let rate = 0;
  if (selectedRate) {
    rate = isVip ? selectedRate.rate_vip : selectedRate.rate_normal;
  }
  const commission = 0;
  const amt = parseFloat(amount) || 0;
  const gross = amt * rate;
  // iter55.24 → 55.27 — Cash delivery to any fiat has no sub-unit
  // denominations available (Cuba ops doesn't stock coins). We floor the
  // deliverable and CREDIT the residue to the client's on-platform balance
  // in the same currency — nothing is lost. The client can accumulate
  // residues across trades or convert them to any allowed currency via
  // /vip/convert (flat 0.01 USDT service fee, 1 USDT minimum, iter55.36i).
  const isCashFiatDelivery = deliveryMethod === "cash" && (toCurr?.type || "").toLowerCase() === "fiat";
  const finalAmountRaw = gross * (1 - commission / 100);
  const finalAmount = isCashFiatDelivery ? Math.floor(finalAmountRaw) : finalAmountRaw;
  const residueCredited = isCashFiatDelivery ? finalAmountRaw - finalAmount : 0;

  const deliveryOptions = useMemo(() => {
    if (!toCurr) return [];
    const LABELS = {
      transfer: { value: "transfer", label: t("exchange.deliveryTransfer") },
      cash: { value: "cash", label: t("exchange.deliveryCash") },
      crypto: { value: "crypto", label: t("exchange.deliveryCrypto") },
    };
    const base = allowedMethods.filter((m) => LABELS[m]).map((m) => LABELS[m]);
    // VIP/normal users (non-staff) can also accumulate balance.
    return !isStaff ? [...base, { value: "accumulate", label: t("exchange.deliveryAccumulate") }] : base;
  }, [toCurr, allowedMethods, isStaff, t]);

  // Auto-correct delivery method when the available options change (e.g. user
  // switches destination from CUP to USDT — 'cash'/'transfer' no longer apply).
  useEffect(() => {
    if (deliveryOptions.length === 0) return;
    if (!deliveryOptions.some((o) => o.value === deliveryMethod)) {
      setDeliveryMethod(deliveryOptions[0].value);
    }
  }, [deliveryOptions, deliveryMethod]);

  const handleFile = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (file.size > 3 * 1024 * 1024) {
      toast.error(t("exchange.imageTooLarge"));
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setProofImage(reader.result);
    reader.readAsDataURL(file);
  };

  const copyAccount = () => {
    if (fromCurr?.payment_account) {
      navigator.clipboard.writeText(fromCurr.payment_account);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const submit = async () => {
    if (!fromCode || !toCode || !amt || !proofImage || !senderName) {
      toast.error(t("exchange.completeRequired"));
      return;
    }
    if (deliveryMethod !== "accumulate" && !deliveryDetails) {
      toast.error(t("exchange.deliveryDetailsRequired"));
      return;
    }
    setSubmitting(true);
    try {
      const res = await axios.post(`${API}/orders`, {
        from_code: fromCode,
        to_code: toCode,
        amount_from: amt,
        delivery_method: deliveryMethod,
        delivery_details: deliveryDetails,
        sender_name: senderName,
        proof_image: proofImage,
      }, { withCredentials: true });
      setSuccess(res.data);
      toast.success(t("exchange.successPending"));
    } catch (err) {
      toast.error(extractDetailMessage(err, "Error al crear orden"));
    } finally {
      setSubmitting(false);
    }
  };

  if (success) {
    return (
      <div className="max-w-2xl mx-auto tactile-card p-8 text-center" data-testid="order-success">
        <CheckCircle2 className="w-16 h-16 text-[#22C55E] mx-auto mb-4" />
        <h2 className="font-display text-2xl mb-2">{t("exchange.orderReceived")}</h2>
        <p className="text-neutral-400 mb-6">{t("exchange.orderInReview", { id: success.id.slice(0,8) })}</p>
        <div className="text-left space-y-2 border border-white/10 p-4 mb-6 font-mono text-sm">
          <div className="flex justify-between"><span className="text-neutral-500">{t("exchange.sendsLabel")}</span> <span>{success.amount_from} {success.from_code}</span></div>
          <div className="flex justify-between"><span className="text-neutral-500">{t("exchange.receivesLabel")}</span> <span className="text-[#8B5CF6]">{success.amount_to} {success.to_code}</span></div>
          <div className="flex justify-between"><span className="text-neutral-500">{t("exchange.rateLabel")}</span> <span>{success.rate_applied}</span></div>
          {success.commission_percent > 0 && (
            <div className="flex justify-between"><span className="text-neutral-500">{t("exchange.commissionLabel")}</span> <span>{success.commission_percent}%</span></div>
          )}
        </div>
        <Button data-testid="new-order-btn" onClick={() => { setSuccess(null); setAmount(""); setProofImage(""); setSenderName(""); setDeliveryDetails(""); setCryptoNetwork(""); }} className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none">
          {t("exchange.newOrderBtn")}
        </Button>
      </div>
    );
  }

  return (
    <div className="max-w-4xl space-y-6" data-testid="exchange-view">
      <div>
        <div className="micro-label text-[#8B5CF6] mb-2">{t("exchange.eyebrow")}</div>
        <h1 className="font-display text-3xl">{t("exchange.title")}</h1>
        <p className="text-neutral-400 mt-2">
          {isVip ? t("exchange.subtitleVip") : t("exchange.subtitleStandard")}
        </p>
      </div>

      <VerificationGateBanner blocking action="createOrders">
      <div className="tactile-card p-6 lg:p-8 space-y-6">
        <div className="grid md:grid-cols-2 gap-4">
          <div>
            <Label className="micro-label text-neutral-500">{t("exchange.from")}</Label>
            <Select value={fromCode} onValueChange={setFromCode}>
              <SelectTrigger data-testid="from-currency-select" className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12">
                <SelectValue placeholder={t("exchange.selectCurrency")} />
              </SelectTrigger>
              <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                {currencies.map(c => (
                  <SelectItem key={c.id} value={c.code} className="rounded-none">{c.code} — {c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="micro-label text-neutral-500">{t("exchange.to")}</Label>
            <Select value={toCode} onValueChange={setToCode}>
              <SelectTrigger data-testid="to-currency-select" className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12">
                <SelectValue placeholder={t("exchange.selectCurrency")} />
              </SelectTrigger>
              <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                {currencies.map(c => (
                  <SelectItem key={c.id} value={c.code} className="rounded-none">{c.code} — {c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div>
          <Label className="micro-label text-neutral-500">{t("exchange.amount")}</Label>
          <Input
            data-testid="amount-input"
            type="number"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="0.00"
            className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12 text-lg font-mono"
          />
        </div>

        {/* iter55.24 → 55.27 — orient the client on cash-fiat delivery BEFORE
            they calculate/submit. The residue is credited to their balance,
            not lost — copy updated to reflect the new "no funds lost" policy. */}
        {isCashFiatDelivery && (
          <div
            data-testid="cash-fiat-guidance"
            className="border border-[#8B5CF6]/40 bg-[#8B5CF6]/10 p-4 text-xs font-mono text-neutral-200 leading-relaxed"
          >
            <div className="micro-label text-[#8B5CF6] text-[0.65rem] mb-2">
              {t("exchange.cashFiatEyebrow", { code: toCode })}
            </div>
            <p>
              {t("exchange.cashFiatExplainer", { code: toCode })}
            </p>
          </div>
        )}

        {selectedRate && amt > 0 && (
          <div className="border border-[#8B5CF6]/30 bg-[#8B5CF6]/5 p-5 space-y-2 font-mono text-sm">
            <div className="flex justify-between"><span className="text-neutral-400">{t("exchange.rateApplied")}</span><span>{rate} {toCode}/{fromCode}</span></div>
            <div className="flex justify-between"><span className="text-neutral-400">{t("exchange.gross")}</span><span>{gross.toFixed(4)} {toCode}</span></div>
            {commission > 0 && (
              <div className="flex justify-between"><span className="text-neutral-400">{t("exchange.commission", { pct: commission })}</span><span className="text-[#EF4444]">-{(gross - finalAmountRaw).toFixed(4)}</span></div>
            )}
            {isCashFiatDelivery && residueCredited > 0 && (
              <div
                className="flex justify-between text-[#8B5CF6]"
                data-testid="cash-fiat-residue-credit"
              >
                <span>{t("exchange.residueCredit")}</span>
                <span>+{residueCredited.toFixed(4)} {toCode}</span>
              </div>
            )}
            <div className="border-t border-white/10 pt-2 mt-2 flex justify-between text-base">
              <span className="text-white">{isCashFiatDelivery ? t("exchange.receiveInCash") : t("exchange.receiveIn", { code: toCode })}</span>
              <span
                className="text-[#8B5CF6] font-bold"
                data-testid="final-amount-display"
              >
                {isCashFiatDelivery ? finalAmount.toFixed(0) : finalAmount.toFixed(4)} {toCode}
              </span>
            </div>
          </div>
        )}

        {fromCurr?.payment_account && (
          <div className="border border-white/10 p-4">
            <div className="micro-label text-neutral-500 mb-2">Cuenta destino — envía tu pago aquí:</div>
            <div className="flex items-center justify-between gap-3">
              <code className="text-sm break-all">{fromCurr.payment_account}</code>
              <button onClick={copyAccount} data-testid="copy-account-btn" className="text-[#8B5CF6] hover:text-[#A78BFA] shrink-0">
                {copied ? <CheckCircle2 className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
              </button>
            </div>
          </div>
        )}

        <div>
          <Label className="micro-label text-neutral-500">
            {t("exchange.senderNameLabel")} <span className="text-[#8B5CF6]">*</span>
          </Label>
          <Input
            data-testid="sender-name-input"
            value={senderName}
            onChange={(e) => setSenderName(e.target.value)}
            placeholder={t("exchange.senderNamePlaceholder")}
            className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12"
            required
          />
          <p className="text-[0.65rem] text-neutral-600 mt-1">
            {t("exchange.senderNameHint")}
          </p>
        </div>

        <div>
          <Label className="micro-label text-neutral-500">{t("exchange.proofLabel")}</Label>
          <label className="block mt-2 border-2 border-dashed border-white/15 hover:border-[#8B5CF6] p-6 cursor-pointer transition-colors">
            <input type="file" accept="image/*" onChange={handleFile} className="hidden" data-testid="proof-upload" />
            {proofImage ? (
              <img src={proofImage} alt="proof" className="max-h-40 mx-auto" />
            ) : (
              <div className="text-center">
                <Upload className="w-8 h-8 text-neutral-500 mx-auto mb-2" />
                <p className="text-sm text-neutral-400">{t("exchange.uploadCta")}</p>
                <p className="text-xs text-neutral-600 mt-1">{t("exchange.uploadHint2")}</p>
              </div>
            )}
          </label>
        </div>

        <div>
          <Label className="micro-label text-neutral-500">{t("exchange.selectMethodLabel")}</Label>
          <Select
            value={deliveryMethod}
            onValueChange={(v) => {
              setDeliveryMethod(v);
              // Reset the crypto network hint when leaving a crypto method so
              // the mandatory-selection guard doesn't stay stale.
              if (v !== "crypto") setCryptoNetwork("");
            }}
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
          {toCurr?.type !== "crypto" && deliveryOptions.length > 0 &&
           !deliveryOptions.some((o) => o.value === "cash") &&
           !deliveryOptions.some((o) => o.value === "accumulate") && (
            <p className="text-[0.65rem] text-neutral-600 mt-2">
              Esta moneda ({toCurr?.name || toCurr?.code}) se entrega únicamente por transferencia bancaria.
            </p>
          )}
          {toCurr?.type !== "crypto" && deliveryOptions.length > 0 &&
           !deliveryOptions.some((o) => o.value === "transfer") &&
           deliveryOptions.some((o) => o.value === "cash") && (
            <p className="text-[0.65rem] text-neutral-600 mt-2">
              Esta moneda ({toCurr?.name || toCurr?.code}) se entrega únicamente en efectivo.
            </p>
          )}
        </div>

        {deliveryMethod !== "accumulate" && (() => {
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

              {/* Structured hint from central validator */}
              {validator?.hint ? (
                <p
                  data-testid={`delivery-hint-${toCurr?.code}-${deliveryMethod}`}
                  className="mt-2 text-[0.7rem] text-[#8B5CF6]/90 font-mono flex items-center gap-1.5"
                >
                  <span className="opacity-70">{validator.icon}</span>
                  {validator.hint}
                </p>
              ) : (
                <p className="mt-2 text-[0.7rem] text-neutral-500">
                  {t("exchange.detailsHelperGeneric")}
                </p>
              )}

              <Textarea
                data-testid="delivery-details-input"
                value={deliveryDetails}
                onChange={(e) => setDeliveryDetails(e.target.value)}
                rows={3}
                placeholder={validator?.example || ""}
                className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 font-mono text-sm"
              />

              {/* iter55.12 — explicit chain selector for crypto: BEP20/ERC20
                  addresses look identical (0x...) but sending to the wrong
                  chain loses funds. Forcing a selection removes ambiguity. */}
              {isCrypto && (
                <div className="mt-3">
                  <Label className="micro-label text-neutral-500 flex items-center gap-2">
                    <span className="text-[#EF4444]">*</span> Red / cadena
                    <span className="text-[0.6rem] text-neutral-600 normal-case tracking-normal">
                      (obligatorio)
                    </span>
                  </Label>
                  <Select
                    value={cryptoNetwork}
                    onValueChange={(v) => {
                      setCryptoNetwork(v);
                      // Inject/replace the "Red: X" line inside deliveryDetails
                      setDeliveryDetails((current) => {
                        const lines = current.split("\n").filter((l) => !/^\s*Red:/i.test(l));
                        const stripped = lines.join("\n").trimEnd();
                        return stripped ? `${stripped}\nRed: ${v}` : `Red: ${v}`;
                      });
                    }}
                  >
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
              )}

              {feedback && (
                <p
                  data-testid="delivery-validation-feedback"
                  className={`mt-1.5 text-[0.7rem] font-mono ${
                    feedback.ok ? "text-[#22C55E]" : "text-[#EF4444]"
                  }`}
                >
                  {feedback.feedback}
                </p>
              )}

              <p className="mt-2 text-[0.7rem] text-neutral-500 leading-relaxed">
                {t("exchange.accuracyWarning")}
              </p>
            </div>
          );
        })()}

        <Button
          data-testid="submit-order-btn"
          onClick={submit}
          disabled={
            submitting ||
            (deliveryMethod === "crypto" && !cryptoNetwork) ||
            (toCurr?.type === "crypto" && deliveryMethod !== "accumulate" && !cryptoNetwork)
          }
          className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-14 text-base disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? t("exchange.submitting") : (<>{t("exchange.submit")} <ArrowRight className="w-4 h-4 ml-2" /></>)}
        </Button>
      </div>
      </VerificationGateBanner>
    </div>
  );
}
