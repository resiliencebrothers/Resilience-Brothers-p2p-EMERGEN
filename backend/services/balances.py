"""Money — rate lookup, USDT conversion, user balance helpers, defensive mode
and account-status guards. Extracted from server.py during iter33 refactor.

Pure business helpers, no HTTP layer; the only side effect is MongoDB I/O via
the shared `db_client`.
"""
from typing import Optional
from datetime import datetime, timezone, timedelta

from fastapi import HTTPException

from db_client import db

# iter260(E07) — horizonte de seguridad de la compactación: un op 'applied'
# más joven que esto NUNCA se retira del registro embebido (un ejecutor lento
# del mismo op podría seguir en vuelo).
COMPACT_SAFETY_HOURS = 24


# ============================================================
# Rate lookup + USDT conversion
# ============================================================

async def build_rate_lookup() -> dict:
    """Return rate lookup dict { (from,to): rate_normal } for conversion."""
    docs = await db.rates.find({}, {"_id": 0}).to_list(1000)
    return {(d["from_code"], d["to_code"]): float(d["rate_normal"])
            for d in docs if d.get("rate_normal") is not None}


def _convert_direct(amount: float, code: str, rates: dict) -> Optional[float]:
    """Try inverse `USDT→code` first (canonical *valuation* rate used by the
    operator), falling back to direct `code→USDT` if no inverse is available.

    Rationale: when displaying a user balance in USDT-equivalent terms (or when
    checking the VIP threshold), we want the "buy-back" valuation rate the
    operator quotes — i.e. *how much USDT would I need to buy this balance*.
    The direct `code→USDT` rate is an order-execution price (the spread the
    operator applies when *receiving* USDT for code), which would understate
    holdings. Order-creation code paths use the dedicated rate-lookup logic in
    `resolve_order_rate` and are unaffected by this preference.
    """
    inverse = rates.get(("USDT", code))
    if inverse and inverse > 0:
        return amount / inverse
    if (code, "USDT") in rates:
        return amount * rates[(code, "USDT")]
    return None


def _convert_via_usd(amount: float, code: str, rates: dict) -> Optional[float]:
    """Convert code → USD → USDT. Returns None if no path."""
    usd_val = None
    if (code, "USD") in rates:
        usd_val = amount * rates[(code, "USD")]
    else:
        inv = rates.get(("USD", code))
        if inv and inv > 0:
            usd_val = amount / inv
    if usd_val is None:
        return None
    direct = _convert_direct(usd_val, "USD", rates)
    if direct is not None:
        return direct
    return usd_val  # assume 1 USD ≈ 1 USDT if no rate found


def convert_to_usdt(amount: float, code: str, rates: dict) -> Optional[float]:
    """Convert amount in `code` to USDT using available rates. Returns None if no path."""
    if amount == 0:
        return 0.0
    if code == "USDT":
        return amount
    direct = _convert_direct(amount, code, rates)
    if direct is not None:
        return direct
    return _convert_via_usd(amount, code, rates)


def convert_from_usdt(amount_usdt: float, code: str, rates: dict) -> Optional[float]:
    """Inverse of `convert_to_usdt`: given a USDT amount, return the equivalent
    in `code` using the available rate lookup. Returns None if no rate path
    exists between USDT and `code` in either direction.

    Used by `POST /vip/convert` (iter55.36i) to translate the flat 0.10 USDT
    service fee into whatever destination currency the client is converting
    into. The lookup preference mirrors `_convert_direct`:
      1. Direct `USDT→code` rate — the operator's sell-side quote for `code`.
      2. Inverse `code→USDT` rate — inverted for symmetric behavior.
    """
    if amount_usdt == 0:
        return 0.0
    if code == "USDT":
        return amount_usdt
    direct = rates.get(("USDT", code))
    if direct and direct > 0:
        return amount_usdt * direct
    inverse = rates.get((code, "USDT"))
    if inverse and inverse > 0:
        return amount_usdt / inverse
    return None


