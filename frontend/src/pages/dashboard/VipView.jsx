import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { Wallet, ArrowDownToLine, FileDown } from "lucide-react";

export default function VipView() {
  const { user, refresh } = useAuth();
  const [withdrawals, setWithdrawals] = useState([]);
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("transfer");
  const [details, setDetails] = useState("");
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

  const load = async () => {
    const r = await axios.get(`${API}/vip/withdrawals/mine`, { withCredentials: true });
    setWithdrawals(r.data);
  };
  useEffect(() => { load(); }, []);

  const submit = async () => {
    const amt = parseFloat(amount);
    if (!amt || amt <= 0) return toast.error("Monto inválido");
    if (!details) return toast.error("Detalles requeridos");
    setBusy(true);
    try {
      await axios.post(`${API}/vip/withdraw`, { amount_usd: amt, method, details }, { withCredentials: true });
      toast.success("Solicitud de retiro enviada");
      setAmount(""); setDetails("");
      await load(); await refresh();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-8" data-testid="vip-view">
      <div>
        <div className="micro-label text-[#EAB308] mb-2">/ Saldo VIP</div>
        <h1 className="font-display text-3xl">Tu tesorería acumulada</h1>
      </div>

      <div className="tactile-card p-8 glow-yellow">
        <Wallet className="w-8 h-8 text-[#EAB308] mb-3" />
        <div className="micro-label text-neutral-500">Saldo disponible</div>
        <div className="font-display text-5xl text-[#EAB308] mt-2">${(user?.vip_balance_usd || 0).toFixed(2)}</div>
        <div className="text-sm text-neutral-500 mt-1">USD · Disponible para retiro o canje</div>
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
              <Label className="micro-label text-neutral-500">Monto USD</Label>
              <Input data-testid="withdraw-amount" type="number" value={amount} onChange={e => setAmount(e.target.value)} className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12 font-mono" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">Método</Label>
              <Select value={method} onValueChange={setMethod}>
                <SelectTrigger data-testid="withdraw-method" className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-[#141414] border-white/10 text-white rounded-none">
                  <SelectItem value="transfer">Transferencia</SelectItem>
                  <SelectItem value="cash">Efectivo</SelectItem>
                  <SelectItem value="crypto">Cripto</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">Detalles</Label>
              <Textarea data-testid="withdraw-details" value={details} onChange={e => setDetails(e.target.value)} rows={3} className="rounded-none mt-2 bg-[#0a0a0a] border-white/10" />
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
            {withdrawals.map(w => (
              <div key={w.id} className="border border-white/10 p-3 text-sm">
                <div className="flex justify-between items-start">
                  <div>
                    <div className="font-mono">${w.amount_usd} · {w.method}</div>
                    <div className="text-xs text-neutral-500 mt-1">{new Date(w.created_at).toLocaleString()}</div>
                  </div>
                  <span className={`text-xs uppercase tracking-wider border px-2 py-1 ${
                    w.status === "paid" ? "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30" :
                    w.status === "rejected" ? "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30" :
                    "bg-[#EAB308]/10 text-[#EAB308] border-[#EAB308]/30"
                  }`}>{w.status}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
