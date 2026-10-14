"""Inventario por ubicación de la Empresa — Fase 2 (EMP-02).

Modelo NO disruptivo sobre el producto de la Empresa (`products`, company_id):
- `stock`      = TOTAL que tiene la Empresa (fuente de verdad; las ventas del
                 marketplace lo decrementan por la vía existente, intacta).
- `by_store`   = mapa {store_id: cantidad} DISTRIBUIDA a cada tienda.
- `distributed`= suma de `by_store` (se mantiene en la misma escritura atómica).
- ALMACÉN CENTRAL (lo distribuible) = stock − distributed  (derivado en lectura).

Operaciones (todas atómicas en UN solo documento del producto e idempotentes
por `op_id` vía el guard `inv_ops`):
- receive  : +stock           (recibir mercancía en el almacén central).
- distribute: central → tienda (by_store[sid] += q, distributed += q; exige
              central ≥ q, si no → 'insufficient').
- return   : tienda → central  (by_store[sid] -= q; exige by_store[sid] ≥ q).

No toca `products.stock` en distribute/return (solo reubica), por lo que NUNCA
entra en conflicto con el decremento de stock de una venta.
"""
import uuid
import logging
from typing import Any, Optional

from pymongo import ReturnDocument

from db_client import db
from auth_utils import now_utc, iso

logger = logging.getLogger(__name__)

QTY_DECIMALS = 3
INV_OPS_CAP = 1000  # tope del guard embebido de idempotencia
_MOVES_IDX_READY = False


def _q(v: Any) -> float:
    try:
        return round(float(v or 0), QTY_DECIMALS)
    except (TypeError, ValueError):
        return 0.0


def _slice_concat(field: str, value: Any) -> dict:
    return {"$slice": [{"$concatArrays": [{"$ifNull": [f"${field}", []]}, [value]]},
                       -INV_OPS_CAP]}


async def _log_move(company_id: str, product: dict, mtype: str, qty: float,
                    op_id: str, store_id: str = "", store_name: str = "",
                    actor: Optional[dict] = None) -> None:
    global _MOVES_IDX_READY
    if not _MOVES_IDX_READY:
        await db.company_inventory_moves.create_index("op_id", unique=True, sparse=True)
        _MOVES_IDX_READY = True
    doc = {
        "id": str(uuid.uuid4()),
        "op_id": op_id,
        "company_id": company_id,
        "product_id": product["id"],
        "product_name": product.get("name", ""),
        "type": mtype,
        "qty": _q(qty),
        "store_id": store_id,
        "store_name": store_name,
        "actor_id": (actor or {}).get("user_id", ""),
        "created_at": iso(now_utc()),
    }
    try:
        await db.company_inventory_moves.insert_one(doc)
    except Exception:
        pass  # dedupe por op_id — el movimiento ya quedó registrado


async def receive_central(company_id: str, product_id: str, qty: float,
                          actor: Optional[dict] = None) -> str:
    """Recibe mercancía en el almacén central (incrementa el stock total)."""
    qty = _q(qty)
    if qty <= 0:
        return "invalid"
    op_id = f"recv:{uuid.uuid4().hex}"
    res = await db.products.find_one_and_update(
        {"id": product_id, "company_id": company_id, "inv_ops": {"$nin": [op_id]}},
        [{"$set": {
            "stock": {"$round": [{"$add": [{"$ifNull": ["$stock", 0]}, qty]}, QTY_DECIMALS]},
            "inv_ops": _slice_concat("inv_ops", op_id),
        }}],
        projection={"_id": 0, "id": 1, "name": 1},
        return_document=ReturnDocument.AFTER)
    if res is None:
        return "not_found"
    await _log_move(company_id, res, "receive", qty, op_id, actor=actor)
    return "applied"


