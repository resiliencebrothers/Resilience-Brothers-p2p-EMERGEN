/**
 * iter98 — LiveToaster
 *
 * App-level sink for SSE events that surface a discrete `sonner` toast
 * whenever something changes in the background (order approved,
 * withdrawal paid, new rate posted, balance updated, or — for admin
 * users — a fresh order/withdrawal landing in the queue).
 *
 * Rendered ONCE inside <LiveStreamProvider> so it lives for the whole
 * session and never mounts twice.
 *
 * Rate-limit rules (avoid nagging the user):
 * - `rates_updated`   → 30s throttle (many admin edits arrive as bursts)
 * - `balance_updated` → 10s throttle (approved orders also fire a balance
 *                       event; we don't want two toasts for the same act)
 * - Everything else fires immediately.
 *
 * Localised via i18n `liveToast.*` keys.
 */
import { useCallback, useRef } from "react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { CheckCircle2, XCircle, TrendingUp, Wallet, Inbox, ArrowDownToLine } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { useLiveEvent } from "@/hooks/useLiveStream";
import { playCashSound } from "@/utils/cashSound";

const RATE_THROTTLE_MS = 30_000;
const BALANCE_THROTTLE_MS = 10_000;
const CASH_SOUND_THROTTLE_MS = 3_000;

// iter225 — motivos de balance_updated que significan dinero ENTRANDO.
const CASH_IN_REASONS = [
  "capital_request_disbursed",
  "capital_deposit_confirmed",
  "vendor_product_sale",
  "referral_bonus",
  "settlement_payout",
  "order_residue",
];

function useThrottle() {
  const lastByKeyRef = useRef({});
  return useCallback((key, windowMs) => {
    const now = Date.now();
    const last = lastByKeyRef.current[key] || 0;
    if (now - last < windowMs) return true; // dropped
    lastByKeyRef.current[key] = now;
    return false;
  }, []);
}

export default function LiveToaster() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const throttled = useThrottle();
  const isStaff = ["admin", "employee"].includes(user?.role);

  /* ------------------- client-facing events ------------------- */

  useLiveEvent("order_status_changed", (data) => {
    if (!data?.status) return;
    const s = data.status;
    if (s === "approved" || s === "completed") {
      if (!throttled("cash-sound", CASH_SOUND_THROTTLE_MS)) playCashSound();
      toast.success(t("liveToast.order.approved"), {
        icon: <CheckCircle2 className="w-4 h-4 text-[#22C55E]" />,
        description: t("liveToast.order.pair", { from: data.from_code, to: data.to_code }),
      });
    } else if (s === "rejected") {
      toast.error(t("liveToast.order.rejected"), {
        icon: <XCircle className="w-4 h-4 text-[#EF4444]" />,
        description: t("liveToast.order.pair", { from: data.from_code, to: data.to_code }),
      });
    }
  });

  useLiveEvent("withdrawal_status_changed", (data) => {
    if (!data?.status) return;
    const s = data.status;
    if (s === "approved") {
      toast.success(t("liveToast.withdrawal.approved"), {
        icon: <CheckCircle2 className="w-4 h-4 text-[#22C55E]" />,
      });
    } else if (s === "paid") {
      toast.success(t("liveToast.withdrawal.paid"), {
        icon: <CheckCircle2 className="w-4 h-4 text-[#22C55E]" />,
      });
    } else if (s === "rejected") {
      toast.error(t("liveToast.withdrawal.rejected"), {
        icon: <XCircle className="w-4 h-4 text-[#EF4444]" />,
      });
    }
  });

  useLiveEvent("balance_updated", (data) => {
    // iter225 — caja registradora suave cuando entra dinero al saldo.
    if (CASH_IN_REASONS.includes(data?.reason) &&
        !throttled("cash-sound", CASH_SOUND_THROTTLE_MS)) {
      playCashSound();
    }
    if (throttled("balance", BALANCE_THROTTLE_MS)) return;
    toast(t("liveToast.balance.updated"), {
      icon: <Wallet className="w-4 h-4 text-[#8B5CF6]" />,
    });
  });

  useLiveEvent("rates_updated", () => {
    if (throttled("rates", RATE_THROTTLE_MS)) return;
    toast(t("liveToast.rates.updated"), {
      icon: <TrendingUp className="w-4 h-4 text-[#8B5CF6]" />,
    });
  });

  /* ------------------- admin-only events ------------------- */

  useLiveEvent("order_created", (data) => {
    if (!isStaff) return;
    toast(t("liveToast.admin.orderCreated"), {
      icon: <Inbox className="w-4 h-4 text-[#8B5CF6]" />,
      description: t("liveToast.admin.orderCreatedDesc", {
        user: data?.user_name || "—",
        from: data?.from_code,
        to: data?.to_code,
      }),
    });
  });

  useLiveEvent("withdrawal_created", (data) => {
    if (!isStaff) return;
    toast(t("liveToast.admin.withdrawalCreated"), {
      icon: <ArrowDownToLine className="w-4 h-4 text-[#8B5CF6]" />,
      description: t("liveToast.admin.withdrawalCreatedDesc", {
        user: data?.user_name || "—",
        amount: data?.amount_usd,
        currency: data?.currency || "USD",
      }),
    });
  });

  return null;
}
