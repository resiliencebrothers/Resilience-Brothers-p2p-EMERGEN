/**
 * ProfileSectionTabs — shared sub-navigation for the "Mi Perfil" hub.
 *
 * iter55.26 (Feb 2026): Verificación (KYC) and Seguridad (2FA / sessions) used
 * to live at the top level of the sidebar. The owner asked to nest them
 * under Mi Perfil since they're all "account settings" from the user's POV.
 *
 * Rather than merge the 3 pages into one giant component (would explode
 * ProfileView.jsx which is already 500 LOC), we keep each page as-is and
 * render a shared tab strip at the top. Clicking a tab is a real react-router
 * navigation — bookmark/share links to `/dashboard/kyc` still work exactly as
 * before, they just render under the same visual header now.
 */
import { NavLink } from "react-router-dom";
import { UserCircle, IdCard, ShieldCheck } from "lucide-react";

const TABS = [
  { to: "/dashboard/profile",  icon: UserCircle,  label: "Datos personales", end: true, testid: "profile-tab-datos" },
  { to: "/dashboard/kyc",      icon: IdCard,      label: "Verificación",     end: true, testid: "profile-tab-kyc" },
  { to: "/dashboard/security", icon: ShieldCheck, label: "Seguridad",        end: true, testid: "profile-tab-security" },
];

export default function ProfileSectionTabs() {
  return (
    <div className="mb-6" data-testid="profile-section-tabs">
      <div className="micro-label text-[#EAB308] mb-2">/ Mi Perfil</div>
      <div
        className="flex gap-1 border-b border-white/10 overflow-x-auto no-scrollbar"
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
              "flex items-center gap-2 px-4 py-2.5 text-sm border-b-2 -mb-px transition-colors " +
              (isActive
                ? "border-[#EAB308] text-[#EAB308]"
                : "border-transparent text-neutral-400 hover:text-white hover:border-white/20")
            }
          >
            <Icon className="w-4 h-4" />
            <span>{label}</span>
          </NavLink>
        ))}
      </div>
    </div>
  );
}
