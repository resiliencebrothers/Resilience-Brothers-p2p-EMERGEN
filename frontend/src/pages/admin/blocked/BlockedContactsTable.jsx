/**
 * iter85 — BlockedContactsTable
 *
 * Search bar + table of blocked contacts. Presentation-only — receives
 * items, loading, total, search state and the per-row `onRemove` callback.
 */
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import { Search, Trash2 } from "lucide-react";

export default function BlockedContactsTable({ items, total, q, setQ, loading, onRemove }) {
  const { t } = useTranslation();
  return (
    <>
      <div className="tactile-card p-3 flex items-center gap-2">
        <Search className="w-4 h-4 text-neutral-500 ml-2" />
        <Input
          data-testid="blocked-contacts-search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("admin.blocked.searchPh")}
          className="rounded-none bg-transparent border-none focus-visible:ring-0 h-9"
        />
        <span className="text-xs text-neutral-500 mr-2 font-mono">
          {total} {t("admin.blocked.total")}
        </span>
      </div>

      <div className="tactile-card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="border-b border-white/10 bg-[#0F0F0F]">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.blocked.colPhone")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.blocked.colName")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.blocked.colEmail")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.blocked.colReason")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.blocked.colBlockedBy")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.blocked.colDate")}</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan="7" className="text-center text-neutral-500 py-8">
                  {t("admin.common.loadingEllipsis")}
                </td>
              </tr>
            )}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan="7" className="text-center text-neutral-500 py-8">
                  {t("admin.blocked.empty")}
                </td>
              </tr>
            )}
            {items.map((c) => (
              <BlockedContactRow key={c.id} c={c} onRemove={onRemove} t={t} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function BlockedContactRow({ c, onRemove, t }) {
  return (
    <tr data-testid={`blocked-row-${c.id}`} className="border-b border-white/5 hover:bg-white/[0.02]">
      <td className="px-4 py-3 font-mono text-neutral-300">
        {c.phone || <span className="text-neutral-600">—</span>}
      </td>
      <td className="px-4 py-3 text-neutral-300 text-xs">
        {c.name || <span className="text-neutral-600">—</span>}
      </td>
      <td className="px-4 py-3 text-neutral-300 text-xs break-all">
        {c.email || <span className="text-neutral-600">—</span>}
      </td>
      <td className="px-4 py-3 text-neutral-400 text-xs max-w-xs">
        <div className="line-clamp-2 whitespace-pre-line">{c.reason}</div>
        {c.notes && (
          <div className="text-[0.65rem] text-neutral-600 mt-1 line-clamp-1">{c.notes}</div>
        )}
      </td>
      <td className="px-4 py-3 text-xs text-neutral-500 break-all">{c.created_by_email}</td>
      <td className="px-4 py-3 text-xs text-neutral-500">
        {new Date(c.created_at).toLocaleDateString()}
      </td>
      <td className="px-4 py-3">
        <button
          type="button"
          onClick={() => onRemove(c.id)}
          data-testid={`unblock-${c.id}`}
          title={t("admin.blocked.removeConfirm")}
          className="text-neutral-400 hover:text-[#22C55E]"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </td>
    </tr>
  );
}
