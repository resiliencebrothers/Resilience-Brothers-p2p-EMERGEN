import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { useTranslation, Trans } from "react-i18next";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { CRYPTO_NETWORKS, validateCryptoAddress, detectAddressFamily } from "@/services/cryptoValidators";
import { CryptoAddressField } from "./AddressTools";
import { getDeliveryValidator } from "@/services/delivery_validators";
import CourierQuotePicker from "@/components/CourierQuotePicker";
import { toast } from "sonner";
import { ArrowDownToLine, ShieldCheck, Lock } from "lucide-react";

// Module-level constants — hoisted out of the render path so they don't
// create fresh object identities on every keystroke.
const TRANS_STRONG_ONE = { 1: <strong /> };
const TRANS_STRONG_ONE_TWO = { 1: <strong />, 2: <strong /> };

/**
 * iter153 — Method-first withdrawal form. The method (crypto / transfer /
 * cash) is now chosen BEFORE this form renders (see MethodPicker), so it
 * arrives as a prop and only the fields for that method are shown. The
 * currency dropdown is filtered to currencies compatible with the method.
 *
 * Props:
 *   - balances: from /vip/balances — currency dropdown + available/frozen.
 *   - method: "crypto" | "transfer" | "cash" (fixed, from MethodPicker).
 *   - onBack: switch back to the method picker.
 *   - onSubmitted: callback fired after a successful POST /vip/withdraw.
 */
