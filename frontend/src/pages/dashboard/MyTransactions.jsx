import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Pagination } from "@/components/Pagination";
import { Receipt, ArrowDown, ArrowUp, Download, FileText, X } from "lucide-react";

const PAGE_SIZE = 50;

export default function MyTransactions() {
  const [items, setItems] = useState([]);
  const [totals, setTotals] = useState({ by_currency: {} });
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(false);

  const [direction, setDirection] = useState("all");
  const [currency, setCurrency] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [minAmount, setMinAmount] = useState("");
  const [maxAmount, setMaxAmount] = useState("");
  const [selected, setSelected] = useState(null);

  const [currencies, setCurrencies] = useState([]);
  useEffect(() => {
    axios.get(`${API}/currencies`, { withCredentials: true })
      .then((r) => setCurrencies(r.data.filter((c) => c.is_active)))
      .catch(() => {});
  }, []);

  useEffect(() => { setPage(0); }, [direction, currency, since, until, minAmount, maxAmount]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit: PAGE_SIZE, offset: page * PAGE_SIZE };
      if (direction !== "all") params.direction = direction;
      if (currency) params.currency = currency;
      if (since) params.since = since;
      if (until) params.until = until;
      if (minAmount !== "") params.min_amount = minAmount;
      if (maxAmount !== "") params.max_amount = maxAmount;
      const r = await axios.get(`${API}/me/transactions`, { params, withCredentials: true });
      setItems(r.data.items);
      setTotals(r.data.totals);
      const t = Number(r.headers["x-total-count"]);
      setTotal(Number.isFinite(t) ? t : r.data.items.length);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error al cargar transacciones");
    } finally {
      setLoading(false);
    }
  }, [direction, currency, since, until, minAmount, maxAmount, page]);
  useEffect(() => { load(); }, [load]);

  const downloadExport = async (kind) => {
    try {
      const params = new URLSearchParams();
      if (direction !== "all") params.set("direction", direction);
      if (currency) params.set("currency", currency);
      if (since) params.set("since", since);
      if (until) params.set("until", until);
      if (minAmount !== "") params.set("min_amount", minAmount);
      if (maxAmount !== "") params.set("max_amount", maxAmount);
      const url = `${API}/me/transactions/export.${kind}?${params.toString()}`;
      const r = await axios.get(url, { responseType: "blob", withCredentials: true });
      const blobUrl = URL.createObjectURL(new Blob([r.data], { type: r.headers["content-type"] }));
      const a = document.createElement("a");
      a.href = blobUrl;
      const ts = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
      a.download = `mis_transacciones_${ts}.${kind}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(blobUrl);
      toast.success(`Exportado (${kind.toUpperCase()})`);
    } catch (e) {
      toast.error(`Error al exportar ${kind.toUpperCase()}`);
    }
  };

  const clearFilters = () => {
    setDirection("all");
    setCurrency("");
    setSince("");
    setUntil("");
    setMinAmount("");
    setMaxAmount("");
  };

  const hasFilters = direction !== "all" || currency || since || until || minAmount !== "" || maxAmount !== "";
  const totalsRows = Object.entries(totals?.by_currency || {})
    .map(([code, v]) => ({ code, ...v, net: (v.in || 0) - (v.out || 0) }))
    .sort((a, b) => Math.abs(b.net) - Math.abs(a.net));

  return (
    <div data-testid="my-transactions" className="space-y-5">
      <div className="mb-2">
        <div className="micro-label text-[#EAB308] mb-2 flex items-center gap-2">
          <Receipt className="w-3.5 h-3.5" /> / Mi Historial
        </div>
        <h1 className="font-display text-3xl">Mis Transacciones</h1>
        <p className="text-neutral-500 text-sm mt-1">
          Registro de tus entradas (transferencias recibidas) y salidas (retiros pagados) con titulares verificados.
        </p>
      </div>

      {totalsRows.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3" data-testid="my-tx-totals">
          {totalsRows.slice(0, 6).map((row) => (
            <div key={row.code} className="tactile-card p-4">
              <div className="micro-label text-neutral-500 mb-1">{row.code}</div>
              <div className="space-y-1 text-sm">
                <div className="flex justify-between">
                  <span className="text-neutral-400 flex items-center gap-1">
                    <ArrowDown className="w-3 h-3 text-[#22C55E]" /> Entradas
                  </span>
                  <span className="font-mono text-[#22C55E]">+{row.in.toLocaleString()}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-neutral-400 flex items-center gap-1">
                    <ArrowUp className="w-3 h-3 text-[#EF4444]" /> Salidas
                  </span>
                  <span className="font-mono text-[#EF4444]">-{row.out.toLocaleString()}</span>
                </div>
                <div className="flex justify-between border-t border-white/5 pt-1 mt-1">
                  <span className="text-neutral-300 text-xs">Neto</span>
                  <span className={`font-mono font-bold ${row.net >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"}`}>
                    {row.net >= 0 ? "+" : ""}{row.net.toLocaleString()}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-end justify-between">
        <div className="flex flex-wrap gap-3 items-end">
          <div>
            <div className="micro-label text-neutral-500 mb-1">Dirección</div>
            <Select value={direction} onValueChange={setDirection}>
              <SelectTrigger data-testid="my-tx-direction" className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-[#141414] border-white/10 text-white rounded-none">
                <SelectItem value="all">Todas</SelectItem>
                <SelectItem value="in">Solo Entradas ↓</SelectItem>
                <SelectItem value="out">Solo Salidas ↑</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <div className="micro-label text-neutral-500 mb-1">Moneda</div>
            <Select value={currency || "all"} onValueChange={(v) => setCurrency(v === "all" ? "" : v)}>
              <SelectTrigger data-testid="my-tx-currency" className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-36">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-[#141414] border-white/10 text-white rounded-none">
                <SelectItem value="all">Todas</SelectItem>
                {currencies.map((c) => (
                  <SelectItem key={c.code} value={c.code}>{c.code}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <div className="micro-label text-neutral-500 mb-1">Desde</div>
            <Input type="date" data-testid="my-tx-since" value={since} onChange={(e) => setSince(e.target.value)}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-40 font-mono text-xs" />
          </div>
          <div>
            <div className="micro-label text-neutral-500 mb-1">Hasta</div>
            <Input type="date" data-testid="my-tx-until" value={until} onChange={(e) => setUntil(e.target.value)}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-40 font-mono text-xs" />
          </div>
          <div>
            <div className="micro-label text-neutral-500 mb-1">Mín.</div>
            <Input type="number" min="0" step="0.01" data-testid="my-tx-min" value={minAmount}
              onChange={(e) => setMinAmount(e.target.value)} placeholder="0"
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-24 font-mono text-xs" />
          </div>
          <div>
            <div className="micro-label text-neutral-500 mb-1">Máx.</div>
            <Input type="number" min="0" step="0.01" data-testid="my-tx-max" value={maxAmount}
              onChange={(e) => setMaxAmount(e.target.value)} placeholder="∞"
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-24 font-mono text-xs" />
          </div>
          {hasFilters && (
            <button data-testid="my-tx-clear" onClick={clearFilters}
              className="text-xs text-neutral-500 hover:text-[#EAB308] underline underline-offset-4 h-10">
              limpiar
            </button>
          )}
        </div>
        <div className="flex gap-2">
          <Button data-testid="my-tx-export-csv" onClick={() => downloadExport("csv")}
            className="rounded-none bg-transparent border border-white/15 hover:border-[#EAB308]/60 hover:bg-[#EAB308]/5 text-white h-10 px-4 font-mono text-xs uppercase tracking-wider">
            <Download className="w-3.5 h-3.5 mr-2" /> CSV
          </Button>
          <Button data-testid="my-tx-export-pdf" onClick={() => downloadExport("pdf")}
            className="rounded-none bg-[#EAB308] hover:bg-[#EAB308]/90 text-black h-10 px-4 font-mono text-xs uppercase tracking-wider font-bold">
            <FileText className="w-3.5 h-3.5 mr-2" /> PDF
          </Button>
        </div>
      </div>

      {/* Table */}
      <div className="tactile-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-white/10 bg-[#0a0a0a]">
              <tr className="text-left">
                <th className="px-3 py-3 micro-label text-neutral-500">Fecha</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Tipo</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Moneda</th>
                <th className="px-3 py-3 micro-label text-neutral-500 text-right">Monto</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Titular</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Método</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Estado</th>
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan="7" className="text-center text-neutral-500 py-8">Cargando...</td></tr>}
              {!loading && items.length === 0 && (
                <tr><td colSpan="7" className="text-center text-neutral-500 py-8">
                  {hasFilters ? "Sin resultados para los filtros aplicados" : "Aún no tienes transacciones registradas"}
                </td></tr>
              )}
              {items.map((it) => (
                <tr key={`${it.ref_type}-${it.ref_id}`}
                  data-testid={`my-tx-row-${it.ref_id}`}
                  onClick={() => setSelected(it)}
                  className="border-b border-white/5 hover:bg-[#EAB308]/5 cursor-pointer transition-colors"
                >
                  <td className="px-3 py-2 font-mono text-xs text-neutral-400">{new Date(it.created_at).toLocaleString()}</td>
                  <td className="px-3 py-2">
                    {it.direction === "in" ? (
                      <span className="inline-flex items-center gap-1 text-[#22C55E] text-xs font-bold uppercase">
                        <ArrowDown className="w-3 h-3" /> Entrada
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[#EF4444] text-xs font-bold uppercase">
                        <ArrowUp className="w-3 h-3" /> Salida
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 font-mono text-[#EAB308]">{it.currency}</td>
                  <td className="px-3 py-2 font-mono text-right">{it.amount.toLocaleString()}</td>
                  <td className="px-3 py-2">{it.holder_name || "—"}</td>
                  <td className="px-3 py-2 text-xs uppercase text-neutral-500">{it.method}</td>
                  <td className="px-3 py-2 text-xs uppercase text-neutral-500">{it.status}</td>
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
        testidPrefix="my-tx-pagination"
      />

      {/* Detail modal */}
      <Dialog open={!!selected} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent data-testid="my-tx-modal" className="bg-[#0c0c0c] border border-white/10 text-white max-w-2xl rounded-none">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-white">
              <Receipt className="w-5 h-5 text-[#EAB308]" />
              Detalle
              {selected?.direction === "in" ? (
                <span className="ml-2 text-[#22C55E] text-xs font-bold uppercase flex items-center gap-1">
                  <ArrowDown className="w-3 h-3" /> Entrada
                </span>
              ) : (
                <span className="ml-2 text-[#EF4444] text-xs font-bold uppercase flex items-center gap-1">
                  <ArrowUp className="w-3 h-3" /> Salida
                </span>
              )}
            </DialogTitle>
          </DialogHeader>
          {selected && (
            <div className="space-y-4 text-sm">
              <div className="grid grid-cols-2 gap-3 border border-white/5 p-4 bg-[#0a0a0a]">
                <div>
                  <div className="micro-label text-neutral-500 mb-1">Moneda</div>
                  <div className="font-mono text-[#EAB308] text-lg">{selected.currency}</div>
                </div>
                <div>
                  <div className="micro-label text-neutral-500 mb-1">Monto</div>
                  <div className="font-mono text-xl">{selected.amount.toLocaleString()}</div>
                </div>
                <div>
                  <div className="micro-label text-neutral-500 mb-1">Titular</div>
                  <div className="font-medium">{selected.holder_name || "—"}</div>
                </div>
                <div>
                  <div className="micro-label text-neutral-500 mb-1">Método</div>
                  <div className="uppercase text-xs">{selected.method}</div>
                </div>
                <div>
                  <div className="micro-label text-neutral-500 mb-1">Estado</div>
                  <div className="uppercase text-xs text-[#22C55E]">{selected.status}</div>
                </div>
                <div>
                  <div className="micro-label text-neutral-500 mb-1">Fecha</div>
                  <div className="font-mono text-xs">{new Date(selected.created_at).toLocaleString()}</div>
                </div>
                <div className="col-span-2">
                  <div className="micro-label text-neutral-500 mb-1">
                    {selected.ref_type === "withdrawal" ? "ID Retiro" : "ID Orden"}
                  </div>
                  <div className="font-mono text-xs text-neutral-400">{selected.ref_id}</div>
                </div>
              </div>
              {selected.delivery_details && (
                <div className="border border-white/5 p-4 bg-[#0a0a0a]">
                  <div className="micro-label text-neutral-500 mb-2">
                    {selected.direction === "in" ? "Datos del envío" : "Datos del beneficiario"}
                  </div>
                  <div className="text-sm whitespace-pre-wrap font-mono text-neutral-300">{selected.delivery_details}</div>
                </div>
              )}
              {(selected.direction === "in" || selected.ref_type === "order_payout") && selected.proof_image && (
                <div>
                  <div className="micro-label text-neutral-500 mb-2">
                    {selected.ref_type === "order_payout" ? "Comprobante del pago recibido" : "Comprobante"}
                  </div>
                  <a href={selected.proof_image} target="_blank" rel="noreferrer" className="block border border-white/10 bg-[#0a0a0a] p-2">
                    <img src={selected.proof_image} alt="Comprobante" className="w-full max-h-96 object-contain bg-black"
                      onError={(e) => { e.currentTarget.style.display = "none"; }} />
                  </a>
                </div>
              )}
              {selected.direction === "out" && selected.ref_type !== "order_payout" && (
                <div className="border border-dashed border-white/10 p-4 text-center text-xs text-neutral-500">
                  <X className="w-4 h-4 inline mr-1" /> Las salidas no incluyen comprobante de transferencia entrante.
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
