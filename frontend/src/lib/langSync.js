/**
 * iter67 — Cross-device language preference sync.
 *
 * When an authenticated user changes the UI language, we PATCH their
 * preference to /api/profile/language so the next time they open the app
 * on another device (mobile, desktop, incognito) the same language is
 * loaded automatically — instead of re-detecting from `navigator.language`
 * on every visit.
 *
 * Fire-and-forget: any error is silently swallowed so the user's UI
 * change never blocks on a network hiccup.
 */
import axios from "axios";
import i18n from "@/i18n";
import { API } from "@/App";

export function syncLanguagePreferenceToServer(lang) {
  // Skip anonymous visitors — their preference lives in localStorage only.
  if (!lang || (lang !== "es" && lang !== "en")) return;
  // Best-effort PATCH; we don't await it so the UI feels instant.
  axios
    .patch(`${API}/profile/language`, { language: lang }, { withCredentials: true })
    .catch(() => {
      // Silent by design — anonymous users get 401, offline users get network
      // errors, both are OK. The browser's localStorage keeps the choice.
    });
}

/**
 * iter154 — Apply the user's server-side language on login/session load so
 * the preference follows them to ANY device:
 *   - has `preferred_language` → switch the UI to it (overrides whatever the
 *     new device's browser detected).
 *   - has none yet → adopt the device's current language as their global
 *     preference (first login wins; from then on every device inherits it).
 */
export function applyServerLanguage(userDoc) {
  if (!userDoc) return;
  const preferred = userDoc.preferred_language;
  const current = (i18n.resolvedLanguage || i18n.language || "es").split("-")[0];
  if (preferred && preferred !== current) {
    i18n.changeLanguage(preferred);
  } else if (!preferred) {
    syncLanguagePreferenceToServer(current);
  }
}
