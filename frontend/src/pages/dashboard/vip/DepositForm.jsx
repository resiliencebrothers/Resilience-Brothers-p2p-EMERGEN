import { useState, useEffect, useCallback, useMemo } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { PiggyBank, Upload, Trash2, Clock, Check, X as XIcon, Building2, Truck, ChevronRight } from "lucide-react";
import { useLiveEvent } from "@/hooks/useLiveStream";
import { fileToDataUrl, isImageTooLarge } from "@/utils/fileToDataUrl";
import { CRYPTO_NETWORKS } from "@/services/cryptoValidators";
import { DepositDetailDialog } from "./DepositDetailDialog";

/**
 * iter153 — Method-first client deposit form ("Depósitos y Retiros").
 * The method (crypto / transfer / cash) is chosen BEFORE this form renders
 * (see MethodPicker) and arrives as a prop; only the fields for that method
 * are shown and the currency dropdown is filtered to compatible currencies.
 *
 * Rules (owner, 30 Jul 2026):
 *  - Deposits credit the SAME currency once staff confirms receipt.
 *  - transfer → proof screenshot + account holder
 *  - crypto   → network + tx hash (+ optional proof)
 *  - cash     → >1000 USDT eq: courier pickup (address/phone/contact);
 *               ≤1000 USDT eq: bring to company offices (address shown).
 */
