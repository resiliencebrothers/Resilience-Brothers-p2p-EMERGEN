import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { AlertTriangle, ArrowLeft, ShieldCheck } from "lucide-react";
import UserStatsHero from "./user-stats/UserStatsHero";
import NetPositionCard from "./user-stats/NetPositionCard";
import UserStatsPersonal from "./user-stats/UserStatsPersonal";
import UserStatsKpis from "./user-stats/UserStatsKpis";
import BalanceBreakdown from "./user-stats/BalanceBreakdown";
import CapitalDebtsSection from "./user-stats/CapitalDebtsSection";
import AuditTrailSection from "./user-stats/AuditTrailSection";

/**
 * iter55.32 — Admin/staff drill-down for one specific user. Reachable from
 * the "Ver estadísticas" button in AdminUsers row. Uses the
 * `/api/admin/users/{id}/stats` aggregate endpoint.
 */
export default function AdminUserStatsPage() {
  const { userId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const r = await axios.get(`${API}/admin/users/${userId}/stats`, { withCredentials: true });
        if (!cancelled) setData(r.data);
      } catch (e) {
        const status = e.response?.status;
        const detail = e.response?.data?.detail;
        if (status === 403) {
          toast.error(typeof detail === "string"
            ? detail
            : "Acceso restringido — pídele a un admin el permiso 'Estadísticas de usuario'.");
        } else if (status === 404) {
          toast.error(typeof detail === "string" ? detail : "Usuario no encontrado.");
        } else {
          toast.error(typeof detail === "string" ? detail : "No se pudieron cargar las estadísticas.");
        }
        navigate("/admin/users");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [userId, navigate]);

  if (loading) {
    return <div className="p-6 text-neutral-500" data-testid="user-stats-loading">Cargando…</div>;
  }
  if (!data) return null;

  const { user, kyc, balances, balance_total_usdt, orders, capital, net_position } = data;

  return (
    <div className="space-y-6" data-testid="admin-user-stats-page">
      <UserStatsHero user={user} onBack={() => navigate("/admin/users")} />
      <NetPositionCard netPosition={net_position} />
      <UserStatsPersonal user={user} kyc={kyc} />
      <UserStatsKpis orders={orders} balanceTotalUsdt={balance_total_usdt} />
      <BalanceBreakdown balances={balances} />
      <CapitalDebtsSection capital={capital} />
      <AuditTrailSection
        userId={userId}
        onOpenInAudit={() => navigate(`/admin/audit?tab=by-user&user_id=${userId}`)}
      />

      <div className="flex gap-2 flex-wrap">
        <Button
          onClick={() => navigate("/admin/users")}
          className="rounded-none bg-transparent border border-white/15 text-white hover:bg-white/5"
          data-testid="user-stats-goto-users-btn"
        >
          <ArrowLeft className="w-4 h-4 mr-2" /> Lista de usuarios
        </Button>
        <Button
          onClick={() => navigate("/admin/company-funds?tab=requests")}
          className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white"
          data-testid="user-stats-goto-requests-btn"
        >
          <ShieldCheck className="w-4 h-4 mr-2" /> Ver todas las solicitudes de capital
        </Button>
      </div>

      {net_position.net_usdt < 0 && (
        <div className="border-l-4 border-amber-500 bg-amber-500/5 p-4 flex gap-3">
          <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
          <div className="text-sm text-amber-200/90">
            Este cliente <strong>tiene deuda pendiente</strong> con la empresa. Sus próximas
            órdenes acumuladas se descontarán automáticamente según el porcentaje configurado
            en cada solicitud hasta cerrar el balance.
          </div>
        </div>
      )}
    </div>
  );
}
