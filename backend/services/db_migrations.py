"""Idempotent one-shot DB migrations that run on FastAPI startup.

iter55.3 + iter55.7 — strip whitespace and upper-case every currency code
across every collection that stores one. Data-entry typos like `"CUP "` or
`" USD"` would otherwise split accounting rows or break rate lookups.

Extracted from `server.py` during the iter45 refactor to keep the bootstrap
module small and focused on wiring routers + middleware.
"""
import logging
from typing import Any, Iterable

logger = logging.getLogger(__name__)

# (collection_attr, [field, field, ...]) — every string field on the collection
# that must be normalised. Keys resolve against `db.<attr>`.
_WHITESPACE_TARGETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("currencies", ("code",)),
    ("rates", ("from_code", "to_code")),
    ("orders", ("from_code", "to_code")),
    ("withdrawals", ("currency",)),
    ("company_withdrawals", ("currency",)),
    ("company_fund_adjustments", ("currency",)),
)


async def _clean_field(collection: Any, coll_name: str, field: str) -> int:
    """Trim + upper-case a single field on every row that has leading/trailing
    whitespace. Returns the count of updated rows."""
    updated = 0
    cursor = collection.find(
        {field: {"$regex": r"^\s|\s$"}},
        {"_id": 0, "id": 1, field: 1},
    )
    async for row in cursor:
        raw = row.get(field) or ""
        fixed = raw.strip().upper()
        if fixed and fixed != raw:
            await collection.update_one(
                {"id": row["id"]}, {"$set": {field: fixed}}
            )
            logger.info(
                f"Migrated {coll_name}.{field} {raw!r} → {fixed!r} on id={row['id']}"
            )
            updated += 1
    return updated


async def clean_currency_whitespace(
    db: Any, targets: Iterable[tuple[str, tuple[str, ...]]] = _WHITESPACE_TARGETS,
) -> int:
    """Iterate every (collection, fields) pair in `targets` and clean each field
    in place. Failures on one collection are logged but don't abort the rest.
    Returns the total number of rows updated across all targets."""
    total = 0
    for coll_attr, fields in targets:
        collection = getattr(db, coll_attr, None)
        if collection is None:
            continue
        for field in fields:
            try:
                total += await _clean_field(collection, coll_attr, field)
            except Exception as e:  # noqa: BLE001
                logger.error(f"Currency whitespace migration failed on {coll_attr}.{field}: {e}")
    return total


async def migrate_vip_ledger_positive_to_balances(db: Any) -> int:
    """iter113 — one-shot: move every VIP ledger `positive_usdt` into the
    user's per-currency balance (`vip_balances.USDT`). Owner decision
    (30 Jul 2026): the ledger surplus IS account balance — withdrawable via
    Depósitos y Retiros like any other balance. Idempotent via a marker doc
    in the `migrations` collection."""
    from datetime import datetime, timezone
    key = "vip_ledger_positive_to_balances"
    if await db.migrations.find_one({"key": key}):
        return 0
    moved = 0
    now = datetime.now(timezone.utc).isoformat()
    async for row in db.vip_ledger.find({"positive_usdt": {"$gt": 0}}, {"_id": 0}):
        amount = round(float(row.get("positive_usdt") or 0.0), 4)
        if amount <= 0:
            continue
        await db.users.update_one(
            {"user_id": row["vip_user_id"]},
            {"$inc": {"vip_balances.USDT": amount}},
        )
        await db.vip_ledger.update_one(
            {"vip_user_id": row["vip_user_id"]},
            {"$set": {"positive_usdt": 0.0, "updated_at": now}},
        )
        await db.audit_log.insert_one({
            "id": f"mig_{row['vip_user_id'][-8:]}_{int(datetime.now(timezone.utc).timestamp())}",
            "actor_id": "system",
            "actor_email": "system@resilience",
            "actor_name": "Migración automática",
            "actor_role": "system",
            "action": "vip_ledger.migrate_positive_to_balance",
            "entity_type": "user",
            "entity_id": row["vip_user_id"],
            "summary": f"Saldo a favor del ledger ({amount} USDT) migrado al balance USDT de la cuenta",
            "details": {"amount_usdt": amount},
            "created_at": now,
        })
        logger.info(f"Migrated vip_ledger positive {amount} USDT → vip_balances.USDT for {row['vip_user_id']}")
        moved += 1
    await db.migrations.insert_one({"key": key, "at": now, "moved": moved})
    return moved


