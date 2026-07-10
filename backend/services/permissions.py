"""iter55.16 — Granular per-staff permissions catalog + gate helper.

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
a gate should call `await require_permission(request, "code")`.
"""
from typing import Any, Dict, List

from fastapi import HTTPException, Request


# Codes are stable strings — do NOT rename them once persisted in user docs.
PERMISSION_CATALOG: List[Dict[str, str]] = [
    {"code": "orders",           "label": "Órdenes",              "description": "Aprobar / rechazar / gestionar órdenes P2P"},
    {"code": "withdrawals",      "label": "Retiros VIP",          "description": "Aprobar retiros de saldo VIP"},
    {"code": "kyc",              "label": "Verificación KYC",     "description": "Revisar y aprobar verificaciones de identidad"},
    {"code": "appeals",          "label": "Apelaciones",          "description": "Revisar apelaciones self-service de usuarios"},
    {"code": "products",         "label": "Productos",            "description": "Crear / editar / eliminar productos del marketplace"},
    {"code": "rates",            "label": "Tasas",                "description": "Ajustar tasas de cambio (reales y comisiones)"},
    {"code": "currencies",       "label": "Monedas",              "description": "Añadir / editar / ocultar monedas"},
    {"code": "users",            "label": "Usuarios",             "description": "Ver / editar usuarios (no puede tocar admins)"},
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


async def require_permission(request: Request, code: str) -> dict:
    """Gate an admin/staff endpoint by a specific permission code.

    Admins bypass. Employees pass if their `allowed_permissions` is empty OR
    contains the code. Everything else → 403 with a message that names the
    missing permission (so the admin can grant it in 1 click).

    Usage:
        actor = await require_permission(request, "kyc")
    """
    # Local import avoids a circular import at module load (auth_utils imports
    # from this module for the /me endpoint enrichment).
    from auth_utils import require_user

    if code not in VALID_CODES:
        # Programmer error — refuse silently in prod, loud in tests.
        raise HTTPException(status_code=500, detail=f"unknown_permission_code:{code}")

    user = await require_user(request)
    if _has_permission(user, code):
        return user

    role = user.get("role")
    if role not in ("admin", "employee"):
        raise HTTPException(status_code=403, detail="Staff only")

    # Employee without the required permission — explain clearly.
    label = next((p["label"] for p in PERMISSION_CATALOG if p["code"] == code), code)
    raise HTTPException(
        status_code=403,
        detail=(
            f"No tienes el permiso '{label}' asignado. "
            f"Contacta al admin para que te lo habilite."
        ),
    )


def sanitize_permissions(raw: Any) -> List[str]:
    """Filter incoming permissions payload to valid codes only. Never trust
    the client — reject anything not in the catalog."""
    if not isinstance(raw, list):
        return []
    return [p for p in raw if isinstance(p, str) and p in VALID_CODES]
