/**
 * iter100 — Extracted from AdminUsers.jsx.
 * Search + role dropdown + result counter (mounted above the users table).
 */
import { useTranslation } from "react-i18next";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export default function UsersFiltersBar({
  searchInput, onSearchInputChange,
  roleFilter, onRoleFilterChange,
  total, onClear,
}) {
  const { t } = useTranslation();
  const showClear = Boolean(searchInput) || roleFilter !== "all";
  return (
    <div className="flex items-end gap-3 mb-4 flex-wrap">
      <div>
        <div className="micro-label text-neutral-500 mb-1">{t("admin.users.searchLabel")}</div>
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500 pointer-events-none" />
          <Input
            data-testid="users-search"
            value={searchInput}
            onChange={(e) => onSearchInputChange(e.target.value)}
            placeholder={t("admin.users.searchPlaceholder")}
            className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-80 pl-9 font-mono text-xs"
          />
        </div>
      </div>
      <div>
        <div className="micro-label text-neutral-500 mb-1">{t("admin.users.roleLabel")}</div>
        <Select value={roleFilter} onValueChange={onRoleFilterChange}>
          <SelectTrigger
            data-testid="users-role-filter"
            className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-44"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
            <SelectItem value="all">{t("admin.users.allRoles")}</SelectItem>
            <SelectItem value="normal">{t("admin.users.roleNormal")}</SelectItem>
            <SelectItem value="vip">{t("admin.users.roleVip")}</SelectItem>
            <SelectItem value="employee">{t("admin.users.roleEmployee")}</SelectItem>
            <SelectItem value="admin">{t("admin.users.roleAdmin")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {showClear && (
        <button
          data-testid="users-clear-search"
          onClick={onClear}
          className="text-xs text-neutral-500 hover:text-[#8B5CF6] underline underline-offset-4 h-10"
        >
          {t("admin.common.clearFilters")}
        </button>
      )}
      <div className="ml-auto text-xs text-neutral-500" data-testid="users-result-count">
        {total} {total === 1 ? t("admin.users.resultOne") : t("admin.users.resultMany")}
      </div>
    </div>
  );
}
