"""iter55.16 — Granular per-staff permissions catalog + pure predicates.

Rationale: prior to this iter, employees were gated by `role="employee"` only.
The admin could restrict them to specific currencies via `allowed_currencies`,
but every employee had access to every staff function (orders, KYC, withdrawals,
company funds, etc.). This iter introduces a fine-grained capability system so
admins can assign focused responsibilities to each team member.

Semantics:
- Admins always pass (they are the root role).
- Employees with `allowed_permissions=[]` (empty list OR field absent) pass
  everything — **backward compatible** default. Existing employees keep working
  without any admin action.
- Employees with a non-empty list pass ONLY the codes in the list. Everything
  else returns 403 with a clear message so they know which permission is
  missing.

The catalog below is the single source of truth. Any admin route that needs
a gate should call `await require_permission(request, "code")` — the HTTP
gate lives in `auth_utils` to avoid a circular import (this module stays a
pure data + predicate layer with zero FastAPI dependencies).
"""
from typing import Any, Dict, List


# Codes are stable strings — do NOT rename them once persisted in user docs.
PERMISSION_CATALOG: List[Dict[str, str]] = [
    {"code": "orders",           "label": "Órdenes",              "description": "Aprobar / rechazar / gestionar órdenes P2P"},
    {"code": "withdrawals",      "label": "Retiros VIP",          "description": "Aprobar retiros de saldo VIP"},
    {"code": "kyc",              "label": "Verificación KYC",     "description": "Revisar y aprobar verificaciones de identidad"},
    {"code": "appeals",          "label": "Apelaciones",          "description": "Revisar apelaciones self-service de usuarios"},
    {"code": "products",         "label": "Productos",            "description": "Crear / editar / eliminar productos del marketplace"},
    {"code": "rates",            "label": "Tasas",                "description": "Ajustar tasas de cambio (reales y comisiones)"},
    {"code": "currencies",       "label": "Monedas",              "description": "Añadir / editar / ocultar monedas"},
    {"code": "users",            "label": "Usuarios",             "description": "Ver la lista de usuarios (sin datos sensibles ni funciones)"},
    {"code": "user_stats",       "label": "Estadísticas de usuario", "description": "Ver la página de estadísticas detalladas de un cliente (saldo, deudas, KYC, teléfono)"},
    {"code": "user_functions",   "label": "Funciones de usuario", "description": "Modificar rol, permisos, monedas y accesos del marketplace de un usuario"},
    {"code": "view_user_sensitive", "label": "Datos sensibles del usuario", "description": "Ver teléfonos, saldos y comisiones en la lista de usuarios"},
    {"code": "company_funds",    "label": "Fondo Empresa",        "description": "Registrar aportes / retiros de capital"},
    {"code": "blocked_contacts", "label": "Bloqueos",             "description": "Gestionar la lista de contactos bloqueados"},
    {"code": "transactions",     "label": "Registro Contable",    "description": "Ver el registro de transacciones (auditoría)"},
    {"code": "quick_view",       "label": "Vista Rápida / Cola",  "description": "Acceso a la vista rápida y a mi cola de trabajo"},
    {"code": "profile_changes",  "label": "Cambios de datos",     "description": "Aprobar cambios de teléfono/email solicitados por clientes"},
]

VALID_CODES = {p["code"] for p in PERMISSION_CATALOG}


def _has_permission(user: dict, code: str) -> bool:
    """Pure predicate — testable without HTTP context."""
    role = user.get("role")
    if role == "admin":
        return True
    if role != "employee":
        return False
    # Empty / missing list = "no restriction" (backward compatible default).
    perms = user.get("allowed_permissions") or []
    if not perms:
        return True
    return code in perms


def permission_label(code: str) -> str:
    """Human-readable label for a code (falls back to the code itself)."""
    return next((p["label"] for p in PERMISSION_CATALOG if p["code"] == code), code)


def sanitize_permissions(raw: Any) -> List[str]:
    """Filter incoming permissions payload to valid codes only. Never trust
    the client — reject anything not in the catalog."""
    if not isinstance(raw, list):
        return []
    return [p for p in raw if isinstance(p, str) and p in VALID_CODES]
