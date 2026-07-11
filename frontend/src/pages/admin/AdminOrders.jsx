import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Pagination } from "@/components/Pagination";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";
import { Eye, Search, Upload, Copy, Check } from "lucide-react";
import { toast } from "sonner";
import { getDeliveryBadge, extractCryptoNetwork, NETWORK_META } from "@/services/delivery_validators";

const STATUS_STYLES = {
  pending: "bg-[#8B5CF6]/10 text-[#8B5CF6] border-[#8B5CF6]/30",
  requires_double_approval: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/40",
  approved: "bg-[#F59E0B]/10 text-[#F59E0B] border-[#F59E0B]/30",
  completed: "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  rejected: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30",
};

// iter55.9 — small helper used inside the delivery-details panel. Copies the
// given `value` to the clipboard and briefly shows a green check, so the
// operator has visual feedback that the payload landed in the buffer.
function CopyBtn({ label, value, testid }) {
  const [ok, setOk] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setOk(true);
      toast.success("Copiado al portapapeles");
      setTimeout(() => setOk(false), 1500);
    } catch {
      toast.error("No se pudo copiar (permiso denegado)");
    }
  };
  return (
    <button
      type="button"
      data-testid={testid}
      onClick={copy}
      className="inline-flex items-center gap-1.5 border border-white/10 hover:border-[#8B5CF6]/50 bg-[#1A1730] hover:bg-[#8B5CF6]/5 px-2.5 py-1 text-[0.7rem] font-mono text-neutral-300 transition-colors"
    >
      {ok ? <Check className="w-3 h-3 text-[#22C55E]" /> : <Copy className="w-3 h-3" />}
      {label}
    </button>
  );
}

// Iter14 — labels for order status (user requested: "Aprobado" → "Confirmado")
const STATUS_LABELS = {
  pending: "pendiente",
  requires_double_approval: "doble aprobación",
  approved: "confirmado",
  completed: "completado",
  rejected: "rechazado",
};

const PAGE_SIZE = 50;

