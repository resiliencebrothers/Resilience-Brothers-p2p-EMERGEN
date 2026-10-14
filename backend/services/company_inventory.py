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
import json
import hashlib
import logging
from typing import Any, Awaitable, Callable, Optional

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from db_client import db
from auth_utils import now_utc, iso

logger = logging.getLogger(__name__)

QTY_DECIMALS = 3
INV_OPS_CAP = 1000  # tope del guard embebido (ventana de concurrencia, NO durable)
_MOVES_IDX_READY = False
_OPS_IDX_READY = False


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


def _payload_hash(op_type: str, payload: dict) -> str:
    raw = json.dumps({"t": op_type, "p": payload}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


async def _run_idempotent(company_id: str, op_key: Optional[str], op_type: str,
                          payload: dict,
                          apply_fn: "Callable[[str], Awaitable[str]]") -> str:
    """Idempotencia DURADERA por clave estable de operación (F2-02).

    - `company_inventory_ops` (único por empresa+clave) es la evidencia PERMANENTE:
      misma clave + mismo payload ⇒ devuelve el resultado ya calculado SIN
      reaplicar (aunque el tope de `inv_ops` ya haya rotado el id antiguo);
      misma clave + payload DISTINTO ⇒ 'conflict'.
    - El guard `inv_ops` del documento del producto garantiza, además,
      exactamente-UNA mutación en la ventana de concurrencia.
    - Si `op_key` falta, se genera uno (camino legado: no deduplica reintentos).
    - Dos operaciones DISTINTAS con mismo producto/cantidad usan claves distintas,
      por lo que ambas se aplican (no se confunden).
    """
    global _OPS_IDX_READY
    if not _OPS_IDX_READY:
        await db.company_inventory_ops.create_index(
            [("company_id", 1), ("op_key", 1)], unique=True)
        _OPS_IDX_READY = True
    oid = op_key or f"auto:{uuid.uuid4().hex}"
    phash = _payload_hash(op_type, payload)
    try:
        prior = await db.company_inventory_ops.find_one_and_update(
            {"company_id": company_id, "op_key": oid},
            {"$setOnInsert": {"company_id": company_id, "op_key": oid,
                              "op_type": op_type, "payload_hash": phash,
                              "status": "pending", "created_at": iso(now_utc())}},
            upsert=True, return_document=ReturnDocument.BEFORE)
    except DuplicateKeyError:
        # Carrera de inserción concurrente: el registro ya existe → trátalo como previo.
        prior = await db.company_inventory_ops.find_one(
            {"company_id": company_id, "op_key": oid})
    if prior is not None:
        if prior.get("payload_hash") != phash:
            return "conflict"
        if prior.get("status") == "done":
            return prior.get("result", "applied")
        # 'pending': intento previo incompleto o concurrente → se sigue a apply;
        # el guard inv_ops impide una segunda mutación.
    result = await apply_fn(oid)
    await db.company_inventory_ops.update_one(
        {"company_id": company_id, "op_key": oid},
        {"$set": {"status": "done", "result": result, "done_at": iso(now_utc())}})
    return result


async def receive_central(company_id: str, product_id: str, qty: float,
                          op_key: Optional[str] = None,
                          actor: Optional[dict] = None) -> str:
    """Recibe mercancía en el almacén central (incrementa el stock total)."""
    qty = _q(qty)
    if qty <= 0:
        return "invalid"

    async def _apply(oid: str) -> str:
        res = await db.products.find_one_and_update(
            {"id": product_id, "company_id": company_id, "inv_ops": {"$nin": [oid]}},
            [{"$set": {
                "stock": {"$round": [{"$add": [{"$ifNull": ["$stock", 0]}, qty]}, QTY_DECIMALS]},
                "inv_ops": _slice_concat("inv_ops", oid),
            }}],
            projection={"_id": 0, "id": 1, "name": 1},
            return_document=ReturnDocument.AFTER)
        if res is not None:
            await _log_move(company_id, res, "receive", qty, oid, actor=actor)
            return "applied"
        dup = await db.products.find_one(
            {"id": product_id, "company_id": company_id, "inv_ops": oid}, {"_id": 1})
        return "applied" if dup else "not_found"

    return await _run_idempotent(company_id, op_key, "receive",
                                 {"product_id": product_id, "qty": qty}, _apply)


async def distribute(company_id: str, product_id: str, store_id: str, qty: float,
                     op_key: Optional[str] = None,
                     actor: Optional[dict] = None) -> str:
    """Mueve `qty` del almacén central a una tienda. Atómico en un solo doc.
    Exige central (= stock − distributed) ≥ qty, si no devuelve 'insufficient'."""
    qty = _q(qty)
    if qty <= 0:
        return "invalid"

    async def _apply(oid: str) -> str:
        res = await db.products.find_one_and_update(
            {"id": product_id, "company_id": company_id,
             "inv_ops": {"$nin": [oid]},
             "$expr": {"$gte": [
                 {"$subtract": [{"$ifNull": ["$stock", 0]}, {"$ifNull": ["$distributed", 0]}]},
                 qty]}},
            [{"$set": {
                f"by_store.{store_id}": {"$round": [
                    {"$add": [{"$ifNull": [f"$by_store.{store_id}", 0]}, qty]}, QTY_DECIMALS]},
                "distributed": {"$round": [
                    {"$add": [{"$ifNull": ["$distributed", 0]}, qty]}, QTY_DECIMALS]},
                "inv_ops": _slice_concat("inv_ops", oid),
            }}],
            projection={"_id": 0, "id": 1, "name": 1},
            return_document=ReturnDocument.AFTER)
        if res is not None:
            store = await db.stores.find_one({"id": store_id}, {"_id": 0, "name": 1}) or {}
            await _log_move(company_id, res, "distribute", qty, oid,
                            store_id=store_id, store_name=store.get("name", ""), actor=actor)
            return "applied"
        dup = await db.products.find_one(
            {"id": product_id, "company_id": company_id, "inv_ops": oid}, {"_id": 1})
        if dup:
            return "applied"
        exists = await db.products.find_one(
            {"id": product_id, "company_id": company_id}, {"_id": 1})
        return "insufficient" if exists else "not_found"

    return await _run_idempotent(
        company_id, op_key, "distribute",
        {"product_id": product_id, "store_id": store_id, "qty": qty}, _apply)


async def return_to_central(company_id: str, product_id: str, store_id: str,
                            qty: float, op_key: Optional[str] = None,
                            actor: Optional[dict] = None) -> str:
    """Devuelve `qty` de una tienda al almacén central."""
    qty = _q(qty)
    if qty <= 0:
        return "invalid"

    async def _apply(oid: str) -> str:
        res = await db.products.find_one_and_update(
            {"id": product_id, "company_id": company_id,
             "inv_ops": {"$nin": [oid]},
             "$expr": {"$gte": [{"$ifNull": [f"$by_store.{store_id}", 0]}, qty]}},
            [{"$set": {
                f"by_store.{store_id}": {"$round": [
                    {"$subtract": [{"$ifNull": [f"$by_store.{store_id}", 0]}, qty]}, QTY_DECIMALS]},
                "distributed": {"$round": [
                    {"$subtract": [{"$ifNull": ["$distributed", 0]}, qty]}, QTY_DECIMALS]},
                "inv_ops": _slice_concat("inv_ops", oid),
            }}],
            projection={"_id": 0, "id": 1, "name": 1},
            return_document=ReturnDocument.AFTER)
        if res is not None:
            store = await db.stores.find_one({"id": store_id}, {"_id": 0, "name": 1}) or {}
            await _log_move(company_id, res, "return", qty, oid,
                            store_id=store_id, store_name=store.get("name", ""), actor=actor)
            return "applied"
        dup = await db.products.find_one(
            {"id": product_id, "company_id": company_id, "inv_ops": oid}, {"_id": 1})
        if dup:
            return "applied"
        exists = await db.products.find_one(
            {"id": product_id, "company_id": company_id}, {"_id": 1})
        return "insufficient" if exists else "not_found"

    return await _run_idempotent(
        company_id, op_key, "return",
        {"product_id": product_id, "store_id": store_id, "qty": qty}, _apply)


async def adjust_total(company_id: str, product_id: str, new_total: float,
                       expected_total: float, op_key: Optional[str] = None,
                       actor: Optional[dict] = None) -> str:
    """Ajuste ABSOLUTO del total (stock) con control de versión y traza (F2-04).

    - CAS: el `stock` actual debe ser EXACTAMENTE `expected_total`; si una venta
      o recepción concurrente lo cambió, devuelve 'stale' (el cliente recarga).
    - No puede dejar el total por debajo de lo ya distribuido a tiendas
      (`new_total >= distributed`), si no devuelve 'below_distributed'.
    - Registra un movimiento 'adjust' con el delta (firmado). IDEMPOTENTE y
      DURADERO por `op_id` (un reintento no reaplica)."""
    new_total = _q(new_total)
    expected_total = _q(expected_total)
    if new_total < 0:
        return "invalid"

    async def _apply(oid: str) -> str:
        res = await db.products.find_one_and_update(
            {"id": product_id, "company_id": company_id,
             "inv_ops": {"$nin": [oid]},
             "$expr": {"$and": [
                 {"$eq": [{"$round": [{"$ifNull": ["$stock", 0]}, QTY_DECIMALS]},
                          expected_total]},
                 {"$gte": [new_total, {"$ifNull": ["$distributed", 0]}]},
             ]}},
            [{"$set": {
                "stock": new_total,
                "inv_ops": _slice_concat("inv_ops", oid),
            }}],
            projection={"_id": 0, "id": 1, "name": 1},
            return_document=ReturnDocument.AFTER)
        if res is not None:
            delta = round(new_total - expected_total, QTY_DECIMALS)
            if delta != 0:
                await _log_move(company_id, res, "adjust", delta, oid, actor=actor)
            return "applied"
        dup = await db.products.find_one(
            {"id": product_id, "company_id": company_id, "inv_ops": oid}, {"_id": 1})
        if dup:
            return "applied"
        cur = await db.products.find_one(
            {"id": product_id, "company_id": company_id},
            {"_id": 0, "stock": 1, "distributed": 1})
        if not cur:
            return "not_found"
        if _q(cur.get("stock")) != expected_total:
            return "stale"
        return "below_distributed"

    return await _run_idempotent(
        company_id, op_key, "adjust",
        {"product_id": product_id, "new_total": new_total,
         "expected_total": expected_total}, _apply)


async def dispatch_from_store(company_id: str, product_id: str, store_id: str,
                              qty: float, op_id: str,
                              actor: Optional[dict] = None) -> str:
    """Despacha `qty` DESDE una tienda (venta/envío con origen en tienda):
    descuenta total + tienda + distributed en UNA escritura atómica. Exige
    by_store[sid] ≥ qty. IDEMPOTENTE y DURADERA por `op_id` (un reintento no
    reaplica, ni siquiera tras rotar `inv_ops`)."""
    qty = _q(qty)
    if qty <= 0:
        return "invalid"

    async def _apply(oid: str) -> str:
        res = await db.products.find_one_and_update(
            {"id": product_id, "company_id": company_id,
             "inv_ops": {"$nin": [oid]},
             "$expr": {"$gte": [{"$ifNull": [f"$by_store.{store_id}", 0]}, qty]}},
            [{"$set": {
                "stock": {"$round": [
                    {"$subtract": [{"$ifNull": ["$stock", 0]}, qty]}, QTY_DECIMALS]},
                f"by_store.{store_id}": {"$round": [
                    {"$subtract": [{"$ifNull": [f"$by_store.{store_id}", 0]}, qty]}, QTY_DECIMALS]},
                "distributed": {"$round": [
                    {"$subtract": [{"$ifNull": ["$distributed", 0]}, qty]}, QTY_DECIMALS]},
                "inv_ops": _slice_concat("inv_ops", oid),
            }}],
            projection={"_id": 0, "id": 1, "name": 1},
            return_document=ReturnDocument.AFTER)
        if res is not None:
            store = await db.stores.find_one({"id": store_id}, {"_id": 0, "name": 1}) or {}
            await _log_move(company_id, res, "dispatch", qty, oid,
                            store_id=store_id, store_name=store.get("name", ""), actor=actor)
            return "applied"
        dup = await db.products.find_one(
            {"id": product_id, "company_id": company_id, "inv_ops": oid}, {"_id": 1})
        if dup:
            return "applied"
        exists = await db.products.find_one(
            {"id": product_id, "company_id": company_id}, {"_id": 1})
        return "insufficient" if exists else "not_found"

    return await _run_idempotent(
        company_id, op_id, "dispatch",
        {"product_id": product_id, "store_id": store_id, "qty": qty}, _apply)


async def return_dispatch(company_id: str, product_id: str, store_id: str,
                          qty: float, op_id: str,
                          actor: Optional[dict] = None) -> str:
    """Reverso de dispatch_from_store (cancelación/rechazo): devuelve total +
    tienda + distributed. IDEMPOTENTE y DURADERA por `op_id` (exactamente una vez)."""
    qty = _q(qty)
    if qty <= 0:
        return "invalid"

    async def _apply(oid: str) -> str:
        res = await db.products.find_one_and_update(
            {"id": product_id, "company_id": company_id, "inv_ops": {"$nin": [oid]}},
            [{"$set": {
                "stock": {"$round": [
                    {"$add": [{"$ifNull": ["$stock", 0]}, qty]}, QTY_DECIMALS]},
                f"by_store.{store_id}": {"$round": [
                    {"$add": [{"$ifNull": [f"$by_store.{store_id}", 0]}, qty]}, QTY_DECIMALS]},
                "distributed": {"$round": [
                    {"$add": [{"$ifNull": ["$distributed", 0]}, qty]}, QTY_DECIMALS]},
                "inv_ops": _slice_concat("inv_ops", oid),
            }}],
            projection={"_id": 0, "id": 1, "name": 1},
            return_document=ReturnDocument.AFTER)
        if res is not None:
            store = await db.stores.find_one({"id": store_id}, {"_id": 0, "name": 1}) or {}
            await _log_move(company_id, res, "dispatch_return", qty, oid,
                            store_id=store_id, store_name=store.get("name", ""), actor=actor)
            return "applied"
        dup = await db.products.find_one(
            {"id": product_id, "company_id": company_id, "inv_ops": oid}, {"_id": 1})
        return "applied" if dup else "not_found"

    return await _run_idempotent(
        company_id, op_id, "dispatch_return",
        {"product_id": product_id, "store_id": store_id, "qty": qty}, _apply)



async def release_store(company_id: str, store_id: str) -> None:
    """Cierre RECUPERABLE de una tienda (F2-03): devuelve TODA su mercancía
    distribuida al almacén central.

    Por cada producto hace UNA escritura ATÓMICA que, en la misma pipeline,
    resta de `distributed` el valor VIGENTE de `by_store[sid]` y elimina la
    clave. Nunca usa una lectura previa que pueda quedar obsoleta, por lo que el
    invariante `distributed == suma(by_store)` se conserva ante cualquier
    devolución/distribución concurrente y `distributed` jamás queda negativo.

    Es idempotente y REANUDABLE: si un intento falla a mitad de varios
    productos, reejecutar continúa con los pendientes (los ya liberados ya no
    tienen la clave y no vuelven a coincidir). Cada traslado se registra UNA
    sola vez gracias al `op_id` estable por producto."""
    while True:
        before = await db.products.find_one_and_update(
            {"company_id": company_id, f"by_store.{store_id}": {"$gt": 0}},
            [
                {"$set": {"distributed": {"$round": [{"$subtract": [
                    {"$ifNull": ["$distributed", 0]},
                    {"$ifNull": [f"$by_store.{store_id}", 0]},
                ]}, QTY_DECIMALS]}}},
                {"$unset": f"by_store.{store_id}"},
            ],
            projection={"_id": 0, "id": 1, "name": 1, f"by_store.{store_id}": 1},
            return_document=ReturnDocument.BEFORE)
        if before is None:
            break
        qty = _q((before.get("by_store") or {}).get(store_id))
        if qty > 0:
            await _log_move(company_id, before, "release", qty,
                            f"release:{store_id}:{before['id']}",
                            store_id=store_id)


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
