"""iter55.16 — Granular per-staff permissions catalog + pure predicates.

Rationale: prior to this iter, employees were gated by `role="employee"` only.
The admin could restrict them to specific currencies via `allowed_currencies`,
but every employee had access to every staff function (orders, KYC, withdrawals,
company funds, etc.). This iter introduces a fine-grained capability system so
admins can assign focused responsibilities to each team member.

Semantics (STAFF-01 — DENY-BY-DEFAULT desde la auditoría 26-10-2026):
- Admins always pass (they are the root role).
- Employees pass ONLY the codes granted EXPLÍCITAMENTE in `allowed_permissions`.
  An empty list OR an absent field = NO access. Removing the last permission no
  longer widens access — it leaves the employee with no functions until an admin
  grants new ones.
- Any missing code returns 403 naming the permission that is missing so the
  admin can grant it in one click.

The catalog below is the single source of truth. Any admin route that needs
a gate should call `await require_permission(request, "code")` — the HTTP
gate lives in `auth_utils` to avoid a circular import (this module stays a
pure data + predicate layer with zero FastAPI dependencies).
"""
from typing import Any, Dict, List


# Codes are stable strings — do NOT rename them once persisted in user docs.
# iter108.2 — added `category` field so the admin UI can group permissions.
# Category codes are stable too; frontend maps them to display metadata.
PERMISSION_CATALOG: List[Dict[str, str]] = [
    {"code": "orders",           "category": "operations", "label": "Órdenes",              "description": "Aprobar / rechazar / gestionar órdenes P2P"},
    {"code": "withdrawals",      "category": "operations", "label": "Retiros VIP",          "description": "Aprobar retiros de saldo VIP"},
    {"code": "deliveries",       "category": "operations", "label": "Mensajería",           "description": "Ver y gestionar entregas: confirmar, cancelar, incidencias, caja y mensajeros (NO incluye asignar repartos)"},
    {"code": "deliveries_assign", "category": "operations", "label": "Asignar mensajería",    "description": "Asignar/reservar repartos a un mensajero. Un mensajero que solo hace entregas NO debe tener este permiso"},
    {"code": "kyc",              "category": "operations", "label": "Verificación KYC",     "description": "Revisar y aprobar verificaciones de identidad"},
    {"code": "appeals",          "category": "operations", "label": "Apelaciones",          "description": "Revisar apelaciones self-service de usuarios"},
    {"code": "profile_changes",  "category": "operations", "label": "Cambios de datos",     "description": "Aprobar cambios de teléfono/email solicitados por clientes"},
    {"code": "products",         "category": "catalog",    "label": "Productos",            "description": "Crear / editar / eliminar productos del marketplace"},
    {"code": "rates",            "category": "catalog",    "label": "Tasas",                "description": "Ajustar tasas de cambio (reales y comisiones)"},
    {"code": "currencies",       "category": "catalog",    "label": "Monedas",              "description": "Añadir / editar / ocultar monedas"},
    {"code": "payment_accounts", "category": "catalog",    "label": "Cuentas de cobro",     "description": "Gestionar las cuentas a las que los clientes envían sus pagos (por monto)"},
    {"code": "users",            "category": "users",      "label": "Usuarios",             "description": "Ver la lista de usuarios (sin datos sensibles ni funciones)"},
    {"code": "user_stats",       "category": "users",      "label": "Estadísticas de usuario", "description": "Ver la página de estadísticas detalladas de un cliente (saldo, deudas, KYC, teléfono)"},
    {"code": "user_functions",   "category": "users",      "label": "Funciones de usuario", "description": "Modificar rol, permisos, monedas y accesos del marketplace de un usuario"},
    {"code": "view_user_sensitive", "category": "users",   "label": "Datos sensibles del usuario", "description": "Ver teléfonos, saldos y comisiones en la lista de usuarios"},
    {"code": "support",          "category": "users",      "label": "Soporte",              "description": "Responder tickets de soporte de clientes y editar el FAQ"},
    {"code": "blocked_contacts", "category": "users",      "label": "Bloqueos",             "description": "Gestionar la lista de contactos bloqueados"},
    {"code": "vip_requests",     "category": "users",      "label": "Solicitudes VIP",      "description": "Revisar y aprobar / rechazar solicitudes de upgrade a VIP"},
    {"code": "company_requests", "category": "users",      "label": "Solicitudes Empresa",  "description": "Revisar y aprobar / rechazar solicitudes de alta del Programa Empresas (crea una cuenta Empresa nueva)"},
    {"code": "company_funds",    "category": "finance",    "label": "Fondo Empresa",        "description": "Registrar aportes / retiros de capital"},
    {"code": "reconciliation",   "category": "finance",    "label": "Conciliación Bancaria", "description": "Importar extractos bancarios y conciliar pagos contra órdenes pendientes"},
    {"code": "profitability",    "category": "finance",    "label": "Cálculo de Rentabilidad", "description": "Calculadora de rentabilidad por conversión y registro de operaciones"},
    {"code": "transactions",     "category": "finance",    "label": "Registro Contable",    "description": "Ver el registro de transacciones (auditoría)"},
    {"code": "quick_view",       "category": "finance",    "label": "Vista Rápida / Cola",  "description": "Acceso a la vista rápida y a mi cola de trabajo"},
]

VALID_CODES = {p["code"] for p in PERMISSION_CATALOG}

# MEN-01 (histórico) — antes, la «lista vacía = acceso total» excluía estos
# códigos sensibles. Desde STAFF-01 el modelo es DENY-BY-DEFAULT: TODO código,
# incluido `deliveries_assign`, requiere concesión explícita. Se conserva la
# constante por compatibilidad de importación/semántica de negocio.
EXPLICIT_GRANT_CODES = {"deliveries_assign"}


def _has_permission(user: dict, code: str) -> bool:
    """Pure predicate — testable without HTTP context.

    STAFF-01 (auditoría 26-10-2026) — DENY-BY-DEFAULT: un empleado solo pasa los
    códigos concedidos EXPLÍCITAMENTE en `allowed_permissions`. Una lista vacía o
    ausente = SIN acceso (ya NO significa «acceso total»). Los admins, como rol
    raíz, siguen pasando siempre."""
    role = user.get("role")
    if role == "admin":
        return True
    if role != "employee":
        return False
    return code in (user.get("allowed_permissions") or [])


def permission_label(code: str) -> str:
    """Human-readable label for a code (falls back to the code itself)."""
    return next((p["label"] for p in PERMISSION_CATALOG if p["code"] == code), code)


def sanitize_permissions(raw: Any) -> List[str]:
    """Filter incoming permissions payload to valid codes only. Never trust
    the client — reject anything not in the catalog."""
    if not isinstance(raw, list):
        return []
    return [p for p in raw if isinstance(p, str) and p in VALID_CODES]
