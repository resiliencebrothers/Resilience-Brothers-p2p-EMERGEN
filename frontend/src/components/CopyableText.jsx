import { useState } from "react";
import { toast } from "sonner";
import { Copy, Check } from "lucide-react";

/**
 * iter55.19c-copyable — Inline copy-to-clipboard button.
 *
 * Renders the given `value` as a monospace span next to a small icon-only
 * button. Clicking the icon copies the trimmed value, swaps the icon for a
 * checkmark for 1.5s and fires a subtle sonner toast. Handles the classic
 * navigator.clipboard failure modes (insecure context, permissions) with a
 * synchronous fallback via a hidden textarea.
 *
 * Used in AdminWithdrawals modal to let staff copy the client's wallet or
 * bank details without manual highlighting.
 */
export default function CopyableText({
  value,
  label = "Copiar",
  toastMessage = "Copiado al portapapeles",
  testid,
  className = "",
  monospace = true,
}) {
  const [copied, setCopied] = useState(false);
  const safeValue = (value || "").toString().trim();
  if (!safeValue) return null;

  const copy = async (e) => {
    e?.stopPropagation?.();
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(safeValue);
      } else {
        // Legacy fallback — works in older browsers and http contexts
        const ta = document.createElement("textarea");
        ta.value = safeValue;
        ta.setAttribute("readonly", "");
        ta.style.position = "absolute";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      setCopied(true);
      toast.success(toastMessage);
      setTimeout(() => setCopied(false), 1500);
    } catch (_err) {
      toast.error("No se pudo copiar. Intenta manualmente.");
    }
  };

  return (
    <span
      className={`inline-flex items-center gap-1.5 max-w-full min-w-0 ${className}`}
      title={safeValue}
    >
      <span
        className={`truncate whitespace-nowrap ${monospace ? "font-mono" : ""}`}
      >
        {safeValue}
      </span>
      <button
        type="button"
        onClick={copy}
        data-testid={testid}
        title={copied ? "¡Copiado!" : label}
        aria-label={label}
        className="flex-shrink-0 w-6 h-6 inline-flex items-center justify-center text-neutral-500 hover:text-[#8B5CF6] hover:bg-[#8B5CF6]/10 border border-transparent hover:border-[#8B5CF6]/30 transition-colors"
      >
        {copied ? (
          <Check className="w-3.5 h-3.5 text-[#22C55E]" />
        ) : (
          <Copy className="w-3.5 h-3.5" />
        )}
      </button>
    </span>
  );
}
