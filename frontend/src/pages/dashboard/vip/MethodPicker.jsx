import { useTranslation } from "react-i18next";
import { Bitcoin, Landmark, Banknote, ChevronRight } from "lucide-react";

const METHODS = [
  { key: "crypto", Icon: Bitcoin, accent: "text-amber-400", iconBg: "bg-amber-500/10 border-amber-500/30", hover: "hover:border-amber-500/60" },
  { key: "transfer", Icon: Landmark, accent: "text-sky-400", iconBg: "bg-sky-500/10 border-sky-500/30", hover: "hover:border-sky-500/60" },
  { key: "cash", Icon: Banknote, accent: "text-emerald-400", iconBg: "bg-emerald-500/10 border-emerald-500/30", hover: "hover:border-emerald-500/60" },
];

/**
 * iter153 — First step of the deposit/withdraw flow: pick HOW the money
 * moves (crypto transfer / bank transfer / cash hand-off). The specific
 * form then renders only the fields relevant to that method.
 */
export function MethodPicker({ mode, onSelect }) {
  const { t } = useTranslation();
  return (
    <div className="tactile-card p-6" data-testid={`method-picker-${mode}`}>
      <h2 className="font-display text-xl">{t(`methodPicker.${mode}.title`)}</h2>
      <p className="text-sm text-neutral-400 mt-1 mb-5">{t(`methodPicker.${mode}.subtitle`)}</p>
      <div className="grid sm:grid-cols-3 gap-3">
        {METHODS.map(({ key, Icon, accent, iconBg, hover }) => (
          <button
            key={key}
            type="button"
            onClick={() => onSelect(key)}
            data-testid={`method-option-${key}`}
            className={`group flex sm:flex-col items-center sm:items-start gap-3 border border-white/10 bg-black/30 p-4 text-left transition-colors ${hover}`}
          >
            <span className={`w-11 h-11 shrink-0 rounded-full border flex items-center justify-center ${iconBg} ${accent}`}>
              <Icon className="w-5 h-5" />
            </span>
            <span className="flex-1 min-w-0">
              <span className="block text-sm font-semibold text-white">
                {t(`methodPicker.options.${key}.label`)}
              </span>
              <span className="block text-xs text-neutral-500 mt-0.5">
                {t(`methodPicker.options.${key}.desc`)}
              </span>
            </span>
            <ChevronRight className="w-4 h-4 text-neutral-600 group-hover:text-white transition-colors shrink-0 sm:hidden" />
          </button>
        ))}
      </div>
    </div>
  );
}
