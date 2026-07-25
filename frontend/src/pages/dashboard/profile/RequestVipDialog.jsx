import { useState, useMemo } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Crown, Send } from "lucide-react";

/**
 * iter109 — Dialog the client uses to submit a VIP upgrade request.
 * Fields:
 *   - message (motivo)                     20..500 chars
 *   - estimated_monthly_volume_usd (USD)   > 0
 *   - preferred_payment_method             one of ALLOWED_METHODS
 */
const PAYMENT_METHODS = [
  { code: "crypto",        labelKey: "vipRequest.method.crypto" },
  { code: "bank_transfer", labelKey: "vipRequest.method.bank_transfer" },
  { code: "cash",          labelKey: "vipRequest.method.cash" },
  { code: "other",         labelKey: "vipRequest.method.other" },
];

export default function RequestVipDialog({ open, onClose, onSubmitted }) {
  const { t } = useTranslation();
  const [message, setMessage] = useState("");
  const [volume, setVolume] = useState("");
  const [method, setMethod] = useState("bank_transfer");
  const [submitting, setSubmitting] = useState(false);

  const canSubmit = useMemo(() => {
    const m = (message || "").trim();
    const v = Number(volume);
    return m.length >= 20 && m.length <= 500 && v > 0 && !submitting;
  }, [message, volume, submitting]);

  const submit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      await axios.post(
        `${API}/vip/requests`,
        {
          message: message.trim(),
          estimated_monthly_volume_usd: Number(volume),
          preferred_payment_method: method,
        },
        { withCredentials: true },
      );
      toast.success(t("vipRequest.dialog.successToast"));
      setMessage("");
      setVolume("");
      setMethod("bank_transfer");
      onSubmitted?.();
      onClose?.();
    } catch (err) {
      const detail = err?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : t("vipRequest.dialog.errorToast"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent
        data-testid="request-vip-dialog"
        className="bg-[#0c0c0c] border border-amber-500/30 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Crown className="w-5 h-5 text-amber-400" />
            {t("vipRequest.dialog.title")}
          </DialogTitle>
        </DialogHeader>

        <p className="text-xs text-neutral-400 leading-relaxed">
          {t("vipRequest.dialog.body")}
        </p>

        <div className="space-y-3 mt-2">
          <div>
            <Label htmlFor="vip-req-message" className="micro-label text-neutral-500">
              {t("vipRequest.dialog.messageLabel")}
            </Label>
            <textarea
              id="vip-req-message"
              data-testid="vip-request-message"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              maxLength={500}
              placeholder={t("vipRequest.dialog.messagePlaceholder")}
              rows={4}
              className="w-full mt-1 bg-black/40 border border-white/10 rounded-none px-3 py-2 text-sm text-white placeholder:text-neutral-600 focus:border-amber-500/50 focus:outline-none resize-y"
            />
            <div className="text-[0.65rem] text-neutral-500 text-right mt-0.5">
              {message.length} / 500
            </div>
          </div>

          <div>
            <Label htmlFor="vip-req-volume" className="micro-label text-neutral-500">
              {t("vipRequest.dialog.volumeLabel")}
            </Label>
            <Input
              id="vip-req-volume"
              data-testid="vip-request-volume"
              type="number"
              min="1"
              step="100"
              value={volume}
              onChange={(e) => setVolume(e.target.value)}
              placeholder="10000"
              className="rounded-none bg-black/40 border-white/10 text-white h-10 mt-1 font-mono"
            />
          </div>

          <div>
            <Label className="micro-label text-neutral-500">
              {t("vipRequest.dialog.methodLabel")}
            </Label>
            <Select value={method} onValueChange={setMethod}>
              <SelectTrigger
                data-testid="vip-request-method"
                className="rounded-none bg-black/40 border-white/10 text-white h-10 mt-1"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-[#0c0c0c] border border-white/10 rounded-none">
                {PAYMENT_METHODS.map((m) => (
                  <SelectItem key={m.code} value={m.code} className="rounded-none">
                    {t(m.labelKey)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-3 border-t border-white/5 mt-4">
          <Button
            variant="ghost"
            onClick={onClose}
            data-testid="vip-request-cancel"
            className="rounded-none text-neutral-400 hover:text-white"
          >
            {t("common.cancel")}
          </Button>
          <Button
            onClick={submit}
            disabled={!canSubmit}
            data-testid="vip-request-submit"
            className="rounded-none bg-amber-500 hover:bg-amber-400 text-black font-semibold disabled:opacity-40"
          >
            <Send className="w-4 h-4 mr-2" />
            {t("vipRequest.dialog.submit")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
