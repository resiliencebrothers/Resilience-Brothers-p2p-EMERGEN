import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { Truck, Save, Percent } from "lucide-react";

// Panel admin — tarifa fija de mensajería Empresa (company_delivery_fee_usdt)
// y reparto EDITABLE mensajero/Resilience (comisión = 100 − parte mensajero).
export default function CompanyDeliveryFeeTab() {
  const { t } = useTranslation();
  const [cfg, setCfg] = useState(null);
  const [fee, setFee] = useState("");
  const [commission, setCommission] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () =>
    axios.get(`${API}/admin/company-delivery-fee`, { withCredentials: true })
      .then((r) => {
        setCfg(r.data);
        setFee(String(r.data.fee_usdt ?? 0));
        setCommission(String(r.data.resilience_commission_pct ?? 0));
      })
      .catch(() => toast.error(t("admin.deliveries.companyFee.loadError")));

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    const val = parseFloat(fee);
    const comm = parseFloat(commission);
    if (isNaN(val) || val < 0) return toast.error(t("admin.deliveries.companyFee.invalid"));
    if (isNaN(comm) || comm < 0 || comm > 100)
      return toast.error(t("admin.deliveries.companyFee.invalidPct"));
    setBusy(true);
    try {
      const r = await axios.put(`${API}/admin/company-delivery-fee`,
        { fee_usdt: val, resilience_commission_pct: comm }, { withCredentials: true });
      toast.success(t("admin.deliveries.companyFee.saved"));
      setCfg(r.data);
      setFee(String(r.data.fee_usdt));
      setCommission(String(r.data.resilience_commission_pct ?? 0));
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    } finally { setBusy(false); }
  };

  const feeNum = parseFloat(fee) || 0;
  const commNum = Math.min(Math.max(parseFloat(commission) || 0, 0), 100);
  const courierPct = Math.round((100 - commNum) * 100) / 100;
  const courierAmt = (feeNum * courierPct) / 100;
  const commissionAmt = (feeNum * commNum) / 100;
  const dirty = cfg && (String(cfg.fee_usdt ?? 0) !== fee
    || String(cfg.resilience_commission_pct ?? 0) !== commission);

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
          <Input
            type="number" min="0" step="0.5" value={fee}
            onChange={(e) => setFee(e.target.value)}
            data-testid="company-fee-input"
            className="rounded-none bg-[#0a0a0a] border-white/10"
          />
          <p className="text-[0.65rem] text-neutral-500">{t("admin.deliveries.companyFee.feeHint")}</p>
        </div>

        <div className="space-y-2">
          <label className="micro-label text-neutral-500 flex items-center gap-1">
            <Percent className="w-3.5 h-3.5" /> {t("admin.deliveries.companyFee.commissionLabel")}
          </label>
          <Input
            type="number" min="0" max="100" step="1" value={commission}
            onChange={(e) => setCommission(e.target.value)}
            data-testid="company-commission-input"
            className="rounded-none bg-[#0a0a0a] border-white/10"
          />
          <p className="text-[0.65rem] text-neutral-500">{t("admin.deliveries.companyFee.commissionHint")}</p>
        </div>

        <div className="border-t border-white/10 pt-4 space-y-2" data-testid="company-fee-split">
          <div className="micro-label text-neutral-500">{t("admin.deliveries.companyFee.splitTitle")}</div>
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
              {t("admin.deliveries.companyFee.resilienceShare", { pct: commNum })}
            </span>
            <span className="font-mono text-[#8B5CF6]" data-testid="company-fee-resilience-amt">
              {commissionAmt.toFixed(2)} USDT
            </span>
          </div>
        </div>

        <Button
          onClick={save} disabled={busy || !dirty}
          data-testid="company-fee-save"
          className="rounded-none gap-2 w-full"
        >
          <Save className="w-4 h-4" /> {t("admin.deliveries.companyFee.save")}
        </Button>
      </div>
    </div>
  );
}
