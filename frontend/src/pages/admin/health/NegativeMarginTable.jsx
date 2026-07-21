import { useTranslation } from "react-i18next";
import { Section } from "./HealthPrimitives";

export default function NegativeMarginTable({ negativeMargin }) {
  const { t } = useTranslation();
  if (negativeMargin.count === 0) return null;
  return (
    <Section title={t("admin.health.negativeMarginTable", { n: negativeMargin.count })}>
      <div className="border border-white/10 overflow-x-auto">
        <table className="w-full text-sm" data-testid="health-margin-table">
          <thead className="bg-white/5 text-xs uppercase tracking-wider text-neutral-400">
            <tr>
              <th className="text-left p-3">{t("admin.health.colId")}</th>
              <th className="text-left p-3">{t("admin.health.colClient")}</th>
              <th className="text-left p-3">{t("admin.health.colPair")}</th>
              <th className="text-right p-3">{t("admin.health.colLoss")}</th>
              <th className="text-right p-3">{t("admin.health.colLossPct")}</th>
              <th className="text-left p-3">{t("admin.health.colStatus")}</th>
            </tr>
          </thead>
          <tbody>
            {negativeMargin.items.map((it) => (
              <tr key={it.id} className="border-t border-white/5 hover:bg-white/5">
                <td className="p-3 text-neutral-500 font-mono text-xs">{it.id.slice(0, 8)}</td>
                <td className="p-3 text-neutral-300">{it.user_name}</td>
                <td className="p-3 font-mono text-xs">{it.pair}</td>
                <td className="p-3 text-right text-red-400 font-medium">
                  {it.loss_amount.toLocaleString()} {it.loss_currency}
                </td>
                <td className="p-3 text-right text-red-400">{it.loss_pct}%</td>
                <td className="p-3 text-neutral-500 text-xs">{it.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {negativeMargin.count > 20 && (
        <p className="text-xs text-neutral-500">
          {t("admin.health.showingFirst", { n: negativeMargin.count })}
        </p>
      )}
    </Section>
  );
}
