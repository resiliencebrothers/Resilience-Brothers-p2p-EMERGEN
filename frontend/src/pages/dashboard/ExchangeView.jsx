import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { ArrowRight, Upload, Copy, CheckCircle2 } from "lucide-react";

export default function ExchangeView() {
  const { user } = useAuth();
  const [currencies, setCurrencies] = useState([]);
  const [rates, setRates] = useState([]);
  const [fromCode, setFromCode] = useState("");
  const [toCode, setToCode] = useState("");
  const [amount, setAmount] = useState("");
  const [deliveryMethod, setDeliveryMethod] = useState("transfer");
  const [deliveryDetails, setDeliveryDetails] = useState("");
  const [senderName, setSenderName] = useState("");
  const [proofImage, setProofImage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(null);
  const [copied, setCopied] = useState(false);

  const isVip = user?.role === "vip" || user?.role === "admin";
  const isStaff = user?.role === "admin" || user?.role === "employee";

  // Static one-shot load on mount — API/axios are stable module imports
  useEffect(() => {
    axios.get(`${API}/currencies`).then(r => setCurrencies(r.data.filter(c => c.is_active)));
    axios.get(`${API}/rates`).then(r => setRates(r.data));
  }, []);

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
  const finalAmount = gross * (1 - commission / 100);

  // Compute which delivery_method options are valid for the chosen 'to' currency.
  // crypto destination → only crypto (and accumulate for VIP).
  // fiat destination → transfer + cash (and accumulate for VIP). Crypto wallet doesn't apply.
  // Marketplace deliveries (handled elsewhere) still allow cash for physical goods.
  const deliveryOptions = useMemo(() => {
    if (!toCurr) return [];
    if (toCurr.type === "crypto") {
      return [
        { value: "crypto", label: "Cripto (wallet)" },
        ...(!isStaff ? [{ value: "accumulate", label: "Acumular en saldo" }] : []),
      ];
    }
    // fiat (USD, CUP, BRL, MXN, ...)
    return [
      { value: "transfer", label: "Transferencia bancaria" },
      { value: "cash", label: "Efectivo (a domicilio)" },
      ...(!isStaff ? [{ value: "accumulate", label: "Acumular en saldo" }] : []),
    ];
  }, [toCurr, isStaff]);

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
      toast.error("Imagen demasiado grande (máx 3MB)");
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
      toast.error("Completa todos los campos requeridos");
      return;
    }
    if (deliveryMethod !== "accumulate" && !deliveryDetails) {
      toast.error("Detalles de entrega requeridos");
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
      toast.success("Orden creada. Pendiente de verificación.");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Error al crear orden");
    } finally {
      setSubmitting(false);
    }
  };

  if (success) {
    return (
      <div className="max-w-2xl mx-auto tactile-card p-8 text-center" data-testid="order-success">
        <CheckCircle2 className="w-16 h-16 text-[#22C55E] mx-auto mb-4" />
        <h2 className="font-display text-2xl mb-2">Orden Recibida</h2>
        <p className="text-neutral-400 mb-6">Tu orden #{success.id.slice(0,8)} está en revisión por nuestro equipo contable.</p>
        <div className="text-left space-y-2 border border-white/10 p-4 mb-6 font-mono text-sm">
          <div className="flex justify-between"><span className="text-neutral-500">Envías:</span> <span>{success.amount_from} {success.from_code}</span></div>
          <div className="flex justify-between"><span className="text-neutral-500">Recibes:</span> <span className="text-[#EAB308]">{success.amount_to} {success.to_code}</span></div>
          <div className="flex justify-between"><span className="text-neutral-500">Tasa:</span> <span>{success.rate_applied}</span></div>
          {success.commission_percent > 0 && (
            <div className="flex justify-between"><span className="text-neutral-500">Comisión:</span> <span>{success.commission_percent}%</span></div>
          )}
        </div>
        <Button data-testid="new-order-btn" onClick={() => { setSuccess(null); setAmount(""); setProofImage(""); setSenderName(""); setDeliveryDetails(""); }} className="bg-[#EAB308] hover:bg-[#FACC15] text-black rounded-none">
          Nueva Orden
        </Button>
      </div>
    );
  }

  return (
    <div className="max-w-4xl space-y-6" data-testid="exchange-view">
      <div>
        <div className="micro-label text-[#EAB308] mb-2">/ Intercambio</div>
        <h1 className="font-display text-3xl">Cripto ↔ Fiat</h1>
        <p className="text-neutral-400 mt-2">
          {isVip ? "Tasas VIP preferenciales" : "Tasa estándar según tu estatus"}
        </p>
      </div>

      <div className="tactile-card p-6 lg:p-8 space-y-6">
        <div className="grid md:grid-cols-2 gap-4">
          <div>
            <Label className="micro-label text-neutral-500">Envías</Label>
            <Select value={fromCode} onValueChange={setFromCode}>
              <SelectTrigger data-testid="from-currency-select" className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12">
                <SelectValue placeholder="Selecciona moneda" />
              </SelectTrigger>
              <SelectContent className="bg-[#141414] border-white/10 text-white rounded-none">
                {currencies.map(c => (
                  <SelectItem key={c.id} value={c.code} className="rounded-none">{c.code} — {c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="micro-label text-neutral-500">Recibes</Label>
            <Select value={toCode} onValueChange={setToCode}>
              <SelectTrigger data-testid="to-currency-select" className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12">
                <SelectValue placeholder="Selecciona moneda" />
              </SelectTrigger>
              <SelectContent className="bg-[#141414] border-white/10 text-white rounded-none">
                {currencies.map(c => (
                  <SelectItem key={c.id} value={c.code} className="rounded-none">{c.code} — {c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div>
          <Label className="micro-label text-neutral-500">Monto a enviar</Label>
          <Input
            data-testid="amount-input"
            type="number"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="0.00"
            className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12 text-lg font-mono"
          />
        </div>

        {selectedRate && amt > 0 && (
          <div className="border border-[#EAB308]/30 bg-[#EAB308]/5 p-5 space-y-2 font-mono text-sm">
            <div className="flex justify-between"><span className="text-neutral-400">Tasa aplicada:</span><span>{rate} {toCode}/{fromCode}</span></div>
            <div className="flex justify-between"><span className="text-neutral-400">Bruto:</span><span>{gross.toFixed(4)} {toCode}</span></div>
            {commission > 0 && (
              <div className="flex justify-between"><span className="text-neutral-400">Comisión ({commission}%):</span><span className="text-[#EF4444]">-{(gross - finalAmount).toFixed(4)}</span></div>
            )}
            <div className="border-t border-white/10 pt-2 mt-2 flex justify-between text-base">
              <span className="text-white">Recibirás:</span>
              <span className="text-[#EAB308] font-bold">{finalAmount.toFixed(4)} {toCode}</span>
            </div>
          </div>
        )}

        {fromCurr?.payment_account && (
          <div className="border border-white/10 p-4">
            <div className="micro-label text-neutral-500 mb-2">Cuenta destino — envía tu pago aquí:</div>
            <div className="flex items-center justify-between gap-3">
              <code className="text-sm break-all">{fromCurr.payment_account}</code>
              <button onClick={copyAccount} data-testid="copy-account-btn" className="text-[#EAB308] hover:text-[#FACC15] shrink-0">
                {copied ? <CheckCircle2 className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
              </button>
            </div>
          </div>
        )}

        <div>
          <Label className="micro-label text-neutral-500">
            Nombre del titular que envía el pago <span className="text-[#EAB308]">*</span>
          </Label>
          <Input
            data-testid="sender-name-input"
            value={senderName}
            onChange={(e) => setSenderName(e.target.value)}
            placeholder="Nombre completo del titular de la cuenta de origen"
            className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12"
            required
          />
          <p className="text-[0.65rem] text-neutral-600 mt-1">
            Obligatorio · queda registrado en el comprobante contable y auditoría
          </p>
        </div>

        <div>
          <Label className="micro-label text-neutral-500">Comprobante de pago (captura)</Label>
          <label className="block mt-2 border-2 border-dashed border-white/15 hover:border-[#EAB308] p-6 cursor-pointer transition-colors">
            <input type="file" accept="image/*" onChange={handleFile} className="hidden" data-testid="proof-upload" />
            {proofImage ? (
              <img src={proofImage} alt="proof" className="max-h-40 mx-auto" />
            ) : (
              <div className="text-center">
                <Upload className="w-8 h-8 text-neutral-500 mx-auto mb-2" />
                <p className="text-sm text-neutral-400">Click para subir captura</p>
                <p className="text-xs text-neutral-600 mt-1">PNG, JPG · max 3MB</p>
              </div>
            )}
          </label>
        </div>

        <div>
          <Label className="micro-label text-neutral-500">Método de entrega</Label>
          <Select
            value={deliveryMethod}
            onValueChange={setDeliveryMethod}
            disabled={!toCurr}
          >
            <SelectTrigger
              data-testid="delivery-method-select"
              className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12"
            >
              <SelectValue placeholder={toCurr ? "Selecciona método" : "Elige primero la moneda destino"} />
            </SelectTrigger>
            <SelectContent className="bg-[#141414] border-white/10 text-white rounded-none">
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
        </div>

        {deliveryMethod !== "accumulate" && (
          <div>
            <Label className="micro-label text-neutral-500">
              {deliveryMethod === "transfer" && "Datos bancarios del receptor"}
              {deliveryMethod === "cash" && "Nombre, teléfono y dirección del receptor"}
              {deliveryMethod === "crypto" && "Dirección de wallet (red)"}
            </Label>
            <Textarea
              data-testid="delivery-details-input"
              value={deliveryDetails}
              onChange={(e) => setDeliveryDetails(e.target.value)}
              rows={3}
              className="rounded-none mt-2 bg-[#0a0a0a] border-white/10"
            />
          </div>
        )}

        <Button
          data-testid="submit-order-btn"
          onClick={submit}
          disabled={submitting}
          className="w-full bg-[#EAB308] hover:bg-[#FACC15] text-black font-bold rounded-none h-14 text-base"
        >
          {submitting ? "Enviando..." : (<>Confirmar Orden <ArrowRight className="w-4 h-4 ml-2" /></>)}
        </Button>
      </div>
    </div>
  );
}
