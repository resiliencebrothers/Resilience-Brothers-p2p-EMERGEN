/**
 * ProfileSectionTabs — shared sub-navigation for the "Mi Perfil" hub.
 *
 * iter55.26 (Feb 2026): Verificación (KYC) and Seguridad (2FA / sessions) used
 * to live at the top level of the sidebar. Nested them under Mi Perfil.
 *
 * iter55.32: added the "Notificaciones" tab (elevated PushToggle from tiny
 * sidebar-footer widget to a proper page) + rewrote the visual to match the
 * admin AdminUsersHub — violet after-underline, aria-selected, focus rings.
 * Rather than merge the 4 pages into one giant component, we keep each as
 * its own route so bookmarks `/dashboard/kyc`, `/dashboard/security`, etc.
 * still work exactly as before.
 */
import { NavLink } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { UserCircle, IdCard, ShieldCheck, Bell } from "lucide-react";

export default function ProfileSectionTabs() {
  const { t } = useTranslation();
  const TABS = [
    { to: "/dashboard/profile",       icon: UserCircle,  label: t("profile.tabs.personal"),      end: true, testid: "profile-tab-datos" },
    { to: "/dashboard/kyc",           icon: IdCard,      label: t("profile.tabs.kyc"),           end: true, testid: "profile-tab-kyc" },
    { to: "/dashboard/security",      icon: ShieldCheck, label: t("profile.tabs.security"),      end: true, testid: "profile-tab-security" },
    { to: "/dashboard/notifications", icon: Bell,        label: t("profile.tabs.notifications"), end: true, testid: "profile-tab-notifications" },
  ];
  return (
    <div className="mb-6" data-testid="profile-section-tabs">
      <div className="text-[11px] font-semibold tracking-[0.22em] text-violet-400 uppercase mb-2">
        {t("profile.breadcrumb")}
      </div>
      <nav
        className="flex items-center gap-1 border-b border-white/10 overflow-x-auto scrollbar-none"
        role="tablist"
        aria-label="Secciones de mi perfil"
      >
        {TABS.map(({ to, icon: Icon, label, end, testid }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            role="tab"
            data-testid={testid}
            className={({ isActive }) =>
              "relative flex items-center gap-2 px-4 py-2.5 text-sm font-medium whitespace-nowrap " +
              "transition-all duration-200 outline-none focus-visible:ring-2 focus-visible:ring-violet-500 " +
              (isActive
                ? "text-violet-300 after:absolute after:left-3 after:right-3 after:-bottom-[1px] after:h-[2px] after:bg-violet-500 after:rounded-full"
                : "text-white/50 hover:text-white hover:bg-white/[0.03] rounded-md")
            }
            aria-selected={undefined /* NavLink handles active state visually */}
          >
            <Icon className="w-4 h-4" />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
