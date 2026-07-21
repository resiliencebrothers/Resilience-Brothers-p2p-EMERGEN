import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Copy, Check } from "lucide-react";
import { toast } from "sonner";

/**
 * Small clipboard button used inside the delivery-details panel.
 * Copies `value` to the clipboard and briefly shows a green check so the
 * operator has visual feedback that the payload landed in the buffer.
 */
export default function CopyBtn({ label, value, testid }) {
  const { t } = useTranslation();
  const [ok, setOk] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setOk(true);
      toast.success(t("admin.orders.toastCopied"));
      setTimeout(() => setOk(false), 1500);
    } catch {
      toast.error(t("admin.orders.toastCopyError"));
    }
  };
  return (
    <button
      type="button"
      data-testid={testid}
      onClick={copy}
      className="inline-flex items-center gap-1.5 border border-white/10 hover:border-[#8B5CF6]/50 bg-[#1A1730] hover:bg-[#8B5CF6]/5 px-2.5 py-1 text-[0.7rem] font-mono text-neutral-300 transition-colors"
    >
      {ok ? <Check className="w-3 h-3 text-[#22C55E]" /> : <Copy className="w-3 h-3" />}
      {label}
    </button>
  );
}
