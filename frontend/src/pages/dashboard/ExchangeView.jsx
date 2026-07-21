import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { ArrowRight } from "lucide-react";
import VerificationGateBanner from "@/components/VerificationGateBanner";
import { extractDetailMessage } from "@/utils/apiErrors";
import OrderSuccessCard from "./exchange/OrderSuccessCard";
import CurrencyPairSelector from "./exchange/CurrencyPairSelector";
import QuotePreview from "./exchange/QuotePreview";
import PaymentAccountBlock from "./exchange/PaymentAccountBlock";
import SenderAndProof from "./exchange/SenderAndProof";
import DeliverySection from "./exchange/DeliverySection";

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
  // iter55.12 — For crypto delivery we require an explicit chain selection.
  const [cryptoNetwork, setCryptoNetwork] = useState("");
  const [senderName, setSenderName] = useState("");
  const [proofImage, setProofImage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(null);
  const [allowedMethods, setAllowedMethods] = useState([]);
  // iter75 — Whitelist of destinations that have an EXPLICIT rate from
  // `fromCode`. Fetched from `/api/currencies/{fromCode}/receivable`.
  // Strictly directional: inverse rates do NOT enable a destination.
  const [receivable, setReceivable] = useState([]);
  const [receivableLoading, setReceivableLoading] = useState(false);

  const isVip = user?.role === "vip" || user?.role === "admin";
  const isStaff = user?.role === "admin" || user?.role === "employee";

  // Static one-shot load on mount — API/axios are stable module imports
  useEffect(() => {
    axios.get(`${API}/currencies`).then((r) => setCurrencies(r.data.filter((c) => c.is_active)));
    axios.get(`${API}/rates`).then((r) => setRates(r.data));
  }, []);

  // Fetch valid delivery methods for the chosen destination currency (iter43).
  useEffect(() => {
    if (!toCode) { setAllowedMethods([]); return; }
    let cancelled = false;
    axios.get(`${API}/currencies/${encodeURIComponent(toCode)}/delivery-methods`)
      .then((r) => { if (!cancelled) setAllowedMethods(r.data.allowed || []); })
      .catch(() => { if (!cancelled) setAllowedMethods([]); });
    return () => { cancelled = true; };
  }, [toCode]);

  // iter75 — Fetch the whitelist of destinations that have a configured
  // rate FROM the currently-chosen source. Prevents the user from picking
  // a destination for which no rate exists (which would confuse the
  // preview and could route the payment to an unauthorised account).
  useEffect(() => {
    if (!fromCode) { setReceivable([]); return; }
    let cancelled = false;
    setReceivableLoading(true);
    axios.get(`${API}/currencies/${encodeURIComponent(fromCode)}/receivable`)
      .then((r) => { if (!cancelled) setReceivable(r.data.receivable || []); })
      .catch(() => { if (!cancelled) setReceivable([]); })
      .finally(() => { if (!cancelled) setReceivableLoading(false); });
    return () => { cancelled = true; };
  }, [fromCode]);

  // iter75 — Filter currency dropdown for destinations. Uses the receivable
  // whitelist when available, otherwise falls back to the raw list while
  // the request is in flight (avoids flicker of empty dropdown on switch).
  const receivableCurrencies = useMemo(() => {
    if (!fromCode) return currencies;  // no source picked yet → show all
    if (receivableLoading && receivable.length === 0) return currencies;
    const allowed = new Set(receivable);
    return currencies.filter((c) => c.code !== fromCode && allowed.has(c.code));
  }, [currencies, receivable, receivableLoading, fromCode]);

  // If the user changes `fromCode` and the previously-selected `toCode`
  // becomes unreachable, auto-reset to the first available option.
  useEffect(() => {
    if (!fromCode || receivableCurrencies.length === 0) return;
    if (!receivableCurrencies.some((c) => c.code === toCode)) {
      setToCode(receivableCurrencies[0].code);
    }
  }, [fromCode, receivableCurrencies, toCode]);

  const selectedRate = useMemo(
    () => rates.find((r) => r.from_code === fromCode && r.to_code === toCode),
    [rates, fromCode, toCode],
  );

  const fromCurr = currencies.find((c) => c.code === fromCode);
  const toCurr = currencies.find((c) => c.code === toCode);

  const rate = selectedRate ? (isVip ? selectedRate.rate_vip : selectedRate.rate_normal) : 0;
  const commission = 0;
  const amt = parseFloat(amount) || 0;
  const gross = amt * rate;
  // iter55.24 → 55.27 — Cash delivery to any fiat: floor deliverable and
  // CREDIT the residue to the client's on-platform balance.
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
    return !isStaff ? [...base, { value: "accumulate", label: t("exchange.deliveryAccumulate") }] : base;
  }, [toCurr, allowedMethods, isStaff, t]);

  // Auto-correct delivery method when available options change.
  useEffect(() => {
    if (deliveryOptions.length === 0) return;
    if (!deliveryOptions.some((o) => o.value === deliveryMethod)) {
      setDeliveryMethod(deliveryOptions[0].value);
    }
  }, [deliveryOptions, deliveryMethod]);

  const handleDeliveryMethodChange = (v) => {
    setDeliveryMethod(v);
    if (v !== "crypto") setCryptoNetwork("");
  };

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

  const resetForm = () => {
    setSuccess(null);
    setAmount("");
    setProofImage("");
    setSenderName("");
    setDeliveryDetails("");
    setCryptoNetwork("");
  };

  if (success) return <OrderSuccessCard success={success} onNewOrder={resetForm} />;

  const submitDisabled =
    submitting ||
    (deliveryMethod === "crypto" && !cryptoNetwork) ||
    (toCurr?.type === "crypto" && deliveryMethod !== "accumulate" && !cryptoNetwork);

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
          <CurrencyPairSelector
            currencies={currencies}
            receivableCurrencies={receivableCurrencies}
            fromCode={fromCode}
            toCode={toCode}
            amount={amount}
            onFromChange={setFromCode}
            onToChange={setToCode}
            onAmountChange={setAmount}
          />

          {isCashFiatDelivery && (
            <div
              data-testid="cash-fiat-guidance"
              className="border border-[#8B5CF6]/40 bg-[#8B5CF6]/10 p-4 text-xs font-mono text-neutral-200 leading-relaxed"
            >
              <div className="micro-label text-[#8B5CF6] text-[0.65rem] mb-2">
                {t("exchange.cashFiatEyebrow", { code: toCode })}
              </div>
              <p>{t("exchange.cashFiatExplainer", { code: toCode })}</p>
            </div>
          )}

          <QuotePreview
            fromCode={fromCode}
            toCode={toCode}
            rate={rate}
            amount={amt}
            gross={gross}
            finalAmount={finalAmount}
            finalAmountRaw={finalAmountRaw}
            commission={commission}
            residueCredited={residueCredited}
            isCashFiatDelivery={isCashFiatDelivery}
          />

          <PaymentAccountBlock fromCurr={fromCurr} />

          <SenderAndProof
            senderName={senderName}
            onSenderNameChange={setSenderName}
            proofImage={proofImage}
            onProofFile={handleFile}
          />

          <DeliverySection
            toCurr={toCurr}
            deliveryOptions={deliveryOptions}
            deliveryMethod={deliveryMethod}
            onDeliveryMethodChange={handleDeliveryMethodChange}
            deliveryDetails={deliveryDetails}
            onDeliveryDetailsChange={setDeliveryDetails}
            cryptoNetwork={cryptoNetwork}
            onCryptoNetworkChange={setCryptoNetwork}
          />

          <Button
            data-testid="submit-order-btn"
            onClick={submit}
            disabled={submitDisabled}
            className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-14 text-base disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting ? t("exchange.submitting") : (<>{t("exchange.submit")} <ArrowRight className="w-4 h-4 ml-2" /></>)}
          </Button>
        </div>
      </VerificationGateBanner>
    </div>
  );
}