export default function AdminOrders() {
  const navigate = useNavigate();
  const { user: currentUser } = useAuth();
  const isAdmin = currentUser?.role === "admin";
  const [orders, setOrders] = useState([]);
  const [filter, setFilter] = useState("all");
  const [userQuery, setUserQuery] = useState("");
  const [userInput, setUserInput] = useState("");
  const [currencyFilter, setCurrencyFilter] = useState("all");
  const [currencies, setCurrencies] = useState([]);
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(null);
  const [note, setNote] = useState("");
  const [payoutProof, setPayoutProof] = useState("");
  const [payoutHash, setPayoutHash] = useState("");
  const [pendingStatus, setPendingStatus] = useState(null); // status waiting for 2FA (low-margin orders)

  useEffect(() => { setPage(0); }, [filter, userQuery, currencyFilter]);

  // Debounce user query input
  useEffect(() => {
    const t = setTimeout(() => setUserQuery(userInput.trim()), 300);
    return () => clearTimeout(t);
  }, [userInput]);

  // Load currencies once for the filter dropdown
  useEffect(() => {
    axios.get(`${API}/currencies`).then((r) => setCurrencies(r.data || [])).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit: PAGE_SIZE, offset: page * PAGE_SIZE };
      if (filter !== "all") params.status = filter;
      if (userQuery) params.user_q = userQuery;
      if (currencyFilter !== "all") params.currency = currencyFilter;
      const r = await axios.get(`${API}/admin/orders`, { params, withCredentials: true });
      setOrders(r.data);
      const t = Number(r.headers["x-total-count"]);
      setTotal(Number.isFinite(t) ? t : r.data.length);
    } catch (e) {
      toast.error("Error al cargar órdenes");
    } finally {
      setLoading(false);
    }
  }, [filter, page, userQuery, currencyFilter]);
  useEffect(() => { load(); }, [load]);

  const openOrder = (o) => {
    setOpen(o);
    setNote(o.admin_note || "");
    setPayoutProof(o.payout_proof_image || "");
    setPayoutHash(o.payout_tx_hash || "");
  };

  const handlePayoutUpload = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 4 * 1024 * 1024) { toast.error("Máx 4MB"); return; }
    const reader = new FileReader();
    reader.onload = () => setPayoutProof(reader.result);
    reader.readAsDataURL(f);
  };

  const updateStatus = async (status, totpCode = null) => {
    if (!open) return;
    const body = { status, admin_note: note };
    if (totpCode) body.totp_code = totpCode;
    // Only send payout fields when they changed — saves bandwidth on small status flips.
    if (payoutProof && payoutProof !== open.payout_proof_image) body.payout_proof_image = payoutProof;
    if (payoutHash && payoutHash !== open.payout_tx_hash) body.payout_tx_hash = payoutHash;
    try {
      await axios.put(`${API}/admin/orders/${open.id}/status`, body, { withCredentials: true });
      toast.success(`Orden ${status}`);
      setOpen(null); setNote(""); setPayoutProof(""); setPayoutHash(""); setPendingStatus(null); load();
    } catch (e) {
      const detail = e.response?.data?.detail;
      const code = typeof detail === "object" ? detail?.code : null;
      // Server requires step-up 2FA → open prompt
      if (code === "TOTP_CODE_REQUIRED" || code === "TOTP_INVALID") {
        if (code === "TOTP_INVALID") toast.error(detail?.message || "Código 2FA inválido");
        setPendingStatus(status);
        return;
      }
      if (!handleTotpError(e, navigate)) toast.error(detail?.message || detail || "Error");
    }
  };

  return (
    <div data-testid="admin-orders" className="space-y-4">
      <div className="mb-6">
        <div className="micro-label text-[#8B5CF6] mb-2">/ Órdenes</div>
        <h1 className="font-display text-3xl">Cola de Operaciones P2P</h1>
      </div>
      <div className="flex gap-2 mb-3 flex-wrap items-end">
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500 pointer-events-none" />
          <Input
            data-testid="orders-user-search"
            value={userInput}
            onChange={(e) => setUserInput(e.target.value)}
            placeholder="Buscar usuario..."
            className="rounded-none bg-[#0a0a0a] border-white/10 h-9 w-60 pl-9 text-xs"
          />
        </div>
        <Select value={currencyFilter} onValueChange={setCurrencyFilter}>
          <SelectTrigger data-testid="orders-currency-filter" className="rounded-none bg-[#0a0a0a] border-white/10 h-9 w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
            <SelectItem value="all">Todas las monedas</SelectItem>
            {currencies.map((c) => (
              <SelectItem key={c.id || c.code} value={c.code}>{c.code}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {(userInput || currencyFilter !== "all") && (
          <button
            data-testid="orders-clear-filters"
            onClick={() => { setUserInput(""); setCurrencyFilter("all"); }}
            className="text-xs text-neutral-500 hover:text-[#8B5CF6] underline underline-offset-4 h-9"
          >
            limpiar
          </button>
        )}
        <div className="ml-auto text-xs text-neutral-500" data-testid="orders-result-count">
          {total} {total === 1 ? "orden" : "órdenes"}
        </div>
      </div>
      <div className="flex gap-2 mb-4 flex-wrap">
        {["all", "pending", "requires_double_approval", "approved", "rejected", "completed"].map(f => (
          <button key={f} data-testid={`orders-filter-${f}`} onClick={() => setFilter(f)} className={`micro-label px-3 py-1.5 border transition-colors ${filter === f ? "bg-[#8B5CF6] text-white border-[#8B5CF6]" : "border-white/10 text-neutral-400 hover:text-white"}`}>
            {f}
          </button>
        ))}
      </div>
      <div className="tactile-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-white/10 bg-[#0a0a0a]">
              <tr className="text-left">
                <th className="px-3 py-3 micro-label text-neutral-500">ID</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Cliente</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Rol</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Par</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Monto</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Recibe</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Entrega</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Estado</th>
                <th className="px-3 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan="9" className="text-center text-neutral-500 py-8">Cargando...</td></tr>}
              {!loading && orders.length === 0 && <tr><td colSpan="9" className="text-center text-neutral-500 py-8">Sin órdenes</td></tr>}
              {orders.map(o => (
                <tr key={o.id} className="border-b border-white/5 hover:bg-white/5">
                  <td className="px-3 py-3 font-mono text-xs">{o.id.slice(0,6)}</td>
                  <td className="px-3 py-3">{o.user_name}</td>
                  <td className="px-3 py-3"><span className="text-xs uppercase">{o.user_role}</span></td>
                  <td className="px-3 py-3 font-mono">{o.from_code}→{o.to_code}</td>
                  <td className="px-3 py-3 font-mono">{o.amount_from}</td>
                  <td className="px-3 py-3 font-mono text-[#8B5CF6]">{o.amount_to}</td>
                  <td className="px-3 py-3 text-xs">
                    <div className="flex flex-col gap-1">
                      <span>{o.delivery_method}</span>
                      {o.delivery_method === "crypto" && (() => {
                        const net = extractCryptoNetwork(o.delivery_details, "crypto");
                        if (!net) return null;
                        const meta = NETWORK_META[net];
                        if (!meta) return null;
                        return (
                          <span
                            data-testid={`row-network-${net}`}
                            className="inline-flex items-center px-1.5 py-0.5 font-mono text-[0.6rem] font-bold tracking-wider w-fit"
                            style={{ background: meta.bg, color: meta.fg }}
                          >
                            {net}
                          </span>
                        );
                      })()}
                    </div>
                  </td>
                  <td className="px-3 py-3"><span className={`text-xs uppercase border px-2 py-0.5 ${STATUS_STYLES[o.status]}`}>{STATUS_LABELS[o.status] || o.status}</span></td>
                  <td className="px-3 py-3"><button onClick={() => openOrder(o)} data-testid={`view-order-${o.id}`} className="text-neutral-400 hover:text-[#8B5CF6]"><Eye className="w-4 h-4" /></button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <Pagination
        page={page}
        total={total}
        pageSize={PAGE_SIZE}
        loading={loading}
        onPageChange={setPage}
        testidPrefix="orders-pagination"
      />

      <Dialog open={!!open} onOpenChange={() => setOpen(null)}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-display">Orden #{open?.id?.slice(0,8)}</DialogTitle>
            <DialogDescription className="text-neutral-500 text-xs">
              Revisa la captura de pago y confirma o rechaza la operación.
            </DialogDescription>
          </DialogHeader>
          {open && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-2 font-mono text-sm">
                <div><span className="text-neutral-500">Cliente:</span> {open.user_name}</div>
                <div><span className="text-neutral-500">Email:</span> {open.user_email}</div>
                <div><span className="text-neutral-500">Rol:</span> {open.user_role}</div>
                <div><span className="text-neutral-500">Par:</span> {open.from_code}→{open.to_code}</div>
                <div><span className="text-neutral-500">Envía:</span> {open.amount_from} {open.from_code}</div>
                <div><span className="text-neutral-500">Recibe:</span> {open.amount_to} {open.to_code}</div>
                <div><span className="text-neutral-500">Tasa:</span> {open.rate_applied}</div>
                {open.commission_percent > 0 && (
                  <div><span className="text-neutral-500">Comisión:</span> {open.commission_percent}%</div>
                )}
                <div className="col-span-2"><span className="text-neutral-500">Titular pago:</span> {open.sender_name}</div>
              </div>

              {open.delivery_details && (
                <div className="border border-white/10 bg-[#0a0a0a] p-3" data-testid="delivery-block">
                  {/* iter55.13 — Prominent network badge for crypto payouts so
                      the operator can't accidentally send on the wrong chain. */}
                  {open.delivery_method === "crypto" && (() => {
                    const net = extractCryptoNetwork(open.delivery_details, "crypto");
                    if (!net) return null;
                    const meta = NETWORK_META[net];
                    if (!meta) return null;
                    return (
                      <div
                        data-testid={`admin-network-badge-${net}`}
                        className="mb-3 flex items-center gap-3 border-l-4 pl-3 py-2"
                        style={{ borderColor: meta.bg, background: `${meta.bg}12` }}
                      >
                        <span
                          className="inline-flex items-center px-3 py-1.5 font-mono text-xs font-bold tracking-wider uppercase"
                          style={{ background: meta.bg, color: meta.fg }}
                        >
                          {meta.label}
                        </span>
                        <span className="text-[0.7rem] text-neutral-400 leading-tight">
                          {net === "AMBIGUOUS_0X"
                            ? "El cliente NO declaró la red. Contacta antes de enviar."
                            : `Enviar en la red ${net}. Verifica que el wallet destino la acepte.`}
                        </span>
                      </div>
                    );
                  })()}

                  <div className="micro-label text-neutral-500 mb-2 flex items-center justify-between">
                    <span>Entrega ({open.delivery_method})</span>
                    {(() => {
                      const badge = getDeliveryBadge(open.to_code, open.delivery_method, open.delivery_details);
                      if (!badge) return null;
                      return (
                        <span
                          data-testid={badge.ok ? "delivery-badge-ok" : "delivery-badge-warn"}
                          className={`text-[0.65rem] normal-case tracking-normal ${
                            badge.ok ? "text-[#22C55E]" : "text-[#EF4444]"
                          }`}
                        >
                          {badge.feedback}
                        </span>
                      );
                    })()}
                  </div>

                  <div className="whitespace-pre-wrap font-mono text-sm text-neutral-200 break-words">
                    {open.delivery_details}
                  </div>

                  {/* Copy buttons — full text + isolated account number when detectable */}
                  <div className="flex flex-wrap gap-2 mt-3">
                    <CopyBtn
                      testid="copy-delivery-full"
                      label="Copiar todo"
                      value={open.delivery_details}
                    />
                    {(() => {
                      const digitsOnly = (open.delivery_details.match(/\d/g) || []).join("");
                      const isCubanBank =
                        open.delivery_method === "transfer" &&
                        ["CUP", "CUPT", "CUPE"].includes((open.to_code || "").toUpperCase()) &&
                        digitsOnly.length === 16;
                      const isClabe =
                        open.delivery_method === "transfer" &&
                        (open.to_code || "").toUpperCase() === "MXN" &&
                        digitsOnly.length === 18;
                      if (isCubanBank || isClabe) {
                        return (
                          <>
                            <CopyBtn
                              testid="copy-delivery-account-digits"
                              label={`Copiar cuenta (${digitsOnly.length} díg.)`}
                              value={digitsOnly}
                            />
                            <CopyBtn
                              testid="copy-delivery-account-formatted"
                              label="Copiar formateada"
                              value={digitsOnly.match(/.{1,4}/g).join(" ")}
                            />
                          </>
                        );
                      }
                      // Crypto wallet — copy address alone (extract via regex)
                      if (open.delivery_method === "crypto") {
                        const wallet = open.delivery_details.match(
                          /(T[1-9A-HJ-NP-Za-km-z]{33}|0x[a-fA-F0-9]{40}|bc1[a-z0-9]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})/
                        );
                        if (wallet) {
                          return (
                            <CopyBtn
                              testid="copy-delivery-wallet"
                              label={`Copiar wallet (${wallet[0].slice(0, 6)}…${wallet[0].slice(-4)})`}
                              value={wallet[0]}
                            />
                          );
                        }
                      }
                      return null;
                    })()}
                  </div>
                </div>
              )}
              {open.proof_image && (
                <div>
                  <div className="micro-label text-neutral-500 mb-2">Comprobante del cliente (lo que envió)</div>
                  <img src={open.proof_image} alt="proof" className="w-full max-h-96 object-contain border border-white/10" />
                </div>
              )}

              {/* Payout evidence — staff uploads the screenshot of the payment made TO the client.
              {/* iter55.19e — For crypto orders operator opted to require ONLY
                  the tx hash (no screenshot upload). For transfer we still
                  require the bank receipt. Cash + accumulate keep no artefact. */}
              {open.delivery_method !== "cash" && open.delivery_method !== "accumulate" && (
                <div className="border-t border-white/5 pt-4">
                  <div className="micro-label text-[#8B5CF6] mb-2">
                    {open.delivery_method === "crypto"
                      ? "Hash de transacción on-chain"
                      : "Comprobante del pago AL cliente (transferencia)"}
                  </div>
                  <p className="text-[0.7rem] text-neutral-500 mb-3 leading-relaxed">
                    {open.delivery_method === "transfer"
                      ? "Adjunta la captura del banco mostrando que enviaste los " + open.to_code + " al cliente. Es obligatorio antes de marcar como completada."
                      : "Pega solo el hash de la transacción — con eso es suficiente, no hace falta subir captura. El cliente podrá verificarla en el explorer on-chain."}
                  </p>
                  <div className="space-y-2">
                    {open.delivery_method === "crypto" && (
                      <Input
                        data-testid="order-payout-tx-hash"
                        value={payoutHash}
                        onChange={(e) => setPayoutHash(e.target.value)}
                        placeholder="Hash de transacción (TXID)"
                        className="rounded-none bg-[#0a0a0a] border-white/10 h-11 font-mono text-xs"
                      />
                    )}
                    {open.delivery_method === "transfer" && (
                      <>
                        <div className="flex items-center gap-2">
                          <label className="flex-1 flex items-center gap-2 cursor-pointer bg-[#0a0a0a] border border-white/10 hover:border-[#8B5CF6]/40 px-3 py-2 text-xs text-neutral-300">
                            <Upload className="w-3.5 h-3.5 text-[#8B5CF6]" />
                            <span>{payoutProof ? "Cambiar captura" : "Subir captura (PNG/JPG, máx 4MB)"}</span>
                            <input
                              type="file"
                              accept="image/*"
                              onChange={handlePayoutUpload}
                              data-testid="order-payout-proof-upload"
                              className="hidden"
                            />
                          </label>
                          {payoutProof && (
                            <button
                              type="button"
                              data-testid="order-payout-proof-clear"
                              onClick={() => setPayoutProof("")}
                              className="text-[0.7rem] text-neutral-500 hover:text-[#EF4444] underline underline-offset-4"
                            >
                              quitar
                            </button>
                          )}
                        </div>
                        {payoutProof && (
                          <img
                            src={payoutProof}
                            alt="Captura del pago al cliente"
                            data-testid="order-payout-proof-preview"
                            className="w-full max-h-72 object-contain border border-[#8B5CF6]/30"
                          />
                        )}
                      </>
                    )}
                  </div>
                </div>
              )}

              <Textarea value={note} onChange={e => setNote(e.target.value)} placeholder="Nota administrativa..." rows={2} className="rounded-none bg-[#0a0a0a] border-white/10" />
              <div className="grid grid-cols-3 gap-2">
                <Button
                  data-testid="approve-order"
                  onClick={() => updateStatus("approved")}
                  disabled={!isAdmin && (open?.status === "approved" || open?.status === "completed" || open?.status === "rejected")}
                  className="bg-[#22C55E] hover:bg-[#16A34A] text-black rounded-none disabled:opacity-40"
                >
                  Confirmar
                </Button>
                <Button
                  data-testid="complete-order"
                  onClick={() => updateStatus("completed")}
                  disabled={!isAdmin && (open?.status === "completed" || open?.status === "rejected")}
                  className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none disabled:opacity-40"
                >
                  Completar
                </Button>
                <Button
                  data-testid="reject-order"
                  onClick={() => updateStatus("rejected")}
                  disabled={!isAdmin && (open?.status === "approved" || open?.status === "completed" || open?.status === "rejected")}
                  className="bg-[#EF4444] hover:bg-[#DC2626] text-white rounded-none disabled:opacity-40"
                >
                  Rechazar
                </Button>
              </div>
              {!isAdmin && (open?.status === "approved" || open?.status === "completed") && (
                <p className="text-[0.65rem] text-neutral-500 italic">
                  Esta orden ya fue {STATUS_LABELS[open.status]}. Sólo un admin puede revertir su estado.
                </p>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      <TotpPromptDialog
        open={!!pendingStatus}
        title="Confirmar acción de alto riesgo"
        description="Esta orden requiere doble aprobación. Ingresa tu código 2FA para confirmar."
        onConfirm={(code) => updateStatus(pendingStatus, code)}
        onCancel={() => setPendingStatus(null)}
      />
    </div>
  );
}
