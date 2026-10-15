"""E34-06 — reconciliación RECUPERABLE de cancelaciones de envíos Empresa.

Cuando una entrega de `company_delivery` queda CANCELADA (por el admin, por la
propia Empresa o por recuperación), la solicitud debe: (1) reembolsar la tarifa
retenida y (2) devolver el inventario reservado — EXACTAMENTE UNA VEZ.

Antes esto solo ocurría de forma perezosa al abrir `GET /company/deliveries`
(y como mucho sobre las 200 solicitudes más recientes). Este módulo centraliza
la reconciliación idempotente para invocarla desde: el listado, la cancelación
administrativa (inline) y un worker periódico del scheduler — de modo que la
compensación no dependa de que la Empresa abra su pantalla.
"""
import logging

from db_client import db
from auth_utils import now_utc, iso
from services import company_delivery_billing as billing
from services import company_inventory

logger = logging.getLogger(__name__)


async def return_delivery_inventory(req: dict) -> bool:
    """E34-05 — devuelve el inventario reservado y CONFIRMA el resultado. Si la
    tienda de origen ya no existe, el motor lo devuelve al almacén central. Si
    NO se pudo devolver (p. ej. el producto fue borrado → `not_found`), NO se
    sella éxito: registra una INCIDENCIA (idempotente) para gestión manual y
    deja la devolución PENDIENTE. Devuelve True solo si se devolvió de verdad."""
    company_id = req["company_id"]
    status = await company_inventory.return_dispatch(
        company_id, req["product_id"], req["origin_store_id"],
        req["quantity"], op_id=f"cdeliv-ret:{req['id']}")
    if status == "applied":
        await company_inventory.maybe_alert_store_out_of_stock(
            company_id, req["product_id"], req["origin_store_id"])
        return True
    await db.company_delivery_requests.update_one(
        {"id": req["id"], "inv_return_incident": {"$ne": True}},
        {"$set": {"inv_return_incident": True,
                  "inv_return_incident_reason": status,
                  "inv_return_incident_at": iso(now_utc())}})
    did = req.get("delivery_id")
    if did:
        from services.deliveries import flag_origin_conflict
        await flag_origin_conflict(
            did, "company_delivery", req["id"],
            note=("No se pudo devolver el inventario reservado "
                  f"({status}); requiere ajuste manual del stock."))
    return False


async def reconcile_cancelled_request(req: dict) -> bool:
    """Reconcilia EXACTAMENTE UNA VEZ una solicitud cuyo envío quedó cancelado:
    reembolsa la tarifa retenida y devuelve el inventario reservado. Idempotente
    (reembolso/devolución por op_id ligado al reqid; flags que no se repiten).
    Muta `req` in situ para que la respuesta refleje el estado ya aplicado en
    esta misma lectura. Devuelve True si cambió algo."""
    company_id = req.get("company_id")
    if not company_id:
        return False
    updates: dict = {}
    if req.get("fee_status") == "held":
        await billing.refund_fee(company_id, req["id"],
                                 float(req.get("fee_usdt") or 0))
        updates["fee_status"] = "refunded"
    if req.get("inv_reserved") and not req.get("inv_returned") \
            and req.get("product_id") and req.get("origin_store_id"):
        if await return_delivery_inventory(req):
            updates["inv_returned"] = True
    if not updates:
        return False
    updates["status"] = "cancelled"
    updates["updated_at"] = iso(now_utc())
    await db.company_delivery_requests.update_one(
        {"id": req["id"]}, {"$set": updates})
    req.update(updates)
    return True


async def heal_cancelled_company_deliveries(limit: int = 300) -> int:
    """E34-06 — worker recuperable: reconcilia envíos Empresa cuya ENTREGA quedó
    cancelada pero cuya compensación (tarifa/stock) sigue pendiente, SIN depender
    de que la Empresa abra su pantalla ni de cuántas solicitudes recientes haya.
    Solo compensa cuando la entrega vinculada está realmente `cancelled`."""
    rows = await db.company_delivery_requests.find(
        {"status": "requested",
         "$or": [
             {"fee_status": "held"},
             {"inv_reserved": True, "inv_returned": {"$ne": True},
              "inv_return_incident": {"$ne": True}},
         ]},
        {"_id": 0}).to_list(limit)
    healed = 0
    for r in rows:
        did = r.get("delivery_id")
        if not did:
            continue  # sin entrega → lo cubre heal_initializing_company_deliveries
        d = await db.deliveries.find_one({"id": did}, {"_id": 0, "status": 1})
        if not d or d.get("status") != "cancelled":
            continue  # la entrega sigue activa → NO compensar
        try:
            if await reconcile_cancelled_request(r):
                healed += 1
                logger.warning(
                    "[cdeliv-cancel-recover] envío Empresa reconciliado: %s", r["id"])
        except Exception as e:  # noqa: BLE001
            logger.error("[cdeliv-cancel-recover] falló %s: %s", r.get("id"), e)
    return healed