async def compute_total_usdt(user_doc: dict) -> float:
    rates = await build_rate_lookup()
    balances = dict(user_doc.get("vip_balances") or {})
    legacy = float(user_doc.get("vip_balance_usd") or 0.0)
    if legacy > 0:
        balances["USD"] = balances.get("USD", 0.0) + legacy
    return sum((convert_to_usdt(amt, code, rates) or 0) for code, amt in balances.items())


# ============================================================
# Per-currency user balance manipulation
# ============================================================

def get_user_balance(user: dict, code: str) -> float:
    """Get user's balance in a specific currency. Merges legacy vip_balance_usd into USD."""
    bal = float((user.get("vip_balances") or {}).get(code, 0.0))
    if code == "USD":
        bal += float(user.get("vip_balance_usd") or 0.0)
    return bal


async def decrement_balance(user_id: str, code: str, amount: float) -> None:
    """Débito ATÓMICO y condicional de saldo (iter248).

    El guard de saldo suficiente vive en el FILTRO del update, así el chequeo
    y el descuento ocurren en UNA sola operación de MongoDB: dos peticiones
    simultáneas no pueden gastar el mismo dinero ni dejar saldo negativo.
    Lanza 409 INSUFFICIENT_BALANCE si el saldo no alcanza (los pre-chequeos de
    los callers dan mensajes bonitos; esto es la garantía autoritativa).
    Para USD conserva el orden legacy-primero (vip_balance_usd) vía pipeline."""
    amount = float(amount)
    if amount <= 0:
        return
    # Tolerancia de coma flotante: los saldos acumulan ruido binario (p.ej.
    # 5.01 - 5.0 = 0.00999...); sin esto el guard rechazaría débitos legítimos
    # que dejan el saldo en ~0. Muy por debajo del céntimo → no habilita
    # ningún doble gasto real.
    guard = amount - 1e-6
    if code == "USD":
        res = await db.users.update_one(
            {"user_id": user_id,
             "$expr": {"$gte": [
                 {"$add": [{"$ifNull": ["$vip_balances.USD", 0.0]},
                           {"$ifNull": ["$vip_balance_usd", 0.0]}]},
                 guard]}},
            [
                {"$set": {"_legacy_take": {
                    "$min": [{"$ifNull": ["$vip_balance_usd", 0.0]}, amount]}}},
                {"$set": {
                    "vip_balance_usd": {"$subtract": [
                        {"$ifNull": ["$vip_balance_usd", 0.0]}, "$_legacy_take"]},
                    "vip_balances.USD": {"$subtract": [
                        {"$ifNull": ["$vip_balances.USD", 0.0]},
                        {"$subtract": [amount, "$_legacy_take"]}]},
                }},
                {"$unset": "_legacy_take"},
            ],
        )
    else:
        res = await db.users.update_one(
            {"user_id": user_id, f"vip_balances.{code}": {"$gte": guard}},
            {"$inc": {f"vip_balances.{code}": -amount}},
        )
    if res.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INSUFFICIENT_BALANCE",
                "message": (f"Saldo insuficiente en {code}: la operación fue "
                            "rechazada para evitar un saldo negativo."),
            },
        )


async def _ops_log_ensure(op_id: str, user_id: str, code: str, amount: float,
                          kind: str) -> str:
    """iter256(S06) — registro DURADERO insert-first (índice único por op_id).
    El identificador se persiste ANTES de mover dinero; si Mongo falla aquí la
    operación aborta sin tocar saldos (el marker/healer reintenta después).
    Devuelve el estado previo: 'new' | 'pending' | 'applied'."""
    global _OPS_LOG_READY
    if not _OPS_LOG_READY:
        await db.credit_ops.create_index("op_id", unique=True)
        _OPS_LOG_READY = True
    existing = await db.credit_ops.find_one({"op_id": op_id},
                                            {"_id": 0, "state": 1})
    if existing is None:
        try:
            await db.credit_ops.insert_one({
                "op_id": op_id, "user_id": user_id, "code": code,
                "amount": round(float(amount), 8), "kind": kind,
                "state": "pending",
                "at": datetime.now(timezone.utc).isoformat()})
            return "new"
        except Exception:
            # carrera con otro insert del mismo op_id (índice único)
            existing = await db.credit_ops.find_one({"op_id": op_id},
                                                    {"_id": 0, "state": 1})
            if existing is None:
                raise
    return "applied" if existing.get("state", "applied") == "applied" \
        else "pending"


