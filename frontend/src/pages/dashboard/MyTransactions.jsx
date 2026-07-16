import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation();
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
      const totalCount = Number(r.headers["x-total-count"]);
      setTotal(Number.isFinite(totalCount) ? totalCount : r.data.items.length);
    } catch (e) {
      toast.error(e.response?.data?.detail || t("myTransactions.loadError"));
    } finally {
      setLoading(false);
    }
  }, [direction, currency, since, until, minAmount, maxAmount, page, t]);
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
      a.download = `${t("myTransactions.exportFilename")}_${ts}.${kind}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(blobUrl);
      toast.success(t("myTransactions.exportedToast", { kind: kind.toUpperCase() }));
    } catch (e) {
      toast.error(t("myTransactions.exportError", { kind: kind.toUpperCase() }));
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
        <div className="micro-label text-[#8B5CF6] mb-2 flex items-center gap-2">
          <Receipt className="w-3.5 h-3.5" /> {t("myTransactions.breadcrumb")}
        </div>
        <h1 className="font-display text-3xl">{t("myTransactions.title")}</h1>
        <p className="text-neutral-500 text-sm mt-1">
          {t("myTransactions.subtitle")}
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
                    <ArrowDown className="w-3 h-3 text-[#22C55E]" /> {t("myTransactions.in")}
                  </span>
                  <span className="font-mono text-[#22C55E]">+{row.in.toLocaleString()}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-neutral-400 flex items-center gap-1">
                    <ArrowUp className="w-3 h-3 text-[#EF4444]" /> {t("myTransactions.out")}
                  </span>
                  <span className="font-mono text-[#EF4444]">-{row.out.toLocaleString()}</span>
                </div>
                <div className="flex justify-between border-t border-white/5 pt-1 mt-1">
                  <span className="text-neutral-300 text-xs">{t("myTransactions.net")}</span>
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
            <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.filters.direction")}</div>
            <Select value={direction} onValueChange={setDirection}>
              <SelectTrigger data-testid="my-tx-direction" className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                <SelectItem value="all">{t("myTransactions.filters.all")}</SelectItem>
                <SelectItem value="in">{t("myTransactions.filters.onlyIn")}</SelectItem>
                <SelectItem value="out">{t("myTransactions.filters.onlyOut")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.filters.currency")}</div>
            <Select value={currency || "all"} onValueChange={(v) => setCurrency(v === "all" ? "" : v)}>
              <SelectTrigger data-testid="my-tx-currency" className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-36">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                <SelectItem value="all">{t("myTransactions.filters.all")}</SelectItem>
                {currencies.map((c) => (
                  <SelectItem key={c.code} value={c.code}>{c.code}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.filters.since")}</div>
            <Input type="date" data-testid="my-tx-since" value={since} onChange={(e) => setSince(e.target.value)}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-40 font-mono text-xs" />
          </div>
          <div>
            <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.filters.until")}</div>
            <Input type="date" data-testid="my-tx-until" value={until} onChange={(e) => setUntil(e.target.value)}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-40 font-mono text-xs" />
          </div>
          <div>
            <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.filters.min")}</div>
            <Input type="number" min="0" step="0.01" data-testid="my-tx-min" value={minAmount}
              onChange={(e) => setMinAmount(e.target.value)} placeholder="0"
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-24 font-mono text-xs" />
          </div>
          <div>
            <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.filters.max")}</div>
            <Input type="number" min="0" step="0.01" data-testid="my-tx-max" value={maxAmount}
              onChange={(e) => setMaxAmount(e.target.value)} placeholder="∞"
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-24 font-mono text-xs" />
          </div>
          {hasFilters && (
            <button data-testid="my-tx-clear" onClick={clearFilters}
              className="text-xs text-neutral-500 hover:text-[#8B5CF6] underline underline-offset-4 h-10">
              {t("myTransactions.filters.clear")}
            </button>
          )}
        </div>
        <div className="flex gap-2">
          <Button data-testid="my-tx-export-csv" onClick={() => downloadExport("csv")}
            className="rounded-none bg-transparent border border-white/15 hover:border-[#8B5CF6]/60 hover:bg-[#8B5CF6]/5 text-white h-10 px-4 font-mono text-xs uppercase tracking-wider">
            <Download className="w-3.5 h-3.5 mr-2" /> CSV
          </Button>
          <Button data-testid="my-tx-export-pdf" onClick={() => downloadExport("pdf")}
            className="rounded-none bg-[#8B5CF6] hover:bg-[#8B5CF6]/90 text-white h-10 px-4 font-mono text-xs uppercase tracking-wider font-bold">
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
                <th className="px-3 py-3 micro-label text-neutral-500">{t("myTransactions.table.date")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500">{t("myTransactions.table.type")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500">{t("myTransactions.table.currency")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500 text-right">{t("myTransactions.table.amount")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500">{t("myTransactions.table.holder")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500">{t("myTransactions.table.method")}</th>
                <th className="px-3 py-3 micro-label text-neutral-500">{t("myTransactions.table.status")}</th>
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan="7" className="text-center text-neutral-500 py-8">{t("myTransactions.table.loading")}</td></tr>}
              {!loading && items.length === 0 && (
                <tr><td colSpan="7" className="text-center text-neutral-500 py-8">
                  {hasFilters ? t("myTransactions.table.emptyFiltered") : t("myTransactions.table.empty")}
                </td></tr>
              )}
              {items.map((it) => (
                <tr key={`${it.ref_type}-${it.ref_id}`}
                  data-testid={`my-tx-row-${it.ref_id}`}
                  onClick={() => setSelected(it)}
                  className="border-b border-white/5 hover:bg-[#8B5CF6]/5 cursor-pointer transition-colors"
                >
                  <td className="px-3 py-2 font-mono text-xs text-neutral-400">{new Date(it.created_at).toLocaleString()}</td>
                  <td className="px-3 py-2">
                    {it.direction === "in" ? (
                      <span className="inline-flex items-center gap-1 text-[#22C55E] text-xs font-bold uppercase">
                        <ArrowDown className="w-3 h-3" /> {t("myTransactions.table.in")}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[#EF4444] text-xs font-bold uppercase">
                        <ArrowUp className="w-3 h-3" /> {t("myTransactions.table.out")}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 font-mono text-[#8B5CF6]">{it.currency}</td>
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
        <DialogContent data-testid="my-tx-modal" className="bg-[#0c0c0c] border border-white/10 text-white max-w-2xl rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-white">
              <Receipt className="w-5 h-5 text-[#8B5CF6]" />
              {t("myTransactions.detail.title")}
              {selected?.direction === "in" ? (
                <span className="ml-2 text-[#22C55E] text-xs font-bold uppercase flex items-center gap-1">
                  <ArrowDown className="w-3 h-3" /> {t("myTransactions.table.in")}
                </span>
              ) : (
                <span className="ml-2 text-[#EF4444] text-xs font-bold uppercase flex items-center gap-1">
                  <ArrowUp className="w-3 h-3" /> {t("myTransactions.table.out")}
                </span>
              )}
            </DialogTitle>
          </DialogHeader>
          {selected && (
            <div className="space-y-4 text-sm">
              <div className="grid grid-cols-2 gap-3 border border-white/5 p-4 bg-[#0a0a0a]">
                <div>
                  <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.detail.currency")}</div>
                  <div className="font-mono text-[#8B5CF6] text-lg">{selected.currency}</div>
                </div>
                <div>
                  <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.detail.amount")}</div>
                  <div className="font-mono text-xl">{selected.amount.toLocaleString()}</div>
                </div>
                <div>
                  <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.detail.holder")}</div>
                  <div className="font-medium">{selected.holder_name || "—"}</div>
                </div>
                <div>
                  <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.detail.method")}</div>
                  <div className="uppercase text-xs">{selected.method}</div>
                </div>
                <div>
                  <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.detail.status")}</div>
                  <div className="uppercase text-xs text-[#22C55E]">{selected.status}</div>
                </div>
                <div>
                  <div className="micro-label text-neutral-500 mb-1">{t("myTransactions.detail.date")}</div>
                  <div className="font-mono text-xs">{new Date(selected.created_at).toLocaleString()}</div>
                </div>
                <div className="col-span-2">
                  <div className="micro-label text-neutral-500 mb-1">
                    {selected.ref_type === "withdrawal" ? t("myTransactions.detail.withdrawalId") : t("myTransactions.detail.orderId")}
                  </div>
                  <div className="font-mono text-xs text-neutral-400">{selected.ref_id}</div>
                </div>
              </div>
              {selected.delivery_details && (
                <div className="border border-white/5 p-4 bg-[#0a0a0a]">
                  <div className="micro-label text-neutral-500 mb-2">
                    {selected.direction === "in" ? t("myTransactions.detail.senderData") : t("myTransactions.detail.recipientData")}
                  </div>
                  <div className="text-sm whitespace-pre-wrap font-mono text-neutral-300">{selected.delivery_details}</div>
                </div>
              )}
              {(selected.direction === "in" || selected.ref_type === "order_payout") && selected.proof_image && selected.proof_image.trim() && (
                <div>
                  <div className="micro-label text-neutral-500 mb-2">
                    {selected.ref_type === "order_payout" ? t("myTransactions.detail.payoutProof") : t("myTransactions.detail.proof")}
                  </div>
                  <a href={selected.proof_image} target="_blank" rel="noreferrer" className="block border border-white/10 bg-[#0a0a0a] p-2">
                    <img src={selected.proof_image} alt={t("myTransactions.detail.proof")} className="w-full max-h-96 object-contain bg-black"
                      onError={(e) => { e.currentTarget.style.display = "none"; }} />
                  </a>
                </div>
              )}
              {selected.direction === "out" && selected.ref_type !== "order_payout" && (
                <div className="border border-dashed border-white/10 p-4 text-center text-xs text-neutral-500">
                  <X className="w-4 h-4 inline mr-1" /> {t("myTransactions.detail.outflowsHaveNoProof")}
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
