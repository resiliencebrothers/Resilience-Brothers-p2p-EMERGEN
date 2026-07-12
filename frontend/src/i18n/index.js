/**
 * iter55.33 — i18n infrastructure.
 *
 * Approach: partial-first. We translate the highest-visibility surfaces
 * (sidebar nav, section headers, common actions, page hero labels) and
 * leave the rest as literal Spanish strings so untranslated content
 * falls back to the app's original language. Progressive translation
 * from here: every future PR can add more keys without infra churn.
 *
 * Language persistence: `i18next-browser-languagedetector` reads
 * localStorage first, then browser `navigator.language`. Users flip the
 * switch → their choice is stored under `resilience_lang`.
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
    interpolation: { escapeValue: false }, // React auto-escapes.
    detection: {
      order: ["localStorage", "navigator"],
      lookupLocalStorage: "resilience_lang",
      caches: ["localStorage"],
    },
    // Any missing key falls back to the raw key path → still readable in dev.
    returnEmptyString: false,
  });

export default i18n;
