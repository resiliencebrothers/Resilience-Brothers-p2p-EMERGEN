import { useEffect, useRef, useState, useCallback } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";
import CopyableText from "@/components/CopyableText";
import { toast } from "sonner";
import { Search } from "lucide-react";

const STATUS_LABEL = (status, method) => {
  if (method === "cash") {
    return ({ paid: "Entregado", approved: "En progreso", pending: "Pendiente", rejected: "Rechazado" })[status] || status;
  }
  return ({ paid: "Pagado", approved: "Confirmado", pending: "Pendiente", rejected: "Rechazado" })[status] || status;
};

const STATUS_STYLES = {
  paid: "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  approved: "bg-[#EAB308]/10 text-[#EAB308] border-[#EAB308]/30",
  rejected: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30",
  pending: "bg-neutral-700/20 text-neutral-400 border-neutral-700/40",
};

export default function AdminWithdrawals() {
  const navigate = useNavigate();
  const [items, setItems] = useState([]);
  const [redemptions, setRedemptions] = useState([]);
  const [open, setOpen] = useState(null);
  const [note, setNote] = useState("");
  const [payoutProof, setPayoutProof] = useState(""); // base64 preview
  const [payoutHash, setPayoutHash] = useState("");
  const fileRef = useRef(null);
  const [pendingStatus, setPendingStatus] = useState(null); // status awaiting 2FA
  const [statusFilter, setStatusFilter] = useState("all");
  const [currencyFilter, setCurrencyFilter] = useState("all");
  const [currencies, setCurrencies] = useState([]);
  const [userInput, setUserInput] = useState("");
  const [userQuery, setUserQuery] = useState("");

  // Debounced user query
  useEffect(() => {
    const t = setTimeout(() => setUserQuery(userInput.trim()), 300);
    return () => clearTimeout(t);
  }, [userInput]);

  // Load currencies once
  useEffect(() => {
    axios.get(`${API}/currencies`).then((r) => setCurrencies(r.data || [])).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    const params = {};
    if (statusFilter !== "all") params.status = statusFilter;
    if (currencyFilter !== "all") params.currency = currencyFilter;
    if (userQuery) params.user_q = userQuery;
    const [w, r] = await Promise.all([
      axios.get(`${API}/admin/withdrawals`, { params, withCredentials: true }),
      axios.get(`${API}/admin/redemptions`, { withCredentials: true }),
    ]);
    setItems(w.data); setRedemptions(r.data);
  }, [statusFilter, currencyFilter, userQuery]);
  useEffect(() => { load(); }, [load]);

  const openDialog = (w) => {
    setOpen(w);
    setNote(w.admin_note || "");
    setPayoutProof(w.payout_proof_image || "");
    setPayoutHash(w.payout_tx_hash || "");
  };

  const handleProofUpload = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 4 * 1024 * 1024) { toast.error("Máx 4MB"); return; }
    const reader = new FileReader();
    reader.onload = () => setPayoutProof(reader.result);
    reader.readAsDataURL(f);
  };

  const confirmWithTotp = async (code) => {
    try {
      const body = { status: pendingStatus, admin_note: note, totp_code: code };
      if (payoutProof && payoutProof !== open.payout_proof_image) body.payout_proof_image = payoutProof;
      if (payoutHash && payoutHash !== open.payout_tx_hash) body.payout_tx_hash = payoutHash;
      await axios.put(
        `${API}/admin/withdrawals/${open.id}/status`,
        body,
        { withCredentials: true }
      );
      toast.success(`Retiro actualizado`);
      setPendingStatus(null); setOpen(null); setNote("");
      setPayoutProof(""); setPayoutHash("");
      load();
    } catch (e) {
      if (!handleTotpError(e, navigate)) toast.error(e.response?.data?.detail || "Error");
    }
  };

  const askChange = (status) => {
    // For "paid" require proof up front (UX hint — backend also enforces)
    if (status === "paid" && open?.method === "transfer" && !payoutProof) {
      toast.error("Adjunta la captura de la transferencia antes de marcar como pagado");
      return;
    }
    if (status === "paid" && open?.method === "crypto" && !payoutProof && !payoutHash) {
      toast.error("Adjunta hash de transacción o captura antes de marcar como entregado");
      return;
    }
    setPendingStatus(status);
  };

  const updateR = async (id, status) => {
    await axios.put(`${API}/admin/redemptions/${id}/status`, { status }, { withCredentials: true });
    toast.success("Actualizado"); load();
  };

  return (
    <div data-testid="admin-withdrawals" className="space-y-8">
      <div>
        <div className="micro-label text-[#EAB308] mb-2">/ Retiros</div>
        <h1 className="font-display text-3xl">Retiros & Canjes</h1>
      </div>

      <div>
        <h2 className="font-display text-xl mb-3">Retiros</h2>
        <div className="flex flex-wrap gap-2 mb-3 items-end">
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500 pointer-events-none" />
            <Input
              data-testid="withdrawals-user-search"
              value={userInput}
              onChange={(e) => setUserInput(e.target.value)}
              placeholder="Buscar usuario..."
              className="rounded-none bg-[#0a0a0a] border-white/10 h-9 w-60 pl-9 text-xs"
            />
          </div>
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger data-testid="withdrawals-status-filter" className="rounded-none bg-[#0a0a0a] border-white/10 h-9 w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#141414] border-white/10 text-white rounded-none">
              <SelectItem value="all">Todos los estados</SelectItem>
              <SelectItem value="pending">Pendiente</SelectItem>
              <SelectItem value="approved">Confirmado / En progreso</SelectItem>
              <SelectItem value="paid">Pagado / Entregado</SelectItem>
              <SelectItem value="rejected">Rechazado</SelectItem>
            </SelectContent>
          </Select>
          <Select value={currencyFilter} onValueChange={setCurrencyFilter}>
            <SelectTrigger data-testid="withdrawals-currency-filter" className="rounded-none bg-[#0a0a0a] border-white/10 h-9 w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#141414] border-white/10 text-white rounded-none">
              <SelectItem value="all">Todas las monedas</SelectItem>
              {currencies.map((c) => (
                <SelectItem key={c.id || c.code} value={c.code}>{c.code}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          {(userInput || statusFilter !== "all" || currencyFilter !== "all") && (
            <button
              data-testid="withdrawals-clear-filters"
              onClick={() => { setUserInput(""); setStatusFilter("all"); setCurrencyFilter("all"); }}
              className="text-xs text-neutral-500 hover:text-[#EAB308] underline underline-offset-4 h-9"
            >
              limpiar
            </button>
          )}
          <div className="ml-auto text-xs text-neutral-500" data-testid="withdrawals-result-count">
            {items.length} {items.length === 1 ? "retiro" : "retiros"}
          </div>
        </div>
        <div className="tactile-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="border-b border-white/10 bg-[#0a0a0a]">
              <tr className="text-left">
                <th className="px-3 py-3 micro-label text-neutral-500">Usuario</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Monto</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Moneda</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Método</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Detalles</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Estado</th>
                <th className="px-3 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && <tr><td colSpan="7" className="text-center text-neutral-500 py-6">Sin retiros</td></tr>}
              {items.map(w => (
                <tr key={w.id} className="border-b border-white/5">
                  <td className="px-3 py-3">{w.user_name}</td>
                  <td className="px-3 py-3 font-mono text-[#EAB308]">{w.amount_usd}</td>
                  <td className="px-3 py-3 font-mono">{w.currency || "USD"}</td>
                  <td className="px-3 py-3">
                    <span>{w.method}</span>
                    {w.method === "crypto" && w.crypto_network && (
                      <span
                        data-testid={`withdrawal-network-${w.id}`}
                        className="ml-2 inline-flex items-center px-1.5 py-0.5 text-[0.6rem] uppercase tracking-wider bg-[#EAB308]/10 text-[#EAB308] border border-[#EAB308]/30 font-mono"
                      >
                        {w.crypto_network}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-3 text-xs max-w-xs truncate">{w.details}</td>
                  <td className="px-3 py-3">
                    <span className={`text-xs uppercase tracking-wider border px-2 py-1 ${STATUS_STYLES[w.status] || STATUS_STYLES.pending}`}>
                      {STATUS_LABEL(w.status, w.method)}
                    </span>
                  </td>
                  <td className="px-3 py-3">
                    <Button size="sm" onClick={() => openDialog(w)} className="bg-[#EAB308] hover:bg-[#FACC15] text-black rounded-none h-8" data-testid={`manage-withdrawal-${w.id}`}>Gestionar</Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <h2 className="font-display text-xl mb-3">Canjes de Mercancía</h2>
        <div className="tactile-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="border-b border-white/10 bg-[#0a0a0a]">
              <tr className="text-left">
                <th className="px-3 py-3 micro-label text-neutral-500">Usuario</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Producto</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Cant.</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Total</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Dirección</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Estado</th>
                <th className="px-3 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {redemptions.length === 0 && <tr><td colSpan="7" className="text-center text-neutral-500 py-6">Sin canjes</td></tr>}
              {redemptions.map(r => (
                <tr key={r.id} className="border-b border-white/5">
                  <td className="px-3 py-3">{r.user_name}</td>
                  <td className="px-3 py-3">{r.product_name}</td>
                  <td className="px-3 py-3 font-mono">{r.quantity}</td>
                  <td className="px-3 py-3 font-mono text-[#EAB308]">${r.total_usd}</td>
                  <td className="px-3 py-3 text-xs max-w-xs truncate">{r.delivery_address}</td>
                  <td className="px-3 py-3 text-xs uppercase">{r.status}</td>
                  <td className="px-3 py-3">
                    <div className="flex gap-1">
                      <Button size="sm" onClick={() => updateR(r.id, "approved")} className="bg-[#22C55E] text-black rounded-none h-7 text-xs">✓</Button>
                      <Button size="sm" onClick={() => updateR(r.id, "delivered")} className="bg-[#EAB308] text-black rounded-none h-7 text-xs">⇪</Button>
                      <Button size="sm" onClick={() => updateR(r.id, "rejected")} className="bg-[#EF4444] text-white rounded-none h-7 text-xs">✕</Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <Dialog open={!!open} onOpenChange={() => setOpen(null)}>
        <DialogContent className="bg-[#141414] border-white/10 text-white rounded-none max-w-lg">
          <DialogHeader>
            <DialogTitle className="font-display">Retiro #{open?.id?.slice(0,8)}</DialogTitle>
            <DialogDescription className="text-neutral-500 text-xs">
              Gestiona el retiro y adjunta la evidencia de pago al cliente.
            </DialogDescription>
          </DialogHeader>
          {open && (
            <div className="space-y-4">
              <div className="font-mono text-sm space-y-1">
                <div><span className="text-neutral-500">Cliente:</span> {open.user_name}</div>
                <div><span className="text-neutral-500">Monto:</span> {open.amount_usd} {open.currency || "USD"}</div>
                <div><span className="text-neutral-500">Método:</span> {open.method}</div>
                {open.method === "crypto" && open.crypto_network && (
                  <div data-testid="withdrawal-modal-network">
                    <span className="text-neutral-500">Red on-chain:</span>{" "}
                    <span className="inline-flex items-center px-1.5 py-0.5 text-[0.7rem] uppercase tracking-wider bg-[#EAB308]/10 text-[#EAB308] border border-[#EAB308]/30 font-mono ml-1">
                      {open.crypto_network}
                    </span>
                  </div>
                )}
                <div className="flex items-start gap-2 flex-wrap">
                  <span className="text-neutral-500 flex-shrink-0">
                    {open.method === "crypto" ? "Wallet:" : "Detalles:"}
                  </span>
                  <CopyableText
                    value={open.details}
                    label={open.method === "crypto" ? "Copiar wallet" : "Copiar detalles"}
                    toastMessage={open.method === "crypto" ? "Wallet copiada" : "Detalles copiados"}
                    testid="withdrawal-copy-details"
                  />
                </div>
                <div className="flex items-start gap-2 flex-wrap">
                  <span className="text-neutral-500 flex-shrink-0">Beneficiario:</span>
                  {open.beneficiary_name ? (
                    <CopyableText
                      value={open.beneficiary_name}
                      label="Copiar beneficiario"
                      toastMessage="Beneficiario copiado"
                      testid="withdrawal-copy-beneficiary"
                      monospace={false}
                    />
                  ) : (
                    <span>—</span>
                  )}
                </div>
                <div><span className="text-neutral-500">Estado:</span> <span className="uppercase tracking-wider">{STATUS_LABEL(open.status, open.method)}</span></div>
              </div>
              <Textarea value={note} onChange={e => setNote(e.target.value)} placeholder="Nota..." rows={2} className="rounded-none bg-[#0a0a0a] border-white/10" />

              {/* Iter14: payout proof / tx_hash */}
              <div className="border border-white/10 p-3 space-y-3 bg-[#0a0a0a]/50">
                <div className="micro-label text-[#EAB308]">Evidencia de pago al cliente</div>
                {open.method === "crypto" && (
                  <div>
                    <label className="micro-label text-neutral-500">Hash de transacción</label>
                    <Input
                      data-testid="payout-tx-hash"
                      value={payoutHash}
                      onChange={(e) => setPayoutHash(e.target.value)}
                      placeholder="0x... (cripto)"
                      className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10 font-mono text-xs"
                    />
                  </div>
                )}
                <div>
                  <label className="micro-label text-neutral-500">
                    {open.method === "crypto"
                      ? "Captura del envío a wallet (opcional si hay hash)"
                      : "Captura de la transferencia bancaria realizada"}
                  </label>
                  <input
                    ref={fileRef}
                    data-testid="payout-proof-input"
                    type="file"
                    accept="image/*"
                    onChange={handleProofUpload}
                    className="block mt-1 text-xs text-neutral-400"
                  />
                  {payoutProof && (
                    <div className="mt-2">
                      <img src={payoutProof} alt="proof" className="max-h-40 border border-white/10" data-testid="payout-proof-preview" />
                    </div>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2">
                <Button data-testid="withdrawal-approve" onClick={() => askChange("approved")} className="bg-[#22C55E] text-black rounded-none">
                  {open.method === "cash" ? "En progreso" : "Confirmar"}
                </Button>
                <Button data-testid="withdrawal-pay" onClick={() => askChange("paid")} className="bg-[#EAB308] text-black rounded-none">
                  {open.method === "cash" ? "Entregado" : "Pagado"}
                </Button>
                <Button data-testid="withdrawal-reject" onClick={() => askChange("rejected")} className="bg-[#EF4444] text-white rounded-none">Rechazar</Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <TotpPromptDialog
        open={!!pendingStatus}
        title={`Confirmar retiro: ${pendingStatus ?? ""}`}
        description="Modificar un retiro mueve dinero real. Ingresa tu código 2FA para continuar."
        onConfirm={confirmWithTotp}
        onCancel={() => setPendingStatus(null)}
      />
    </div>
  );
}
