/**
 * ProfileSectionTabs — shared sub-navigation for the "Mi Perfil" hub.
 *
 * iter55.26 (Feb 2026): Verificación (KYC) and Seguridad (2FA / sessions) used
 * to live at the top level of the sidebar. Nested them under Mi Perfil.
 *
 * iter55.32: added the "Notificaciones" tab + violet after-underline visual.
 *
 * Jun 2026: mobile swipe hint — on small screens the tab bar overflows and
 * clients had no way to know Seguridad/Notificaciones were reachable by
 * swiping. A right-edge gradient + pulsing chevron (plus a one-line text
 * hint) now shows whenever there is hidden content to the right.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { UserCircle, IdCard, ShieldCheck, Bell, ChevronRight } from "lucide-react";

export default function ProfileSectionTabs() {
  const { t } = useTranslation();
  const scrollRef = useRef(null);
  const [showHint, setShowHint] = useState(false);

  const updateHint = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    setShowHint(el.scrollWidth - el.clientWidth - el.scrollLeft > 12);
  }, []);

  useEffect(() => {
    updateHint();
    window.addEventListener("resize", updateHint);
    return () => window.removeEventListener("resize", updateHint);
  }, [updateHint]);

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
      <div className="relative">
        <nav
          ref={scrollRef}
          onScroll={updateHint}
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
        {showHint && (
          <div
            data-testid="profile-tabs-scroll-hint"
            className="absolute right-0 top-0 bottom-0 w-14 pointer-events-none bg-gradient-to-l from-[#14101F] via-[#14101F]/70 to-transparent flex items-center justify-end pr-1"
          >
            <ChevronRight className="w-4 h-4 text-violet-400 animate-pulse" />
          </div>
        )}
      </div>
      {showHint && (
        <div
          className="sm:hidden text-[0.65rem] text-violet-400/80 mt-1.5 flex items-center gap-1"
          data-testid="profile-tabs-swipe-text"
        >
          {t("profile.tabsSwipeHint")} <ChevronRight className="w-3 h-3" />
        </div>
      )}
    </div>
  );
}