async def migrate_split_sell_rates_to_single(db: Any) -> int:
    """iter287 — la empresa VENDE a UN solo precio para todos los niveles:
    consolida los legados rate_sell_normal/rate_sell_vip en `rate_sell`
    (el mayor de los dos — nunca vender más barato) y retira los campos
    viejos. Idempotente: sin campos legados no hace nada."""
    n = 0
    rows = await db.rates.find(
        {"$or": [{"rate_sell_normal": {"$exists": True}},
                 {"rate_sell_vip": {"$exists": True}}]},
        {"_id": 0}).to_list(1000)
    for d in rows:
        vals = [float(x) for x in (d.get("rate_sell_normal"),
                                   d.get("rate_sell_vip"))
                if x is not None and float(x) > 0]
        update: dict = {"$unset": {"rate_sell_normal": "",
                                   "rate_sell_vip": ""}}
        current = d.get("rate_sell")
        if vals and not (current is not None and float(current) > 0):
            update["$set"] = {"rate_sell": max(vals)}
        await db.rates.update_one({"id": d["id"]}, update)
        n += 1
    return n


async def migrate_assignment_uid_for_existing_reservations(db: Any) -> int:
    """ABA (A08) — sella con `assignment_uid` las reservas `available` YA
    existentes (asignadas a un mensajero pero sin uid) para que el blindaje
    contra peticiones atrasadas (aceptar/rechazar de un ciclo anterior) cubra
    también los datos previos, no solo las asignaciones nuevas. Idempotente:
    solo toca reservas vivas sin uid y cada una recibe un uid único; una
    segunda ejecución no vuelve a tocarlas."""
    import uuid as _uuid

    n = 0
    rows = await db.deliveries.find(
        {"status": "available",
         "assigned_to_courier_id": {"$nin": [None, ""]},
         "assignment_uid": {"$exists": False}},
        {"_id": 0, "id": 1}).to_list(5000)
    for d in rows:
        res = await db.deliveries.update_one(
            {"id": d["id"], "assignment_uid": {"$exists": False}},
            {"$set": {"assignment_uid": _uuid.uuid4().hex}})
        n += res.modified_count
    if n:
        logger.info(f"Sealed assignment_uid on {n} legacy reservations (A08)")
    return n


async def migrate_assignment_uid_for_accepted_deliveries(db: Any) -> int:
    """M01-B — sella con `assignment_uid` las entregas YA `accepted` existentes
    que no tengan uid (aceptaciones de trabajos libres anteriores al cambio que
    sella el ciclo al aceptar). Sin esto, dos ciclos aceptados heredados sin uid
    serían indistinguibles y una reasignación administrativa atrasada podría
    actuar sobre un ciclo aceptado posterior (ABA). Idempotente: cada entrega
    recibe un uid único y una segunda ejecución no vuelve a tocarla."""
    import uuid as _uuid

    n = 0
    rows = await db.deliveries.find(
        {"status": "accepted", "assignment_uid": {"$exists": False}},
        {"_id": 0, "id": 1}).to_list(5000)
    for d in rows:
        res = await db.deliveries.update_one(
            {"id": d["id"], "status": "accepted",
             "assignment_uid": {"$exists": False}},
            {"$set": {"assignment_uid": _uuid.uuid4().hex}})
        n += res.modified_count
    if n:
        logger.info(f"Sealed assignment_uid on {n} legacy accepted deliveries (M01-B)")
    return n



async def migrate_backfill_vendor_commission_snapshot(db: Any) -> int:
    """E01 — congela la comisión de empresa en los canjes YA existentes que
    aún no se han entregado y no tienen snapshot. Decisión de producto
    (efectiva desde el despliegue): cada canje pendiente/aprobado queda sellado
    con la tasa global vigente (p. ej. 1%), base = total_usd y el neto/comisión
    derivados, para que la entrega posterior no dependa de la config global.
    Idempotente: solo toca canjes de vendedor (vendor_owner_id) no entregados
    sin `vendor_commission_pct_snapshot`; una segunda ejecución no hace nada."""
    from datetime import datetime, timezone
    sdoc = await db.settings.find_one(
        {"id": "global"}, {"_id": 0, "vendor_commission_pct": 1}) or {}
    raw = sdoc.get("vendor_commission_pct")
    pct = float(raw) if raw is not None else 1.0
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    rows = await db.redemptions.find(
        {"vendor_owner_id": {"$nin": [None, ""]},
         "status": {"$in": ["pending", "approved"]},
         "vendor_commission_pct_snapshot": {"$exists": False}},
        {"_id": 0, "id": 1, "total_usd": 1}).to_list(10000)
    for d in rows:
        base = round(float(d.get("total_usd") or 0), 6)
        net = round(base * (1 - pct / 100.0), 6)
        commission = round(base - net, 6)
        res = await db.redemptions.update_one(
            {"id": d["id"],
             "vendor_commission_pct_snapshot": {"$exists": False}},
            {"$set": {"vendor_commission_pct_snapshot": pct,
                      "vendor_commission_base_usdt": base,
                      "vendor_commission_usdt": commission,
                      "vendor_net_usdt": net,
                      "vendor_commission_snapshot_at": now}})
        n += res.modified_count
    if n:
        logger.info(f"E01 — sellada comisión congelada ({pct}%) en {n} canjes pendientes")
    return n