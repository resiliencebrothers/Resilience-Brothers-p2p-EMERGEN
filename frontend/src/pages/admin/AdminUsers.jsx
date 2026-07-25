import { useEffect, useState, useCallback, useMemo } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { Pagination } from "@/components/Pagination";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";
import AdminPageHeader from "@/components/AdminPageHeader";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";

import UserFunctionsDialog from "./users/UserFunctionsDialog";
import UsersFiltersBar from "./users/UsersFiltersBar";
import UsersTableRow from "./users/UsersTableRow";

const PAGE_SIZE = 50;

export default function AdminUsers() {
  const { t } = useTranslation();
  const { user: currentUser } = useAuth();
  const navigate = useNavigate();

  const ROLE_LABELS = useMemo(() => ({
    normal: t("admin.users.roleNormal"),
    vip: t("admin.users.roleVip"),
    employee: t("admin.users.roleEmployee"),
    admin: t("admin.users.roleAdmin"),
  }), [t]);

  const [users, setUsers] = useState([]);
  const [permCatalog, setPermCatalog] = useState([]);
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [currencies, setCurrencies] = useState([]);
  // Pending 2FA: { user_id, payload, label, kind? } — kept for email verify
  // flow still triggered from the parent (`verifyEmailManually`).
  const [pendingTotp, setPendingTotp] = useState(null);
  // iter55.33 — the consolidated Functions dialog target
  const [functionsUser, setFunctionsUser] = useState(null);

  useEffect(() => { setPage(0); }, [search, roleFilter]);

  // Debounce search input → 300ms
  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchInput.trim()), 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit: PAGE_SIZE, offset: page * PAGE_SIZE };
      if (search) params.q = search;
      if (roleFilter !== "all") params.role = roleFilter;
      const r = await axios.get(`${API}/admin/users`, { params, withCredentials: true });
      setUsers(r.data);
      const tt = Number(r.headers["x-total-count"]);
      setTotal(Number.isFinite(tt) ? tt : r.data.length);
    } catch (e) {
      toast.error(t("admin.users.loadError"));
    } finally {
      setLoading(false);
    }
  }, [page, search, roleFilter, t]);
  useEffect(() => { load(); }, [load]);

  // Load active currencies once
  useEffect(() => {
    axios.get(`${API}/currencies`)
      .then((r) => setCurrencies(r.data || []))
      .catch((err) => {
        if (process.env.NODE_ENV !== "production") {
          console.warn("[admin.users] currencies load failed:", err);
        }
      });
  }, []);

  // iter55.16 — load permission catalog once for the multi-select.
  useEffect(() => {
    axios.get(`${API}/admin/permissions/catalog`, { withCredentials: true })
      .then((r) => setPermCatalog(r.data?.items || []))
      .catch((err) => {
        if (process.env.NODE_ENV !== "production") {
          console.warn("[admin.users] permCatalog load failed:", err);
        }
      });
  }, []);

  const verifyEmailManually = useCallback((user_id, email) =>
    setPendingTotp({
      kind: "verify-email",
      user_id,
      payload: {},
      label: t("admin.users.totpDescriptionVerify", { email }),
    }), [t]);

  const confirmWithTotp = async (code) => {
    const { user_id, payload, kind } = pendingTotp;
    try {
      if (kind === "verify-email") {
        await axios.post(`${API}/admin/users/${user_id}/verify-email`,
          { totp_code: code }, { withCredentials: true });
        toast.success(t("admin.users.emailVerified"));
      } else {
        await axios.put(`${API}/admin/users/${user_id}`,
          { ...payload, totp_code: code }, { withCredentials: true });
        toast.success(t("admin.users.userUpdated"));
      }
      setPendingTotp(null);
      load();
    } catch (e) {
      if (!handleTotpError(e, navigate)) {
        toast.error(
          e.response?.data?.detail?.message || e.response?.data?.detail || t("admin.common.genericError")
        );
      }
    }
  };

  const isAdmin = currentUser?.role === "admin";
  const canManageBlocklist =
    isAdmin ||
    (currentUser?.role === "employee" && !!currentUser?.can_manage_blocklist);
  const allowedRoles = useMemo(() => (
    isAdmin ? ["normal", "vip", "employee", "admin"] : ["normal", "vip"]
  ), [isAdmin]);

  const clearFilters = useCallback(() => {
    setSearchInput("");
    setRoleFilter("all");
  }, []);

  const openStats = useCallback((uid) => navigate(`/admin/users/${uid}/stats`), [navigate]);
  const openFunctions = useCallback((u) => setFunctionsUser(u), []);
  const closeFunctions = useCallback(() => setFunctionsUser(null), []);
  const onUserUpdated = useCallback((fresh) => {
    setFunctionsUser(fresh);
    load();
  }, [load]);
  const closeTotp = useCallback(() => setPendingTotp(null), []);

  return (
    <div data-testid="admin-users" className="space-y-4">
      <AdminPageHeader
        eyebrow={t("admin.users.eyebrow")}
        title={t("admin.users.title")}
        testid="admin-users-header"
      />

      <UsersFiltersBar
        searchInput={searchInput}
        onSearchInputChange={setSearchInput}
        roleFilter={roleFilter}
        onRoleFilterChange={setRoleFilter}
        total={total}
        onClear={clearFilters}
      />

      <div className="tactile-card overflow-x-auto">
        <table className="w-full text-sm min-w-[1020px]">
          <thead className="border-b border-white/10 bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500 whitespace-nowrap">{t("admin.users.colUser")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 whitespace-nowrap">{t("admin.users.colUserId")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.users.colEmail")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.users.colRole")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("admin.users.colKyc")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 whitespace-nowrap">{t("admin.users.colRegistered")}</th>
              <th
                className="px-4 py-3 micro-label text-neutral-500 sticky right-0 bg-[#0a0a0a] z-10 shadow-[-8px_0_12px_-4px_rgba(0,0,0,0.6)]"
                data-testid="admin-users-col-actions"
              >
                {t("admin.users.colActions")}
              </th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan="7" className="text-center text-neutral-500 py-8">{t("admin.common.loadingEllipsis")}</td>
              </tr>
            )}
            {!loading && users.length === 0 && (
              <tr>
                <td colSpan="7" className="text-center text-neutral-500 py-8">{t("admin.users.empty")}</td>
              </tr>
            )}
            {users.map((u) => (
              <UsersTableRow
                key={u.user_id}
                user={u}
                roleLabel={ROLE_LABELS[u.role] || u.role}
                onVerifyEmail={verifyEmailManually}
                onOpenStats={openStats}
                onOpenFunctions={openFunctions}
              />
            ))}
          </tbody>
        </table>
      </div>

      <Pagination
        page={page}
        total={total}
        pageSize={PAGE_SIZE}
        loading={loading}
        onPageChange={setPage}
        testidPrefix="users-pagination"
      />

      <TotpPromptDialog
        open={!!pendingTotp}
        title={t("admin.users.totpTitle")}
        description={pendingTotp?.label || t("admin.users.totpDescriptionUpdate")}
        onConfirm={confirmWithTotp}
        onCancel={closeTotp}
      />

      <UserFunctionsDialog
        user={functionsUser}
        open={!!functionsUser}
        onClose={closeFunctions}
        currencies={currencies}
        permCatalog={permCatalog}
        allowedRoles={allowedRoles}
        isAdmin={isAdmin}
        canManageBlocklist={canManageBlocklist}
        onUserUpdated={onUserUpdated}
      />
    </div>
  );
}
