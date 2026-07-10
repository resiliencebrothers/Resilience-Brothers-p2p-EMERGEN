import { ExternalLink } from "lucide-react";
import { buildExplorerUrl, explorerLabel } from "@/services/blockExplorers";

/**
 * iter55.19f — Inline "Ver en explorer" button.
 *
 * Renders a small pill link to the block explorer for the given (network,
 * txHash) pair. Falls back to null (renders nothing) when the pair cannot
 * produce a valid URL — safe to drop into any UI that may or may not have
 * on-chain data yet.
 */
export default function ExplorerLink({
  network,
  txHash,
  size = "sm",
  className = "",
  testid,
}) {
  const url = buildExplorerUrl(network, txHash);
  if (!url) return null;
  const label = explorerLabel(network);
  const sizeCls = size === "sm"
    ? "text-[0.65rem] px-2 py-1"
    : "text-xs px-2.5 py-1.5";
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      data-testid={testid}
      className={`inline-flex items-center gap-1.5 font-mono uppercase tracking-wider text-[#EAB308] hover:text-[#FACC15] hover:bg-[#EAB308]/10 border border-[#EAB308]/30 hover:border-[#EAB308]/60 transition-colors ${sizeCls} ${className}`}
      title={`Ver esta transacción en ${label}`}
    >
      <ExternalLink className="w-3 h-3" />
      <span>Ver en {label}</span>
    </a>
  );
}
