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

  const submit = async () => {
    const amt = parseFloat(amount);
    if (!amt || amt <= 0) return toast.error("Monto inválido");
    if (!details) return toast.error("Detalles requeridos");
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
        details,
        beneficiary_name: beneficiaryName.trim(),
        totp_code: totpCode.trim(),
      }, { withCredentials: true });
      toast.success("Solicitud de retiro enviada");
      setAmount(""); setDetails(""); setBeneficiaryName(""); setTotpCode("");
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
            <div>
              <Label className="micro-label text-neutral-500">
                Detalles {method === "cash" && <span className="text-[#EAB308]">*</span>}
              </Label>
              <Textarea
                data-testid="withdraw-details"
                value={details}
                onChange={e => setDetails(e.target.value)}
                rows={method === "cash" ? 5 : 3}
                placeholder={
                  method === "cash"
                    ? "Nombre y apellidos, número de ID/carné y teléfono celular de la persona que recibirá el dinero"
                    : method === "crypto"
                      ? "Dirección de la wallet (TRC20 / BEP20 / ERC20) y red"
                      : "Banco, número de cuenta y titular"
                }
                className="rounded-none mt-2 bg-[#0a0a0a] border-white/10"
              />
              {method === "cash" && (
                <p className="text-[0.7rem] text-[#EAB308] mt-1 leading-relaxed" data-testid="withdraw-cash-hint">
                  Para retiros en efectivo, indica del receptor: <strong>nombre y apellidos</strong>,
                  <strong> número de ID / carné</strong> y <strong>teléfono celular</strong> — el equipo lo
                  necesita para coordinar la entrega.
                </p>
              )}
            </div>
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
                      <div className="font-mono">{w.amount_usd} {w.currency || "USD"} · {w.method}</div>
                      <div className="text-xs text-neutral-500 mt-1">{new Date(w.created_at).toLocaleString()}</div>
                    </div>
                    <span className={`text-xs uppercase tracking-wider border px-2 py-1 ${
                      WITHDRAWAL_STATUS_STYLES[w.status] || WITHDRAWAL_STATUS_STYLES.pending
                    }`}>{label}</span>
                  </div>
                  {(w.payout_proof_image || w.payout_tx_hash) && (
                    <div className="mt-3 border-t border-white/5 pt-2 space-y-1">
                      {w.payout_tx_hash && (
                        <div className="text-[0.65rem] text-neutral-400 break-all" data-testid={`payout-hash-${w.id}`}>
                          <span className="text-neutral-600">Hash: </span>
                          <span className="font-mono text-[#22C55E]">{w.payout_tx_hash}</span>
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
