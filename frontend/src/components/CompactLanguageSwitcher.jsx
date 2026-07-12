import { useTranslation } from "react-i18next";
import { Globe2 } from "lucide-react";

/**
 * iter55.34 — Compact language switcher for the landing header. Cycles
 * between "es" ↔ "en" on click (only 2 languages so no dropdown needed).
 * Persists to localStorage via i18next-browser-languagedetector so anonymous
 * visitors can flip before signing up, and their choice is remembered.
 */
export function CompactLanguageSwitcher({ testid = "compact-lang-switcher" }) {
  const { i18n } = useTranslation();
  const current = i18n.resolvedLanguage || i18n.language || "es";
  const isSpanish = current.startsWith("es");
  const nextCode = isSpanish ? "en" : "es";
  const nextLabel = isSpanish ? "EN" : "ES";
  const flag = isSpanish ? "🇺🇸" : "🇪🇸";

  return (
    <button
      type="button"
      onClick={() => i18n.changeLanguage(nextCode)}
      data-testid={testid}
      aria-label={`Switch language to ${nextCode.toUpperCase()}`}
      className="inline-flex items-center gap-1.5 px-2.5 h-9 rounded-full border border-white/15 hover:border-violet-400/60 hover:bg-white/5 text-white/70 hover:text-white text-xs font-medium transition-all duration-200 outline-none focus-visible:ring-2 focus-visible:ring-violet-500"
    >
      <Globe2 className="w-3.5 h-3.5 opacity-70" />
      <span className="text-base leading-none" aria-hidden>{flag}</span>
      <span className="font-mono tracking-wider">{nextLabel}</span>
    </button>
  );
}