async def distribute(company_id: str, product_id: str, store_id: str, qty: float,
                     actor: Optional[dict] = None) -> str:
    """Mueve `qty` del almacén central a una tienda. Atómico en un solo doc.
    Exige central (= stock − distributed) ≥ qty, si no devuelve 'insufficient'."""
    qty = _q(qty)
    if qty <= 0:
        return "invalid"
    op_id = f"dist:{uuid.uuid4().hex}"
    res = await db.products.find_one_and_update(
        {"id": product_id, "company_id": company_id,
         "inv_ops": {"$nin": [op_id]},
         "$expr": {"$gte": [
             {"$subtract": [{"$ifNull": ["$stock", 0]}, {"$ifNull": ["$distributed", 0]}]},
             qty]}},
        [{"$set": {
            f"by_store.{store_id}": {"$round": [
                {"$add": [{"$ifNull": [f"$by_store.{store_id}", 0]}, qty]}, QTY_DECIMALS]},
            "distributed": {"$round": [
                {"$add": [{"$ifNull": ["$distributed", 0]}, qty]}, QTY_DECIMALS]},
            "inv_ops": _slice_concat("inv_ops", op_id),
        }}],
        projection={"_id": 0, "id": 1, "name": 1},
        return_document=ReturnDocument.AFTER)
    if res is not None:
        store = await db.stores.find_one({"id": store_id}, {"_id": 0, "name": 1}) or {}
        await _log_move(company_id, res, "distribute", qty, op_id,
                        store_id=store_id, store_name=store.get("name", ""), actor=actor)
        return "applied"
    exists = await db.products.find_one(
        {"id": product_id, "company_id": company_id}, {"_id": 1})
    return "insufficient" if exists else "not_found"


async def return_to_central(company_id: str, product_id: str, store_id: str,
                            qty: float, actor: Optional[dict] = None) -> str:
    """Devuelve `qty` de una tienda al almacén central."""
    qty = _q(qty)
    if qty <= 0:
        return "invalid"
    op_id = f"ret:{uuid.uuid4().hex}"
    res = await db.products.find_one_and_update(
        {"id": product_id, "company_id": company_id,
         "inv_ops": {"$nin": [op_id]},
         "$expr": {"$gte": [{"$ifNull": [f"$by_store.{store_id}", 0]}, qty]}},
        [{"$set": {
            f"by_store.{store_id}": {"$round": [
                {"$subtract": [{"$ifNull": [f"$by_store.{store_id}", 0]}, qty]}, QTY_DECIMALS]},
            "distributed": {"$round": [
                {"$subtract": [{"$ifNull": ["$distributed", 0]}, qty]}, QTY_DECIMALS]},
            "inv_ops": _slice_concat("inv_ops", op_id),
        }}],
        projection={"_id": 0, "id": 1, "name": 1},
        return_document=ReturnDocument.AFTER)
    if res is not None:
        store = await db.stores.find_one({"id": store_id}, {"_id": 0, "name": 1}) or {}
        await _log_move(company_id, res, "return", qty, op_id,
                        store_id=store_id, store_name=store.get("name", ""), actor=actor)
        return "applied"
    exists = await db.products.find_one(
        {"id": product_id, "company_id": company_id}, {"_id": 1})
    return "insufficient" if exists else "not_found"


async def dispatch_from_store(company_id: str, product_id: str, store_id: str,
                              qty: float, op_id: str,
                              actor: Optional[dict] = None) -> str:
    """Despacha `qty` DESDE una tienda (venta/envío con origen en tienda):
    descuenta total + tienda + distributed en UNA escritura atómica. Exige
    by_store[sid] ≥ qty. IDEMPOTENTE por op_id (un reintento no reaplica).
    Usado por la solicitud de mensajería con origen en una tienda (Fase 4)."""
    qty = _q(qty)
    if qty <= 0:
        return "invalid"
    res = await db.products.find_one_and_update(
        {"id": product_id, "company_id": company_id,
         "inv_ops": {"$nin": [op_id]},
         "$expr": {"$gte": [{"$ifNull": [f"$by_store.{store_id}", 0]}, qty]}},
        [{"$set": {
            "stock": {"$round": [
                {"$subtract": [{"$ifNull": ["$stock", 0]}, qty]}, QTY_DECIMALS]},
            f"by_store.{store_id}": {"$round": [
                {"$subtract": [{"$ifNull": [f"$by_store.{store_id}", 0]}, qty]}, QTY_DECIMALS]},
            "distributed": {"$round": [
                {"$subtract": [{"$ifNull": ["$distributed", 0]}, qty]}, QTY_DECIMALS]},
            "inv_ops": _slice_concat("inv_ops", op_id),
        }}],
        projection={"_id": 0, "id": 1, "name": 1},
        return_document=ReturnDocument.AFTER)
    if res is not None:
        store = await db.stores.find_one({"id": store_id}, {"_id": 0, "name": 1}) or {}
        await _log_move(company_id, res, "dispatch", qty, op_id,
                        store_id=store_id, store_name=store.get("name", ""), actor=actor)
        return "applied"
    # idempotencia: si el op ya quedó aplicado → duplicado (éxito, sin reaplicar).
    dup = await db.products.find_one(
        {"id": product_id, "company_id": company_id, "inv_ops": op_id}, {"_id": 1})
    if dup:
        return "applied"
    exists = await db.products.find_one(
        {"id": product_id, "company_id": company_id}, {"_id": 1})
    return "insufficient" if exists else "not_found"


