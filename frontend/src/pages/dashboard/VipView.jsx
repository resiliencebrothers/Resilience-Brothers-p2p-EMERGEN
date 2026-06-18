import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { Wallet, ArrowDownToLine, FileDown, Coins, ShieldCheck } from "lucide-react";

const WITHDRAWAL_STATUS_STYLES = {
  paid: "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  approved: "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  rejected: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30",
  pending: "bg-[#EAB308]/10 text-[#EAB308] border-[#EAB308]/30",
};

export default function VipView() {
  const { user, refresh } = useAuth();
  const navigate = useNavigate();
  const [withdrawals, setWithdrawals] = useState([]);
  const [balances, setBalances] = useState({ balances: [], total_usdt: 0 });
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [method, setMethod] = useState("transfer");
  const [details, setDetails] = useState("");
  const [beneficiaryName, setBeneficiaryName] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [closingDate, setClosingDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [downloading, setDownloading] = useState(false);

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
  }, []);
  useEffect(() => { load(); }, [load]);

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
        <h2 className="font-display text-xl mb-4 flex items-center gap-2">
          <Coins className="w-5 h-5 text-[#EAB308]" /> Saldo por moneda
        </h2>
        {balances.balances.length === 0 ? (
          <p className="text-neutral-500 text-sm">Aún no tienes saldo acumulado. Crea órdenes con entrega &laquo;Acumular en saldo VIP&raquo;.</p>
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {balances.balances.map((b) => (
              <div key={b.currency} className="border border-white/10 p-4 hover:border-[#EAB308]/40 transition-colors">
                <div className="flex items-center justify-between mb-1">
                  <span className="micro-label text-neutral-500">{b.currency}</span>
                  <span className="text-xs text-neutral-500">≈ {b.usdt_equivalent?.toFixed(2) ?? "—"} USDT</span>
                </div>
                <div className="font-display text-2xl text-white">
                  {b.amount.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                </div>
              </div>
            ))}
          </div>
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
                  <SelectItem value="transfer">Transferencia bancaria</SelectItem>
                  <SelectItem value="cash">Efectivo (CUP/USD)</SelectItem>
                  <SelectItem value="crypto">Wallet Cripto</SelectItem>
                </SelectContent>
              </Select>
              {method === "cash" && (
                <p className="text-[0.65rem] text-[#EAB308] mt-1">
                  Recogida en efectivo: estará <strong>En progreso</strong> hasta que el equipo lo marque como <strong>Entregado</strong>.
                </p>
              )}
            </div>
            <div>
              <Label className="micro-label text-neutral-500">Detalles</Label>
              <Textarea data-testid="withdraw-details" value={details} onChange={e => setDetails(e.target.value)} rows={3} className="rounded-none mt-2 bg-[#0a0a0a] border-white/10" />
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
              const label = w.method === "cash"
                ? { paid: "Entregado", approved: "En progreso", pending: "Pendiente", rejected: "Rechazado" }[w.status] || w.status
                : { paid: "Pagado", approved: "Confirmado", pending: "Pendiente", rejected: "Rechazado" }[w.status] || w.status;
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
    </div>
  );
}
