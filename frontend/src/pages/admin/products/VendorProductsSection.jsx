import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import TotpPromptDialog from "@/components/TotpPromptDialog";
import { Store, Check, X, Percent } from "lucide-react";
import { toast } from "sonner";

// iter217 — Cola de aprobación de productos publicados por vendedores VIP +
// editor de la comisión de la empresa (solo admin, con 2FA).
const STATUS_BADGE = {
  pending: "bg-amber-500/10 text-amber-300 border-amber-500/30",
  approved: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  rejected: "bg-red-500/10 text-red-400 border-red-500/30",
};

export default function VendorProductsSection() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [items, setItems] = useState([]);
  const [statusFilter, setStatusFilter] = useState("pending");
  const [rejecting, setRejecting] = useState(null);
  const [reason, setReason] = useState("");
  const [pct, setPct] = useState("");
  const [totpOpen, setTotpOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    const params = statusFilter === "all" ? {} : { status: statusFilter };
    axios.get(`${API}/admin/vendor-products`, { params, withCredentials: true })
      .then((r) => setItems(r.data)).catch(() => {});
  }, [statusFilter]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    axios.get(`${API}/admin/settings`, { withCredentials: true })
      .then((r) => setPct(String(r.data.vendor_commission_pct ?? 5)))
      .catch(() => {});
  }, []);

  const approve = async (p) => {
    try {
      await axios.post(`${API}/admin/vendor-products/${p.id}/approve`, {}, { withCredentials: true });
      toast.success(t("vendorProducts.approvedToast"));
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
  };

  const reject = async () => {
    if (!rejecting) return;
    setBusy(true);
    try {
      await axios.post(`${API}/admin/vendor-products/${rejecting.id}/reject`, { reason }, { withCredentials: true });
      toast.success(t("vendorProducts.rejectedToast"));
      setRejecting(null); setReason("");
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
    finally { setBusy(false); }
  };

  const saveCommission = async (totpCode) => {
    setBusy(true);
    try {
      await axios.put(`${API}/admin/settings`, {
        vendor_commission_pct: parseFloat(pct),
        totp_code: totpCode,
      }, { withCredentials: true });
      toast.success(t("vendorProducts.commissionSaved"));
      setTotpOpen(false);
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
    finally { setBusy(false); }
  };

  const statusTabs = ["pending", "approved", "rejected", "all"];

  return (
    <div className="mt-12" data-testid="vendor-products-section">
      <div className="flex items-end justify-between flex-wrap gap-4 mb-4">
        <h2 className="font-display text-xl flex items-center gap-2">
          <Store className="w-5 h-5 text-amber-300" /> {t("vendorProducts.title")}
        </h2>
        {isAdmin && (
          <div className="flex items-end gap-2">
            <div>
              <Label className="micro-label text-neutral-500 flex items-center gap-1">
                <Percent className="w-3 h-3" /> {t("vendorProducts.commissionLabel")}
              </Label>
              <Input data-testid="vendor-commission-input" type="number" step="any" min="0" max="100" value={pct}
                onChange={(e) => setPct(e.target.value)}
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono h-9 w-[110px]" />
            </div>
            <Button data-testid="vendor-commission-save" onClick={() => setTotpOpen(true)}
              className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none h-9">
              {t("vendorProducts.commissionSave")}
            </Button>
          </div>
        )}
      </div>

      <div className="flex gap-2 mb-4 flex-wrap">
        {statusTabs.map((s) => (
          <button key={s} data-testid={`vendor-filter-${s}`} onClick={() => setStatusFilter(s)}
            className={`px-3 py-1.5 text-xs uppercase tracking-wider border transition-colors ${
              statusFilter === s ? "border-amber-400 text-amber-300 bg-amber-500/10" : "border-white/10 text-neutral-400 hover:text-white"
            }`}>
            {t(`vendorProducts.tabs.${s}`)}
          </button>
        ))}
      </div>

      {items.length === 0 && (
        <p className="text-neutral-500 text-sm py-6 text-center tactile-card" data-testid="vendor-products-empty">{t("vendorProducts.empty")}</p>
      )}
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map((p) => (
          <div key={p.id} className="tactile-card overflow-hidden" data-testid={`vendor-product-${p.id}`}>
            <div className="aspect-video bg-[#0a0a0a]">{p.image_url && <img src={p.image_url} alt={p.name} className="w-full h-full object-cover" />}</div>
            <div className="p-4">
              <div className="flex items-center justify-between gap-2">
                <div className="micro-label text-neutral-500">{p.category}</div>
                <span className={`text-[0.6rem] uppercase tracking-wider px-2 py-0.5 border ${STATUS_BADGE[p.approval_status] || ""}`}>
                  {t(`vendorProducts.status.${p.approval_status}`)}
                </span>
              </div>
              <h3 className="font-display text-lg mt-1">{p.name}</h3>
              <div className="text-xs text-amber-300 mt-1">{t("vendorProducts.vendor")}: {p.owner_name}</div>
              {p.approval_status === "rejected" && p.rejection_reason && (
                <div className="text-xs text-red-400 mt-1">{p.rejection_reason}</div>
              )}
              <div className="flex items-center justify-between mt-3">
                <div>
                  <div className="font-display text-xl text-[#8B5CF6]">{p.price_usd} <span className="text-xs text-neutral-500">USDT</span></div>
                  <div className="text-xs text-neutral-500">Stock {p.stock}</div>
                </div>
                <div className="flex gap-2">
                  {p.approval_status !== "approved" && (
                    <Button size="sm" data-testid={`vendor-approve-${p.id}`} onClick={() => approve(p)}
                      className="bg-emerald-600 hover:bg-emerald-500 text-white rounded-none h-8">
                      <Check className="w-4 h-4 mr-1" /> {t("vendorProducts.approve")}
                    </Button>
                  )}
                  {p.approval_status !== "rejected" && (
                    <Button size="sm" variant="outline" data-testid={`vendor-reject-${p.id}`}
                      onClick={() => { setRejecting(p); setReason(""); }}
                      className="border-red-500/40 text-red-400 hover:bg-red-500/10 rounded-none h-8">
                      <X className="w-4 h-4 mr-1" /> {t("vendorProducts.reject")}
                    </Button>
                  )}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      <Dialog open={!!rejecting} onOpenChange={() => setRejecting(null)}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-display">{t("vendorProducts.rejectTitle")}: {rejecting?.name}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div>
              <Label className="micro-label text-neutral-500">{t("vendorProducts.rejectReason")}</Label>
              <Input data-testid="vendor-reject-reason" value={reason} onChange={(e) => setReason(e.target.value)} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <Button data-testid="vendor-reject-confirm" onClick={reject} disabled={busy} className="w-full bg-red-600 hover:bg-red-500 text-white rounded-none">
              {t("vendorProducts.reject")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <TotpPromptDialog
        open={totpOpen}
        busy={busy}
        title={t("vendorProducts.totpTitle")}
        description={t("vendorProducts.totpDesc")}
        onCancel={() => setTotpOpen(false)}
        onConfirm={saveCommission}
      />
    </div>
  );
}
