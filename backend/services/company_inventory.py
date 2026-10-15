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
    """Registra el movimiento de inventario de forma DURADERA (F2-05).

    Evidencia ÚNICA por `op_id` (índice único): reintentar la misma operación
    re-inserta la misma clave y el `DuplicateKeyError` confirma que ya quedó
    registrada. CUALQUIER otro fallo de almacenamiento se PROPAGA (no se traga):
    así nunca se pierde trazabilidad en silencio y la operación queda
    'pending' para reanudarse (el guard `inv_ops` impide un segundo efecto)."""
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
    except DuplicateKeyError:
        pass  # misma op_id → ya registrada (evidencia única garantizada)


async def _relog_if_applied(company_id: str, product_id: str, oid: str,
                            mtype: str, qty: float, store_id: str = "",
                            actor: Optional[dict] = None) -> bool:
    """Recuperación F2-05: si la mutación de stock YA se aplicó (el guard
    `inv_ops` contiene `oid`) pero el movimiento pudo no haberse escrito (p. ej.
    un fallo de almacenamiento en un intento previo), lo re-registra de forma
    idempotente. Devuelve True si la mutación estaba aplicada."""
    dup = await db.products.find_one(
        {"id": product_id, "company_id": company_id, "inv_ops": oid},
        {"_id": 0, "id": 1, "name": 1})
    if not dup:
        return False
    sname = ""
    if store_id:
        s = await db.stores.find_one({"id": store_id}, {"_id": 0, "name": 1}) or {}
        sname = s.get("name", "")
    await _log_move(company_id, dup, mtype, qty, oid,
                    store_id=store_id, store_name=sname, actor=actor)
    return True


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
        if await _relog_if_applied(company_id, product_id, oid, "receive", qty, actor=actor):
            return "applied"
        return "not_found"

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
        if await _relog_if_applied(company_id, product_id, oid, "distribute", qty,
                                   store_id=store_id, actor=actor):
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
        if await _relog_if_applied(company_id, product_id, oid, "return", qty,
                                   store_id=store_id, actor=actor):
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
            {"id": product_id, "company_id": company_id, "inv_ops": oid},
            {"_id": 0, "id": 1, "name": 1})
        if dup:
            delta = round(new_total - expected_total, QTY_DECIMALS)
            if delta != 0:
                await _log_move(company_id, dup, "adjust", delta, oid, actor=actor)
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
        if await _relog_if_applied(company_id, product_id, oid, "dispatch", qty,
                                   store_id=store_id, actor=actor):
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
        if await _relog_if_applied(company_id, product_id, oid, "dispatch_return", qty,
                                   store_id=store_id, actor=actor):
            return "applied"
        return "not_found"

    return await _run_idempotent(
        company_id, op_id, "dispatch_return",
        {"product_id": product_id, "store_id": store_id, "qty": qty}, _apply)


# ============================================================
# Venta con recogida en tienda (F2-B) — CAPA DE UBICACIÓN
# ------------------------------------------------------------
# Una venta del marketplace con origen en una tienda concreta descuenta el
# TOTAL (`stock`) por la vía existente del canje (apply_stock_idempotent, que
# conserva intactos todos los caminos de reserva/rechazo/healer) y, ADEMÁS,
# esta capa descuenta la ESTANTERÍA elegida (`by_store[sid]`) y `distributed`.
# Al ser dos capas sobre el MISMO total, el almacén central (stock−distributed)
# no cambia: la venta consume exactamente la tienda seleccionada. La capa de
# ubicación tiene su propia decisión terminal (burn/undo) para que un crash
# a mitad del alta se recupere con UN solo efecto físico y UNA sola evidencia.
# ============================================================


