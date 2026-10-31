import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Receipt, ListChecks, PiggyBank, ArrowRight } from "lucide-react";

// Qué sale por cada sección — leyenda fija encima del libro contable.
const CARDS = [
  { id: "transactions", icon: Receipt, to: null, cls: "border-[#8B5CF6]/40 bg-[#8B5CF6]/5" },
  { id: "orders", icon: ListChecks, to: "/admin/orders", cls: "border-white/10 bg-[#0a0a0a]" },
  { id: "deposits", icon: PiggyBank, to: "/admin/withdrawals?tab=deposits", cls: "border-white/10 bg-[#0a0a0a]" },
];

export function SectionsLegend() {
  const { t } = useTranslation();
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-2" data-testid="tx-sections-legend">
      {CARDS.map(({ id, icon: Icon, to, cls }) => {
        const body = (
          <>
            <div className="flex items-center justify-between gap-2">
              <div className="micro-label text-neutral-300 flex items-center gap-2">
                <Icon className="w-3.5 h-3.5 text-[#8B5CF6]" />
                {t(`admin.transactions.legend.${id}.title`)}
              </div>
              {to && <ArrowRight className="w-3.5 h-3.5 text-neutral-600" />}
            </div>
            <p className="text-xs text-neutral-400 mt-1.5 leading-relaxed">
              {t(`admin.transactions.legend.${id}.body`)}
            </p>
          </>
        );
        if (!to) {
          return <div key={id} className={`border p-3 ${cls}`} data-testid={`tx-legend-${id}`}>{body}</div>;
        }
        return (
          <Link key={id} to={to} className={`border p-3 hover:border-[#8B5CF6]/50 transition-colors ${cls}`} data-testid={`tx-legend-${id}`}>
            {body}
          </Link>
        );
      })}
    </div>
  );
}
