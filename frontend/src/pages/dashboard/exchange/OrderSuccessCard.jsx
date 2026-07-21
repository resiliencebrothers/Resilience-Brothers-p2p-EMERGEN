import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { CheckCircle2 } from "lucide-react";

/**
 * Order-confirmation card shown after a successful `POST /api/orders`.
 * `onNewOrder` resets the ExchangeView back to the empty form.
 */
export default function OrderSuccessCard({ success, onNewOrder }) {
  const { t } = useTranslation();
  return (
    <div className="max-w-2xl mx-auto tactile-card p-8 text-center" data-testid="order-success">
      <CheckCircle2 className="w-16 h-16 text-[#22C55E] mx-auto mb-4" />
      <h2 className="font-display text-2xl mb-2">{t("exchange.orderReceived")}</h2>
      <p className="text-neutral-400 mb-6">
        {t("exchange.orderInReview", { id: success.id.slice(0, 8) })}
      </p>
      <div className="text-left space-y-2 border border-white/10 p-4 mb-6 font-mono text-sm">
        <div className="flex justify-between">
          <span className="text-neutral-500">{t("exchange.sendsLabel")}</span>
          <span>{success.amount_from} {success.from_code}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-neutral-500">{t("exchange.receivesLabel")}</span>
          <span className="text-[#8B5CF6]">{success.amount_to} {success.to_code}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-neutral-500">{t("exchange.rateLabel")}</span>
          <span>{success.rate_applied}</span>
        </div>
        {success.commission_percent > 0 && (
          <div className="flex justify-between">
            <span className="text-neutral-500">{t("exchange.commissionLabel")}</span>
            <span>{success.commission_percent}%</span>
          </div>
        )}
      </div>
      <Button
        data-testid="new-order-btn"
        onClick={onNewOrder}
        className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none"
      >
        {t("exchange.newOrderBtn")}
      </Button>
    </div>
  );
}
