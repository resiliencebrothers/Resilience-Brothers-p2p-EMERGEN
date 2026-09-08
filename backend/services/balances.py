"""Money — rate lookup, USDT conversion, user balance helpers, defensive mode
and account-status guards. Extracted from server.py during iter33 refactor.

Pure business helpers, no HTTP layer; the only side effect is MongoDB I/O via
the shared `db_client`.
"""
from typing import Optional
from datetime import datetime, timezone

from fastapi import HTTPException

from db_client import db


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


async def _ops_log(op_id: str, user_id: str, code: str, amount: float,
                   kind: str) -> None:
    """iter254(R05) — registro DURADERO de operaciones aplicadas (índice único
    por op_id): aunque el op salga del registro embebido del usuario (cap
    2000), este log lo sigue recordando y bloquea cualquier replay."""
    global _OPS_LOG_READY
    try:
        if not _OPS_LOG_READY:
            await db.credit_ops.create_index("op_id", unique=True)
            _OPS_LOG_READY = True
        await db.credit_ops.insert_one({
            "op_id": op_id, "user_id": user_id, "code": code,
            "amount": round(float(amount), 8), "kind": kind,
            "at": datetime.now(timezone.utc).isoformat()})
    except Exception:
        pass


_OPS_LOG_READY = False


def _registry_push(op_id: str) -> dict:
    return {"applied_credit_ops": {"$each": [op_id], "$slice": -2000}}


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
    if await db.credit_ops.find_one({"op_id": op_id}, {"_id": 1}):
        return False
    field = "vip_balance_usd" if (legacy_usd and code == "USD") \
        else f"vip_balances.{code}"
    res = await db.users.update_one(
        {"user_id": user_id, "applied_credit_ops": {"$ne": op_id}},
        {"$inc": {field: amount}, "$push": _registry_push(op_id)},
    )
    if res.modified_count:
        await _ops_log(op_id, user_id, code, amount, "credit")
    return res.modified_count > 0


async def debit_balance_idempotent(user_id: str, code: str, amount: float,
                                   op_id: str) -> str:
    """iter254(R03) — débito atómico, condicional e IDEMPOTENTE por op_id.

    Devuelve 'applied' | 'duplicate' | 'insufficient'. El guard de saldo, el
    $inc y el registro del op_id ocurren en UNA operación sobre el doc del
    usuario, así el protocolo reserva/operación/activación puede saber con
    certeza (por el op_id) si un intento interrumpido llegó a cobrar o no.
    Para USD drena primero el campo legacy (vip_balance_usd)."""
    amount = float(amount)
    if amount <= 0:
        return "applied"
    if await db.credit_ops.find_one({"op_id": op_id}, {"_id": 1}):
        return "duplicate"
    guard = amount - 1e-6
    if code == "USD":
        res = await db.users.update_one(
            {"user_id": user_id, "applied_credit_ops": {"$ne": op_id},
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
                    "applied_credit_ops": {"$slice": [
                        {"$concatArrays": [
                            {"$ifNull": ["$applied_credit_ops", []]}, [op_id]]},
                        -2000]},
                }},
                {"$unset": "_legacy_take"},
            ],
        )
    else:
        res = await db.users.update_one(
            {"user_id": user_id, "applied_credit_ops": {"$ne": op_id},
             f"vip_balances.{code}": {"$gte": guard}},
            {"$inc": {f"vip_balances.{code}": -amount},
             "$push": _registry_push(op_id)},
        )
    if res.matched_count:
        await _ops_log(op_id, user_id, code, amount, "debit")
        return "applied"
    if await db.users.find_one({"user_id": user_id, "applied_credit_ops": op_id},
                               {"_id": 1}):
        return "duplicate"
    return "insufficient"


async def op_was_applied(user_id: str, op_id: str) -> bool:
    """¿Este op_id llegó a aplicarse? (registro embebido O log duradero)."""
    if await db.users.find_one({"user_id": user_id, "applied_credit_ops": op_id},
                               {"_id": 1}):
        return True
    return bool(await db.credit_ops.find_one({"op_id": op_id}, {"_id": 1}))


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
    from services.credit_recovery import pending_marker, apply_and_clear
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
    prev_docs = await db.capital_requests.find(
        {"user_id": user_id, "currency_code": currency,
         "repayment_events.order_id": order_id},
        {"_id": 0, "repayment_events": 1},
    ).to_list(50)
    for d_ in prev_docs:
        prior += sum(float(ev.get("amount") or 0)
                     for ev in (d_.get("repayment_events") or [])
                     if ev.get("order_id") == order_id)
    prior = round(prior, 6)
    active = await db.capital_requests.find(
        {"user_id": user_id, "status": "disbursed", "currency_code": currency},
        {"_id": 0},
    ).sort("disbursed_at", 1).to_list(50)
    if not active:
        return round(amount - prior, 6)

    # Total per-order discount budget is set by the OLDEST active debt.
    oldest_pct = float(active[0].get("discount_pct") or 0.0)
    budget_total = round(amount * oldest_pct / 100.0, 4)
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
            if not fresh or fresh.get("status") != "disbursed":
                break
            if any(ev.get("order_id") == order_id
                   for ev in (fresh.get("repayment_events") or [])):
                break  # esta orden ya contribuyó a esta deuda
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