async def _ops_log_mark_applied(op_id: str) -> None:
    await db.credit_ops.update_one(
        {"op_id": op_id},
        {"$set": {"state": "applied",
                  "applied_at": datetime.now(timezone.utc).isoformat()}})


_OPS_LOG_READY = False


def _registry_push(op_id: str) -> dict:
    # iter257(D06) — SIN $slice: un op solo sale del registro embebido cuando
    # su log duradero está 'applied' (compact_credit_registries). Así, un log
    # 'pending' cuyo op NO está en el registro significa con certeza que el
    # dinero no se movió (adiós ventana de evicción).
    return {"applied_credit_ops": op_id}


async def credit_balance_idempotent(user_id: str, code: str, amount: float,
                                    op_id: str, legacy_usd: bool = False) -> bool:
    """Acreditación EXACTAMENTE-UNA-VEZ por op_id (iter249). El $inc y el
    registro del op_id ocurren en UNA operación atómica sobre el doc del
    usuario: un reintento (o el healer de credit_recovery) nunca duplica el
    abono. `legacy_usd=True` acredita al campo histórico vip_balance_usd.
    iter254(R05): dedupe duradero vía colección credit_ops (índice único)."""
    amount = float(amount)
    if amount <= 0:
        return False
    state = await _ops_log_ensure(op_id, user_id, code, amount, "credit")
    if state == "applied":
        return False
    field = "vip_balance_usd" if (legacy_usd and code == "USD") \
        else f"vip_balances.{code}"
    res = await db.users.update_one(
        {"user_id": user_id, "applied_credit_ops": {"$ne": op_id}},
        {"$inc": {field: amount}, "$push": _registry_push(op_id)},
    )
    if res.modified_count:
        await _ops_log_mark_applied(op_id)
        return True
    if await db.users.find_one({"user_id": user_id, "applied_credit_ops": op_id},
                               {"_id": 1}):
        # iter256(S06) — aplicado antes con log a medias: reparar el log.
        await _ops_log_mark_applied(op_id)
    return False


async def debit_balance_idempotent(user_id: str, code: str, amount: float,
                                   op_id: str,
                                   allow_negative: bool = False) -> str:
    """iter254(R03) — débito atómico, condicional e IDEMPOTENTE por op_id.

    Devuelve 'applied' | 'duplicate' | 'insufficient'. El guard de saldo, el
    $inc y el registro del op_id ocurren en UNA operación sobre el doc del
    usuario, así el protocolo reserva/operación/activación puede saber con
    certeza (por el op_id) si un intento interrumpido llegó a cobrar o no.
    Para USD drena primero el campo legacy (vip_balance_usd).
    iter257(D07) — `allow_negative=True` omite el guard de saldo (deuda
    explícita, p.ej. reverso de un crédito a vendedor que ya gastó)."""
    amount = float(amount)
    if amount <= 0:
        return "applied"
    state = await _ops_log_ensure(op_id, user_id, code, amount, "debit")
    if state == "applied":
        return "duplicate"
    guard = amount - 1e-6
    if code == "USD":
        filt: dict = {"user_id": user_id, "applied_credit_ops": {"$ne": op_id}}
        if not allow_negative:
            filt["$expr"] = {"$gte": [
                {"$add": [{"$ifNull": ["$vip_balances.USD", 0.0]},
                          {"$ifNull": ["$vip_balance_usd", 0.0]}]},
                guard]}
        res = await db.users.update_one(
            filt,
            [
                {"$set": {"_legacy_take": {
                    "$min": [{"$max": [{"$ifNull": ["$vip_balance_usd", 0.0]},
                                       0.0]}, amount]}}},
                {"$set": {
                    "vip_balance_usd": {"$subtract": [
                        {"$ifNull": ["$vip_balance_usd", 0.0]}, "$_legacy_take"]},
                    "vip_balances.USD": {"$subtract": [
                        {"$ifNull": ["$vip_balances.USD", 0.0]},
                        {"$subtract": [amount, "$_legacy_take"]}]},
                    "applied_credit_ops": {"$concatArrays": [
                        {"$ifNull": ["$applied_credit_ops", []]}, [op_id]]},
                }},
                {"$unset": "_legacy_take"},
            ],
        )
    else:
        filt = {"user_id": user_id, "applied_credit_ops": {"$ne": op_id}}
        if not allow_negative:
            filt[f"vip_balances.{code}"] = {"$gte": guard}
        res = await db.users.update_one(
            filt,
            {"$inc": {f"vip_balances.{code}": -amount},
             "$push": _registry_push(op_id)},
        )
    if res.matched_count:
        await _ops_log_mark_applied(op_id)
        return "applied"
    if await db.users.find_one({"user_id": user_id, "applied_credit_ops": op_id},
                               {"_id": 1}):
        await _ops_log_mark_applied(op_id)
        return "duplicate"
    # insuficiente: liberar el intento pendiente del log duradero.
    await db.credit_ops.delete_one({"op_id": op_id, "state": "pending"})
    return "insufficient"


