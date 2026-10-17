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
from datetime import timedelta

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
    # H03-R2 — CIERRE CONDICIONAL: una decisión TERMINAL DURADERA de aborto
    # ('burned', sellada por freeze_dispatch/burn_or_undo_pickup mientras este
    # intento estaba PAUSADO) JAMÁS puede ser sobrescrita por un ejecutor EN
    # VUELO que resucita tras el aborto. Nunca pisamos un 'burned' con 'applied'.
    await db.company_inventory_ops.update_one(
        {"company_id": company_id, "op_key": oid, "result": {"$ne": "burned"}},
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
        # H03/H03-R2 — GUARD DE ABORTO DURADERO: si el recuperador decidió
        # ABORTAR este intento (freeze_dispatch marcó `inv_burned`), la reserva
        # NO puede aplicarse TARDE. El marcador vive en `inv_burned` (conjunto
        # NO truncado del propio producto), así la carrera se cierra en la MISMA
        # escritura y la decisión SOBREVIVE a la rotación de `inv_ops`: un
        # ejecutor EN VUELO que resucita tras el aborto se bloquea aquí. Un token
        # dentro del array acotado podía desalojarse y dejar pasar esa reserva.
        res = await db.products.find_one_and_update(
            {"id": product_id, "company_id": company_id,
             "inv_ops": {"$nin": [oid]},
             "inv_burned": {"$nin": [oid]},
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
        # Decisión TERMINAL DURADERA de aborto presente → jamás muta.
        if await db.products.find_one(
                {"id": product_id, "company_id": company_id, "inv_burned": oid},
                {"_id": 1}):
            return "burned"
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
        # E34-05/R06 — si la tienda de origen YA NO EXISTE o está EN CIERRE
        # ('closing': su estantería se está desmantelando), la mercancía NO
        # puede volver a un `by_store` que el borrado dejaría huérfano: se
        # devuelve al ALMACÉN CENTRAL (central = stock − distributed ⇒ sube
        # `stock` sin tocar `distributed`). Solo una tienda VIGENTE recupera su
        # estantería. Esto evita la carrera cierre↔devolución.
        store = await db.stores.find_one(
            {"id": store_id, "company_id": company_id,
             "status": {"$ne": "closing"}}, {"_id": 0, "name": 1})
        if store is not None:
            set_stage = {
                "stock": {"$round": [
                    {"$add": [{"$ifNull": ["$stock", 0]}, qty]}, QTY_DECIMALS]},
                f"by_store.{store_id}": {"$round": [
                    {"$add": [{"$ifNull": [f"$by_store.{store_id}", 0]}, qty]}, QTY_DECIMALS]},
                "distributed": {"$round": [
                    {"$add": [{"$ifNull": ["$distributed", 0]}, qty]}, QTY_DECIMALS]},
                "inv_ops": _slice_concat("inv_ops", oid),
            }
            move_type, move_sid, move_sname = "dispatch_return", store_id, store.get("name", "")
        else:
            set_stage = {
                "stock": {"$round": [
                    {"$add": [{"$ifNull": ["$stock", 0]}, qty]}, QTY_DECIMALS]},
                "inv_ops": _slice_concat("inv_ops", oid),
            }
            move_type, move_sid, move_sname = "dispatch_return_central", "", ""
        res = await db.products.find_one_and_update(
            {"id": product_id, "company_id": company_id, "inv_ops": {"$nin": [oid]}},
            [{"$set": set_stage}],
            projection={"_id": 0, "id": 1, "name": 1},
            return_document=ReturnDocument.AFTER)
        if res is not None:
            # H04 — carrera lectura-antigua ↔ cierre de tienda: si decidimos
            # devolver a una ESTANTERÍA (la tienda estaba vigente al LEERLA)
            # pero se cerró/borró ANTES de esta escritura, la cantidad quedaría
            # HUÉRFANA en `by_store` sin documento de tienda. Se RE-VERIFICA tras
            # escribir y, si la tienda ya no está vigente, se reubica esa
            # estantería al CENTRAL ahora mismo (self-heal). El reconciliador
            # duradero `heal_orphan_store_shelves` cubre además el caso de un
            # fallo entre esta escritura y la reubicación.
            if move_type == "dispatch_return":
                still = await db.stores.find_one(
                    {"id": store_id, "company_id": company_id,
                     "status": {"$ne": "closing"}}, {"_id": 1})
                if still is None:
                    moved = await _reclaim_one_shelf_to_central(
                        company_id, product_id, store_id)
                    if moved > 0:
                        # El reclaim ya registró el movimiento al central: no
                        # duplicar el log de esta devolución.
                        return "applied"
                    move_type, move_sid, move_sname = \
                        "dispatch_return_central", "", ""
            await _log_move(company_id, res, move_type, qty, oid,
                            store_id=move_sid, store_name=move_sname, actor=actor)
            return "applied"
        if await _relog_if_applied(company_id, product_id, oid, move_type, qty,
                                   store_id=move_sid, actor=actor):
            return "applied"
        return "not_found"

    return await _run_idempotent(
        company_id, op_id, "dispatch_return",
        {"product_id": product_id, "store_id": store_id, "qty": qty}, _apply)


async def dispatch_applied(company_id: str, op_id: str) -> bool:
    """¿La RESERVA de inventario (dispatch) de este `op_id` se aplicó de forma
    DURADERA? Fuente de verdad: el registro permanente `company_inventory_ops`
    (result 'applied'/'duplicate') o, como respaldo ante un crash entre la
    mutación y su sellado, el guard embebido `inv_ops` del producto.

    R02 — un recuperador debe devolver stock SOLO si la reserva realmente
    ocurrió, nunca a partir de un flag de la solicitud que pudo quedar atrasado
    (ni sellar una devolución ficticia que añadiría inventario inexistente)."""
    rec = await db.company_inventory_ops.find_one(
        {"company_id": company_id, "op_key": op_id},
        {"_id": 0, "status": 1, "result": 1})
    if rec and rec.get("status") == "done" \
            and rec.get("result") in ("applied", "duplicate"):
        return True
    prod = await db.products.find_one(
        {"company_id": company_id, "inv_ops": op_id}, {"_id": 1})
    return prod is not None


async def freeze_dispatch(company_id: str, product_id: str, store_id: str,
                          qty: float, op_id: str) -> bool:
    """H03/H03-R — decisión TERMINAL Y DURADERA de la reserva de un envío: si el
    recuperador abortó este intento, una reserva TARDÍA del creador
    (`dispatch_from_store` con el mismo `op_id`) NO puede aplicarse NUNCA.
    Devuelve si la reserva YA se había aplicado de forma DURADERA (en cuyo caso
    el llamador debe devolverla con `return_dispatch`).

    Dos candados complementarios:
    (1) GUARD DURADERO `inv_burned` en el propio producto — un conjunto
        (`$addToSet`) que NO se trunca (solo crece con abortos, que son raros).
        La reserva TARDÍA de un creador se bloquea en la MISMA escritura del
        producto (`inv_burned: {$nin:[op_id]}`) y, al no vivir en el array
        acotado `inv_ops`, la decisión SOBREVIVE a la rotación: un ejecutor EN
        VUELO que resucite tras el aborto NO puede aplicar (H03-R2).
    (2) H03-R — resultado TERMINAL 'burned' en `company_inventory_ops` (registro
        PERMANENTE de idempotencia). Un creador que reanude —incluso tras rotar
        el array— encuentra ese resultado en `_run_idempotent` y recibe 'burned'
        SIN llegar jamás a `apply_fn`. Se sella con el MISMO payload_hash que
        usaría `dispatch_from_store` (si no, se leería como 'conflict'), y de
        forma CONDICIONAL para no pisar un 'applied'/'duplicate' real."""
    # (1) GUARD DURADERO no truncado en el producto.
    await db.products.update_one(
        {"id": product_id, "company_id": company_id},
        {"$addToSet": {"inv_burned": op_id}})
    if await dispatch_applied(company_id, op_id):
        return True
    phash = _payload_hash("dispatch", {"product_id": product_id,
                                       "store_id": store_id, "qty": _q(qty)})
    try:
        await db.company_inventory_ops.update_one(
            {"company_id": company_id, "op_key": op_id,
             "result": {"$nin": ["applied", "duplicate"]}},
            {"$set": {"op_type": "dispatch", "payload_hash": phash,
                      "status": "done", "result": "burned",
                      "done_at": iso(now_utc())},
             "$setOnInsert": {"company_id": company_id, "op_key": op_id,
                              "created_at": iso(now_utc())}},
            upsert=True)
    except DuplicateKeyError:
        # Existe un registro que NO cumple el filtro (ya 'applied'/'duplicate'):
        # la reserva ganó la carrera del token → el llamador debe devolverla.
        return True
    return False



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
    by_store[sid] ≥ qty. IDEMPOTENTE y DURADERA por `op_id`; respeta el GUARD
    DURADERO de aborto `inv_burned` (decisión terminal del healer). 'applied'
    |'insufficient'|'burned'|'not_found'|'invalid'."""
    qty = _q(qty)
    if qty <= 0:
        return "invalid"

    async def _apply(oid: str) -> str:
        # H03-R2 — GUARD DE ABORTO DURADERO (igual que dispatch): `inv_burned`
        # NO truncado cierra la ventana EN VUELO y sobrevive a la rotación.
        res = await db.products.find_one_and_update(
            {"id": product_id, "company_id": company_id,
             "inv_ops": {"$nin": [oid]},
             "inv_burned": {"$nin": [oid]},
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
        # Decisión TERMINAL DURADERA de aborto presente → jamás muta.
        if await db.products.find_one(
                {"id": product_id, "company_id": company_id, "inv_burned": oid},
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


async def pickup_applied(company_id: str, op_id: str) -> bool:
    """P01 — ¿La RESERVA de UBICACIÓN (pickup) de este `op_id` se aplicó de
    forma DURADERA? Igual criterio que `dispatch_applied` pero para la capa de
    ubicación: fuente de verdad el registro PERMANENTE `company_inventory_ops`
    (result 'applied'/'duplicate'), con respaldo en el guard embebido `inv_ops`
    del producto ante un crash entre la mutación y su sellado.

    `burn_or_undo_pickup` debe restituir la tienda SIEMPRE que la reserva
    realmente ocurrió, aunque el token haya salido del array acotado `inv_ops`
    por rotación (>1000 operaciones) — mirar solo `inv_ops` perdía la devolución."""
    rec = await db.company_inventory_ops.find_one(
        {"company_id": company_id, "op_key": op_id},
        {"_id": 0, "status": 1, "result": 1})
    if rec and rec.get("status") == "done" \
            and rec.get("result") in ("applied", "duplicate"):
        return True
    prod = await db.products.find_one(
        {"company_id": company_id, "inv_ops": op_id}, {"_id": 1})
    return prod is not None


async def burn_or_undo_pickup(company_id: str, product_id: str, store_id: str,
                              qty: float, op_id: str,
                              actor: Optional[dict] = None) -> str:
    """Decisión TERMINAL para la reserva de ubicación de una recogida en tienda
    (mirror de burn_or_undo_stock): marca PRIMERO el GUARD DURADERO `inv_burned`
    (conjunto no truncado del producto) y LUEGO resuelve el efecto por EVIDENCIA
    DURADERA (`pickup_applied`, no solo el array acotado `inv_ops`):

    - Si la reserva YA se aplicó de forma duradera, la deshace con
      `restore_pickup` (`op:undo`, idempotente) y conserva intacta la evidencia
      'applied' original (reverso en una clave separada). P01 — esto funciona
      aunque `op_id` haya salido de `inv_ops` por rotación (>1000 ops).
    - Si NUNCA se aplicó, SELLA la decisión terminal 'burned' en
      `company_inventory_ops` (igual que `freeze_dispatch`) para trazabilidad
      duradera y para que un creador que reanude reciba 'burned' por
      `_run_idempotent`; el guard `inv_burned` bloquea además al ejecutor EN
      VUELO que resucite tras rotar `inv_ops` (H03-R2). 'undone'|'burned'."""
    qty = _q(qty)
    await db.products.update_one(
        {"id": product_id, "company_id": company_id},
        {"$addToSet": {"inv_burned": op_id}})
    if await pickup_applied(company_id, op_id):
        await restore_pickup(company_id, product_id, store_id, qty,
                             f"{op_id}:undo", actor=actor)
        return "undone"
    # Nunca aplicada → sella la decisión TERMINAL 'burned' de forma DURADERA.
    phash = _payload_hash("pickup", {"product_id": product_id,
                                     "store_id": store_id, "qty": qty})
    try:
        await db.company_inventory_ops.update_one(
            {"company_id": company_id, "op_key": op_id,
             "result": {"$nin": ["applied", "duplicate"]}},
            {"$set": {"op_type": "pickup", "payload_hash": phash,
                      "status": "done", "result": "burned",
                      "done_at": iso(now_utc())},
             "$setOnInsert": {"company_id": company_id, "op_key": op_id,
                              "created_at": iso(now_utc())}},
            upsert=True)
    except DuplicateKeyError:
        # Carrera: apareció un registro 'applied'/'duplicate' entretanto → la
        # reserva ganó el token; deshacer en vez de quemar (sin doble efecto).
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


async def _reclaim_one_shelf_to_central(company_id: str, product_id: str,
                                        store_id: str) -> float:
    """Reubica al CENTRAL toda la existencia residual de `by_store[store_id]` de
    UN producto (distributed −= q; `stock` total intacto) y elimina la clave.
    Atómico en un solo documento e idempotente (tras ejecutarse la clave ya no
    existe). Devuelve la cantidad reubicada (0 si no había estantería)."""
    before = await db.products.find_one_and_update(
        {"id": product_id, "company_id": company_id,
         f"by_store.{store_id}": {"$gt": 0}},
        [{"$set": {"distributed": {"$round": [{"$subtract": [
            {"$ifNull": ["$distributed", 0]},
            {"$ifNull": [f"$by_store.{store_id}", 0]}]}, QTY_DECIMALS]}}},
         {"$unset": f"by_store.{store_id}"}],
        projection={"_id": 0, "id": 1, "name": 1, f"by_store.{store_id}": 1},
        return_document=ReturnDocument.BEFORE)
    if before is None:
        return 0.0
    qty = _q((before.get("by_store") or {}).get(store_id))
    if qty > 0:
        await _log_move(company_id, before, "dispatch_return_central", qty,
                        f"orphan-reclaim:{store_id}:{product_id}:{uuid.uuid4().hex}")
    return qty


async def reclaim_store_shelf_to_central(company_id: str, store_id: str) -> int:
    """R06 — barrido FINAL de cierre: reubica al CENTRAL cualquier existencia
    residual que haya quedado en `by_store[store_id]` (p. ej. una devolución que
    ganó la carrera contra el borrado de la tienda). Mueve la cantidad a central
    (distributed −= q; `stock` total intacto) y elimina la clave. Idempotente:
    tras ejecutarse `by_store[store_id]` no existe, por lo que un reintento no
    reaplica. Se ejecuta DESPUÉS de borrar la tienda, cuando ya no pueden
    llegar nuevas devoluciones a su estantería. Devuelve nº de productos saneados."""
    pids = [p["id"] for p in await db.products.find(
        {"company_id": company_id, f"by_store.{store_id}": {"$gt": 0}},
        {"_id": 0, "id": 1}).to_list(5000)]
    reclaimed = 0
    for pid in pids:
        if await _reclaim_one_shelf_to_central(company_id, pid, store_id) > 0:
            reclaimed += 1
    return reclaimed


async def heal_orphan_store_shelves(company_id: Optional[str] = None,
                                    limit: int = 2000) -> int:
    """H04/H04-R — reconciliación DURADERA de estanterías HUÉRFANAS: reubica al
    ALMACÉN CENTRAL cualquier `by_store[sid]` que referencie una tienda que ya
    NO EXISTE (o está en cierre). Garantiza que una devolución con lectura
    antigua reanudada DESPUÉS del barrido final —o interrumpida antes de su
    self-heal— no deje unidades colgando sin tienda, también tras fallos.

    H04-R — se SELECCIONAN los HUÉRFANOS ANTES de limitar (agregación con
    `$lookup` a `stores`): si se limitara primero por `by_store` no vacío, una
    multitud de productos SANOS podría ocupar siempre el lote y dejar fuera a un
    huérfano para siempre. Al filtrar a huérfanos antes del `$limit`, los sanos
    nunca consumen cupo y pasadas sucesivas DRENAN todos los candidatos
    (progreso garantizado). Idempotente, reanudable y aislado por producto.
    Devuelve el nº de estanterías huérfanas saneadas."""
    match: dict = {"by_store": {"$exists": True, "$nin": [None, {}]}}
    if company_id:
        match["company_id"] = company_id
    pipe = [
        {"$match": match},
        {"$project": {"id": 1, "company_id": 1,
                      "shelves": {"$objectToArray": "$by_store"}}},
        {"$unwind": "$shelves"},
        {"$match": {"shelves.v": {"$gt": 0}}},
        {"$lookup": {
            "from": "stores",
            "let": {"cid": "$company_id", "sid": "$shelves.k"},
            "pipeline": [
                {"$match": {"$expr": {"$and": [
                    {"$eq": ["$company_id", "$$cid"]},
                    {"$eq": ["$id", "$$sid"]},
                    {"$ne": ["$status", "closing"]},
                ]}}},
                {"$project": {"_id": 1}},
            ],
            "as": "store"}},
        {"$match": {"store": {"$eq": []}}},   # estantería sin tienda viva = huérfana
        {"$group": {"_id": "$id",
                    "company_id": {"$first": "$company_id"},
                    "sids": {"$addToSet": "$shelves.k"}}},
        {"$limit": int(limit)},
    ]
    rows = await db.products.aggregate(pipe).to_list(int(limit))
    reclaimed = 0
    for r in rows:
        for sid in r.get("sids") or []:
            try:
                if await _reclaim_one_shelf_to_central(
                        r["company_id"], r["_id"], sid) > 0:
                    reclaimed += 1
            except Exception as e:  # noqa: BLE001
                # Un fallo por producto NO debe bloquear el resto de la cola.
                logger.error("[orphan-shelf] falló %s/%s: %s",
                             r.get("_id"), sid, e)
    return reclaimed


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
        store_min = p.get("store_min") or {}
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
                 "qty": _q(q),
                 "min": _q(store_min.get(sid)),
                 "low": bool(_q(store_min.get(sid)) > 0 and _q(q) <= _q(store_min.get(sid)))}
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



async def maybe_alert_store_out_of_stock(company_id: str, product_id: str,
                                         store_id: str) -> None:
    """Alerta POR TIENDA (Empresa): cuando una SUCURSAL concreta cae a/por
    debajo de SU umbral configurable `store_min[sid]` (0 = sin existencias),
    avisa UNA vez a la Empresa para reabastecer ANTES de agotarse. Se RE-ARMA
    cuando la tienda vuelve a superar ese umbral (distribución/reabastecimiento).
    No alerta por tiendas inexistentes o en cierre (vaciado intencional).
    Best-effort: nunca rompe el flujo de la venta/despacho."""
    if not store_id:
        return
    try:
        p = await db.products.find_one(
            {"id": product_id, "company_id": company_id},
            {"_id": 0, "id": 1, "name": 1, f"by_store.{store_id}": 1,
             f"store_min.{store_id}": 1, f"store_low_alerted.{store_id}": 1})
        if not p:
            return
        shelf = _q((p.get("by_store") or {}).get(store_id))
        threshold = _q((p.get("store_min") or {}).get(store_id))
        alerted = bool((p.get("store_low_alerted") or {}).get(store_id))
        if shelf <= threshold and not alerted:
            # No avisar por una tienda inexistente o en cierre (su vaciado es
            # intencional, no un agotamiento por ventas).
            store = await db.stores.find_one(
                {"id": store_id, "company_id": company_id},
                {"_id": 0, "name": 1, "status": 1, "active": 1})
            if not store or store.get("status") == "closing":
                return
            await db.products.update_one(
                {"id": product_id, "company_id": company_id},
                {"$set": {f"store_low_alerted.{store_id}": True}})
            try:
                from routes.notifications import _insert_notification
                sname = store.get("name", "") or "una tienda"
                pname = p.get("name", "")
                if shelf <= 0:
                    title = "Tienda sin existencias"
                    msg = (f"«{pname}» se agotó en {sname}. Reabastece esa "
                           "sucursal (distribuye desde el almacén central) para "
                           "seguir vendiendo allí.")
                else:
                    title = "Stock bajo en tienda"
                    msg = (f"«{pname}» está por debajo del mínimo en {sname} "
                           f"(quedan {_q(shelf)}, mínimo {_q(threshold)}). "
                           "Reabastece esa sucursal antes de que se agote.")
                await _insert_notification(
                    recipient_user_id=company_id, type="company_store_out_of_stock",
                    title=title, message=msg,
                    data={"product_id": product_id, "store_id": store_id,
                          "store_name": sname, "remaining": _q(shelf),
                          "min_stock": _q(threshold)})
            except Exception as e:  # noqa: BLE001
                logger.error(f"store-out-of-stock notify failed: {e}")
        elif shelf > threshold and alerted:
            await db.products.update_one(
                {"id": product_id, "company_id": company_id},
                {"$set": {f"store_low_alerted.{store_id}": False}})
    except Exception as e:  # noqa: BLE001
        logger.error(f"maybe_alert_store_out_of_stock failed: {e}")


# ============================================================
# OBS-01 — observabilidad y RETENCIÓN SEGURA del guard durable `inv_burned`
# ------------------------------------------------------------
# `inv_burned` es un conjunto DURADERO (no truncado) de op_ids de reservas
# abortadas; en la MISMA escritura del producto impide que una reserva TARDÍA o
# EN VUELO con ese op_id vuelva a aplicarse (H03-R / H03-R2). Como solo crece,
# se vigila su tamaño y se poda de forma SEGURA: un guard se retira ÚNICAMENTE
# cuando su operación está TERMINALMENTE resuelta en `company_inventory_ops`
# (`status=done`) y es ANTIGUA. Un ejecutor EN VUELO/pausado deja su op en
# 'pending' (nunca 'done'), así que su guard JAMÁS se poda → nunca se retira un
# candado que aún proteja una escritura en vuelo.
# ============================================================

INV_BURNED_ALERT_THRESHOLD = 5000
INV_BURNED_RETENTION_DAYS = 90


async def inv_burned_stats(threshold: int = INV_BURNED_ALERT_THRESHOLD,
                           top: int = 50) -> dict:
    """Observabilidad: tamaño del guard `inv_burned` por producto. Devuelve los
    agregados y el detalle de los productos que SUPERAN `threshold`."""
    cursor = db.products.aggregate([
        {"$match": {"inv_burned": {"$exists": True, "$ne": []}}},
        {"$project": {"_id": 0, "id": 1, "company_id": 1, "name": 1,
                      "size": {"$size": {"$ifNull": ["$inv_burned", []]}}}},
        {"$sort": {"size": -1}},
    ])
    rows = [r async for r in cursor]
    over = [r for r in rows if r["size"] >= threshold]
    return {
        "threshold": threshold,
        "products_with_guards": len(rows),
        "total_guard_entries": sum(r["size"] for r in rows),
        "max_size": rows[0]["size"] if rows else 0,
        "over_threshold_count": len(over),
        "over_threshold": over[:top],
        "top": rows[:top],
    }


async def prune_inv_burned_guards(retention_days: int = INV_BURNED_RETENTION_DAYS,
                                  max_products: int = 500) -> int:
    """Retención SEGURA del guard `inv_burned`: retira los op_ids cuya operación
    está `done` en `company_inventory_ops` y cuyo `done_at` es MÁS ANTIGUO que
    la ventana. NUNCA retira el guard de una operación 'pending'/en vuelo ni de
    una sin evidencia terminal. Devuelve el nº total de guards podados."""
    cutoff = iso(now_utc() - timedelta(days=retention_days))
    pruned = 0
    cursor = db.products.find(
        {"inv_burned": {"$exists": True, "$ne": []}},
        {"_id": 0, "id": 1, "company_id": 1, "inv_burned": 1}).limit(max_products)
    async for prod in cursor:
        guards = prod.get("inv_burned") or []
        if not guards:
            continue
        # Solo op_ids TERMINALMENTE resueltos ('done') y antiguos son podables.
        terminal = [r["op_key"] async for r in db.company_inventory_ops.find(
            {"company_id": prod["company_id"], "op_key": {"$in": guards},
             "status": "done", "done_at": {"$lt": cutoff}},
            {"_id": 0, "op_key": 1})]
        if not terminal:
            continue
        res = await db.products.update_one(
            {"id": prod["id"], "company_id": prod["company_id"]},
            {"$pull": {"inv_burned": {"$in": terminal}}})
        if res.modified_count:
            pruned += len(terminal)
            logger.info(
                f"[inv-burned-prune] product={prod['id']} podados={len(terminal)}")
    return pruned
