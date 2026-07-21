import { useState } from "react";
import { useTranslation } from "react-i18next";
import { CheckCircle2, Copy } from "lucide-react";

export default function PaymentAccountBlock({ fromCurr }) {
  const [copied, setCopied] = useState(false);
  if (!fromCurr?.payment_account) return null;
  const copy = () => {
    navigator.clipboard.writeText(fromCurr.payment_account);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <div className="border border-white/10 p-4">
      <div className="micro-label text-neutral-500 mb-2">Cuenta destino — envía tu pago aquí:</div>
      <div className="flex items-center justify-between gap-3">
        <code className="text-sm break-all">{fromCurr.payment_account}</code>
        <button onClick={copy} data-testid="copy-account-btn" className="text-[#8B5CF6] hover:text-[#A78BFA] shrink-0">
          {copied ? <CheckCircle2 className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
        </button>
      </div>
    </div>
  );
}
