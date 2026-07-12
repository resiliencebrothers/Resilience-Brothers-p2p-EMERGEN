/**
 * iter55.33 — i18n infrastructure.
 * iter55.36 — Auto-detect language on FIRST VISIT (`en-US`, `en-GB` → `en`).
 *
 * Approach: partial-first. We translate the highest-visibility surfaces
 * (sidebar nav, section headers, common actions, page hero labels) and
 * leave the rest as literal Spanish strings so untranslated content
 * falls back to the app's original language. Progressive translation
 * from here: every future PR can add more keys without infra churn.
 *
 * Language resolution (in order):
 *   1. localStorage `resilience_lang` (user's explicit choice, persists forever)
 *   2. `navigator.language` from the browser — normalized so `en-GB`, `en-US`,
 *      `en-AU`, etc. all map to `en`, and `es-*` variants map to `es`.
 *   3. Fallback `es` for languages we don't ship yet.
 *
 * `load: "languageOnly"` + `nonExplicitSupportedLngs: true` are what make the
 * region-agnostic matching work (before this fix, a first-time visitor on
 * `en-GB` would see the app in Spanish because "en-GB" didn't literally
 * exist in `supportedLngs`).
 */
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";

import es from "./locales/es.json";
import en from "./locales/en.json";

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      es: { translation: es },
      en: { translation: en },
    },
    fallbackLng: "es",
    supportedLngs: ["es", "en"],
    load: "languageOnly",              // "en-GB" → "en", "es-CU" → "es"
    nonExplicitSupportedLngs: true,    // accept region variants as their base language
    interpolation: { escapeValue: false }, // React auto-escapes.
    detection: {
      order: ["localStorage", "navigator", "htmlTag"],
      lookupLocalStorage: "resilience_lang",
      caches: ["localStorage"],
    },
    // Any missing key falls back to the raw key path → still readable in dev.
    returnEmptyString: false,
  });

export default i18n;