async def burn_or_undo_debit(user_id: str, code: str, amount: float,
                             op_id: str) -> str:
    """iter260(E08) — al abortar un plan: QUEMA el op de débito (lo sella en
    el registro del usuario y en el log duradero SIN mover dinero) para que
    un débito tardío aún en vuelo se vuelva 'duplicate'; si el débito ya se
    aplicó, lo compensa con el abono ':undo' idempotente del healer.
    El push con guard $ne y el $inc del débito compiten por el MISMO array:
    exactamente uno gana, en cualquier orden. Devuelve 'burned' | 'undone'."""
    res = await db.users.update_one(
        {"user_id": user_id, "applied_credit_ops": {"$ne": op_id}},
        {"$push": _registry_push(op_id)})
    try:
        await db.credit_ops.update_one(
            {"op_id": op_id},
            {"$set": {"state": "applied", "burned": bool(res.modified_count),
                      "applied_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True)
    except Exception:
        # carrera con el insert del propio débito (índice único): re-sellar.
        await db.credit_ops.update_one(
            {"op_id": op_id}, {"$set": {"state": "applied"}})
    if res.modified_count:
        return "burned"
    if await db.users.find_one({"user_id": user_id,
                                "applied_credit_ops": op_id}, {"_id": 1}):
        await credit_balance_idempotent(user_id, code, amount, f"{op_id}:undo",
                                        legacy_usd=(code == "USD"))
        return "undone"
    return "burned"


async def op_was_applied(user_id: str, op_id: str) -> bool:
    """¿Este op_id llegó a aplicarse? (registro embebido O log duradero en
    estado 'applied' — un log 'pending' NO prueba que el dinero se movió)."""
    if await db.users.find_one({"user_id": user_id, "applied_credit_ops": op_id},
                               {"_id": 1}):
        return True
    doc = await db.credit_ops.find_one({"op_id": op_id}, {"_id": 0, "state": 1})
    return bool(doc) and doc.get("state", "applied") == "applied"


async def accumulate_vip_balance(order: dict) -> bool:
    """Credit a VIP per-currency balance for an `accumulate` order.

    Idempotent: marks the order with `accumulated_at` on first credit and
    refuses to credit a second time. Returns True if a credit was applied,
    False if the order was already credited.

    iter51 — required so any first transition into a "money-settled" status
    (`approved` OR `completed`, including a direct pending→completed jump
    from the admin's "Completar" button) credits exactly once.

    iter254(R04) — el marker nace SIN preparar (prepared=False): el healer no
    acredita importes brutos; si hay crash antes de fijar el neto, recalcula
    la amortización (idempotente por orden) y recién entonces abona.
    """
    from services.credit_markers import pending_marker, apply_and_clear
    gross = float(order["amount_to"])
    marker = pending_marker(order["user_id"], order["to_code"], gross,
                            "order-accum", prepared=False)
    res = await db.orders.update_one(
        {"id": order["id"], "accumulated_at": {"$exists": False}},
        {"$set": {"accumulated_at": datetime.now(timezone.utc).isoformat(),
                  "credit_pending": marker}},
    )
    if res.modified_count == 0:
        # Either the order already had `accumulated_at`, or the order id
        # doesn't exist — in both cases we MUST NOT double-credit.
        return False
    net_amount = await _apply_capital_request_repayment(
        order["user_id"], order["to_code"], gross, order["id"],
    )
    if net_amount <= 0:
        # 100% of the credit went to repay debt — nothing to add to balance.
        await db.orders.update_one({"id": order["id"]},
                                   {"$unset": {"credit_pending": ""}})
        return True
    marker["amount"] = round(float(net_amount), 8)
    marker["prepared"] = True
    await db.orders.update_one(
        {"id": order["id"], "credit_pending.op_id": marker["op_id"]},
        {"$set": {"credit_pending.amount": marker["amount"],
                  "credit_pending.prepared": True}},
    )
    await apply_and_clear("orders", order["id"], marker)
    return True


async def _apply_capital_request_repayment(user_id: str, currency: str,
                                             amount: float, order_id: str) -> float:
    """iter55.32 — pay down active capital debts before crediting an
    accumulated order. Returns the NET amount that should be credited to
    the VIP's balance (original minus deductions).

    Rules:
      - Only requests with `status='disbursed'` and matching `currency_code`
        are considered.
      - FIFO: oldest disbursed-first.
      - Each order is discounted ONCE by the OLDEST active debt's
        `discount_pct`. That total budget is then FIFO-distributed across
        all active debts (older first) up to each debt's remaining amount.
        Rationale: multiple debts should not compound the discount — the
        VIP should never pay >`discount_pct` of any single order back.
      - When `debt_remaining` hits 0 → status flips to `paid_off`.
      - Repayment events are logged inside the request doc for audit.
      - If no active debt or amount <= 0, no-op returning the input amount.

    iter254(R04/R08) — idempotente por orden y condicional por deuda:
      - Cada contribución exige `debt_remaining >= contribución` y que la
        orden NO haya contribuido ya a esa deuda, en el MISMO update: dos
        acumulaciones concurrentes no pueden amortizar más deuda de la real.
      - Las contribuciones previas de la misma orden (recuperación tras un
        crash) se descuentan del presupuesto: reejecutar es seguro.
    """
    if amount <= 0:
        return amount
    now_iso_ = datetime.now(timezone.utc).isoformat()
    # contribuciones ya aplicadas por ESTA orden (reintento/recuperación)
    prior = 0.0
    prior_map: dict = {}
    prev_docs = await db.capital_requests.find(
        {"user_id": user_id, "currency_code": currency,
         "repayment_events.order_id": order_id},
        {"_id": 0, "id": 1, "repayment_events": 1},
    ).to_list(50)
    for d_ in prev_docs:
        got = sum(float(ev.get("amount") or 0)
                  for ev in (d_.get("repayment_events") or [])
                  if ev.get("order_id") == order_id)
        prior_map[d_.get("id")] = round(got, 6)
        prior += got
    prior = round(prior, 6)
    active = await db.capital_requests.find(
        {"user_id": user_id, "status": "disbursed", "currency_code": currency},
        {"_id": 0},
    ).sort("disbursed_at", 1).to_list(50)
    # iter256(S08) — presupuesto ESTABLE por orden: se persiste al primer
    # cálculo (repayment_plans, índice único orden+moneda). Todo retry o
    # recuperación reutiliza el MISMO presupuesto aunque las deudas activas
    # (y sus porcentajes) hayan cambiado — el neto de una orden nunca varía.
    plan = await _load_or_create_repayment_plan(user_id, currency, amount,
                                                order_id, active)
    budget_total = float(plan.get("budget_total") or 0.0)
    if not active or budget_total <= 0:
        return round(amount - prior, 6)
    budget = round(max(budget_total - prior, 0.0), 4)
    consumed = prior
    for cr in active:
        if budget <= 0:
            break
        for _attempt in range(2):
            fresh = await db.capital_requests.find_one(
                {"id": cr["id"]},
                {"_id": 0, "debt_remaining": 1, "status": 1,
                 "repayment_events": 1})
            if not fresh:
                break
            # iter257(D05)/iter260(E06) — contabilizar contribuciones de ESTA
            # orden que aparecieron después de la lectura inicial (ejecutor
            # concurrente o reintento) ANTES de descartar la deuda por estado:
            # si el otro ejecutor acaba de liquidarla (paid_off) con una
            # contribución de esta misma orden, ese importe TAMBIÉN consume
            # presupuesto — de lo contrario dos ejecutores amortizan de más.
            done_now = round(sum(float(ev.get("amount") or 0)
                                 for ev in (fresh.get("repayment_events") or [])
                                 if ev.get("order_id") == order_id), 6)
            known = float(prior_map.get(cr["id"], 0.0))
            if done_now > known + 1e-9:
                delta = round(done_now - known, 6)
                budget = round(max(budget - delta, 0.0), 6)
                consumed = round(consumed + delta, 6)
                prior_map[cr["id"]] = done_now
            if fresh.get("status") != "disbursed" or done_now > 0:
                break  # deuda cerrada o esta orden ya contribuyó aquí
            debt = float(fresh.get("debt_remaining") or 0.0)
            contribution = round(min(budget, debt), 4)
            if contribution <= 0:
                break
            res = await db.capital_requests.update_one(
                {"id": cr["id"], "status": "disbursed",
                 "debt_remaining": {"$gte": contribution - 1e-9},
                 "repayment_events": {"$not": {"$elemMatch": {"order_id": order_id}}}},
                {"$inc": {"debt_remaining": -contribution},
                 "$set": {"updated_at": now_iso_},
                 "$push": {"repayment_events": {
                     "order_id": order_id, "amount": contribution,
                     "at": now_iso_}}},
            )
            if res.matched_count:
                budget = round(budget - contribution, 6)
                consumed = round(consumed + contribution, 6)
                # liquidada → paid_off (claim condicional al llegar a ~0)
                await db.capital_requests.update_one(
                    {"id": cr["id"], "status": "disbursed",
                     "debt_remaining": {"$lte": 0.0001}},
                    {"$set": {"status": "paid_off", "paid_off_at": now_iso_,
                              "debt_remaining": 0.0}})
                break
            # perdimos una carrera: reintentar UNA vez con lectura fresca

    return round(amount - consumed, 6)


_PLAN_INDEX_READY = False


async def _load_or_create_repayment_plan(user_id: str, currency: str,
                                         amount: float, order_id: str,
                                         active: list) -> dict:
    """iter256(S08) — plan de amortización por orden (insert-first, único)."""
    global _PLAN_INDEX_READY
    if not _PLAN_INDEX_READY:
        await db.repayment_plans.create_index(
            [("order_id", 1), ("currency", 1)], unique=True)
        _PLAN_INDEX_READY = True
    key = {"order_id": order_id, "currency": currency}
    plan = await db.repayment_plans.find_one(key, {"_id": 0})
    if plan:
        return plan
    oldest_pct = float(active[0].get("discount_pct") or 0.0) if active else 0.0
    doc = {**key, "user_id": user_id, "gross": round(float(amount), 6),
           "pct": oldest_pct,
           "budget_total": round(float(amount) * oldest_pct / 100.0, 4),
           "at": datetime.now(timezone.utc).isoformat()}
    try:
        await db.repayment_plans.insert_one({**doc})
        return doc
    except Exception:
        return await db.repayment_plans.find_one(key, {"_id": 0}) or doc


async def compact_credit_registries(threshold: int = 2000,
                                    keep: int = 1500) -> int:
    """iter257(D06) — compactación del registro embebido de ops de saldo.

    Sustituye al viejo $slice ciego: solo se retiran ops cuyo log duradero
    está 'applied' (o que no tienen log — legado anterior a iter254, cuyos
    intentos están muertos). Un op con log 'pending' se CONSERVA siempre:
    su presencia/ausencia en el registro es la evidencia que desambigua si
    el dinero llegó a moverse.

    iter260(E07) — además, un op 'applied' RECIENTE (< horizonte de
    seguridad) también se conserva: un ejecutor lento del mismo op_id podría
    seguir en vuelo con su decisión antigua, y retirar el ID le permitiría
    re-aplicar la operación. Ningún request HTTP sobrevive 24h, así que el
    horizonte cierra esa ventana sin transacciones multi-documento."""
    horizon = (datetime.now(timezone.utc)
               - timedelta(hours=COMPACT_SAFETY_HOURS)).isoformat()
    users = await db.users.find(
        {f"applied_credit_ops.{threshold}": {"$exists": True}},
        {"_id": 0, "user_id": 1, "applied_credit_ops": 1}).to_list(50)
    removed = 0
    for u in users:
        ops = u.get("applied_credit_ops") or []
        candidates = ops[:-keep] if keep else ops
        if not candidates:
            continue
        rows = await db.credit_ops.find(
            {"op_id": {"$in": candidates}},
            {"_id": 0, "op_id": 1, "state": 1, "at": 1,
             "applied_at": 1}).to_list(len(candidates))
        by_id = {d["op_id"]: d for d in rows}
        removable = []
        for op in candidates:
            d = by_id.get(op)
            if d is None:
                removable.append(op)  # sin log duradero (legado muerto)
                continue
            if d.get("state", "applied") != "applied":
                continue  # pending → evidencia, se conserva
            applied_at = d.get("applied_at") or d.get("at") or ""
            if applied_at >= horizon:
                continue  # E07: aplicado hace poco → posible ejecutor en vuelo
            removable.append(op)
        if removable:
            await db.users.update_one(
                {"user_id": u["user_id"]},
                {"$pull": {"applied_credit_ops": {"$in": removable}}})
            removed += len(removable)
    return removed


# ============================================================
# Account status + defensive mode
# ============================================================

DEFENSIVE_MODE_KEY = "defensive_mode"


async def get_defensive_mode() -> dict:
    doc = await db.system_config.find_one({"key": DEFENSIVE_MODE_KEY}, {"_id": 0})
    return doc or {
        "key": DEFENSIVE_MODE_KEY, "enabled": False, "reason": "",
        "enabled_at": None, "enabled_by_email": "",
    }


async def assert_not_defensive(action_label: str) -> None:
    state = await get_defensive_mode()
    if state.get("enabled"):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "DEFENSIVE_MODE",
                "message": (f"La plataforma está en modo defensivo y temporalmente "
                            f"no acepta {action_label}. Intenta de nuevo en unos minutos."),
                "reason": state.get("reason", ""),
            },
        )


async def assert_account_active(user: dict) -> None:
    """Gate client operations (orders, withdrawals, redemptions) on account_status.
    Staff/admin always pass through."""
    if user.get("role") in ("admin", "employee"):
        return
    status = user.get("account_status", "active")
    if status == "active":
        return
    if status == "under_review":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ACCOUNT_UNDER_REVIEW",
                "message": ("Tu cuenta está bajo revisión. Un miembro del staff debe "
                            "verificar tu teléfono antes de poder operar. Contacta a "
                            "soporte para acelerar la verificación."),
            },
        )
    # blocked
    raise HTTPException(
        status_code=403,
        detail={
            "code": "ACCOUNT_BLOCKED",
            "message": "Tu cuenta está bloqueada. Si crees que es un error, contacta a soporte.",
        },
    )
