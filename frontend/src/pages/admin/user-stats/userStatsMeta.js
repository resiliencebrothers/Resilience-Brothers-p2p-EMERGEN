/** Shared helpers + label maps for the AdminUserStats subcomponents. */
import { CheckCircle2, Clock, IdCard, XCircle } from "lucide-react";

export const fmtNum = (n, digits = 2) =>
  Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: digits });

export const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString() : "—");

export const STATUS_META = {
  active: { label: "Activo", cls: "text-emerald-400" },
  under_review: { label: "En revisión", cls: "text-amber-400" },
  blocked: { label: "Bloqueado", cls: "text-red-400" },
};

export const KYC_META = {
  approved:    { label: "Aprobado",   cls: "text-emerald-400", icon: CheckCircle2 },
  pending:     { label: "Pendiente",  cls: "text-amber-400",   icon: Clock },
  rejected:    { label: "Rechazado",  cls: "text-red-400",     icon: XCircle },
  not_started: { label: "Sin iniciar",cls: "text-neutral-500", icon: IdCard },
};

export const ROLE_LABELS = {
  normal: "Normal",
  vip: "VIP",
  employee: "Staff",
  admin: "Admin",
};
