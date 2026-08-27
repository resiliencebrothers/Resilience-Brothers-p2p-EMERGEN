import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

// iter198 — inline km editor so staff can charge/adjust the courier fee of a
// marketplace delivery (manual review or corrections). TOTP handled upstream.
function RowCourierFee({ r, onSetCourierFee, onCreateDelivery }) {
  const { t } = useTranslation();
  const [km, setKm] = useState(Number(r.courier_km) > 0 ? String(r.courier_km) : "");
  if (r.courier_fee_status === "free") {
    return (
      <div className="space-y-1">
        <span className="text-[#22C55E] text-xs">{t("marketplace.courierFree")}</span>
        {onCreateDelivery && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => onCreateDelivery(r)}
            data-testid={`redemption-create-delivery-${r.id}`}
            className="block rounded-none border-[#8B5CF6]/40 text-[#8B5CF6] hover:bg-[#8B5CF6]/10 h-6 text-[0.6rem] px-2"
          >
            {t("admin.withdrawals.createDeliveryBtn")}
          </Button>
        )}
      </div>
    );
  }
  if (r.status === "rejected") {
    return Number(r.courier_fee_usd) > 0
      ? <span className="font-mono text-xs text-neutral-500">-${r.courier_fee_usd}</span>
      : <span className="text-neutral-600 text-xs">—</span>;
  }
  return (
    <div className="space-y-1">
      {Number(r.courier_fee_usd) > 0 && (
        <div className="font-mono text-xs text-amber-300">
          -${r.courier_fee_usd} · {r.courier_km} km
        </div>
      )}
      <div className="flex items-center gap-1">
        <Input
          type="number"
          min="0"
          step="0.1"
          value={km}
          onChange={(e) => setKm(e.target.value)}
          placeholder="km"
          data-testid={`redemption-courier-km-${r.id}`}
          className="rounded-none h-7 w-16 bg-[#0a0a0a] border-white/10 text-xs font-mono px-1.5"
        />
        <Button
          size="sm"
          onClick={() => onSetCourierFee(r.id, parseFloat(km || "0") || 0)}
          data-testid={`redemption-courier-apply-${r.id}`}
          className="bg-[#8B5CF6] text-white rounded-none h-7 text-[0.65rem] px-2"
        >
          {t("admin.withdrawals.courier.apply")}
        </Button>
      </div>
      {r.courier_fee_status === "manual_review" && Number(r.courier_fee_usd) === 0 && (
        <div className="text-[0.6rem] text-amber-400">{t("marketplace.courierPending")}</div>
      )}
    </div>
  );
}

export default function RedemptionsTable({ redemptions, onUpdateStatus, onSetCourierFee, onCreateDelivery }) {
  const { t } = useTranslation();
  return (
    <div className="tactile-card overflow-x-auto overflow-y-auto max-h-[70vh]" data-testid="admin-redemptions-scroll">
      <table className="w-full text-sm min-w-[820px]">
        <thead className="border-b border-white/10 bg-[#0a0a0a] sticky top-0 z-10">
          <tr className="text-left">
            <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colUser")}</th>
            <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colProduct")}</th>
            <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colQty")}</th>
            <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colTotal")}</th>
            <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colAddress")}</th>
            <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colCourier")}</th>
            <th className="px-3 py-3 micro-label text-neutral-500">{t("admin.withdrawals.colStatus")}</th>
            <th className="px-3 py-3"></th>
          </tr>
        </thead>
        <tbody>
          {redemptions.length === 0 && (
            <tr>
              <td colSpan="8" className="text-center text-neutral-500 py-6">{t("admin.withdrawals.emptyRedemptions")}</td>
            </tr>
          )}
          {redemptions.map((r) => (
            <tr key={r.id} className="border-b border-white/5">
              <td className="px-3 py-3">{r.user_name}</td>
              <td className="px-3 py-3">{r.product_name}</td>
              <td className="px-3 py-3 font-mono">{r.quantity}</td>
              <td className="px-3 py-3 font-mono text-[#8B5CF6]">${r.total_usd}</td>
              <td className="px-3 py-3 text-xs max-w-xs truncate">{r.delivery_address}</td>
              <td className="px-3 py-3">
                <RowCourierFee r={r} onSetCourierFee={onSetCourierFee} onCreateDelivery={onCreateDelivery} />
              </td>
              <td className="px-3 py-3 text-xs uppercase">{r.status}</td>
              <td className="px-3 py-3">
                <div className="flex gap-1">
                  <Button size="sm" onClick={() => onUpdateStatus(r.id, "approved")} className="bg-[#22C55E] text-black rounded-none h-7 text-xs">✓</Button>
                  <Button size="sm" onClick={() => onUpdateStatus(r.id, "delivered")} className="bg-[#8B5CF6] text-white rounded-none h-7 text-xs">⇪</Button>
                  <Button size="sm" onClick={() => onUpdateStatus(r.id, "rejected")} className="bg-[#EF4444] text-white rounded-none h-7 text-xs">✕</Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
