import { useTranslation } from "react-i18next";
import { originOf } from "./originMeta";

export function OriginBadge({ refType, testid }) {
  const { t } = useTranslation();
  const meta = originOf(refType);
  return (
    <span
      data-testid={testid}
      className={`inline-flex items-center px-1.5 py-0.5 text-[0.6rem] uppercase tracking-wider border font-mono whitespace-nowrap ${meta.cls}`}
    >
      {t(`admin.transactions.origin.${refType}`, refType || "—")}
    </span>
  );
}
