import { useEffect, useMemo, useState, useCallback } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import CopyableText from "@/components/CopyableText";
import ExplorerLink from "@/components/ExplorerLink";
import {
  CRYPTO_NETWORKS, validateCryptoAddress,
} from "@/services/cryptoValidators";
import { toast } from "sonner";
import { Wallet, ArrowDownToLine, FileDown, Coins, ShieldCheck, History, Eye } from "lucide-react";

const WITHDRAWAL_STATUS_STYLES = {
  paid: "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  approved: "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  rejected: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30",
  pending: "bg-[#EAB308]/10 text-[#EAB308] border-[#EAB308]/30",
};

// Labels are method-specific: cash deliveries use "Entregado / En progreso"
// while transfers/crypto use "Pagado / Confirmado".
const WITHDRAWAL_LABELS_BY_METHOD = {
  cash:     { paid: "Entregado", approved: "En progreso", pending: "Pendiente", rejected: "Rechazado" },
  transfer: { paid: "Pagado",    approved: "Confirmado",  pending: "Pendiente", rejected: "Rechazado" },
  crypto:   { paid: "Pagado",    approved: "Confirmado",  pending: "Pendiente", rejected: "Rechazado" },
};

function getWithdrawalLabel(method, status) {
  const map = WITHDRAWAL_LABELS_BY_METHOD[method] ?? WITHDRAWAL_LABELS_BY_METHOD.transfer;
  return map[status] ?? status;
}

