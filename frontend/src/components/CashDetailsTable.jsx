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
import { Copy, Check, MessageCircle, MapPin } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

// Labels we recognise. Order matters — we render rows in this order.
const KNOWN_LABELS = ["Nombre", "Celular", "Dirección", "ID / Carné"];

// Default WhatsApp message pre-loaded when the operator hits the WA button.
// Kept short and professional — Cuban ops asked for something they can send
// as-is without editing.
const WHATSAPP_TEMPLATE =
  "Hola, soy del equipo de Resilience Brothers. " +
  "Estamos coordinando la entrega de su retiro en efectivo. " +
  "¿Puede confirmar disponibilidad para recibirlo?";

/** Strip everything that isn't a digit — wa.me requires bare digits. */
function normalisePhone(raw) {
  return String(raw || "").replace(/\D+/g, "");
}

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

function WhatsappCell({ phone }) {
  const normalised = normalisePhone(phone);
  if (!normalised) return null;

  const openWhatsApp = () => {
    // Best-effort copy to keep parity with the plain copy button — nice when
    // the operator wants the raw number too (e.g. paste into CRM). Wrapped
    // in `.catch()` because navigator.clipboard.writeText returns a Promise
    // that rejects on lost-focus / permission denied — WA is the primary
    // action and we don't want an unhandled rejection to crash the UI.
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(phone).catch(() => {});
    }
    const url = `https://wa.me/${normalised}?text=${encodeURIComponent(WHATSAPP_TEMPLATE)}`;
    window.open(url, "_blank", "noopener,noreferrer");
    toast.success("Abriendo WhatsApp…");
  };

  return (
    <button
      type="button"
      onClick={openWhatsApp}
      data-testid="cash-details-whatsapp"
      title="Abrir WhatsApp con saludo pre-cargado"
      aria-label="Abrir WhatsApp"
      className="p-1 text-neutral-500 hover:text-[#25D366] transition-colors shrink-0"
    >
      <MessageCircle className="w-3.5 h-3.5" />
    </button>
  );
}

function MapsCell({ address }) {
  const clean = String(address || "").trim();
  if (!clean) return null;
  const openMaps = () => {
    // Google Maps universal search URL — works on web and deep-links to the
    // native Maps app on mobile.
    const url = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(clean)}`;
    window.open(url, "_blank", "noopener,noreferrer");
    toast.success("Abriendo Google Maps…");
  };
  return (
    <button
      type="button"
      onClick={openMaps}
      data-testid="cash-details-maps"
      title="Ver dirección en Google Maps"
      aria-label="Ver en Google Maps"
      className="p-1 text-neutral-500 hover:text-[#4285F4] transition-colors shrink-0"
    >
      <MapPin className="w-3.5 h-3.5" />
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
            <td className="pr-2 py-1 w-16 text-right align-middle whitespace-nowrap">
              {label === "Celular" && <WhatsappCell phone={parsed[label]} />}
              {label === "Dirección" && <MapsCell address={parsed[label]} />}
              <CopyCell value={parsed[label]} label={label} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
