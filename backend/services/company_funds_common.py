"""Helpers de permisos compartidos entre los módulos de fondos de la empresa
(`routes/admin_company_funds.py` y `routes/company_fund_accounts.py`).

Extraído a services/ para eliminar los imports cruzados entre ambos routers
(hallazgo del code review — acoplamiento circular vía lazy imports).
"""
from typing import Any, Dict, List, Optional

from fastapi import HTTPException


async def assert_can_manage_company_funds(actor: dict) -> None:
    """iter54 — Admin siempre; empleados necesitan can_manage_company_funds=True
    O (iter55.16) el permiso `company_funds` en allowed_permissions."""
    if actor.get("role") == "admin":
        return
    if actor.get("role") == "employee":
        perms = actor.get("allowed_permissions") or []
        if not perms or "company_funds" in perms:
            return
        if actor.get("can_manage_company_funds"):
            return
    raise HTTPException(
        status_code=403,
        detail=(
            "No tienes permiso para gestionar los fondos de la empresa. "
            "Pídeselo a un administrador."
        ),
    )


def actor_currency_scope(actor: Dict[str, Any]) -> Optional[List[str]]:
    """Restricción `allowed_currencies` del empleado (None = sin restricción)."""
    if actor.get("role") != "employee":
        return None
    return actor.get("allowed_currencies") or None
