import ProfileSectionTabs from "@/components/ProfileSectionTabs";
import PushToggle from "@/components/PushToggle";
import { Bell, Info } from "lucide-react";

/**
 * iter55.32 — Notifications tab inside "Mi Perfil". Elevates the push toggle
 * from a tiny sidebar-footer widget to a proper account page. Discoverable,
 * with context text so users understand what they're enabling.
 */
export default function NotificationsView() {
  return (
    <div className="space-y-6" data-testid="notifications-view">
      <ProfileSectionTabs />

      <div className="tactile-card p-6" data-testid="push-notifications-block">
        <div className="flex items-start gap-3 mb-5">
          <div className="w-10 h-10 rounded-lg bg-violet-500/10 border border-violet-500/20 flex items-center justify-center">
            <Bell className="w-5 h-5 text-violet-400" />
          </div>
          <div>
            <h2 className="font-display text-xl">Notificaciones push</h2>
            <p className="text-sm text-neutral-500 mt-1">
              Recibe alertas al instante cuando el equipo apruebe tu orden, entregue tu retiro o solicite información adicional.
            </p>
          </div>
        </div>

        <PushToggle />

        <div className="mt-6 border-t border-white/5 pt-4">
          <div className="flex items-start gap-2 text-xs text-neutral-500 leading-relaxed">
            <Info className="w-3.5 h-3.5 mt-0.5 shrink-0 text-violet-400/70" />
            <span>
              Las notificaciones funcionan aunque cierres esta pestaña. En iOS,
              necesitas <strong>añadir la web a tu pantalla de inicio</strong> desde
              Safari (icono de compartir → &ldquo;Añadir a pantalla de inicio&rdquo;) y luego
              activarlas desde la app instalada.
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
