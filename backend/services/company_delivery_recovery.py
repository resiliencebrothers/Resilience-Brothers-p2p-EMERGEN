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


async def _compensate_request_effects(req: dict) -> dict:
    """Compensa tarifa e inventario basándose en EFECTOS DURADEROS, nunca en
    flags que puedan ir atrasados (R02). Devuelve los campos a sellar.

    - Tarifa: SIEMPRE se reconcilia (`refund_fee` deja el saldo correcto tanto si
      el débito fue real como si nunca movió dinero) y se sella el estado
      VERDADERO: 'refunded' (débito real devuelto), 'void' (nunca cobró) o
      'none'. Si la reconciliación no concluye, NO se sella (reintentable).
    - Inventario: se devuelve SOLO si la reserva se aplicó de forma DURADERA
      (`dispatch_applied`). Si nunca se reservó, no hay stock que devolver y se
      marca `inv_returned` (no se añade inventario fantasma). Si la devolución
      no se pudo aplicar (producto borrado…), `return_delivery_inventory` deja
      una incidencia y NO se sella éxito."""
    cid, reqid = req["company_id"], req["id"]
    fee = float(req.get("fee_usdt") or 0)
    updates: dict = {}
    if req.get("fee_status") not in ("refunded", "void", "none"):
        res = await billing.refund_fee(cid, reqid, fee)
        if fee <= 0:
            updates["fee_status"] = "none"
        elif res == "undone":
            updates["fee_status"] = "refunded"
        elif res == "burned":
            updates["fee_status"] = "void"
        # cualquier otro resultado → no sellar (se reintenta la próxima pasada)
    if not req.get("inv_returned") and req.get("product_id") \
            and req.get("origin_store_id"):
        if await company_inventory.dispatch_applied(cid, f"cdeliv:{reqid}"):
            if await return_delivery_inventory(req):
                updates["inv_returned"] = True
            # si no se pudo devolver → incidencia dejada por return_delivery_inventory
        else:
            # la reserva nunca se aplicó de forma duradera → nada que devolver
            updates["inv_returned"] = True
    return updates


async def reconcile_cancelled_request(req: dict) -> bool:
    """Reconcilia EXACTAMENTE UNA VEZ una solicitud cuyo envío quedó cancelado:
    reembolsa la tarifa retenida y devuelve el inventario reservado, basándose en
    EFECTOS DURADEROS (R02). Idempotente. Muta `req` in situ para que la respuesta
    refleje el estado ya aplicado en esta misma lectura. True si cambió algo."""
    company_id = req.get("company_id")
    if not company_id:
        return False
    updates = await _compensate_request_effects(req)
    if not updates:
        return False
    updates["status"] = "cancelled"
    updates["updated_at"] = iso(now_utc())
    await db.company_delivery_requests.update_one(
        {"id": req["id"]}, {"$set": updates})
    req.update(updates)
    return True


async def heal_cancelled_company_deliveries(limit: int = 300) -> int:
    """E34-06/R07 — worker recuperable: reconcilia envíos Empresa cuya ENTREGA
    quedó cancelada pero cuya compensación (tarifa/stock) sigue pendiente, SIN
    depender de que la Empresa abra su pantalla.

    R07 — el filtrado por entrega cancelada se hace mediante un JOIN explícito
    ($lookup) ANTES de aplicar el límite, de modo que una avalancha de
    solicitudes ACTIVAS no pueda desplazar indefinidamente a una cancelada: el
    pipeline selecciona únicamente candidatas cuya entrega vinculada está
    realmente `cancelled`."""
    pipeline = [
        {"$match": {
            "status": "requested",
            "delivery_id": {"$ne": None},
            "$or": [
                {"fee_status": "held"},
                {"inv_reserved": True, "inv_returned": {"$ne": True},
                 "inv_return_incident": {"$ne": True}},
            ]}},
        {"$lookup": {
            "from": "deliveries", "localField": "delivery_id",
            "foreignField": "id", "as": "_d"}},
        {"$match": {"_d.status": "cancelled"}},
        {"$limit": limit},
        {"$project": {"_d": 0, "_id": 0}},
    ]
    rows = await db.company_delivery_requests.aggregate(pipeline).to_list(limit)
    healed = 0
    for r in rows:
        try:
            if await reconcile_cancelled_request(r):
                healed += 1
                logger.warning(
                    "[cdeliv-cancel-recover] envío Empresa reconciliado: %s", r["id"])
        except Exception as e:  # noqa: BLE001
            logger.error("[cdeliv-cancel-recover] falló %s: %s", r.get("id"), e)
    return healed
