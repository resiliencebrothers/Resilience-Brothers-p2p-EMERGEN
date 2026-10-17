"""OBS-01 — observabilidad del guard durable `inv_burned` (salud del inventario
Empresa). Solo-lectura para staff con permiso `products`; la poda SEGURA la
ejecuta el scheduler (`run_inv_burned_maintenance`), nunca este endpoint."""
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from auth_utils import require_permission
from services.company_inventory import (
    inv_burned_stats, inv_burned_product_detail, inventory_abort_metrics,
    INV_BURNED_ALERT_THRESHOLD)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["AdminInventoryHealth"])


@router.get("/admin/inventory/guard-stats")
async def admin_inventory_guard_stats(
        request: Request, threshold: int = INV_BURNED_ALERT_THRESHOLD) -> Any:
    """Tamaño del guard `inv_burned` por producto (agregados + productos sobre
    umbral) + métricas de reservas abortadas/tardías bloqueadas. Solo-lectura."""
    await require_permission(request, "products")
    stats = await inv_burned_stats(threshold=threshold)
    stats["abort_metrics"] = await inventory_abort_metrics()
    return stats


@router.get("/admin/inventory/guard-detail/{product_id}")
async def admin_inventory_guard_detail(request: Request, product_id: str) -> Any:
    """Detalle de los candados `inv_burned` de un producto (op_id, tipo,
    resultado, bloqueo tardío, podable). Solo-lectura."""
    await require_permission(request, "products")
    detail = await inv_burned_product_detail(product_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return detail