export default function VipView() {
  const { user, refresh } = useAuth();
  const navigate = useNavigate();
  const [withdrawals, setWithdrawals] = useState([]);
  const [balances, setBalances] = useState({ balances: [], total_usdt: 0 });
  // iter52 — per-currency ledger (which orders contributed to each balance)
  const [ledger, setLedger] = useState({ by_currency: {}, total_orders: 0 });
  const [ledgerOpen, setLedgerOpen] = useState(false);
  const [ledgerCurrency, setLedgerCurrency] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [method, setMethod] = useState("transfer");
  const [details, setDetails] = useState("");
  // iter55.22 — cash retiros: 3 obligatorios + 1 opcional. Ver composeCashDetails().
  const [cashReceiverName, setCashReceiverName] = useState("");
  const [cashReceiverPhone, setCashReceiverPhone] = useState("");
  const [cashReceiverAddress, setCashReceiverAddress] = useState("");
  const [cashReceiverId, setCashReceiverId] = useState(""); // opcional (Cuba: carné)
  const [beneficiaryName, setBeneficiaryName] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [closingDate, setClosingDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [downloading, setDownloading] = useState(false);
  // iter55.19 — Delivery methods allowed for the selected balance currency.
  // Fetched from GET /api/currencies/{code}/delivery-methods (backend source
  // of truth, iter43), so an admin marking "USD Efectivo" as cash-only will
  // instantly narrow the dropdown here without a frontend deploy.
  const [allowedMethods, setAllowedMethods] = useState([]);
  // iter55.19c — crypto network selector (TRC20 / BEP20). Default TRC20 —
  // the dominant network for USDT payouts in LatAm operations.
  const [cryptoNetwork, setCryptoNetwork] = useState("TRC20");

  const downloadClosing = async () => {
    setDownloading(true);
    try {
      const res = await axios.get(`${API}/vip/daily-closing`, {
        params: { date: closingDate },
        responseType: "blob",
        withCredentials: true,
      });
      const url = window.URL.createObjectURL(new Blob([res.data], { type: "application/pdf" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `cierre_vip_${closingDate}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      toast.success("Cierre descargado");
    } catch (e) {
      toast.error("Error al generar el cierre");
    } finally {
      setDownloading(false);
    }
  };

  const load = useCallback(async () => {
    // Each call independent so a 403 on one (e.g. legacy guard) doesn't break the page
    try {
      const r = await axios.get(`${API}/vip/withdrawals/mine`, { withCredentials: true });
      setWithdrawals(r.data);
    } catch (_) { setWithdrawals([]); }
    try {
      const b = await axios.get(`${API}/vip/balances`, { withCredentials: true });
      setBalances(b.data);
    } catch (_) { setBalances({ balances: [], total_usdt: 0 }); }
    try {
      const l = await axios.get(`${API}/vip/balance-ledger`, { withCredentials: true });
      setLedger(l.data);
    } catch (_) { setLedger({ by_currency: {}, total_orders: 0 }); }
  }, []);
  useEffect(() => { load(); }, [load]);

  // iter55.19 — Refresh the allowed delivery methods when the withdrawal
  // currency changes. If the admin didn't set delivery_methods on the
  // currency, the backend falls back to the name heuristic (e.g. "USD
  // Efectivo" → cash-only). Guarded by a cancellation flag so a fast
  // currency-flip doesn't clobber the state.
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
      transfer: { value: "transfer", label: "Transferencia bancaria" },
      cash: { value: "cash", label: "Efectivo (CUP/USD)" },
      crypto: { value: "crypto", label: "Wallet Cripto" },
    };
    // Fallback: while the endpoint is loading OR the currency doesn't declare
    // any method, keep the historical 3-option UX so users aren't stuck with
    // an empty dropdown.
    if (!allowedMethods || allowedMethods.length === 0) {
      return [LABELS.transfer, LABELS.cash, LABELS.crypto];
    }
    return allowedMethods.filter((m) => LABELS[m]).map((m) => LABELS[m]);
  }, [allowedMethods]);

  // Auto-correct the selected method whenever the allowed options change so
  // the user can never submit a combination the backend will reject.
  useEffect(() => {
    if (withdrawalMethodOptions.length === 0) return;
    if (!withdrawalMethodOptions.some((o) => o.value === method)) {
      setMethod(withdrawalMethodOptions[0].value);
    }
  }, [withdrawalMethodOptions, method]);

  // iter55.19c — Live crypto address ↔ network validation. `null` means the
  // check does not apply (non-crypto method or empty address); otherwise
  // returns the boolean the UI badge + submit gate consume.
  const cryptoAddressMatch = useMemo(() => {
    if (method !== "crypto") return null;
    if (!details || !details.trim()) return null;
    return validateCryptoAddress(details, cryptoNetwork);
  }, [method, details, cryptoNetwork]);

  const activeNetwork = CRYPTO_NETWORKS.find((n) => n.value === cryptoNetwork) || CRYPTO_NETWORKS[0];

  // iter55.22 — compose the structured cash `details` string from the 4
  // sub-fields. Persisted verbatim in withdrawals.details so admin sees
  // exactly the same labelled block, and PDFs / emails inherit it too.
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

  const submit = async () => {
    const amt = parseFloat(amount);
    if (!amt || amt <= 0) return toast.error("Monto inválido");
    // iter55.22 — cash: 3 sub-campos obligatorios (nombre, celular, dirección).
    // Otros métodos siguen usando el textarea `details` como antes.
    if (method === "cash") {
      if (!cashReceiverName.trim() || cashReceiverName.trim().length < 3) {
        return toast.error("Nombre y apellidos del receptor son obligatorios");
      }
      if (!cashReceiverPhone.trim() || cashReceiverPhone.trim().length < 6) {
        return toast.error("Teléfono celular del receptor es obligatorio");
      }
      if (!cashReceiverAddress.trim() || cashReceiverAddress.trim().length < 5) {
        return toast.error("Dirección de entrega es obligatoria");
      }
    } else {
      if (!details) return toast.error("Detalles requeridos");
    }
    // iter55.19c — Hard block crypto withdrawals when the address doesn't
    // match the declared network. Prevents irrecoverable transfers to the
    // wrong chain (BingX-style "No coinciden" gate).
    if (method === "crypto") {
      if (!cryptoNetwork) {
        return toast.error("Selecciona la red on-chain del retiro.");
      }
      if (cryptoAddressMatch !== true) {
        return toast.error(
          `La dirección no coincide con ${activeNetwork.label}. Revisa la red o pega otra dirección — enviar por la red incorrecta puede perder los fondos permanentemente.`
        );
      }
    }
    if (!beneficiaryName || beneficiaryName.trim().length < 2) {
      return toast.error("Nombre del titular beneficiario requerido");
    }
    if (!totpCode || totpCode.length < 6) {
      return toast.error("Ingresa tu código 2FA (6 dígitos) o código de recuperación");
    }
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
      toast.success("Solicitud de retiro enviada");
      setAmount(""); setDetails(""); setBeneficiaryName(""); setTotpCode("");
      setCashReceiverName(""); setCashReceiverPhone(""); setCashReceiverAddress(""); setCashReceiverId("");
      await load(); await refresh();
    } catch (e) {
      const detail = e.response?.data?.detail;
      if (e.response?.status === 412 && detail?.code === "TOTP_SETUP_REQUIRED") {
        toast.error("Debes configurar 2FA antes de realizar retiros");
        setTimeout(() => navigate("/dashboard/security"), 1500);
        return;
      }
      if (detail?.code === "TOTP_INVALID" || detail?.code === "TOTP_CODE_REQUIRED") {
        toast.error(detail.message || "Código 2FA inválido");
        return;
      }
      toast.error(detail?.message || detail || "Error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-8" data-testid="vip-view">
      <div>
        <div className="micro-label text-[#EAB308] mb-2">/ Saldo y Retiros</div>
        <h1 className="font-display text-3xl">Tu balance acumulado</h1>
      </div>

      <div className="tactile-card p-8 glow-yellow">
        <Wallet className="w-8 h-8 text-[#EAB308] mb-3" />
        <div className="micro-label text-neutral-500">Valor total (USDT)</div>
        <div className="font-display text-5xl text-[#EAB308] mt-2">
          {balances.total_usdt?.toLocaleString(undefined, { maximumFractionDigits: 2 }) || "0.00"} <span className="text-2xl text-neutral-400">USDT</span>
        </div>
        <div className="text-sm text-neutral-500 mt-1">Equivalente consolidado de todas tus monedas · usa tasa normal</div>
      </div>

      <div className="tactile-card p-6" data-testid="vip-balances-card">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
          <h2 className="font-display text-xl flex items-center gap-2">
            <Coins className="w-5 h-5 text-[#EAB308]" /> Saldo por moneda
          </h2>
          {ledger.total_orders > 0 && (
            <span
              className="text-xs text-neutral-500 flex items-center gap-1"
              data-testid="ledger-summary"
            >
              <History className="w-3.5 h-3.5" />
              {ledger.total_orders} {ledger.total_orders === 1 ? "orden" : "órdenes"} acreditadas
            </span>
          )}
        </div>
        {balances.balances.length === 0 ? (
          <p className="text-neutral-500 text-sm">Aún no tienes saldo acumulado. Crea órdenes con entrega &laquo;Acumular en saldo&raquo;.</p>
        ) : (
          <>
            <p className="text-xs text-neutral-500 mb-3">
              Click en una moneda para ver las órdenes que la acreditaron.
            </p>
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {balances.balances.map((b) => {
                const bucket = ledger.by_currency?.[b.currency];
                const orderCount = bucket?.orders?.length || 0;
                const hasDrillDown = orderCount > 0;
                return (
                  <button
                    type="button"
                    key={b.currency}
                    onClick={() => {
                      if (!hasDrillDown) return;
                      setLedgerCurrency(b.currency);
                      setLedgerOpen(true);
                    }}
                    disabled={!hasDrillDown}
                    className={`text-left border border-white/10 p-4 transition-colors ${
                      hasDrillDown
                        ? "hover:border-[#EAB308]/60 hover:bg-white/5 cursor-pointer"
                        : "opacity-80 cursor-default"
                    }`}
                    data-testid={`balance-card-${b.currency}`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="micro-label text-neutral-500">{b.currency}</span>
                      <span className="text-xs text-neutral-500">≈ {b.usdt_equivalent?.toFixed(2) ?? "—"} USDT</span>
                    </div>
                    <div className="font-display text-2xl text-white">
                      {b.amount.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                    </div>
                    {hasDrillDown && (
                      <div className="text-[0.65rem] text-[#EAB308] mt-2 flex items-center gap-1">
                        <Eye className="w-3 h-3" />
                        {orderCount} {orderCount === 1 ? "orden" : "órdenes"} · ver desglose
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          </>
        )}
      </div>

      <div className="tactile-card p-6">
        <div className="flex items-center justify-between flex-wrap gap-4">
          <div>
            <h2 className="font-display text-xl flex items-center gap-2">
              <FileDown className="w-5 h-5 text-[#EAB308]" /> Cierre Diario
            </h2>
            <p className="text-sm text-neutral-400 mt-1">Descarga el reporte PDF de tus órdenes aprobadas del día.</p>
          </div>
          <div className="flex items-center gap-3">
            <Input
              data-testid="closing-date-input"
              type="date"
              value={closingDate}
              onChange={(e) => setClosingDate(e.target.value)}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-11 font-mono w-44"
            />
            <Button
              data-testid="download-closing-btn"
              onClick={downloadClosing}
              disabled={downloading}
              className="bg-[#EAB308] hover:bg-[#FACC15] text-black font-semibold rounded-none h-11"
            >
              <FileDown className="w-4 h-4 mr-2" />
              {downloading ? "Generando..." : "Descargar PDF"}
            </Button>
          </div>
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <div className="tactile-card p-6">
          <h2 className="font-display text-xl mb-4 flex items-center gap-2"><ArrowDownToLine className="w-5 h-5 text-[#EAB308]" /> Solicitar Retiro</h2>
          <div className="space-y-4">
            <div>
              <Label className="micro-label text-neutral-500">Monto</Label>
              <Input data-testid="withdraw-amount" type="number" value={amount} onChange={e => setAmount(e.target.value)} className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12 font-mono" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">Moneda</Label>
              <Select value={currency} onValueChange={setCurrency}>
                <SelectTrigger data-testid="withdraw-currency" className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-[#141414] border-white/10 text-white rounded-none">
                  {(balances.balances.length > 0 ? balances.balances.map(b => b.currency) : ["USD"]).map(c => (
                    <SelectItem key={c} value={c}>{c}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">Método</Label>
              <Select value={method} onValueChange={setMethod}>
                <SelectTrigger data-testid="withdraw-method" className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-[#141414] border-white/10 text-white rounded-none">
                  {withdrawalMethodOptions.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {method === "cash" && (
                <p className="text-[0.65rem] text-[#EAB308] mt-1">
                  Recogida en efectivo: estará <strong>En progreso</strong> hasta que el equipo lo marque como <strong>Entregado</strong>.
                </p>
              )}
            </div>
            {method === "crypto" && (
              <div data-testid="crypto-network-block">
                <Label className="micro-label text-neutral-500">
                  Red on-chain <span className="text-[#EAB308]">*</span>
                </Label>
                <Select value={cryptoNetwork} onValueChange={setCryptoNetwork}>
                  <SelectTrigger data-testid="withdraw-crypto-network" className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-[#141414] border-white/10 text-white rounded-none">
                    {CRYPTO_NETWORKS.map((n) => (
                      <SelectItem key={n.value} value={n.value}>{n.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-[0.65rem] text-neutral-500 mt-1">
                  Elige la red correcta. Enviar por la red equivocada puede perder los fondos permanentemente.
                </p>
              </div>
            )}
            {/* iter55.22 — cash: formulario estructurado (Nombre / Celular / Dirección / ID opcional) */}
            {method === "cash" ? (
              <div className="space-y-3" data-testid="cash-receiver-block">
                <div>
                  <Label className="micro-label text-neutral-500">
                    Nombre y apellidos del receptor <span className="text-[#EAB308]">*</span>
                  </Label>
                  <Input
                    data-testid="cash-receiver-name"
                    value={cashReceiverName}
                    onChange={(e) => setCashReceiverName(e.target.value)}
                    placeholder="ej. Juan Pérez Rodríguez"
                    className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12"
                    required
                  />
                </div>
                <div>
                  <Label className="micro-label text-neutral-500">
                    Teléfono celular <span className="text-[#EAB308]">*</span>
                  </Label>
                  <Input
                    data-testid="cash-receiver-phone"
                    value={cashReceiverPhone}
                    onChange={(e) => setCashReceiverPhone(e.target.value)}
                    placeholder="+5355555555"
                    inputMode="tel"
                    className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12 font-mono"
                    required
                  />
                </div>
                <div>
                  <Label className="micro-label text-neutral-500">
                    Dirección de entrega <span className="text-[#EAB308]">*</span>
                  </Label>
                  <Textarea
                    data-testid="cash-receiver-address"
                    value={cashReceiverAddress}
                    onChange={(e) => setCashReceiverAddress(e.target.value)}
                    rows={2}
                    placeholder="Calle, número, entre calles, municipio, provincia"
                    className="rounded-none mt-2 bg-[#0a0a0a] border-white/10"
                    required
                  />
                </div>
                <div>
                  <Label className="micro-label text-neutral-500">
                    Número de ID / Carné <span className="text-neutral-600 normal-case">(opcional)</span>
                  </Label>
                  <Input
                    data-testid="cash-receiver-id"
                    value={cashReceiverId}
                    onChange={(e) => setCashReceiverId(e.target.value)}
                    placeholder="Solo si el equipo lo pide para coordinar"
                    inputMode="numeric"
                    className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12 font-mono"
                  />
                </div>
                <p className="text-[0.7rem] text-[#EAB308] mt-1 leading-relaxed" data-testid="withdraw-cash-hint">
                  El equipo usa estos datos para coordinar la entrega en efectivo. Verifica que el <strong>celular</strong> esté activo y la <strong>dirección</strong> sea clara.
                </p>
              </div>
            ) : (
              <div>
                <Label className="micro-label text-neutral-500">
                  Detalles {method === "crypto" && <span className="text-[#EAB308]">*</span>}
                </Label>
                <Textarea
                  data-testid="withdraw-details"
                  value={details}
                  onChange={e => setDetails(e.target.value)}
                  rows={method === "crypto" ? 2 : 3}
                  placeholder={
                    method === "crypto"
                      ? activeNetwork.addressPlaceholder
                      : "Banco, número de cuenta y titular"
                  }
                  className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 font-mono"
                />
                {method === "crypto" && cryptoAddressMatch === true && (
                  <p
                    data-testid="crypto-address-match-ok"
                    className="text-[0.75rem] text-[#22C55E] mt-1 leading-relaxed flex items-center gap-1.5"
                  >
                    <span aria-hidden>✓</span>
                    <span>Dirección compatible con <strong>{activeNetwork.label}</strong></span>
                  </p>
                )}
                {method === "crypto" && cryptoAddressMatch === false && (
                  <p
                    data-testid="crypto-address-mismatch"
                    className="text-[0.75rem] text-[#EF4444] mt-1 leading-relaxed flex items-start gap-1.5"
                  >
                    <span aria-hidden className="mt-0.5">⚠</span>
                    <span>
                      <strong>No coincide con {activeNetwork.label}</strong>. Revisa la red seleccionada o pega otra dirección —
                      enviar por la red incorrecta puede perder los fondos permanentemente.
                    </span>
                  </p>
                )}
              </div>
            )}
            <div>
              <Label className="micro-label text-neutral-500">
                Titular de la cuenta beneficiaria <span className="text-[#EAB308]">*</span>
              </Label>
              <Input
                data-testid="withdraw-beneficiary"
                value={beneficiaryName}
                onChange={(e) => setBeneficiaryName(e.target.value)}
                placeholder="Nombre completo de quien recibe"
                className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12"
                required
              />
              <p className="text-[0.65rem] text-neutral-600 mt-1">
                Obligatorio · queda registrado en contabilidad
              </p>
            </div>
            <div className="border border-[#EAB308]/40 bg-[#EAB308]/5 p-3">
              <Label className="micro-label text-[#EAB308] flex items-center gap-1.5">
                <ShieldCheck className="w-3.5 h-3.5" /> Código 2FA <span className="text-[#EAB308]">*</span>
              </Label>
              <Input
                data-testid="withdraw-totp"
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value)}
                placeholder="123456 o XXXXX-XXXXX"
                maxLength={11}
                inputMode="text"
                className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12 font-mono text-center text-lg tracking-wider"
                required
              />
              <p className="text-[0.65rem] text-neutral-500 mt-1">
                Código de 6 dígitos de tu app autenticadora o un código de recuperación.{" "}
                <a href="/dashboard/security" className="text-[#EAB308] hover:underline">¿Aún no configuras 2FA?</a>
              </p>
            </div>
            <Button data-testid="submit-withdraw-btn" onClick={submit} disabled={busy} className="w-full bg-[#EAB308] hover:bg-[#FACC15] text-black font-bold rounded-none h-12">
              {busy ? "Enviando..." : "Solicitar Retiro"}
            </Button>
          </div>
        </div>

        <div className="tactile-card p-6">
          <h2 className="font-display text-xl mb-4">Historial de Retiros</h2>
          <div className="space-y-2 max-h-[400px] overflow-y-auto">
            {withdrawals.length === 0 && <p className="text-neutral-500 text-sm">Sin retiros aún.</p>}
            {withdrawals.map(w => {
              const label = getWithdrawalLabel(w.method, w.status);
              return (
                <div key={w.id} className="border border-white/10 p-3 text-sm" data-testid={`withdrawal-row-${w.id}`}>
                  <div className="flex justify-between items-start">
                    <div>
                      <div className="font-mono">{w.amount_usd} {w.currency || "USD"} · {w.method}{w.crypto_network ? ` · ${w.crypto_network}` : ""}</div>
                      <div className="text-xs text-neutral-500 mt-1">{new Date(w.created_at).toLocaleString()}</div>
                    </div>
                    <span className={`text-xs uppercase tracking-wider border px-2 py-1 ${
                      WITHDRAWAL_STATUS_STYLES[w.status] || WITHDRAWAL_STATUS_STYLES.pending
                    }`}>{label}</span>
                  </div>
                  {(w.payout_proof_image || w.payout_tx_hash) && (
                    <div className="mt-3 border-t border-white/5 pt-2 space-y-2">
                      {w.payout_tx_hash && (
                        <div className="text-[0.65rem] text-neutral-400 flex flex-wrap items-center gap-2" data-testid={`payout-hash-${w.id}`}>
                          <span className="text-neutral-600">Hash:</span>
                          <span className="text-[#22C55E]">
                            <CopyableText
                              value={w.payout_tx_hash}
                              label="Copiar hash"
                              toastMessage="Hash copiado"
                              testid={`payout-hash-copy-${w.id}`}
                            />
                          </span>
                          <ExplorerLink
                            network={w.crypto_network}
                            txHash={w.payout_tx_hash}
                            testid={`payout-explorer-${w.id}`}
                          />
                        </div>
                      )}
                      {w.payout_proof_image && (
                        <a
                          href={w.payout_proof_image}
                          target="_blank"
                          rel="noreferrer"
                          className="text-xs text-[#EAB308] underline underline-offset-4"
                          data-testid={`payout-proof-${w.id}`}
                        >
                          Ver captura de la transferencia
                        </a>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* iter52 — Per-currency drill-down: which orders contributed */}
      <Dialog open={ledgerOpen} onOpenChange={setLedgerOpen}>
        <DialogContent
          className="bg-[#111] border-white/10 text-white rounded-none max-w-2xl max-h-[80vh] overflow-y-auto"
          data-testid="ledger-dialog"
        >
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <History className="w-5 h-5 text-[#EAB308]" />
              Órdenes que acreditaron {ledgerCurrency}
            </DialogTitle>
          </DialogHeader>
          <div className="pt-2 space-y-3" data-testid={`ledger-orders-${ledgerCurrency}`}>
            {(() => {
              const bucket = ledger.by_currency?.[ledgerCurrency];
              if (!bucket || bucket.orders.length === 0) {
                return (
                  <p className="text-sm text-neutral-500">
                    No hay órdenes registradas para esta moneda.
                  </p>
                );
              }
              return (
                <>
                  <div className="border border-[#EAB308]/30 bg-[#EAB308]/5 p-3 flex justify-between items-baseline">
                    <span className="text-xs text-neutral-400">Total acreditado:</span>
                    <span className="font-mono text-lg text-[#EAB308]">
                      {bucket.total.toLocaleString(undefined, { maximumFractionDigits: 4 })} {ledgerCurrency}
                    </span>
                  </div>
                  {bucket.orders.map((o) => (
                    <div
                      key={o.id}
                      className="border border-white/10 p-3 text-sm"
                      data-testid={`ledger-order-${o.id}`}
                    >
                      <div className="flex justify-between items-start gap-2 flex-wrap">
                        <div>
                          <div className="font-mono">
                            +{Number(o.amount_to).toLocaleString(undefined, { maximumFractionDigits: 4 })} {o.to_code}
                          </div>
                          <div className="text-xs text-neutral-500 mt-0.5">
                            desde {Number(o.amount_from).toLocaleString(undefined, { maximumFractionDigits: 2 })} {o.from_code}
                            {o.sender_name && (
                              <span className="text-neutral-600"> · {o.sender_name}</span>
                            )}
                          </div>
                        </div>
                        <div className="text-right">
                          <span className="text-[0.65rem] uppercase tracking-wider text-[#22C55E]">
                            {o.status}
                          </span>
                          <div className="text-[0.65rem] text-neutral-600 mt-0.5">
                            {new Date(o.accumulated_at || o.created_at).toLocaleString()}
                          </div>
                        </div>
                      </div>
                      <div className="text-[0.6rem] text-neutral-700 font-mono mt-2">
                        ID: {o.id}
                      </div>
                    </div>
                  ))}
                </>
              );
            })()}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