export function DepositForm({ onSubmitted, showHistory = true, method = "transfer", onBack }) {
  const { t } = useTranslation();
  const [config, setConfig] = useState(null);
  const [currency, setCurrency] = useState("");
  const [amount, setAmount] = useState("");
  const [holder, setHolder] = useState("");
  const [txHash, setTxHash] = useState("");
  const [network, setNetwork] = useState("TRC20");
  const [proof, setProof] = useState(null);
  const [contactName, setContactName] = useState("");
  const [pickupPhone, setPickupPhone] = useState("");
  const [pickupAddress, setPickupAddress] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    axios.get(`${API}/deposits/config`, { withCredentials: true })
      .then((r) => setConfig(r.data))
      .catch(() => setConfig({ currencies: [], courier_min_usdt: 1000, office_address: "" }));
  }, []);

  const currencyList = useMemo(
    () => (config?.currencies || []).filter((c) => (c.methods || []).includes(method)),
    [config, method],
  );

  useEffect(() => {
    if (currencyList.length === 0) { setCurrency(""); return; }
    if (!currencyList.some((c) => c.code === currency)) setCurrency(currencyList[0].code);
  }, [currencyList, currency]);

  const cur = currencyList.find((c) => c.code === currency);
  const usdtEq = cur?.usdt_per_unit != null && amount
    ? Number(amount) * cur.usdt_per_unit
    : null;
  const cashMode = method === "cash"
    ? (usdtEq != null && usdtEq > (config?.courier_min_usdt || 1000) ? "courier" : "office")
    : null;

  const pickProof = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (isImageTooLarge(f)) { toast.error(t("deposits.proofTooLarge")); return; }
    setProof({ name: f.name, dataUrl: await fileToDataUrl(f) });
  };

  const canSubmit = () => {
    if (!currency || !amount || Number(amount) <= 0 || !method) return false;
    if (method === "transfer") return !!proof && holder.trim().length >= 3;
    if (method === "crypto") return txHash.trim().length >= 10 && !!network;
    if (method === "cash" && cashMode === "courier") {
      return contactName.trim().length >= 3 && pickupPhone.trim().length >= 6 && pickupAddress.trim().length >= 5;
    }
    return true;
  };

  const submit = async () => {
    setBusy(true);
    try {
      await axios.post(`${API}/deposits`, {
        currency,
        amount: Number(amount),
        method,
        account_holder: holder.trim() || null,
        tx_hash: txHash.trim() || null,
        network: method === "crypto" ? network : null,
        proof_image: proof?.dataUrl || null,
        contact_name: contactName.trim() || null,
        pickup_phone: pickupPhone.trim() || null,
        pickup_address: pickupAddress.trim() || null,
        note: note.trim() || null,
      }, { withCredentials: true });
      toast.success(t("deposits.submitted"));
      setAmount(""); setHolder(""); setTxHash(""); setProof(null);
      setContactName(""); setPickupPhone(""); setPickupAddress(""); setNote("");
      setRefreshKey((k) => k + 1);
      onSubmitted?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("deposits.error"));
    } finally { setBusy(false); }
  };

  const noCurrencies = config !== null && currencyList.length === 0;

  return (
    <div className="tactile-card p-6 space-y-4" data-testid="deposit-form">
      <div className="flex items-start justify-between gap-2 flex-wrap">
        <div>
          <h2 className="font-display text-xl flex items-center gap-2">
            <PiggyBank className="w-5 h-5 text-emerald-400" /> {t("deposits.title")}
            <span className="text-[0.6rem] font-mono uppercase tracking-widest text-neutral-400 border border-white/10 px-2 py-1">
              {t(`methodPicker.options.${method}.label`)}
            </span>
          </h2>
          <p className="text-sm text-neutral-400 mt-1">{t("deposits.subtitle")}</p>
        </div>
        {onBack && (
          <button
            type="button"
            onClick={onBack}
            data-testid="deposit-change-method"
            className="text-xs text-neutral-500 hover:text-[#8B5CF6] underline underline-offset-4"
          >
            {t("methodPicker.back")}
          </button>
        )}
      </div>

      {noCurrencies ? (
        <p className="text-sm text-neutral-400 py-2" data-testid="deposit-no-currency">
          {t("deposits.noCurrencyForMethod")}
        </p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="micro-label text-neutral-500">{t("deposits.currencyLabel")}</Label>
              <Select value={currency} onValueChange={setCurrency}>
                <SelectTrigger data-testid="deposit-currency" className="rounded-none bg-black/40 border-white/10 text-white h-10 mt-1">
                  <SelectValue placeholder="—" />
                </SelectTrigger>
                <SelectContent className="bg-[#0c0c0c] border border-white/10 rounded-none max-h-64">
                  {currencyList.map((c) => (
                    <SelectItem key={c.code} value={c.code} className="rounded-none">
                      {c.code} — {c.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("deposits.amountLabel")}</Label>
              <Input
                data-testid="deposit-amount"
                type="number"
                min="0.01"
                step="0.01"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="0.00"
                className="rounded-none bg-black/40 border-white/10 text-white h-10 mt-1 font-mono"
              />
              {usdtEq != null && usdtEq > 0 && (
                <div className="text-[0.65rem] text-neutral-500 mt-1 font-mono" data-testid="deposit-usdt-eq">
                  ≈ {usdtEq.toLocaleString(undefined, { maximumFractionDigits: 2 })} USDT
                </div>
              )}
            </div>
          </div>

          {method === "transfer" && (
            <div className="space-y-3">
              <div>
                <Label className="micro-label text-neutral-500">{t("deposits.holderLabel")}</Label>
                <Input
                  data-testid="deposit-holder"
                  value={holder}
                  onChange={(e) => setHolder(e.target.value)}
                  placeholder={t("deposits.holderPlaceholder")}
                  maxLength={120}
                  className="rounded-none bg-black/40 border-white/10 text-white h-10 mt-1"
                />
              </div>
              <ProofPicker proof={proof} onPick={pickProof} onClear={() => setProof(null)} t={t} required />
            </div>
          )}

          {method === "crypto" && (
            <div className="space-y-3">
              <div>
                <Label className="micro-label text-neutral-500">{t("deposits.networkLabel")}</Label>
                <Select value={network} onValueChange={setNetwork}>
                  <SelectTrigger data-testid="deposit-network" className="rounded-none bg-black/40 border-white/10 text-white h-10 mt-1">
                    <SelectValue placeholder="—" />
                  </SelectTrigger>
                  <SelectContent className="bg-[#0c0c0c] border border-white/10 rounded-none">
                    {CRYPTO_NETWORKS.map((n) => (
                      <SelectItem key={n.value} value={n.value} className="rounded-none">
                        {n.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-[0.65rem] text-neutral-500 mt-1">{t("deposits.networkHint")}</p>
              </div>
              <div>
                <Label className="micro-label text-neutral-500">{t("deposits.hashLabel")}</Label>
                <Input
                  data-testid="deposit-hash"
                  value={txHash}
                  onChange={(e) => setTxHash(e.target.value)}
                  placeholder={t("deposits.hashPlaceholder")}
                  maxLength={200}
                  className="rounded-none bg-black/40 border-white/10 text-white h-10 mt-1 font-mono"
                />
              </div>
              <ProofPicker proof={proof} onPick={pickProof} onClear={() => setProof(null)} t={t} />
            </div>
          )}

          {method === "cash" && cashMode === "courier" && (
            <div className="border border-amber-500/30 bg-amber-500/5 p-3 space-y-3" data-testid="deposit-courier-box">
              <div className="flex items-center gap-2 text-amber-400 text-xs font-semibold uppercase tracking-widest">
                <Truck className="w-4 h-4" /> {t("deposits.courierTitle")}
              </div>
              <p className="text-xs text-neutral-400">{t("deposits.courierHint", { min: config?.courier_min_usdt || 1000 })}</p>
              <Input
                data-testid="deposit-contact-name"
                value={contactName}
                onChange={(e) => setContactName(e.target.value)}
                placeholder={t("deposits.contactName")}
                maxLength={120}
                className="rounded-none bg-black/40 border-white/10 text-white h-10"
              />
              <Input
                data-testid="deposit-pickup-phone"
                value={pickupPhone}
                onChange={(e) => setPickupPhone(e.target.value)}
                placeholder={t("deposits.pickupPhone")}
                maxLength={40}
                className="rounded-none bg-black/40 border-white/10 text-white h-10"
              />
              <Input
                data-testid="deposit-pickup-address"
                value={pickupAddress}
                onChange={(e) => setPickupAddress(e.target.value)}
                placeholder={t("deposits.pickupAddress")}
                maxLength={300}
                className="rounded-none bg-black/40 border-white/10 text-white h-10"
              />
            </div>
          )}

          {method === "cash" && cashMode === "office" && (
            <div className="border border-[#8B5CF6]/30 bg-[#8B5CF6]/5 p-3" data-testid="deposit-office-box">
              <div className="flex items-center gap-2 text-[#A78BFA] text-xs font-semibold uppercase tracking-widest">
                <Building2 className="w-4 h-4" /> {t("deposits.officeTitle")}
              </div>
              <p className="text-xs text-neutral-400 mt-2">{t("deposits.officeHint", { min: config?.courier_min_usdt || 1000 })}</p>
              <div className="text-sm text-white mt-2 font-mono" data-testid="deposit-office-address">
                {config?.office_address || t("deposits.officeAddressFallback")}
              </div>
            </div>
          )}

          <div>
            <Label className="micro-label text-neutral-500">{t("deposits.noteLabel")}</Label>
            <Input
              data-testid="deposit-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={t("deposits.notePlaceholder")}
              maxLength={300}
              className="rounded-none bg-black/40 border-white/10 text-white h-10 mt-1"
            />
          </div>

          <Button
            onClick={submit}
            disabled={busy || !canSubmit()}
            data-testid="deposit-submit"
            className="w-full rounded-none bg-emerald-500 hover:bg-emerald-400 text-black h-11 font-semibold uppercase tracking-widest text-xs disabled:opacity-40"
          >
            {t("deposits.submit")}
          </Button>
        </>
      )}

      {showHistory && <DepositHistory refreshKey={refreshKey} />}
    </div>
  );
}


function ProofPicker({ proof, onPick, onClear, t, required = false }) {
  return (
    <div>
      <Label className="micro-label text-neutral-500">
        {t("deposits.proofLabel")}{required ? " *" : ""}
      </Label>
      {proof ? (
        <div className="flex items-center justify-between border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 mt-1">
          <span className="text-xs text-emerald-400 truncate">{proof.name}</span>
          <button type="button" onClick={onClear} data-testid="deposit-proof-clear" className="text-neutral-400 hover:text-white">
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      ) : (
        <label
          className="flex items-center gap-2 border border-dashed border-white/15 hover:border-[#8B5CF6]/50 px-3 py-2.5 mt-1 cursor-pointer text-xs text-neutral-400"
          data-testid="deposit-proof-picker"
        >
          <Upload className="w-4 h-4" /> {t("deposits.proofPick")}
          <input type="file" accept="image/*" className="hidden" onChange={onPick} />
        </label>
      )}
    </div>
  );
}


export function DepositHistory({ refreshKey, alwaysShow = false }) {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState(null);

  const load = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/deposits/mine`, { params: { limit: 50 }, withCredentials: true });
      setItems(r.data?.items || []);
    } catch { setItems([]); }
  }, []);
  useEffect(() => { load(); }, [load, refreshKey]);
  useLiveEvent("balance_updated", load);

  if (items.length === 0 && !alwaysShow) return null;
  return (
    <div className={alwaysShow ? "" : "border-t border-white/5 pt-4"} data-testid="deposit-history">
      {!alwaysShow && <div className="micro-label text-neutral-500 mb-2">{t("deposits.historyTitle")}</div>}
      {items.length === 0 && (
        <div className="text-sm text-neutral-500 py-8 text-center border border-white/5 bg-black/20" data-testid="deposit-history-empty">
          {t("deposits.historyEmpty")}
        </div>
      )}
      <div className={alwaysShow ? "space-y-2 max-h-[50vh] overflow-y-auto" : "space-y-2 max-h-56 overflow-y-auto"}>
        {items.map((d) => (
          <button
            type="button"
            key={d.id}
            onClick={() => setSelected(d)}
            className="w-full flex items-center justify-between text-left text-xs border border-white/5 bg-black/20 hover:border-[#8B5CF6]/40 transition-colors px-3 py-2"
            data-testid={`deposit-row-${d.id}`}
          >
            <div>
              <span className="font-mono text-white">
                {Number(d.amount).toLocaleString()} {d.currency}
              </span>
              <span className="text-neutral-500 ml-2">
                {t(`deposits.method.${d.method}`, d.method)}
                {d.network ? ` · ${d.network}` : ""}
                {d.cash_mode ? ` · ${t(`deposits.cashMode.${d.cash_mode}`)}` : ""}
              </span>
              {d.admin_note && <div className="text-[0.65rem] italic text-neutral-500 mt-0.5">{d.admin_note}</div>}
            </div>
            <div className="flex items-center gap-3 shrink-0">
              <span className="text-[0.6rem] text-neutral-500">{new Date(d.created_at).toLocaleDateString()}</span>
              <DepositStatusPill status={d.status} t={t} />
              <ChevronRight className="w-3.5 h-3.5 text-neutral-600" />
            </div>
          </button>
        ))}
      </div>
      <DepositDetailDialog d={selected} onClose={() => setSelected(null)} />
    </div>
  );
}


function DepositStatusPill({ status, t }) {
  const map = {
    pending:   { cls: "border-amber-500/40 bg-amber-500/5 text-amber-400", Icon: Clock },
    confirmed: { cls: "border-emerald-500/40 bg-emerald-500/5 text-emerald-400", Icon: Check },
    rejected:  { cls: "border-[#EF4444]/40 bg-[#EF4444]/10 text-[#EF4444]", Icon: XIcon },
  }[status] || {};
  const Icon = map.Icon || Clock;
  return (
    <span className={`inline-flex items-center gap-1 text-[0.6rem] uppercase tracking-widest px-1.5 py-0.5 border font-mono ${map.cls || ""}`}>
      <Icon className="w-3 h-3" /> {t(`deposits.status.${status}`, status)}
    </span>
  );
}
