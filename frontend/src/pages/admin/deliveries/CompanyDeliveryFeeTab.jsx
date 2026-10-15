import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { Truck, Save, Percent } from "lucide-react";

// Panel admin — tarifa fija de mensajería Empresa (company_delivery_fee_usdt)
// y vista del reparto mensajero/Resilience. Editable con permiso de Mensajería.
export default function CompanyDeliveryFeeTab() {
  const { t } = useTranslation();
  const [cfg, setCfg] = useState(null);
  const [fee, setFee] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () =>
    axios.get(`${API}/admin/company-delivery-fee`, { withCredentials: true })
      .then((r) => { setCfg(r.data); setFee(String(r.data.fee_usdt ?? 0)); })
      .catch(() => toast.error(t("admin.deliveries.companyFee.loadError")));

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    const val = parseFloat(fee);
    if (isNaN(val) || val < 0) return toast.error(t("admin.deliveries.companyFee.invalid"));
    setBusy(true);
    try {
      const r = await axios.put(`${API}/admin/company-delivery-fee`,
        { fee_usdt: val }, { withCredentials: true });
      toast.success(t("admin.deliveries.companyFee.saved"));
      setFee(String(r.data.fee_usdt));
      await load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    } finally { setBusy(false); }
  };

  const feeNum = parseFloat(fee) || 0;
  const courierPct = cfg?.courier_share_pct ?? 0;
  const commissionPct = cfg?.resilience_commission_pct ?? 0;
  const courierAmt = (feeNum * courierPct) / 100;
  const commissionAmt = (feeNum * commissionPct) / 100;
  const dirty = cfg && String(cfg.fee_usdt ?? 0) !== fee;

  return (
    <div className="space-y-6 max-w-xl" data-testid="company-delivery-fee-tab">
      <div className="border border-white/10 bg-[#0d0d0d] p-5 space-y-5">
        <div className="flex items-center gap-2">
          <Truck className="w-5 h-5 text-[#8B5CF6]" />
          <h2 className="text-lg font-semibold">{t("admin.deliveries.companyFee.title")}</h2>
        </div>
        <p className="text-sm text-neutral-400">{t("admin.deliveries.companyFee.desc")}</p>

        <div className="space-y-2">
          <label className="micro-label text-neutral-500">{t("admin.deliveries.companyFee.feeLabel")}</label>
          <div className="flex gap-2">
            <Input
              type="number" min="0" step="0.5" value={fee}
              onChange={(e) => setFee(e.target.value)}
              data-testid="company-fee-input"
              className="rounded-none bg-[#0a0a0a] border-white/10"
            />
            <Button
              onClick={save} disabled={busy || !dirty}
              data-testid="company-fee-save"
              className="rounded-none gap-2 whitespace-nowrap"
            >
              <Save className="w-4 h-4" /> {t("admin.deliveries.companyFee.save")}
            </Button>
          </div>
          <p className="text-[0.65rem] text-neutral-500">
            {t("admin.deliveries.companyFee.feeHint")}
          </p>
        </div>

        {cfg && (
          <div className="border-t border-white/10 pt-4 space-y-2" data-testid="company-fee-split">
            <div className="micro-label text-neutral-500 flex items-center gap-1">
              <Percent className="w-3.5 h-3.5" /> {t("admin.deliveries.companyFee.splitTitle")}
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-neutral-400">
                {t("admin.deliveries.companyFee.courierShare", { pct: courierPct })}
              </span>
              <span className="font-mono text-[#22C55E]" data-testid="company-fee-courier-amt">
                {courierAmt.toFixed(2)} USDT
              </span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-neutral-400">
                {t("admin.deliveries.companyFee.resilienceShare", { pct: commissionPct })}
              </span>
              <span className="font-mono text-[#8B5CF6]" data-testid="company-fee-resilience-amt">
                {commissionAmt.toFixed(2)} USDT
              </span>
            </div>
            <p className="text-[0.65rem] text-neutral-500 pt-1">
              {t("admin.deliveries.companyFee.splitNote")}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