async def reserve_pickup(company_id: str, product_id: str, store_id: str,
                         qty: float, op_id: str,
                         actor: Optional[dict] = None) -> str:
    """Reserva de ubicación de una venta con recogida en tienda: descuenta
    `qty` de la ESTANTERÍA (by_store[sid]) y de `distributed`, SIN tocar
    `stock` (el total lo descuenta la capa de stock del canje). Exige
    by_store[sid] ≥ qty. IDEMPOTENTE y DURADERA por `op_id`; respeta el TOKEN
    de quema `op:burn` (decisión terminal del healer). 'applied'|'insufficient'
    |'burned'|'not_found'|'invalid'."""
    qty = _q(qty)
    if qty <= 0:
        return "invalid"

    async def _apply(oid: str) -> str:
        burn_token = f"{oid}:burn"
        res = await db.products.find_one_and_update(
            {"id": product_id, "company_id": company_id,
             "inv_ops": {"$nin": [oid, burn_token]},
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
            await _log_move(company_id, res, "pickup_sale", qty, oid,
                            store_id=store_id, store_name=store.get("name", ""), actor=actor)
            return "applied"
        if await _relog_if_applied(company_id, product_id, oid, "pickup_sale", qty,
                                   store_id=store_id, actor=actor):
            return "applied"
        # TOKEN de quema presente → decisión terminal: jamás muta.
        if await db.products.find_one(
                {"id": product_id, "company_id": company_id, "inv_ops": burn_token},
                {"_id": 1}):
            return "burned"
        exists = await db.products.find_one(
            {"id": product_id, "company_id": company_id}, {"_id": 1})
        return "insufficient" if exists else "not_found"

    return await _run_idempotent(
        company_id, op_id, "pickup",
        {"product_id": product_id, "store_id": store_id, "qty": qty}, _apply)


async def restore_pickup(company_id: str, product_id: str, store_id: str,
                         qty: float, op_id: str,
                         actor: Optional[dict] = None) -> str:
    """Restitución del reverso de una venta con recogida en tienda
    (rechazo/cancelación/recuperación): devuelve `qty` a la ESTANTERÍA
    (by_store[sid]) y a `distributed`, SIN tocar `stock` (ese reverso lo hace
    la capa de stock del canje). IDEMPOTENTE y DURADERA por `op_id`
    (exactamente una vez, incluso tras rotar `inv_ops`)."""
    qty = _q(qty)
    if qty <= 0:
        return "invalid"

    async def _apply(oid: str) -> str:
        res = await db.products.find_one_and_update(
            {"id": product_id, "company_id": company_id, "inv_ops": {"$nin": [oid]}},
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
            await _log_move(company_id, res, "pickup_restore", qty, oid,
                            store_id=store_id, store_name=store.get("name", ""), actor=actor)
            return "applied"
        if await _relog_if_applied(company_id, product_id, oid, "pickup_restore", qty,
                                   store_id=store_id, actor=actor):
            return "applied"
        return "not_found"

    return await _run_idempotent(
        company_id, op_id, "pickup_restore",
        {"product_id": product_id, "store_id": store_id, "qty": qty}, _apply)


async def burn_or_undo_pickup(company_id: str, product_id: str, store_id: str,
                              qty: float, op_id: str,
                              actor: Optional[dict] = None) -> str:
    """Decisión TERMINAL para la reserva de ubicación de una recogida en tienda
    (mirror de burn_or_undo_stock): empuja PRIMERO el TOKEN de quema `op:burn`
    al guard embebido y LUEGO comprueba si la reserva llegó a aplicarse. Si YA
    se aplicó (inv_ops contiene `op_id`), la deshace con `restore_pickup`
    (`op:undo`, idempotente); si no, el token impide que un creador lento la
    aplique más tarde. Empujar el token antes de comprobar cierra la carrera:
    la reserva tardía fracasa (guard) o se detecta ya aplicada. 'undone'|'burned'."""
    qty = _q(qty)
    burn_token = f"{op_id}:burn"
    await db.products.update_one(
        {"id": product_id, "company_id": company_id,
         "inv_ops": {"$ne": burn_token}},
        {"$push": {"inv_ops": burn_token}})
    if await db.products.find_one(
            {"id": product_id, "company_id": company_id, "inv_ops": op_id},
            {"_id": 1}):
        await restore_pickup(company_id, product_id, store_id, qty,
                             f"{op_id}:undo", actor=actor)
        return "undone"
    return "burned"




async def _release_one(company_id: str, store_id: str, product_id: str) -> None:
    """Libera un producto de una tienda (cierre F2-03) con traza DURADERA (F2-05).

    Atómico por documento: resta de `distributed` el valor VIGENTE de
    `by_store[sid]` y elimina la clave (nunca una lectura obsoleta). La cantidad
    liberada se PERSISTE en el registro durable de la operación ANTES de intentar
    el movimiento, de modo que si la escritura del log falla, un reintento la
    recupera y re-registra sin reaplicar el stock (guard `inv_ops`)."""
    op_key = f"release:{store_id}:{product_id}"

    async def _apply(oid: str) -> str:
        before = await db.products.find_one_and_update(
            {"id": product_id, "company_id": company_id,
             "inv_ops": {"$nin": [oid]},
             f"by_store.{store_id}": {"$gt": 0}},
            [
                {"$set": {"distributed": {"$round": [{"$subtract": [
                    {"$ifNull": ["$distributed", 0]},
                    {"$ifNull": [f"$by_store.{store_id}", 0]},
                ]}, QTY_DECIMALS]},
                    "inv_ops": _slice_concat("inv_ops", oid)}},
                {"$unset": f"by_store.{store_id}"},
            ],
            projection={"_id": 0, "id": 1, "name": 1, f"by_store.{store_id}": 1},
            return_document=ReturnDocument.BEFORE)
        if before is not None:
            qty = _q((before.get("by_store") or {}).get(store_id))
            # Persiste la cantidad liberada ANTES del log → recuperable.
            await db.company_inventory_ops.update_one(
                {"company_id": company_id, "op_key": oid},
                {"$set": {"applied_qty": qty, "product_name": before.get("name", "")}})
            if qty > 0:
                await _log_move(company_id, before, "release", qty, oid,
                                store_id=store_id)
            return "applied"
        # La mutación ya se aplicó en un intento previo: re-registra el log desde
        # la cantidad persistida (recuperación), de forma idempotente.
        dup = await db.products.find_one(
            {"id": product_id, "company_id": company_id, "inv_ops": oid}, {"_id": 1})
        if dup:
            rec = await db.company_inventory_ops.find_one(
                {"company_id": company_id, "op_key": oid},
                {"_id": 0, "applied_qty": 1, "product_name": 1})
            q = _q((rec or {}).get("applied_qty"))
            if q > 0:
                await _log_move(
                    company_id,
                    {"id": product_id, "name": (rec or {}).get("product_name", "")},
                    "release", q, oid, store_id=store_id)
            return "applied"
        return "noop"  # nada que liberar para esta tienda en este producto

    await _run_idempotent(
        company_id, op_key, "release",
        {"store_id": store_id, "product_id": product_id}, _apply)


async def release_store(company_id: str, store_id: str) -> None:
    """Cierre RECUPERABLE de una tienda (F2-03 + F2-05): devuelve TODA su
    mercancía distribuida al almacén central, con un movimiento trazable por
    cada producto afectado y evidencia duradera.

    1) Reanuda operaciones de cierre ya mutadas pero cuyo log no se completó
       (estado != 'done' con `applied_qty`): re-registra sin reaplicar.
    2) Libera cada producto que aún tenga stock en la tienda.
    Es idempotente y reanudable: reejecutar continúa con lo pendiente."""
    # 1) Recuperación: ops de cierre mutadas pero no completadas (log pendiente).
    pending = await db.company_inventory_ops.find(
        {"company_id": company_id, "op_type": "release",
         "op_key": {"$regex": f"^release:{store_id}:"},
         "status": {"$ne": "done"}, "applied_qty": {"$exists": True}},
        {"_id": 0, "op_key": 1}).to_list(5000)
    for rec in pending:
        parts = rec["op_key"].split(":", 2)
        if len(parts) == 3:
            await _release_one(company_id, store_id, parts[2])
    # 2) Libera los productos que aún tienen existencias en la tienda.
    pids = [p["id"] for p in await db.products.find(
        {"company_id": company_id, f"by_store.{store_id}": {"$gt": 0}},
        {"_id": 0, "id": 1}).to_list(5000)]
    for pid in pids:
        await _release_one(company_id, store_id, pid)


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
        min_stock = _q(p.get("min_stock"))
        rows.append({
            "product_id": p["id"],
            "name": p.get("name", ""),
            "approval_status": p.get("approval_status", "approved"),
            "total": total,
            "distributed": distributed,
            "central": central if central > 0 else 0.0,
            "over_distributed": central < 0,
            "min_stock": min_stock,
            "low": bool(min_stock > 0 and central <= min_stock),
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


async def maybe_alert_low_stock(company_id: str, product_id: str) -> None:
    """Alerta de stock bajo (Empresa): si el almacén CENTRAL (stock−distributed)
    cae a/por debajo del mínimo configurado del producto (`min_stock`), avisa
    UNA vez a la Empresa para que reponga. Se RE-ARMA cuando el central vuelve a
    subir por encima del mínimo (recibir/devolver/ajustar). Best-effort: nunca
    rompe el flujo de la venta/operación."""
    try:
        p = await db.products.find_one(
            {"id": product_id, "company_id": company_id},
            {"_id": 0, "id": 1, "name": 1, "stock": 1, "distributed": 1,
             "min_stock": 1, "low_stock_alerted": 1})
        if not p:
            return
        threshold = _q(p.get("min_stock"))
        if threshold <= 0:
            return  # sin mínimo configurado → sin alerta
        central = round(_q(p.get("stock")) - _q(p.get("distributed")), QTY_DECIMALS)
        alerted = bool(p.get("low_stock_alerted"))
        if central <= threshold and not alerted:
            await db.products.update_one(
                {"id": product_id, "company_id": company_id},
                {"$set": {"low_stock_alerted": True}})
            try:
                from routes.notifications import _insert_notification
                await _insert_notification(
                    recipient_user_id=company_id, type="company_low_stock",
                    title="Stock bajo en almacén central",
                    message=(f"«{p.get('name', '')}» tiene {central} en el almacén "
                             f"central (mínimo {threshold}). Recibe más mercancía "
                             "para no quedarte sin existencias."),
                    data={"product_id": product_id, "central": central,
                          "min_stock": threshold})
            except Exception as e:  # noqa: BLE001
                logger.error(f"low-stock notify failed: {e}")
        elif central > threshold and alerted:
            await db.products.update_one(
                {"id": product_id, "company_id": company_id},
                {"$set": {"low_stock_alerted": False}})
    except Exception as e:  # noqa: BLE001
        logger.error(f"maybe_alert_low_stock failed: {e}")
