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
import { CRYPTO_NETWORKS, validateCryptoAddress } from "@/services/cryptoValidators";
import { toast } from "sonner";
import { ArrowDownToLine, ShieldCheck } from "lucide-react";

/**
 * iter55.29 — Extracted from VipView.jsx. Owns the withdrawal request form
 * (currency + method + method-specific fields + 2FA + submit). Kept all
 * existing testids and validation copy verbatim so E2E tests continue to
 * pass unchanged.
 *
 * Props:
 *   - balances: from /vip/balances — used to populate the currency dropdown.
 *   - onSubmitted: callback fired after a successful POST /vip/withdraw so
 *                  the parent can reload withdrawals + balances.
 */
export function VipWithdrawalForm({ balances, onSubmitted }) {
  const navigate = useNavigate();
  const { t } = useTranslation();

  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [method, setMethod] = useState("transfer");
  const [details, setDetails] = useState("");
  const [cashReceiverName, setCashReceiverName] = useState("");
  const [cashReceiverPhone, setCashReceiverPhone] = useState("");
  const [cashReceiverAddress, setCashReceiverAddress] = useState("");
  const [cashReceiverId, setCashReceiverId] = useState(""); // opcional (Cuba: carné)
  const [beneficiaryName, setBeneficiaryName] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [allowedMethods, setAllowedMethods] = useState([]);
  const [cryptoNetwork, setCryptoNetwork] = useState("TRC20");

  // Fetch allowed delivery methods per currency (iter43 backend source of truth)
  useEffect(() => {
    if (!currency) { setAllowedMethods([]); return; }
    let cancelled = false;
    axios.get(`${API}/currencies/${encodeURIComponent(currency)}/delivery-methods`)
      .then(r => { if (!cancelled) setAllowedMethods(r.data?.allowed || []); })
      .catch(() => { if (!cancelled) setAllowedMethods([]); });
    return () => { cancelled = true; };
  }, [currency]);

  const withdrawalMethodOptions = useMemo(() => {
    const LABELS = {
      transfer: { value: "transfer", label: t("withdraw.methodTransfer2") },
      cash: { value: "cash", label: t("withdraw.methodCashUsdCup") },
      crypto: { value: "crypto", label: t("withdraw.methodCryptoWallet") },
    };
    if (!allowedMethods || allowedMethods.length === 0) {
      return [LABELS.transfer, LABELS.cash, LABELS.crypto];
    }
    return allowedMethods.filter((m) => LABELS[m]).map((m) => LABELS[m]);
  }, [allowedMethods, t]);

  useEffect(() => {
    if (withdrawalMethodOptions.length === 0) return;
    if (!withdrawalMethodOptions.some((o) => o.value === method)) {
      setMethod(withdrawalMethodOptions[0].value);
    }
  }, [withdrawalMethodOptions, method]);

  const cryptoAddressMatch = useMemo(() => {
    if (method !== "crypto") return null;
    if (!details || !details.trim()) return null;
    return validateCryptoAddress(details, cryptoNetwork);
  }, [method, details, cryptoNetwork]);

  const activeNetwork = CRYPTO_NETWORKS.find((n) => n.value === cryptoNetwork) || CRYPTO_NETWORKS[0];

  const composedCashDetails = useMemo(() => {
    if (method !== "cash") return "";
    const lines = [
      `Nombre: ${cashReceiverName.trim()}`,
      `Celular: ${cashReceiverPhone.trim()}`,
      `Dirección: ${cashReceiverAddress.trim()}`,
    ];
    if (cashReceiverId.trim()) lines.push(`ID / Carné: ${cashReceiverId.trim()}`);
    return lines.join("\n");
  }, [method, cashReceiverName, cashReceiverPhone, cashReceiverAddress, cashReceiverId]);

  const resetForm = () => {
    setAmount(""); setDetails(""); setBeneficiaryName(""); setTotpCode("");
    setCashReceiverName(""); setCashReceiverPhone("");
    setCashReceiverAddress(""); setCashReceiverId("");
  };

  const validate = (amt) => {
    if (!amt || amt <= 0) return t("withdraw.errInvalidAmount");
    if (method === "cash") {
      if (!cashReceiverName.trim() || cashReceiverName.trim().length < 3) {
        return t("withdraw.errReceiverName");
      }
      if (!cashReceiverPhone.trim() || cashReceiverPhone.trim().length < 6) {
        return t("withdraw.errReceiverPhone");
      }
      if (!cashReceiverAddress.trim() || cashReceiverAddress.trim().length < 5) {
        return t("withdraw.errReceiverAddress");
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
    if (!beneficiaryName || beneficiaryName.trim().length < 2) {
      return t("withdraw.errBeneficiaryName");
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
        beneficiary_name: beneficiaryName.trim(),
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

  const currencyOptions = balances.balances.length > 0
    ? balances.balances.map(b => b.currency)
    : ["USD"];

  return (
    <div className="tactile-card p-6">
      <h2 className="font-display text-xl mb-4 flex items-center gap-2">
        <ArrowDownToLine className="w-5 h-5 text-[#8B5CF6]" /> {t("withdraw.submitBtn")}
      </h2>
      <div className="space-y-4">
        <FormField label={t("withdraw.amountLabel")}>
          <Input data-testid="withdraw-amount" type="number" value={amount}
            onChange={e => setAmount(e.target.value)}
            className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12 font-mono" />
        </FormField>

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

        <div>
          <Label className="micro-label text-neutral-500">{t("withdraw.methodLabel")}</Label>
          <Select value={method} onValueChange={setMethod}>
            <SelectTrigger data-testid="withdraw-method"
              className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
              {withdrawalMethodOptions.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          {method === "cash" && (
            <p className="text-[0.65rem] text-[#8B5CF6] mt-1">
              {t("withdraw.cashProgressNote")}
            </p>
          )}
        </div>

        {method === "crypto" && (
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
              {t("withdraw.chooseCorrectNetwork")}
            </p>
          </div>
        )}

        {method === "cash" ? (
          <CashReceiverFields
            name={cashReceiverName} setName={setCashReceiverName}
            phone={cashReceiverPhone} setPhone={setCashReceiverPhone}
            address={cashReceiverAddress} setAddress={setCashReceiverAddress}
            id={cashReceiverId} setId={setCashReceiverId}
          />
        ) : (
          <NonCashDetailsField
            method={method} details={details} setDetails={setDetails}
            activeNetwork={activeNetwork}
            cryptoAddressMatch={cryptoAddressMatch}
          />
        )}

        <div>
          <Label className="micro-label text-neutral-500">
            {t("withdraw.beneficiaryName2")} <span className="text-[#8B5CF6]">*</span>
          </Label>
          <Input
            data-testid="withdraw-beneficiary"
            value={beneficiaryName}
            onChange={(e) => setBeneficiaryName(e.target.value)}
            placeholder={t("withdraw.cashReceiverNamePh")}
            className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12"
            required
          />
          <p className="text-[0.65rem] text-neutral-600 mt-1">
            {t("withdraw.beneficiaryHint")}
          </p>
        </div>

        <TotpField totpCode={totpCode} setTotpCode={setTotpCode} />

        <Button data-testid="submit-withdraw-btn" onClick={submit} disabled={busy}
          className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-12">
          {busy ? t("withdraw.submittingBtn") : t("withdraw.submitBtn")}
        </Button>
      </div>
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


function CashReceiverFields({ name, setName, phone, setPhone, address, setAddress, id, setId }) {
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
        <Trans i18nKey="withdraw.cashHint" components={{ 1: <strong />, 2: <strong /> }} />
      </p>
    </div>
  );
}


function NonCashDetailsField({ method, details, setDetails, activeNetwork, cryptoAddressMatch }) {
  const { t } = useTranslation();
  return (
    <div>
      <Label className="micro-label text-neutral-500">
        {t("withdraw.detailsLabel")} {method === "crypto" && <span className="text-[#8B5CF6]">*</span>}
      </Label>
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
      {method === "crypto" && cryptoAddressMatch === true && (
        <p
          data-testid="crypto-address-match-ok"
          className="text-[0.75rem] text-[#22C55E] mt-1 leading-relaxed flex items-center gap-1.5"
        >
          <span aria-hidden>✓</span>
          <span>
            <Trans
              i18nKey="withdraw.cryptoMatchOk"
              values={{ network: activeNetwork.label }}
              components={{ 1: <strong /> }}
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
              values={{ network: activeNetwork.label }}
              components={{ 1: <strong /> }}
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
