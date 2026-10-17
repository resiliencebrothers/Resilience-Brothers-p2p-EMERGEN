"""OBS-01 — observabilidad del guard durable `inv_burned` (salud del inventario
Empresa). Solo-lectura para staff con permiso `products`; la poda SEGURA la
ejecuta el scheduler (`run_inv_burned_maintenance`), nunca este endpoint."""
import logging
from typing import Any

from fastapi import APIRouter, Request

from auth_utils import require_permission
from services.company_inventory import inv_burned_stats, INV_BURNED_ALERT_THRESHOLD

logger = logging.getLogger(__name__)
router = APIRouter(tags=["AdminInventoryHealth"])


@router.get("/admin/inventory/guard-stats")
async def admin_inventory_guard_stats(
        request: Request, threshold: int = INV_BURNED_ALERT_THRESHOLD) -> Any:
    """Tamaño del guard `inv_burned` por producto: agregados + productos que
    superan el umbral. Solo-lectura."""
    await require_permission(request, "products")
    return await inv_burned_stats(threshold=threshold)
