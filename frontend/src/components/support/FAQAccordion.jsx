import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown } from "lucide-react";

const CATEGORY_LABELS_KEY = {
  general: "support.category.general",
  kyc: "support.category.kyc",
  convert: "support.category.convert",
  withdrawal: "support.category.withdrawal",
  fees: "support.category.fees",
  other: "support.category.other",
};

/**
 * iter102 — FAQ accordion for /dashboard/support (client) and reused inside
 * the admin editor as a preview. Groups by category, sorts by `order`.
 * Renders ES/EN according to the current i18n language.
 */
export default function FAQAccordion({ entries }) {
  const { t, i18n } = useTranslation();
  const lang = (i18n.language || "es").startsWith("en") ? "en" : "es";
  const [openId, setOpenId] = useState(null);

  const grouped = useMemo(() => {
    const map = new Map();
    for (const e of entries) {
      if (!map.has(e.category)) map.set(e.category, []);
      map.get(e.category).push(e);
    }
    for (const list of map.values()) list.sort((a, b) => (a.order || 0) - (b.order || 0));
    return Array.from(map.entries());
  }, [entries]);

  if (!entries?.length) {
    return (
      <div className="tactile-card p-8 text-center text-sm text-neutral-500" data-testid="faq-empty">
        {t("support.faq.empty")}
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="faq-accordion">
      {grouped.map(([category, list]) => (
        <section key={category}>
          <h3 className="micro-label text-[#8B5CF6] mb-3">
            {t(CATEGORY_LABELS_KEY[category] || category)}
          </h3>
          <div className="space-y-2">
            {list.map((e) => {
              const isOpen = openId === e.id;
              const question = lang === "en" ? e.question_en : e.question_es;
              const answer = lang === "en" ? e.answer_en : e.answer_es;
              return (
                <div key={e.id} className="tactile-card overflow-hidden">
                  <button
                    type="button"
                    data-testid={`faq-toggle-${e.id}`}
                    onClick={() => setOpenId(isOpen ? null : e.id)}
                    className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left hover:bg-white/[0.02] transition-colors"
                  >
                    <span className="text-sm font-medium">{question}</span>
                    <ChevronDown
                      className={`w-4 h-4 shrink-0 text-neutral-500 transition-transform ${isOpen ? "rotate-180" : ""}`}
                    />
                  </button>
                  {isOpen && (
                    <div
                      data-testid={`faq-answer-${e.id}`}
                      className="px-4 pb-4 pt-1 text-sm text-neutral-300 leading-relaxed whitespace-pre-wrap"
                    >
                      {answer}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
