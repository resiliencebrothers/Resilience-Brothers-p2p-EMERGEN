import { useTranslation } from "react-i18next";
import { Check, Globe2 } from "lucide-react";
import { syncLanguagePreferenceToServer } from "@/lib/langSync";

/**
 * iter55.33 — Language switcher. Renders 2 pill buttons (Español · English),
 * highlights the active language, and persists the choice via i18next's
 * localStorage detector (`resilience_lang` key).
 *
 * iter67 — Also PATCHes the authenticated user's preference to the backend
 * so the language follows them across devices (mobile, desktop, incognito).
 */
export function LanguageSwitcher({ testid = "language-switcher" }) {
  const { t, i18n } = useTranslation();
  const current = i18n.resolvedLanguage || i18n.language || "es";

  const options = [
    { code: "es", label: t("language.spanish"), flag: "🇪🇸" },
    { code: "en", label: t("language.english"), flag: "🇺🇸" },
  ];

  const change = (code) => {
    if (code === current) return;
    i18n.changeLanguage(code);
    syncLanguagePreferenceToServer(code);
  };

  return (
    <div data-testid={testid} className="space-y-3">
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-lg bg-violet-500/10 border border-violet-500/20 flex items-center justify-center">
          <Globe2 className="w-5 h-5 text-violet-400" />
        </div>
        <div>
          <h3 className="font-display text-lg">{t("language.label")}</h3>
          <p className="text-sm text-neutral-500 mt-1 max-w-md">
            {t("language.description")}
          </p>
        </div>
      </div>
      <div className="flex gap-2" role="radiogroup" aria-label={t("language.label")}>
        {options.map((opt) => {
          const isActive = opt.code === current;
          return (
            <button
              key={opt.code}
              type="button"
              role="radio"
              aria-checked={isActive}
              onClick={() => change(opt.code)}
              data-testid={`lang-option-${opt.code}`}
              className={
                "flex items-center gap-2 px-4 py-2.5 rounded-full text-sm font-medium " +
                "transition-all duration-200 outline-none focus-visible:ring-2 focus-visible:ring-violet-500 " +
                (isActive
                  ? "bg-violet-500/15 text-violet-200 border border-violet-500/40 shadow-[0_0_20px_rgba(139,92,246,0.15)]"
                  : "bg-transparent text-white/60 border border-white/10 hover:border-white/25 hover:text-white")
              }
            >
              <span className="text-base leading-none">{opt.flag}</span>
              {opt.label}
              {isActive && <Check className="w-3.5 h-3.5 text-violet-400" aria-hidden />}
            </button>
          );
        })}
      </div>
    </div>
  );
}