async def return_dispatch(company_id: str, product_id: str, store_id: str,
                          qty: float, op_id: str,
                          actor: Optional[dict] = None) -> str:
    """Reverso de dispatch_from_store (cancelación/rechazo): devuelve total +
    tienda + distributed. IDEMPOTENTE por op_id (devuelve exactamente una vez)."""
    qty = _q(qty)
    if qty <= 0:
        return "invalid"
    res = await db.products.find_one_and_update(
        {"id": product_id, "company_id": company_id, "inv_ops": {"$nin": [op_id]}},
        [{"$set": {
            "stock": {"$round": [
                {"$add": [{"$ifNull": ["$stock", 0]}, qty]}, QTY_DECIMALS]},
            f"by_store.{store_id}": {"$round": [
                {"$add": [{"$ifNull": [f"$by_store.{store_id}", 0]}, qty]}, QTY_DECIMALS]},
            "distributed": {"$round": [
                {"$add": [{"$ifNull": ["$distributed", 0]}, qty]}, QTY_DECIMALS]},
            "inv_ops": _slice_concat("inv_ops", op_id),
        }}],
        projection={"_id": 0, "id": 1, "name": 1},
        return_document=ReturnDocument.AFTER)
    if res is not None:
        store = await db.stores.find_one({"id": store_id}, {"_id": 0, "name": 1}) or {}
        await _log_move(company_id, res, "dispatch_return", qty, op_id,
                        store_id=store_id, store_name=store.get("name", ""), actor=actor)
        return "applied"
    dup = await db.products.find_one(
        {"id": product_id, "company_id": company_id, "inv_ops": op_id}, {"_id": 1})
    return "applied" if dup else "not_found"



async def release_store(company_id: str, store_id: str) -> None:
    """Al borrar una tienda, devuelve su mercancía distribuida al central
    (resta de `distributed` y quita la clave del mapa `by_store`)."""
    prods = await db.products.find(
        {"company_id": company_id, f"by_store.{store_id}": {"$gt": 0}},
        {"_id": 0, "id": 1, f"by_store.{store_id}": 1}).to_list(1000)
    for p in prods:
        qty = _q((p.get("by_store") or {}).get(store_id))
        if qty <= 0:
            continue
        await db.products.update_one(
            {"id": p["id"], "company_id": company_id},
            {"$inc": {"distributed": -qty},
             "$unset": {f"by_store.{store_id}": ""}})


async def build_inventory_rows(company_id: str) -> list:
    """Una fila por producto de la Empresa con el desglose por ubicación."""
    products = await db.products.find(
        {"company_id": company_id}, {"_id": 0}).sort("created_at", -1).to_list(500)
    stores = await db.stores.find(
        {"company_id": company_id}, {"_id": 0, "id": 1, "name": 1}).to_list(500)
    name_by_id = {s["id"]: s["name"] for s in stores}
    rows = []
    for p in products:
        total = _q(p.get("stock"))
        by_store = p.get("by_store") or {}
        distributed = round(sum(_q(v) for v in by_store.values()), QTY_DECIMALS)
        central = round(total - distributed, QTY_DECIMALS)
        rows.append({
            "product_id": p["id"],
            "name": p.get("name", ""),
            "approval_status": p.get("approval_status", "approved"),
            "total": total,
            "distributed": distributed,
            "central": central if central > 0 else 0.0,
            "over_distributed": central < 0,
            "stores": [
                {"store_id": sid, "store_name": name_by_id.get(sid, "tienda eliminada"),
                 "qty": _q(q)}
                for sid, q in by_store.items() if _q(q) > 0
            ],
        })
    return rows


async def list_moves(company_id: str, limit: int = 100) -> list:
    return await db.company_inventory_moves.find(
        {"company_id": company_id}, {"_id": 0, "op_id": 0}) \
        .sort("created_at", -1).to_list(limit)
