import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Pagination } from "@/components/Pagination";
import { Banknote, ArrowDown, ArrowUp, Download, FileText } from "lucide-react";

const PAGE_SIZE = 50;

export default function AdminTransactions() {
  const [items, setItems] = useState([]);
  const [totals, setTotals] = useState({ by_currency: {}, total_count: 0 });
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(false);

  // filters
  const [direction, setDirection] = useState("all");
  const [currency, setCurrency] = useState("");
  const [holder, setHolder] = useState("");
  const [holderInput, setHolderInput] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");

  // currencies for dropdown
  const [currencies, setCurrencies] = useState([]);

  useEffect(() => {
    axios.get(`${API}/currencies`, { withCredentials: true })
      .then((r) => setCurrencies(r.data.filter((c) => c.is_active)))
      .catch(() => {});
  }, []);

  // debounce holder search
  useEffect(() => {
    const t = setTimeout(() => setHolder(holderInput.trim()), 300);
    return () => clearTimeout(t);
  }, [holderInput]);

  // reset page on filter change
  useEffect(() => {
    setPage(0);
  }, [direction, currency, holder, since, until]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit: PAGE_SIZE, offset: page * PAGE_SIZE };
      if (direction !== "all") params.direction = direction;
      if (currency) params.currency = currency;
      if (holder) params.holder = holder;
      if (since) params.since = since;
      if (until) params.until = until;
      const r = await axios.get(`${API}/admin/transactions`, { params, withCredentials: true });
      setItems(r.data.items);
      setTotals(r.data.totals);
      const t = Number(r.headers["x-total-count"]);
      setTotal(Number.isFinite(t) ? t : r.data.items.length);
    } catch (e) {
      toast.error("Error al cargar transacciones");
    } finally {
      setLoading(false);
    }
  }, [direction, currency, holder, since, until, page]);
  useEffect(() => { load(); }, [load]);

  const downloadExport = async (kind) => {
    try {
      const params = new URLSearchParams();
      if (direction !== "all") params.set("direction", direction);
      if (currency) params.set("currency", currency);
      if (holder) params.set("holder", holder);
      if (since) params.set("since", since);
      if (until) params.set("until", until);
      const url = `${API}/admin/transactions/export.${kind}?${params.toString()}`;
      const r = await axios.get(url, { responseType: "blob", withCredentials: true });
      const blobUrl = URL.createObjectURL(new Blob([r.data], { type: r.headers["content-type"] }));
      const a = document.createElement("a");
      a.href = blobUrl;
      const ts = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
      a.download = `transacciones_${ts}.${kind}`;
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
    setHolderInput("");
    setSince("");
    setUntil("");
  };

  const hasFilters = direction !== "all" || currency || holderInput || since || until;
  const totalsByCurrency = totals?.by_currency || {};
  const totalsRows = Object.entries(totalsByCurrency)
    .map(([code, v]) => ({ code, ...v, net: (v.in || 0) - (v.out || 0) }))
    .sort((a, b) => Math.abs(b.net) - Math.abs(a.net));

  return (
    <div data-testid="admin-transactions" className="space-y-5">
      <div className="mb-2">
        <div className="micro-label text-[#EAB308] mb-2 flex items-center gap-2">
          <Banknote className="w-3.5 h-3.5" /> / Contabilidad
        </div>
        <h1 className="font-display text-3xl">Registro de Transacciones</h1>
        <p className="text-neutral-500 text-sm mt-1">
          Entradas (transferencias recibidas) y salidas (retiros pagados) con titular para resguardo y auditoría.
        </p>
      </div>

      {/* Totals summary cards */}
      {totalsRows.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3" data-testid="transactions-totals">
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
              <SelectTrigger data-testid="tx-direction-filter" className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-44">
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
              <SelectTrigger data-testid="tx-currency-filter" className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-36">
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
            <div className="micro-label text-neutral-500 mb-1">Titular (contiene)</div>
            <Input
              data-testid="tx-holder-filter"
              value={holderInput}
              onChange={(e) => setHolderInput(e.target.value)}
              placeholder="ej. juan pérez"
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-60 font-mono text-xs"
            />
          </div>
          <div>
            <div className="micro-label text-neutral-500 mb-1">Desde</div>
            <Input
              type="date"
              data-testid="tx-since-filter"
              value={since}
              onChange={(e) => setSince(e.target.value)}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-40 font-mono text-xs"
            />
          </div>
          <div>
            <div className="micro-label text-neutral-500 mb-1">Hasta</div>
            <Input
              type="date"
              data-testid="tx-until-filter"
              value={until}
              onChange={(e) => setUntil(e.target.value)}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-40 font-mono text-xs"
            />
          </div>
          {hasFilters && (
            <button
              data-testid="tx-clear-filters"
              onClick={clearFilters}
              className="text-xs text-neutral-500 hover:text-[#EAB308] underline underline-offset-4 h-10"
            >
              limpiar filtros
            </button>
          )}
        </div>
        <div className="flex gap-2">
          <Button
            data-testid="tx-export-csv"
            onClick={() => downloadExport("csv")}
            className="rounded-none bg-transparent border border-white/15 hover:border-[#EAB308]/60 hover:bg-[#EAB308]/5 text-white h-10 px-4 font-mono text-xs uppercase tracking-wider"
          >
            <Download className="w-3.5 h-3.5 mr-2" /> CSV
          </Button>
          <Button
            data-testid="tx-export-pdf"
            onClick={() => downloadExport("pdf")}
            className="rounded-none bg-[#EAB308] hover:bg-[#EAB308]/90 text-black h-10 px-4 font-mono text-xs uppercase tracking-wider font-bold"
          >
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
                <th className="px-3 py-3 micro-label text-neutral-500">Titular de cuenta</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Cliente</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Método</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Estado</th>
                <th className="px-3 py-3 micro-label text-neutral-500">Ref</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan="9" className="text-center text-neutral-500 py-8">Cargando...</td></tr>
              )}
              {!loading && items.length === 0 && (
                <tr><td colSpan="9" className="text-center text-neutral-500 py-8">Sin transacciones que mostrar</td></tr>
              )}
              {items.map((it) => (
                <tr key={`${it.ref_type}-${it.ref_id}`} className="border-b border-white/5 hover:bg-white/5">
                  <td className="px-3 py-2 font-mono text-xs text-neutral-400">
                    {new Date(it.created_at).toLocaleString()}
                  </td>
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
                  <td className="px-3 py-2">{it.holder_name || <span className="text-neutral-600">—</span>}</td>
                  <td className="px-3 py-2 text-neutral-400">{it.client_name}</td>
                  <td className="px-3 py-2 text-xs uppercase text-neutral-500">{it.method}</td>
                  <td className="px-3 py-2 text-xs uppercase text-neutral-500">{it.status}</td>
                  <td className="px-3 py-2 font-mono text-xs text-neutral-600">{it.ref_id?.slice(0, 6)}</td>
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
        testidPrefix="tx-pagination"
      />
    </div>
  );
}
