/**
 * CashDetailsTable — pretty renderer for the structured cash-withdrawal
 * details block introduced in iter55.22.
 *
 * Since iter55.22 the client fills 3 mandatory sub-fields (Nombre / Celular /
 * Dirección) plus 1 optional (ID / Carné). The frontend serialises them as a
 * labelled multiline block:
 *
 *     Nombre: Juan Pérez
 *     Celular: +5355551234
 *     Dirección: Calle 23 nº 456
 *     ID / Carné: 91020412345
 *
 * The admin panel used to display this as one blob of text next to a single
 * "Copiar detalles" button. That works but the operator has to visually scan
 * a paragraph to find the phone number when they're on the phone with the
 * courier. This component renders the block as a compact 2-column mini-table
 * with a per-row copy button so the operator can grab exactly the field they
 * need in one click.
 *
 * Backward compatibility: legacy free-form details (or empty strings) render
 * as a plain <CopyableText> — the caller decides which mode via the
 * `structured` boolean returned by `parseCashDetails`.
 */
import { Copy, Check } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

// Labels we recognise. Order matters — we render rows in this order.
const KNOWN_LABELS = ["Nombre", "Celular", "Dirección", "ID / Carné"];

/** Parse the composed block. Returns `null` if not recognisable. */
export function parseCashDetails(raw) {
  if (!raw || typeof raw !== "string") return null;
  const lines = raw.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  // Every known line follows "<Label>: <value>". Detect at least 2 known
  // labels to consider it structured (guards against a legacy line that
  // happens to contain a colon).
  const found = {};
  for (const line of lines) {
    const idx = line.indexOf(":");
    if (idx <= 0) continue;
    const label = line.slice(0, idx).trim();
    const value = line.slice(idx + 1).trim();
    if (KNOWN_LABELS.includes(label) && value) {
      found[label] = value;
    }
  }
  return Object.keys(found).length >= 2 ? found : null;
}

function CopyCell({ value, label }) {
  const [copied, setCopied] = useState(false);
  const doCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      toast.success(`${label} copiado`);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("No se pudo copiar");
    }
  };
  const Icon = copied ? Check : Copy;
  return (
    <button
      type="button"
      onClick={doCopy}
      data-testid={`cash-details-copy-${label.toLowerCase().replace(/[^a-z]+/g, "-")}`}
      title={`Copiar ${label.toLowerCase()}`}
      className="p-1 text-neutral-500 hover:text-[#EAB308] transition-colors shrink-0"
      aria-label={`Copiar ${label}`}
    >
      <Icon className={`w-3.5 h-3.5 ${copied ? "text-[#22C55E]" : ""}`} />
    </button>
  );
}

export default function CashDetailsTable({ details }) {
  const parsed = parseCashDetails(details);
  if (!parsed) return null;

  return (
    <table
      data-testid="cash-details-table"
      className="w-full text-xs font-mono border border-white/5"
    >
      <tbody>
        {KNOWN_LABELS.filter((k) => parsed[k]).map((label) => (
          <tr
            key={label}
            className="border-b border-white/5 last:border-0"
            data-testid={`cash-details-row-${label.toLowerCase().replace(/[^a-z]+/g, "-")}`}
          >
            <td className="px-2 py-1.5 text-neutral-500 uppercase text-[0.65rem] tracking-wider align-top w-24">
              {label}
            </td>
            <td className="px-2 py-1.5 text-white break-all">{parsed[label]}</td>
            <td className="pr-2 py-1 w-8 text-right align-middle">
              <CopyCell value={parsed[label]} label={label} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
