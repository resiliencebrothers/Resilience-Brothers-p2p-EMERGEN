import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { Boxes, Package } from "lucide-react";
import BalanceConverterCard from "@/components/BalanceConverterCard";
import VerificationGateBanner from "@/components/VerificationGateBanner";
import { extractDetailMessage } from "@/utils/apiErrors";

export default function MarketplaceView() {
  const { refresh } = useAuth();
  const { t } = useTranslation();
  const [products, setProducts] = useState([]);
  const [open, setOpen] = useState(null);
  const [qty, setQty] = useState(1);
  const [addr, setAddr] = useState("");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState([]);
  // iter50 — multi-currency VIP balance moved into the shared
  // <BalanceConverterCard /> component which fetches its own state.
  const [balances, setBalances] = useState({ balances: [], total_usdt: 0 });

  const loadBalances = () =>
    axios.get(`${API}/vip/balances`, { withCredentials: true })
      .then((r) => setBalances(r.data))
      .catch(() => {});

  useEffect(() => {
    axios.get(`${API}/products`).then(r => setProducts(r.data));
    axios.get(`${API}/vip/redemptions/mine`, { withCredentials: true }).then(r => setHistory(r.data)).catch(() => {});
    loadBalances();
  }, []);

  const redeem = async () => {
    if (!open) return;
    if (qty < 1) return toast.error(t("marketplace.invalidQty"));
    if (!addr) return toast.error(t("marketplace.addressRequired"));
    setBusy(true);
    try {
      await axios.post(`${API}/vip/redeem`, { product_id: open.id, quantity: qty, delivery_address: addr }, { withCredentials: true });
      toast.success(t("marketplace.successPending"));
      setOpen(null); setQty(1); setAddr("");
      await refresh();
      const p = await axios.get(`${API}/products`); setProducts(p.data);
      const h = await axios.get(`${API}/vip/redemptions/mine`, { withCredentials: true }); setHistory(h.data);
      await loadBalances();
    } catch (e) {
      toast.error(extractDetailMessage(e, "Error al canjear"));
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-8" data-testid="marketplace-view">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="micro-label text-[#8B5CF6] mb-2">{t("marketplace.eyebrow")}</div>
          <h1 className="font-display text-3xl flex items-center gap-3"><Boxes className="w-8 h-8 text-[#8B5CF6]" /> {t("marketplace.titleFull")}</h1>
        </div>
        <div className="tactile-card px-5 py-3 min-w-[180px]" data-testid="marketplace-balance-widget">
          <div className="micro-label text-neutral-500">{t("marketplace.balanceLabel")}</div>
          <div
            className="font-display text-2xl text-[#8B5CF6]"
            data-testid="marketplace-balance-usdt"
          >
            {(balances.total_usdt || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
            <span className="text-sm text-neutral-400 ml-1">USDT</span>
          </div>
        </div>
      </div>

      {/* iter55.36o — full-verification gate applies to both the converter
          widget above and the redeem grid below. Rendered inline so the
          balance summary at the top remains visible even when locked. */}
      <VerificationGateBanner action="redeemAndConvert" />

      {/* iter50 — shared converter widget (also rendered on the main Dashboard) */}
      <BalanceConverterCard onConverted={loadBalances} />

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {products.length === 0 && <p className="text-neutral-500 col-span-full text-center py-12">{t("marketplace.empty")}</p>}
        {products.map(p => (
          <div key={p.id} className="tactile-card overflow-hidden flex flex-col">
            <div className="aspect-video bg-[#0a0a0a] overflow-hidden">
              {p.image_url ? (
                <img src={p.image_url} alt={p.name} className="w-full h-full object-cover" />
              ) : (
                <div className="w-full h-full flex items-center justify-center">
                  <Package className="w-12 h-12 text-neutral-700" />
                </div>
              )}
            </div>
            <div className="p-5 flex-1 flex flex-col">
              <div className="micro-label text-neutral-500 mb-1">{p.category}</div>
              <h3 className="font-display text-lg mb-2">{p.name}</h3>
              <p className="text-sm text-neutral-400 mb-4 line-clamp-2">{p.description}</p>
              <div className="mt-auto flex items-center justify-between">
                <div>
                  <div className="font-display text-xl text-[#8B5CF6]">${p.price_usd}</div>
                  <div className="text-xs text-neutral-500">{t("marketplace.stock")} {p.stock}</div>
                </div>
                <Button data-testid={`redeem-${p.id}`} onClick={() => setOpen(p)} disabled={p.stock === 0} className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-semibold rounded-none">
                  {t("marketplace.redeem")}
                </Button>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div>
        <h2 className="font-display text-xl mb-4">{t("marketplace.myRedemptions")}</h2>
        <div className="tactile-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="border-b border-white/10 bg-[#0a0a0a]">
              <tr className="text-left">
                <th className="px-4 py-3 micro-label text-neutral-500">{t("marketplace.columnProduct")}</th>
                <th className="px-4 py-3 micro-label text-neutral-500">{t("marketplace.columnQty")}</th>
                <th className="px-4 py-3 micro-label text-neutral-500">{t("marketplace.columnTotal")}</th>
                <th className="px-4 py-3 micro-label text-neutral-500">{t("marketplace.columnStatus")}</th>
                <th className="px-4 py-3 micro-label text-neutral-500">{t("marketplace.columnDate")}</th>
              </tr>
            </thead>
            <tbody>
              {history.length === 0 && <tr><td colSpan="5" className="text-center text-neutral-500 py-8">Sin canjes.</td></tr>}
              {history.map(h => (
                <tr key={h.id} className="border-b border-white/5">
                  <td className="px-4 py-3">{h.product_name}</td>
                  <td className="px-4 py-3 font-mono">{h.quantity}</td>
                  <td className="px-4 py-3 font-mono text-[#8B5CF6]">${h.total_usd}</td>
                  <td className="px-4 py-3"><span className="text-xs uppercase tracking-wider">{h.status}</span></td>
                  <td className="px-4 py-3 text-xs text-neutral-500">{new Date(h.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <Dialog open={!!open} onOpenChange={() => setOpen(null)}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-display">{t("marketplace.redeem")}: {open?.name}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label className="micro-label text-neutral-500">{t("marketplace.redeemQuantity")}</Label>
              <Input data-testid="redeem-qty" type="number" min="1" value={qty} onChange={e => setQty(parseInt(e.target.value) || 1)} className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("marketplace.redeemAddressLabel")}</Label>
              <Textarea data-testid="redeem-addr" value={addr} onChange={e => setAddr(e.target.value)} rows={3} className="rounded-none mt-2 bg-[#0a0a0a] border-white/10" />
            </div>
            <div className="border border-white/10 p-3 font-mono text-sm flex justify-between">
              <span className="text-neutral-500">{t("marketplace.columnTotal")}:</span>
              <span className="text-[#8B5CF6]">${(open?.price_usd * qty || 0).toFixed(2)}</span>
            </div>
            <Button data-testid="confirm-redeem" onClick={redeem} disabled={busy} className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-12">
              {busy ? t("marketplace.processing") : t("marketplace.confirmRedeem")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