export function VipWithdrawalForm({ balances, onSubmitted, method = "transfer", onBack }) {
  const navigate = useNavigate();
  const { t } = useTranslation();

  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("");
  const [details, setDetails] = useState("");
  const [cashReceiverName, setCashReceiverName] = useState("");
  const [cashReceiverPhone, setCashReceiverPhone] = useState("");
  const [cashReceiverAddress, setCashReceiverAddress] = useState("");
  const [cashReceiverId, setCashReceiverId] = useState("");
  // iter192 — cash delivery province (availability controlled by admin).
  const [cashProvince, setCashProvince] = useState("");
  const [provinces, setProvinces] = useState([]);

  useEffect(() => {
    if (method !== "cash" || provinces.length) return;
    axios.get(`${API}/vip/cash-provinces`, { withCredentials: true })
      .then((r) => setProvinces(r.data?.provinces || []))
      .catch(() => setProvinces([]));
  }, [method, provinces.length]); // opcional (Cuba: carné)
  const [totpCode, setTotpCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [cryptoNetwork, setCryptoNetwork] = useState("TRC20");
  const [methodsMap, setMethodsMap] = useState(null);
  // iter198 — courier fee quote for cash withdrawals (per-km pricing +
  // free-above-threshold badge).
  const [courierQuote, setCourierQuote] = useState(null);
  const [deliveryCoords, setDeliveryCoords] = useState(null);
  // iter205 — resultado del cálculo de ruta (obligatorio para enviar) y
  // modalidad: entrega a domicilio (mensajería) o recogida en oficina.
  const [routeQuote, setRouteQuote] = useState(null);
  const [cashDeliveryMode, setCashDeliveryMode] = useState("courier");

  useEffect(() => {
    setRouteQuote(null);
    setDeliveryCoords(null);
  }, [cashReceiverAddress, cashDeliveryMode, currency]);

  // Fetch allowed delivery methods for every balance currency so we can
  // filter the dropdown down to the ones compatible with `method`.
  useEffect(() => {
    const codes = (balances.balances || []).map((b) => b.currency);
    if (codes.length === 0) { setMethodsMap({}); return undefined; }
    let cancelled = false;
    Promise.all(codes.map((c) =>
      axios.get(`${API}/currencies/${encodeURIComponent(c)}/delivery-methods`)
        .then((r) => [c, r.data?.allowed || null])
        .catch(() => [c, null]),
    )).then((entries) => { if (!cancelled) setMethodsMap(Object.fromEntries(entries)); });
    return () => { cancelled = true; };
  }, [balances]);

  const currencyOptions = useMemo(() => {
    const codes = (balances.balances || []).map((b) => b.currency);
    if (!methodsMap) return codes;
    return codes.filter((c) => {
      const allowed = methodsMap[c];
      return !allowed || allowed.length === 0 || allowed.includes(method);
    });
  }, [balances, methodsMap, method]);

  useEffect(() => {
    if (currencyOptions.length === 0) return;
    if (!currencyOptions.includes(currency)) setCurrency(currencyOptions[0]);
  }, [currencyOptions, currency]);

  const selBal = (balances.balances || []).find((b) => b.currency === currency);

  useEffect(() => {
    if (method !== "cash" || !currency) { setCourierQuote(null); return undefined; }
    const amt = parseFloat(amount) || 0;
    let cancelled = false;
    const id = setTimeout(() => {
      axios.get(`${API}/vip/courier-fee-quote`, {
        params: { currency, amount: amt },
        withCredentials: true,
      })
        .then((r) => { if (!cancelled) setCourierQuote(r.data); })
        .catch(() => { if (!cancelled) setCourierQuote(null); });
    }, 350);
    return () => { cancelled = true; clearTimeout(id); };
  }, [method, currency, amount]);

  const cryptoAddressMatch = useMemo(() => {
    if (method !== "crypto") return null;
    if (!details || !details.trim()) return null;
    return validateCryptoAddress(details, cryptoNetwork);
  }, [method, details, cryptoNetwork]);

  const activeNetwork = CRYPTO_NETWORKS.find((n) => n.value === cryptoNetwork) || CRYPTO_NETWORKS[0];

  // iter158 — live bank-account validation for transfer withdrawals
  // (16-digit Cuban card, CLABE, IBAN, Zelle…) with anti-placeholder rules.
  const transferValidator = useMemo(
    () => (method === "transfer" ? getDeliveryValidator(currency, "transfer") : null),
    [method, currency],
  );
  const transferFeedback = useMemo(
    () => (transferValidator?.validate ? transferValidator.validate(details, { code: currency }) : null),
    [transferValidator, details, currency],
  );

  const composedCashDetails = useMemo(() => {
    if (method !== "cash") return "";
    const lines = cashDeliveryMode === "office_pickup"
      ? [
          "Modalidad: Recogida en oficina",
          `Nombre: ${cashReceiverName.trim()}`,
          `Celular: ${cashReceiverPhone.trim()}`,
        ]
      : [
          `Provincia: ${cashProvince}`,
          `Nombre: ${cashReceiverName.trim()}`,
          `Celular: ${cashReceiverPhone.trim()}`,
          `Dirección: ${cashReceiverAddress.trim()}`,
        ];
    if (cashReceiverId.trim()) lines.push(`ID / Carné: ${cashReceiverId.trim()}`);
    return lines.join("\n");
  }, [method, cashDeliveryMode, cashProvince, cashReceiverName, cashReceiverPhone, cashReceiverAddress, cashReceiverId]);

  // iter184 — typing/scanning an address auto-selects the compatible network.
  const handleAddressChange = (val) => {
    setDetails(val);
    const fam = detectAddressFamily(val);
    if (fam === "tron") setCryptoNetwork("TRC20");
    else if (fam === "evm") setCryptoNetwork("BEP20");
  };

  const resetForm = () => {
    setAmount(""); setDetails(""); setTotpCode("");
    setCashReceiverName(""); setCashReceiverPhone("");
    setCashReceiverAddress(""); setCashReceiverId(""); setCashProvince("");
    setDeliveryCoords(null); setRouteQuote(null); setCashDeliveryMode("courier");
  };

  const validate = (amt) => {
    if (!amt || amt <= 0) return t("withdraw.errInvalidAmount");
    if (selBal && amt > Number(selBal.amount || 0)) {
      return t("withdraw.insufficientBalance");
    }
    if (method === "cash") {
      const pickup = cashDeliveryMode === "office_pickup";
      if (!pickup && !cashProvince) {
        return t("withdraw.errProvince");
      }
      if (!cashReceiverName.trim() || cashReceiverName.trim().length < 3) {
        return t("withdraw.errReceiverName");
      }
      if (!cashReceiverPhone.trim() || cashReceiverPhone.trim().length < 6) {
        return t("withdraw.errReceiverPhone");
      }
      if (!pickup && (!cashReceiverAddress.trim() || cashReceiverAddress.trim().length < 5)) {
        return t("withdraw.errReceiverAddress");
      }
      // iter205 — el costo de mensajería DEBE calcularse antes de enviar.
      if (!pickup && courierQuote?.enabled && !courierQuote?.free && !routeQuote) {
        return t("withdraw.errCourierQuoteRequired");
      }
    } else if (!details) {
      return t("withdraw.errDetailsRequired");
    }
    if (method === "crypto") {
      if (!cryptoNetwork) return t("withdraw.errCryptoNetwork");
      if (cryptoAddressMatch !== true) {
        return `${t("withdraw.networkMismatch")} ${activeNetwork.label}. ${t("withdraw.networkMismatchHint")}`;
      }
    }
    if (method === "transfer" && transferValidator && transferFeedback && !transferFeedback.ok) {
      return transferFeedback.feedback.replace(/^⚠\s*/, "");
    }
    if (!totpCode || totpCode.length < 6) {
      return t("withdraw.err2FA");
    }
    return null;
  };

  const submit = async () => {
    const amt = parseFloat(amount);
    const err = validate(amt);
    if (err) return toast.error(err);
    setBusy(true);
    try {
      await axios.post(`${API}/vip/withdraw`, {
        amount_usd: amt,
        currency,
        method,
        details: method === "cash" ? composedCashDetails : details,
        beneficiary_name: method === "cash" ? cashReceiverName.trim() : "",
        ...(method === "cash" ? { province: cashProvince, cash_delivery_mode: cashDeliveryMode } : {}),
        ...(method === "cash" && cashDeliveryMode === "courier" && deliveryCoords
          ? { delivery_latitude: deliveryCoords.lat, delivery_longitude: deliveryCoords.lon }
          : {}),
        ...(method === "cash" && cashDeliveryMode === "courier" && routeQuote?.municipality
          ? { courier_municipality: routeQuote.municipality }
          : {}),
        crypto_network: method === "crypto" ? cryptoNetwork : null,
        totp_code: totpCode.trim(),
      }, { withCredentials: true });
      toast.success(t("withdraw.successToast"));
      resetForm();
      if (onSubmitted) await onSubmitted();
    } catch (e) {
      const detail = e.response?.data?.detail;
      if (e.response?.status === 412 && detail?.code === "TOTP_SETUP_REQUIRED") {
        toast.error(t("withdraw.setupNeededToast"));
        setTimeout(() => navigate("/dashboard/security"), 1500);
        return;
      }
      if (detail?.code === "TOTP_INVALID" || detail?.code === "TOTP_CODE_REQUIRED") {
        toast.error(detail.message || t("withdraw.invalidTotpToast"));
        return;
      }
      toast.error(detail?.message || detail || t("withdraw.genericErr"));
    } finally {
      setBusy(false);
    }
  };

  const noCurrencies = methodsMap !== null && currencyOptions.length === 0;

  const amountBlock = (
    <div>
      <Label className="micro-label text-neutral-500">{t("withdraw.amountLabel")}</Label>
      <Input data-testid="withdraw-amount" type="number" value={amount}
        onChange={e => setAmount(e.target.value)}
        className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12 font-mono" />
      {selBal && (
        <div className="flex items-center justify-between text-xs mt-2">
          <span className="text-neutral-500">
            {t("withdraw.availableLabel")}:{" "}
            <span className="text-white font-mono" data-testid="withdraw-available">
              {Number(selBal.amount || 0).toLocaleString(undefined, { maximumFractionDigits: 4 })} {currency}
            </span>
          </span>
          <button
            type="button"
            data-testid="withdraw-max-btn"
            onClick={() => setAmount(String(selBal.amount || 0))}
            className="text-[#8B5CF6] hover:text-[#A78BFA] font-semibold uppercase tracking-widest text-[0.65rem]"
          >
            {t("withdraw.allBtn")}
          </button>
        </div>
      )}
      {Number(selBal?.frozen) > 0 && (
        <div className="flex items-center gap-1.5 text-[0.65rem] text-amber-400 mt-1" data-testid="withdraw-frozen-hint">
          <Lock className="w-3 h-3" />
          {t("withdraw.frozenLabel")}: {Number(selBal.frozen).toLocaleString(undefined, { maximumFractionDigits: 4 })} {currency}
        </div>
      )}
    </div>
  );

  return (
    <div className="tactile-card p-6">
      <div className="flex items-center justify-between mb-4 gap-2 flex-wrap">
        <h2 className="font-display text-xl flex items-center gap-2">
          <ArrowDownToLine className="w-5 h-5 text-[#8B5CF6]" /> {t("withdraw.submitBtn")}
          <span className="text-[0.6rem] font-mono uppercase tracking-widest text-neutral-400 border border-white/10 px-2 py-1">
            {t(`methodPicker.options.${method}.label`)}
          </span>
        </h2>
        {onBack && (
          <button
            type="button"
            onClick={onBack}
            data-testid="withdraw-change-method"
            className="text-xs text-neutral-500 hover:text-[#8B5CF6] underline underline-offset-4"
          >
            {t("methodPicker.back")}
          </button>
        )}
      </div>

      {noCurrencies ? (
        <p className="text-sm text-neutral-400 py-4" data-testid="withdraw-no-currency">
          {t("withdraw.noCompatibleCurrency")}
        </p>
      ) : (
        <div className="space-y-4">
          <FormField label={t("withdraw.currencyLabel")}>
            <Select value={currency} onValueChange={setCurrency}>
              <SelectTrigger data-testid="withdraw-currency"
                className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                {currencyOptions.map(c => (
                  <SelectItem key={c} value={c}>{c}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>

          {method === "crypto" ? (
            <>
              <CryptoAddressField
                currency={currency}
                details={details}
                onChange={handleAddressChange}
                activeNetwork={activeNetwork}
                cryptoAddressMatch={cryptoAddressMatch}
                cryptoNetwork={cryptoNetwork}
                onPickSaved={(a) => { setDetails(a.address); setCryptoNetwork(a.network); }}
              />

              <div data-testid="crypto-network-block">
                <Label className="micro-label text-neutral-500">
                  {t("withdraw.networkLabel")} <span className="text-[#8B5CF6]">*</span>
                </Label>
                <Select value={cryptoNetwork} onValueChange={setCryptoNetwork}>
                  <SelectTrigger data-testid="withdraw-crypto-network"
                    className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12">
                    <SelectValue placeholder={t("withdraw.selectNetwork")} />
                  </SelectTrigger>
                  <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                    {CRYPTO_NETWORKS.map((n) => (
                      <SelectItem key={n.value} value={n.value}>{n.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-[0.65rem] text-neutral-500 mt-1">
                  {cryptoAddressMatch === true
                    ? t("withdraw.networkAutoDetected")
                    : t("withdraw.chooseCorrectNetwork")}
                </p>
              </div>

              {amountBlock}
            </>
          ) : (
            <>
              {amountBlock}

              {method === "cash" && (
                <p className="text-[0.65rem] text-[#8B5CF6]">
                  {t("withdraw.cashProgressNote")}
                </p>
              )}

              {method === "cash" && (
                <div data-testid="cash-delivery-mode">
                  <Label className="micro-label text-neutral-500">{t("withdraw.deliveryModeLabel")}</Label>
                  <div className="grid grid-cols-2 gap-2 mt-2">
                    <button
                      type="button"
                      data-testid="cash-mode-courier"
                      onClick={() => setCashDeliveryMode("courier")}
                      className={`px-3 py-2.5 border text-xs font-medium transition-colors text-left ${
                        cashDeliveryMode === "courier"
                          ? "border-[#8B5CF6] bg-[#8B5CF6]/10 text-[#A78BFA]"
                          : "border-white/10 text-neutral-400 hover:border-white/30"
                      }`}
                    >
                      {t("withdraw.modeCourier")}
                    </button>
                    <button
                      type="button"
                      data-testid="cash-mode-pickup"
                      onClick={() => setCashDeliveryMode("office_pickup")}
                      className={`px-3 py-2.5 border text-xs font-medium transition-colors text-left ${
                        cashDeliveryMode === "office_pickup"
                          ? "border-[#22C55E] bg-[#22C55E]/10 text-[#22C55E]"
                          : "border-white/10 text-neutral-400 hover:border-white/30"
                      }`}
                    >
                      {t("withdraw.modePickup")}
                    </button>
                  </div>
                  {cashDeliveryMode === "office_pickup" && (
                    <p className="text-[0.65rem] text-[#22C55E]/90 mt-1.5" data-testid="cash-pickup-hint">
                      {t("withdraw.modePickupHint")}
                    </p>
                  )}
                </div>
              )}

              {method === "cash" && cashDeliveryMode === "courier" && courierQuote?.enabled && (
                courierQuote.free ? (
                  <p
                    className="text-[0.7rem] text-[#22C55E] border border-[#22C55E]/30 bg-[#22C55E]/5 px-3 py-2 leading-relaxed"
                    data-testid="withdraw-courier-free"
                  >
                    {t("withdraw.courierFreeBadge", { min: courierQuote.free_min_usdt })}
                  </p>
                ) : (
                  <p
                    className="text-[0.7rem] text-neutral-400 border border-white/10 bg-white/[0.02] px-3 py-2 leading-relaxed"
                    data-testid="withdraw-courier-fee-note"
                  >
                    {t("withdraw.courierFeeNote", {
                      rate: courierQuote.rate_usdt_per_km,
                      minFee: courierQuote.min_fee_usdt,
                      min: courierQuote.free_min_usdt,
                    })}
                  </p>
                )
              )}

              {method === "cash" ? (
                <>
                  {cashDeliveryMode === "courier" && (
                  <div data-testid="cash-province-block">
                    <Label className="micro-label text-neutral-500">
                      {t("withdraw.cashProvinceLabel")} <span className="text-[#8B5CF6]">*</span>
                    </Label>
                    <Select value={cashProvince} onValueChange={setCashProvince}>
                      <SelectTrigger data-testid="withdraw-cash-province"
                        className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12">
                        <SelectValue placeholder={t("withdraw.cashProvincePh")} />
                      </SelectTrigger>
                      <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-72">
                        {provinces.map((p) => (
                          <SelectItem key={p.name} value={p.name} disabled={!p.available}>
                            {p.name}{!p.available ? ` — ${t("withdraw.provinceUnavailable")}` : ""}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <p className="text-[0.65rem] text-neutral-600 mt-1">
                      {t("withdraw.cashProvinceHint")}
                    </p>
                  </div>
                  )}
                  <CashReceiverFields
                    name={cashReceiverName} setName={setCashReceiverName}
                    phone={cashReceiverPhone} setPhone={setCashReceiverPhone}
                    address={cashReceiverAddress} setAddress={setCashReceiverAddress}
                    id={cashReceiverId} setId={setCashReceiverId}
                    showAddress={cashDeliveryMode === "courier"}
                  />
                  {cashDeliveryMode === "courier" && courierQuote?.enabled && !courierQuote?.free && (
                    <>
                      <CourierQuotePicker
                        currency={currency}
                        amount={parseFloat(amount) || 0}
                        addressText={cashReceiverAddress}
                        province={cashProvince}
                        onCoords={setDeliveryCoords}
                        onQuote={setRouteQuote}
                      />
                      {!routeQuote && (
                        <p className="text-[0.65rem] text-amber-400" data-testid="courier-quote-required-hint">
                          {t("withdraw.courierQuoteRequiredHint")}
                        </p>
                      )}
                    </>
                  )}
                </>
              ) : (
                <NonCashDetailsField
                  method={method} details={details} setDetails={setDetails}
                  activeNetwork={activeNetwork}
                  cryptoAddressMatch={cryptoAddressMatch}
                  transferValidator={transferValidator}
                  transferFeedback={transferFeedback}
                />
              )}
            </>
          )}

          <TotpField totpCode={totpCode} setTotpCode={setTotpCode} />

          <Button data-testid="submit-withdraw-btn" onClick={submit} disabled={busy}
            className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-12">
            {busy ? t("withdraw.submittingBtn") : t("withdraw.submitBtn")}
          </Button>
        </div>
      )}
    </div>
  );
}


function FormField({ label, children }) {
  return (
    <div>
      <Label className="micro-label text-neutral-500">{label}</Label>
      {children}
    </div>
  );
}


function CashReceiverFields({ name, setName, phone, setPhone, address, setAddress, id, setId, showAddress = true }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-3" data-testid="cash-receiver-block">
      <div>
        <Label className="micro-label text-neutral-500">
          {t("withdraw.cashReceiverNameLabel")} <span className="text-[#8B5CF6]">*</span>
        </Label>
        <Input
          data-testid="cash-receiver-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t("withdraw.cashReceiverNamePh")}
          className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12"
          required
        />
      </div>
      <div>
        <Label className="micro-label text-neutral-500">
          {t("withdraw.cashReceiverPhoneLabel")} <span className="text-[#8B5CF6]">*</span>
        </Label>
        <Input
          data-testid="cash-receiver-phone"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          placeholder={t("withdraw.cashReceiverPhonePh")}
          inputMode="tel"
          className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12 font-mono"
          required
        />
      </div>
      {showAddress && (
      <div>
        <Label className="micro-label text-neutral-500">
          {t("withdraw.cashReceiverAddressLabel")} <span className="text-[#8B5CF6]">*</span>
        </Label>
        <Textarea
          data-testid="cash-receiver-address"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          rows={2}
          placeholder={t("withdraw.cashReceiverAddressPh")}
          className="rounded-none mt-2 bg-[#0a0a0a] border-white/10"
          required
        />
      </div>
      )}
      <div>
        <Label className="micro-label text-neutral-500">
          {t("withdraw.cashReceiverIdLabel")}{" "}
          <span className="text-neutral-600 normal-case">{t("withdraw.cashReceiverIdOptional")}</span>
        </Label>
        <Input
          data-testid="cash-receiver-id"
          value={id}
          onChange={(e) => setId(e.target.value)}
          placeholder={t("withdraw.cashReceiverIdPh")}
          inputMode="numeric"
          className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12 font-mono"
        />
      </div>
      <p
        className="text-[0.7rem] text-[#8B5CF6] mt-1 leading-relaxed"
        data-testid="withdraw-cash-hint"
      >
        <Trans i18nKey="withdraw.cashHint" components={TRANS_STRONG_ONE_TWO} />
      </p>
    </div>
  );
}


function NonCashDetailsField({ method, details, setDetails, activeNetwork, cryptoAddressMatch, transferValidator, transferFeedback }) {
  const { t } = useTranslation();
  const cryptoTransValues = useMemo(
    () => ({ network: activeNetwork.label }),
    [activeNetwork.label]
  );
  return (
    <div>
      <Label className="micro-label text-neutral-500">
        {t("withdraw.detailsLabel")} {method === "crypto" && <span className="text-[#8B5CF6]">*</span>}
      </Label>
      {method === "transfer" && transferValidator?.hint && (
        <p className="text-[0.7rem] text-[#8B5CF6] mt-1 leading-relaxed" data-testid="transfer-details-hint">
          {transferValidator.icon ? `${transferValidator.icon} ` : ""}{transferValidator.hint}
        </p>
      )}
      <Textarea
        data-testid="withdraw-details"
        value={details}
        onChange={e => setDetails(e.target.value)}
        rows={method === "crypto" ? 2 : 3}
        placeholder={
          method === "crypto"
            ? activeNetwork.addressPlaceholder
            : t("withdraw.detailsPhTransfer")
        }
        className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 font-mono"
      />
      {method === "transfer" && transferFeedback && (
        <p
          data-testid="transfer-details-feedback"
          className={`text-[0.75rem] mt-1 leading-relaxed ${transferFeedback.ok ? "text-[#22C55E]" : "text-[#EF4444]"}`}
        >
          {transferFeedback.feedback}
        </p>
      )}
      {method === "crypto" && cryptoAddressMatch === true && (
        <p
          data-testid="crypto-address-match-ok"
          className="text-[0.75rem] text-[#22C55E] mt-1 leading-relaxed flex items-center gap-1.5"
        >
          <span aria-hidden>✓</span>
          <span>
            <Trans
              i18nKey="withdraw.cryptoMatchOk"
              values={cryptoTransValues}
              components={TRANS_STRONG_ONE}
            />
          </span>
        </p>
      )}
      {method === "crypto" && cryptoAddressMatch === false && (
        <p
          data-testid="crypto-address-mismatch"
          className="text-[0.75rem] text-[#EF4444] mt-1 leading-relaxed flex items-start gap-1.5"
        >
          <span aria-hidden className="mt-0.5">⚠</span>
          <span>
            <Trans
              i18nKey="withdraw.cryptoMismatch"
              values={cryptoTransValues}
              components={TRANS_STRONG_ONE}
            />
          </span>
        </p>
      )}
    </div>
  );
}


function TotpField({ totpCode, setTotpCode }) {
  const { t } = useTranslation();
  return (
    <div className="border border-[#8B5CF6]/40 bg-[#8B5CF6]/5 p-3">
      <Label className="micro-label text-[#8B5CF6] flex items-center gap-1.5">
        <ShieldCheck className="w-3.5 h-3.5" /> {t("withdraw.totpLabel")} <span className="text-[#8B5CF6]">*</span>
      </Label>
      <Input
        data-testid="withdraw-totp"
        value={totpCode}
        onChange={(e) => setTotpCode(e.target.value)}
        placeholder={t("withdraw.totpPh")}
        maxLength={11}
        inputMode="text"
        className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12 font-mono text-center text-lg tracking-wider"
        required
      />
      <p className="text-[0.65rem] text-neutral-500 mt-1">
        {t("withdraw.totpHelper")}{" "}
        <a href="/dashboard/security" className="text-[#8B5CF6] hover:underline">{t("withdraw.totpSetupLink")}</a>
      </p>
    </div>
  );
}
