"""Client deposits — deposit assets into the on-platform per-currency balance.

Business rules (owner, 30 Jul 2026):
  - Deposits credit the SAME currency deposited (no conversion) once staff
    confirms the money was received. Conversion happens via the converter or
    VIP batch pairs.
  - Allowed methods derive from the currency's delivery methods (same source
    of truth as withdrawals): transfer → proof + account holder required;
    crypto → tx hash required; cash → two sub-modes:
      * courier: only for amounts > COURIER_MIN_USDT (USDT equivalent) —
        requires pickup address + phone + contact name of the person handing
        over the money.
      * office: any amount — the client brings the cash to the company
        offices (address configurable via settings.global.office_address).

Collection `deposits`:
  { id, user_id, user_email, user_name, user_role,
    currency, amount, method, cash_mode?, usdt_equivalent?,
    account_holder?, tx_hash?, proof_url?,
    pickup_address?, pickup_phone?, contact_name?, note?,
    status: pending|confirmed|rejected,
    admin_note?, reviewed_at?, reviewed_by?, created_at, updated_at }
"""
from __future__ import annotations

import re
import uuid
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from db_client import db
from auth_utils import (require_user, require_permission, iso, now_utc,
                        _enforce_employee_currency_scope)
from audit_log import log_action
from services.balances import (
    build_rate_lookup, convert_to_usdt, MIN_CRYPTO_USDT,
    usdt_equivalent_decimal,
    assert_account_active, assert_not_defensive,
)
from services.delivery_rules import allowed_delivery_methods
from services.proof_upload import maybe_upload_proof

logger = logging.getLogger("deposits")

router = APIRouter(tags=["Deposits"])

COURIER_MIN_USDT = 1000.0
ALLOWED_METHODS = {"transfer", "crypto", "cash"}

_claims_index_ready = False


async def _ensure_evidence_claims_index() -> None:
    """DR02 — índice único de la reserva durable + incorporación de los
    depósitos históricos confirmados ANTES de existir la reserva: una
    identidad ya consumida queda registrada y no puede volver a acreditarse."""
    global _claims_index_ready
    if _claims_index_ready:
        return
    from pymongo.errors import DuplicateKeyError
    await db.crypto_evidence_claims.create_index("claim_key", unique=True)
    # DR02 v2 — MIGRACIÓN de reservas con el formato anterior (la clave
    # terminaba en el importe): se reescriben a la clave canónica actual
    # preservando la exclusión del movimiento consumido. Una colisión (dos
    # históricos con la misma identidad, doble abono antiguo) conserva la
    # clave canónica en la primera fila y marca la otra como duplicado
    # legado SIN liberar la identidad.
    async for row in db.crypto_evidence_claims.find(
            {}, {"_id": 1, "claim_key": 1, "deposit_id": 1, "network": 1,
                 "tx_hash": 1, "currency": 1, "movement_id": 1}):
        if not row.get("tx_hash") or not row.get("currency"):
            continue
        canonical = _evidence_claim_key(row.get("network") or "",
                                        row["tx_hash"], row["currency"],
                                        row.get("movement_id") or "")
        if row.get("claim_key") == canonical:
            continue
        try:
            await db.crypto_evidence_claims.update_one(
                {"_id": row["_id"], "claim_key": row["claim_key"]},
                {"$set": {"claim_key": canonical,
                          "legacy_key": row["claim_key"],
                          "migrated_at": iso(now_utc())}})
        except DuplicateKeyError:
            await db.crypto_evidence_claims.update_one(
                {"_id": row["_id"], "claim_key": row["claim_key"]},
                {"$set": {"claim_key": (f"{canonical}|legacy-dup:"
                                        f"{row['deposit_id']}"),
                          "legacy_key": row["claim_key"],
                          "migrated_at": iso(now_utc())}})
    async for d in db.deposits.find(
            {"method": "crypto", "status": "confirmed",
             "tx_hash": {"$nin": [None, ""]}},
            {"_id": 0, "id": 1, "user_id": 1, "network": 1, "tx_hash": 1,
             "currency": 1, "amount": 1, "evidence_movement_id": 1}):
        if await db.crypto_evidence_claims.find_one(
                {"deposit_id": d["id"]}, {"_id": 1}):
            continue
        key = _evidence_claim_key(d.get("network") or "", d["tx_hash"],
                                  d["currency"],
                                  d.get("evidence_movement_id") or "")
        try:
            await db.crypto_evidence_claims.insert_one({
                "claim_key": key, "deposit_id": d["id"],
                "user_id": d.get("user_id"), "network": d.get("network"),
                "tx_hash": d["tx_hash"], "currency": d["currency"],
                "amount": d.get("amount"),
                "movement_id": d.get("evidence_movement_id") or "",
                "backfilled": True, "at": iso(now_utc())})
        except DuplicateKeyError:
            # dos históricos con la misma identidad (doble abono antiguo): la
            # reserva queda con el primero; el resto se detecta como gemelo
            # sin reserva y bloquea nuevas acreditaciones de ese hash.
            pass
    _claims_index_ready = True


def _amount_precision(currency: dict) -> int:
    """DR01 — precisión por tipo de activo: cripto 8 decimales, fiat 2."""
    return 8 if (currency.get("type") or "").lower() == "crypto" else 2


def _evidence_base_key(network: str, tx_hash: str, currency: str) -> str:
    return (f"{(network or '').strip().upper()}|{tx_hash.strip().lower()}|"
            f"{currency.strip().upper()}")


def _evidence_claim_key(network: str, tx_hash: str, currency: str,
                        movement_id: str = "") -> str:
    """DR02 — identidad de la evidencia: red + hash + activo. El importe
    DECLARADO ya no forma parte de la identidad (cambiarlo no demuestra otra
    transferencia recibida). Dos transferencias reales distintas dentro de la
    misma transacción se distinguen SOLO con un identificador de movimiento
    explícito aportado por el personal al confirmar."""
    base = _evidence_base_key(network, tx_hash, currency)
    return f"{base}|{(movement_id or '').strip()}"


async def _claim_crypto_evidence(doc: dict, movement_id: str = "") -> None:
    """DR02 — reserva DURABLE de la evidencia antes de acreditar: el mismo
    pago on-chain (red+hash+activo) produce UNA acreditación aunque cambie el
    importe declarado, el documento o el usuario; la segunda recibe 409 con
    la referencia del depósito que ya consumió la evidencia. Un histórico
    confirmado sin reserva bloquea el hash hasta resolver su identidad."""
    from pymongo.errors import DuplicateKeyError
    await _ensure_evidence_claims_index()
    # Gemelo histórico confirmado SIN reserva (registro anterior al cambio o
    # restaurado): identidad consumida pero no registrada — se bloquea.
    twins = await db.deposits.find(
        {"method": "crypto", "tx_hash": doc["tx_hash"],
         "currency": doc["currency"], "status": "confirmed",
         "id": {"$ne": doc["id"]}}, {"_id": 0, "id": 1}).to_list(50)
    if twins:
        claimed = set(await db.crypto_evidence_claims.distinct(
            "deposit_id", {"tx_hash": doc["tx_hash"],
                           "currency": doc["currency"]}))
        orphan = [t["id"] for t in twins if t["id"] not in claimed]
        if orphan:
            raise HTTPException(
                status_code=409,
                detail=(f"Esta evidencia ya fue consumida por el depósito "
                        f"confirmado {orphan[0][:16]} (sin reserva "
                        "registrada) — resuélvelo antes de volver a "
                        "acreditar este hash."))
    own = await db.crypto_evidence_claims.find_one(
        {"deposit_id": doc["id"], "superseded": {"$ne": True}},
        {"_id": 1, "claim_key": 1, "movement_id": 1})
    req_mid = (movement_id or "").strip()
    if own:
        if (own.get("movement_id") or "").strip() == req_mid:
            return  # reserva propia con la MISMA identidad (reanudación)
        # DR02 v4 — reanudación con OTRO ID de movimiento. La identidad vieja
        # NUNCA se libera: se INSERTA la reserva nueva y la anterior queda
        # sellada como LÁPIDA (`superseded`) conservando su clave. Así su
        # entrada sigue ocupando el índice único y una confirmación viva que
        # aún apunte a la identidad vieja jamás deja ese movimiento disponible
        # para que un SEGUNDO depósito lo reclame y acredite (doble abono con
        # un único pago on-chain). El depósito y su reserva vigente terminan
        # con la MISMA identidad nueva; un movimiento REALMENTE distinto (jamás
        # reservado) se sigue aceptando.
        fresh_dep = await db.deposits.find_one(
            {"id": doc["id"]}, {"_id": 0, "status": 1})
        if (fresh_dep or {}).get("status") != "pending":
            raise HTTPException(
                status_code=409,
                detail="Este depósito ya fue procesado — la identidad de su "
                       "reserva no puede cambiar.")
        new_key = _evidence_claim_key(doc.get("network") or "",
                                      doc["tx_hash"], doc["currency"],
                                      req_mid)
        moved_at = iso(now_utc())
        try:
            await db.crypto_evidence_claims.insert_one({
                "claim_key": new_key, "deposit_id": doc["id"],
                "user_id": doc["user_id"], "network": doc.get("network"),
                "tx_hash": doc["tx_hash"], "currency": doc["currency"],
                "amount": doc["amount"], "movement_id": req_mid,
                "moved_from_key": own["claim_key"], "moved_at": moved_at,
                "at": moved_at})
        except DuplicateKeyError:
            prior = await db.crypto_evidence_claims.find_one(
                {"claim_key": new_key}, {"_id": 0, "deposit_id": 1})
            # Reintento idempotente del propio move: si la reserva nueva ya es
            # de ESTE depósito, solo falta asegurar la lápida de la vieja.
            if (prior or {}).get("deposit_id") != doc["id"]:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "EVIDENCE_ALREADY_USED",
                            "message": (
                                "Ese ID de movimiento ya respalda el depósito "
                                f"{str((prior or {}).get('deposit_id') or '¿?')[:16]}"
                                " — el mismo movimiento no puede acreditarse "
                                "dos veces."),
                            "deposit_id": (prior or {}).get("deposit_id")})
        # Sella la identidad anterior como lápida (conserva su clave para
        # bloquear cualquier reclamo de otro depósito). Idempotente.
        await db.crypto_evidence_claims.update_one(
            {"_id": own["_id"], "claim_key": own["claim_key"],
             "deposit_id": doc["id"]},
            {"$set": {"superseded": True, "superseded_at": moved_at,
                      "superseded_by": new_key}})
        return
    key = _evidence_claim_key(doc.get("network") or "", doc["tx_hash"],
                              doc["currency"], req_mid)
    try:
        await db.crypto_evidence_claims.insert_one({
            "claim_key": key, "deposit_id": doc["id"],
            "user_id": doc["user_id"], "network": doc.get("network"),
            "tx_hash": doc["tx_hash"], "currency": doc["currency"],
            "amount": doc["amount"],
            "movement_id": req_mid,
            "at": iso(now_utc())})
    except DuplicateKeyError:
        prior = await db.crypto_evidence_claims.find_one(
            {"claim_key": key}, {"_id": 0, "deposit_id": 1})
        raise HTTPException(
            status_code=409,
            detail={"code": "EVIDENCE_ALREADY_USED",
                    "message": (
                        f"Esta evidencia (hash) ya respalda el depósito "
                        f"{str((prior or {}).get('deposit_id') or '¿?')[:16]} "
                        "— el mismo pago on-chain no puede acreditarse dos "
                        "veces. Si la transacción contiene OTRA transferencia "
                        "real, identifícala con un ID de movimiento distinto "
                        "al confirmar."),
                    "deposit_id": (prior or {}).get("deposit_id")})


def _deposit_currency_scope(staff: dict) -> list:
    """DR06 — monedas autorizadas del empleado (lista vacía = sin límite)."""
    if staff.get("role") != "employee":
        return []
    return [str(c).upper() for c in (staff.get("allowed_currencies") or [])]


class DepositCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    currency: str = Field(..., min_length=1, max_length=16)
    amount: float = Field(..., gt=0, le=10_000_000)
    method: str = Field(..., min_length=2, max_length=16)
    account_holder: Optional[str] = Field(default=None, max_length=120)
    tx_hash: Optional[str] = Field(default=None, max_length=200)
    network: Optional[str] = Field(default=None, max_length=16)
    proof_image: Optional[str] = None
    pickup_address: Optional[str] = Field(default=None, max_length=300)
    pickup_phone: Optional[str] = Field(default=None, max_length=40)
    contact_name: Optional[str] = Field(default=None, max_length=120)
    note: Optional[str] = Field(default=None, max_length=300)


class RejectPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    admin_note: str = Field(default="", max_length=300)


class ConfirmDepositPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    # DR02 — identificador explícito de OTRA transferencia real dentro de la
    # misma transacción (p. ej. índice del movimiento en el explorador).
    evidence_movement_id: Optional[str] = Field(default=None, max_length=64)


def _require_client(user: dict) -> None:
    if user.get("role") == "employee":
        raise HTTPException(status_code=403, detail="Empleados no pueden depositar saldo de cliente.")


async def _get_office_address() -> str:
    doc = await db.settings.find_one({"id": "global"}, {"_id": 0, "office_address": 1})
    return (doc or {}).get("office_address") or ""


async def _notify_staff_new_deposit(doc: dict) -> None:
    try:
        from routes.notifications import _insert_notification
    except Exception as e:  # noqa: BLE001
        logger.error(f"[deposits] notif import failed: {e}")
        return
    cursor = db.users.find(
        {"$or": [
            {"role": "admin"},
            {"role": "employee", "allowed_permissions": "withdrawals"},
            {"role": "employee", "allowed_permissions": {"$in": [[], None]}},
        ]},
        {"_id": 0, "user_id": 1},
    )
    async for r in cursor:
        try:
            await _insert_notification(
                recipient_user_id=r["user_id"],
                type="new_deposit",
                title="Nuevo depósito de cliente",
                message=f"{doc.get('user_name') or doc.get('user_email')} depositó {doc['amount']} {doc['currency']} ({doc['method']}).",
                data={"id": doc["id"], "user_id": doc["user_id"]},
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"[deposits] staff notify failed: {e}")


async def _notify_client_decision(doc: dict, approved: bool, admin_note: str = "") -> None:
    """iter156 — in-app + Web Push to the deposit owner, localised to their
    preferred language. Rejections include the staff note as the reason."""
    try:
        from routes.notifications import _insert_notification
        from push_service import send_push_to_user, build_deposit_decision_payload
        from services.notification_i18n import t as _t, resolve_lang
    except Exception as e:  # noqa: BLE001
        logger.error(f"[deposits] notif import failed: {e}")
        return
    key = "deposit_confirmed" if approved else "deposit_rejected"
    try:
        lang = await resolve_lang(db, doc["user_id"])
        note = (admin_note or "").strip()
        if note:
            reason = f" Reason: {note}." if lang == "en" else f" Motivo: {note}."
        else:
            reason = ""
        await _insert_notification(
            recipient_user_id=doc["user_id"],
            type=key,
            title=_t(key, lang, "title"),
            message=_t(key, lang, "message",
                       amt=doc["amount"], code=doc["currency"], reason=reason),
            data={"id": doc["id"], "amount": doc["amount"],
                  "currency": doc["currency"]},
        )
        await send_push_to_user(
            db, doc["user_id"],
            build_deposit_decision_payload(doc, approved, lang=lang),
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"[deposits] client notify failed: {e}")


@router.get("/deposits/config")
async def deposits_config(request: Request) -> Any:
    """Depositable currencies + their allowed methods + cash rules."""
    user = await require_user(request)
    _require_client(user)
    currencies = await db.currencies.find({}, {"_id": 0}).to_list(500)
    rates = await build_rate_lookup()
    items = []
    seen: set = set()
    for c in currencies:
        if c.get("is_active") is False:
            continue
        code = (c.get("code") or "").strip().upper()
        if not code or code in seen:
            continue
        methods = allowed_delivery_methods(c)
        if not methods:
            continue
        seen.add(code)
        per_unit = convert_to_usdt(1.0, code, rates)
        items.append({
            "code": code,
            "name": (c.get("name") or code).strip(),
            "type": c.get("type") or "",
            "methods": methods,
            "usdt_per_unit": round(float(per_unit), 6) if per_unit else None,
        })
    items.sort(key=lambda x: (x["code"] != "USDT", x["code"]))
    return {
        "currencies": items,
        "courier_min_usdt": COURIER_MIN_USDT,
        "office_address": await _get_office_address(),
    }


@router.post("/deposits")
async def create_deposit(payload: DepositCreate, request: Request) -> Any:
    user = await require_user(request)
    _require_client(user)
    await assert_account_active(user)
    if user["role"] != "admin":
        await assert_not_defensive("depósitos")

    code = payload.currency.strip().upper()
    currency = await db.currencies.find_one(
        {"code": code, "is_active": {"$ne": False}}, {"_id": 0},
    )
    if not currency:
        raise HTTPException(status_code=422, detail=f"Moneda {code} no disponible para depósitos.")
    method = payload.method.strip().lower()
    allowed = allowed_delivery_methods(currency)
    if method not in ALLOWED_METHODS or method not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Para depositar {code} usa: {', '.join(allowed)}.",
        )

    holder = (payload.account_holder or "").strip()
    tx_hash = (payload.tx_hash or "").strip()
    network = (payload.network or "").strip().upper() or None
    proof_raw = (payload.proof_image or "").strip()
    cash_mode = None

    rates = await build_rate_lookup()
    # DE01 v2 — la VALIDACIÓN del mínimo usa aritmética decimal SIN redondeo
    # de presentación (0.99995 ya no "se vuelve" 1); el redondeo a 4
    # decimales es solo para almacenar/mostrar la equivalencia.
    from decimal import Decimal
    eq_dec = usdt_equivalent_decimal(float(payload.amount), code, rates)
    usdt_eq = round(float(eq_dec), 4) if eq_dec is not None else None
    # DE01 — regla de plataforma: depósito mínimo en cripto = 1 USDT (o su
    # equivalente al cambio vigente).
    if (currency.get("type") or "").lower() == "crypto" \
            and eq_dec is not None and eq_dec < Decimal(str(MIN_CRYPTO_USDT)):
        raise HTTPException(
            status_code=422,
            detail=(f"El depósito mínimo en cripto es {MIN_CRYPTO_USDT:g} "
                    "USDT (o su equivalente)."))

    if method == "transfer":
        if not proof_raw:
            raise HTTPException(status_code=422, detail="Adjunta la captura de la transferencia realizada.")
        if len(holder) < 3:
            raise HTTPException(status_code=422, detail="Indica el titular de la cuenta que envió la transferencia.")
    elif method == "crypto":
        if len(tx_hash) < 10:
            raise HTTPException(status_code=422, detail="Indica el hash de la transacción on-chain.")
        from services.crypto_networks import (
            SUPPORTED_NETWORKS, is_supported_network,
            is_tx_hash_valid_for_network, tx_hash_mismatch_reason,
        )
        if network and not is_supported_network(network):
            raise HTTPException(
                status_code=422,
                detail=f"Red no soportada. Usa: {', '.join(SUPPORTED_NETWORKS)}.",
            )
        if network and not is_tx_hash_valid_for_network(tx_hash, network):
            raise HTTPException(status_code=422,
                                detail=tx_hash_mismatch_reason(tx_hash, network))
    else:  # cash
        if usdt_eq is not None and usdt_eq > COURIER_MIN_USDT:
            cash_mode = "courier"
            if len((payload.pickup_address or "").strip()) < 5:
                raise HTTPException(status_code=422, detail="Indica la dirección de recogida del efectivo.")
            if len((payload.pickup_phone or "").strip()) < 6:
                raise HTTPException(status_code=422, detail="Indica el celular de la persona que entrega el dinero.")
            if len((payload.contact_name or "").strip()) < 3:
                raise HTTPException(status_code=422, detail="Indica el nombre de la persona que entrega el dinero.")
        else:
            cash_mode = "office"

    proof_ref = maybe_upload_proof(proof_raw, "deposits") if proof_raw else None
    # DR01 — normalización explícita por precisión del activo: nunca se
    # acepta en silencio un importe que la precisión soportada altere ni se
    # crea una solicitud que normalice a cero.
    precision = _amount_precision(currency)
    normalized = round(float(payload.amount), precision)
    if normalized <= 0:
        raise HTTPException(
            status_code=422,
            detail=f"El importe es menor que la precisión mínima de {code} "
                   f"({precision} decimales).")
    if abs(float(payload.amount) - normalized) > 10 ** -(precision + 3):
        raise HTTPException(
            status_code=422,
            detail=f"{code} admite máximo {precision} decimales; ajusta el importe.")
    # DR02 — advertencia visible para el personal si la misma evidencia ya
    # aparece declarada en otro depósito (cualquier estado).
    evidence_dup = None
    if method == "crypto" and tx_hash:
        prior = await db.deposits.find_one(
            {"method": "crypto", "tx_hash": tx_hash},
            {"_id": 0, "id": 1, "status": 1, "user_name": 1})
        if prior:
            evidence_dup = {"deposit_id": prior["id"],
                            "status": prior["status"],
                            "user_name": prior.get("user_name") or ""}
    now = iso(now_utc())
    doc = {
        "id": f"dep_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "user_email": user.get("email", ""),
        "user_name": user.get("name", ""),
        "user_role": user.get("role", ""),
        "currency": code,
        "amount": normalized,
        "method": method,
        "cash_mode": cash_mode,
        "network": network if method == "crypto" else None,
        "usdt_equivalent": usdt_eq,
        "account_holder": holder or None,
        "tx_hash": tx_hash or None,
        "proof_url": proof_ref,
        "evidence_reused_from": evidence_dup,
        "pickup_address": (payload.pickup_address or "").strip() or None,
        "pickup_phone": (payload.pickup_phone or "").strip() or None,
        "contact_name": (payload.contact_name or "").strip() or None,
        "note": (payload.note or "").strip() or None,
        "status": "pending",
        "admin_note": None,
        "reviewed_at": None,
        "reviewed_by": None,
        "created_at": now,
        "updated_at": now,
    }
    await db.deposits.insert_one(dict(doc))
    doc.pop("_id", None)
    # iter208 — For cash + courier-pickup deposits, spawn a delivery job
    # so the courier can accept the pickup and staff can only CONFIRM the
    # deposit once the courier marks the pickup as delivered.
    if method == "cash" and cash_mode == "courier":
        try:
            from services.deliveries import ensure_delivery_job
            await ensure_delivery_job("deposit", doc, km=0.0, fee_usdt=0.0,
                                       actor_id=user["user_id"])
        except Exception as e:
            logger.error(f"[deposits] delivery job creation failed: {e}")
    await log_action(
        db=db, actor=user, action="deposit.create",
        entity_type="deposit", entity_id=doc["id"],
        details={"amount": doc["amount"], "currency": code, "method": method,
                 "cash_mode": cash_mode},
    )
    await _notify_staff_new_deposit(doc)
    # iter196 — email the client confirming the deposit request landed in
    # the review queue ("en proceso"). Wrapped so Resend outages never
    # break the create flow.
    try:
        from email_service import notify_deposit_received
        client_row = await db.users.find_one(
            {"user_id": user["user_id"]},
            {"_id": 0, "email": 1, "name": 1, "preferred_language": 1},
        )
        if client_row and client_row.get("email"):
            notify_deposit_received(doc, client_row)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[deposits] client received-email failed: {e}")
    try:
        from services.live_bus import publish as live_publish
        await live_publish("deposit_created", {"id": doc["id"], "user_name": doc["user_name"],
                                                "amount": doc["amount"], "currency": code},
                           roles=("admin", "employee"))
    except Exception as e:  # noqa: BLE001
        logger.error(f"[deposits] SSE publish failed: {e}")
    return doc


@router.get("/deposits/mine")
async def my_deposits(request: Request, limit: int = 50) -> Any:
    user = await require_user(request)
    _require_client(user)
    rows = await db.deposits.find(
        {"user_id": user["user_id"]}, {"_id": 0},
    ).sort("created_at", -1).to_list(min(max(1, limit), 200))
    return {"items": rows}


@router.get("/admin/deposits")
async def admin_list_deposits(request: Request, status: Optional[str] = None,
                               method: Optional[str] = None,
                               user_q: Optional[str] = None,
                               limit: int = 200) -> Any:
    # iter163 — deposits moved from the `orders` gate to `withdrawals` so the
    # designated money-in/money-out staff handles both flows.
    staff = await require_permission(request, "withdrawals")
    q: dict[str, Any] = {}
    if status in ("pending", "confirmed", "rejected"):
        q["status"] = status
    # iter164 — method filter (cash / transfer / crypto) to speed up review.
    if method in ALLOWED_METHODS:
        q["method"] = method
    # iter165 — client search by name or email (same UX as withdrawals).
    if user_q:
        rx = {"$regex": re.escape(user_q.strip()), "$options": "i"}
        q["$or"] = [{"user_name": rx}, {"user_email": rx}]
    # DR06 — alcance de monedas del empleado (mismo criterio que retiros).
    scope = _deposit_currency_scope(staff)
    if scope:
        q["currency"] = {"$in": scope}
    rows = await db.deposits.find(q, {"_id": 0}).sort("created_at", -1).to_list(min(max(1, limit), 500))
    # iter208 — attach courier pickup status so the frontend can disable
    # "Confirmar" until the courier confirms the pickup for cash-courier deposits.
    cash_ids = [d["id"] for d in rows
                if d.get("method") == "cash"
                and d.get("cash_mode") == "courier"
                and d.get("status") == "pending"]
    if cash_ids:
        jobs = await db.deliveries.find(
            {"kind": "deposit", "ref_id": {"$in": cash_ids},
             "status": {"$ne": "cancelled"}},
            {"_id": 0, "ref_id": 1, "status": 1, "courier_id": 1,
             "courier_name": 1},
        ).to_list(len(cash_ids))
        by_ref = {j["ref_id"]: j for j in jobs}
        for d in rows:
            if d["id"] in by_ref:
                j = by_ref[d["id"]]
                d["courier_delivery_status"] = j.get("status")
                d["courier_delivery_courier_name"] = j.get("courier_name") or ""
                d["courier_delivery_assigned"] = bool(j.get("courier_id"))
    # DR02 — señalar al personal las evidencias cripto ya reclamadas por
    # OTRO depósito (reserva durable en crypto_evidence_claims).
    hashes = [d["tx_hash"] for d in rows
              if d.get("method") == "crypto" and d.get("tx_hash")
              and d.get("status") == "pending"]
    if hashes:
        claims = await db.crypto_evidence_claims.find(
            {"tx_hash": {"$in": hashes}},
            {"_id": 0, "tx_hash": 1, "deposit_id": 1}).to_list(len(hashes) * 4)
        by_hash: dict[str, str] = {}
        for c in claims:
            by_hash.setdefault(c["tx_hash"], c["deposit_id"])
        for d in rows:
            used_by = by_hash.get(d.get("tx_hash") or "")
            if used_by and used_by != d["id"]:
                d["evidence_already_used_by"] = used_by
    pending_q: dict[str, Any] = {"status": "pending"}
    if scope:
        pending_q["currency"] = {"$in": scope}
    pending = await db.deposits.count_documents(pending_q)
    return {"items": rows, "pending": pending}


@router.get("/admin/deposits-hub/pending-count")
async def admin_deposits_hub_pending_count(request: Request) -> Any:
    """iter163 — badges for the Deposits & Withdrawals hub tabs.
    iter166 — capital deposits retired; capital REQUESTS joined the hub."""
    staff = await require_permission(request, "withdrawals")
    # DR06 — los contadores también respetan el alcance de monedas.
    scope = _deposit_currency_scope(staff)
    dep_q: dict[str, Any] = {"status": "pending"}
    wd_q: dict[str, Any] = {"status": "pending"}
    if scope:
        dep_q["currency"] = {"$in": scope}
        wd_q["currency"] = {"$in": scope}
    deposits_pending = await db.deposits.count_documents(dep_q)
    requests_pending = await db.capital_requests.count_documents({"status": "pending"})
    withdrawals_pending = await db.withdrawals.count_documents(wd_q)
    return {
        "deposits_pending": deposits_pending,
        "requests_pending": requests_pending,
        "withdrawals_pending": withdrawals_pending,
    }


@router.post("/admin/deposits/{dep_id}/confirm")
async def admin_confirm_deposit(dep_id: str, request: Request,
                                payload: Optional[ConfirmDepositPayload] = None) -> Any:
    staff = await require_permission(request, "withdrawals")
    doc = await db.deposits.find_one({"id": dep_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Depósito no encontrado.")
    # DR06 — alcance de monedas del empleado también al confirmar.
    _enforce_employee_currency_scope(staff, (doc.get("currency") or "").upper())
    if doc["status"] != "pending":
        raise HTTPException(status_code=409, detail="Este depósito ya fue procesado.")
    # iter208 — For cash+courier deposits: only allow confirmation once the
    # courier has picked up the money. The delivery job must exist and be
    # in a "delivered" / "confirmed" state.
    if doc.get("method") == "cash" and doc.get("cash_mode") == "courier":
        job = await db.deliveries.find_one(
            {"kind": "deposit", "ref_id": dep_id,
             "status": {"$ne": "cancelled"}}, {"_id": 0})
        if not job:
            raise HTTPException(
                status_code=409,
                detail=("No hay trabajo de mensajería para esta recogida. "
                        "Créalo en la sección Mensajería antes de confirmar."))
        if job.get("status") not in ("delivered", "confirmed"):
            if not job.get("courier_id"):
                raise HTTPException(
                    status_code=409,
                    detail=("Ningún mensajero ha tomado la recogida todavía. "
                            "Asigna un mensajero o espera a que uno la acepte."))
            raise HTTPException(
                status_code=409,
                detail=(f"El mensajero {job.get('courier_name') or ''} aún no "
                        "confirmó haber recogido el dinero. Espera su "
                        "confirmación antes de aprobar el depósito."))
    movement_id = (payload.evidence_movement_id or "").strip() if payload else ""
    return await _do_confirm_deposit(doc, staff, movement_id)


async def confirm_deposit_from_delivery(dep_id: str, staff: dict) -> Any:
    """iter209b — Al confirmar la recogida en Mensajería, el depósito cash
    vinculado se confirma automáticamente (acredita el saldo al cliente)."""
    doc = await db.deposits.find_one({"id": dep_id}, {"_id": 0})
    if not doc:
        return None
    # MSG03 — un depósito rechazado con recogida ejecutada es un conflicto
    # de origen: no se cierra la sincronización como resuelta.
    if doc["status"] == "rejected":
        from services.delivery_settlement import OriginConflict
        raise OriginConflict(
            f"depósito {dep_id[:8]} rechazado — la recogida quedó ejecutada")
    if doc["status"] != "pending":
        return None
    return await _do_confirm_deposit(doc, staff)


async def _do_confirm_deposit(doc: dict, staff: dict,
                              evidence_movement_id: str = "") -> Any:
    """Núcleo de la confirmación (acredita saldo + notifica). Compartido por
    el endpoint y la sincronización automática desde mensajería (iter209b)."""
    dep_id = doc["id"]
    now = iso(now_utc())
    # DR01 — defensa en profundidad: jamás confirmar un importe no positivo.
    if float(doc.get("amount") or 0) <= 0:
        raise HTTPException(
            status_code=409,
            detail="Este depósito tiene un importe inválido (0) — recházalo.")
    # DE01 v2 — el mínimo cripto se protege TAMBIÉN al confirmar: exige una
    # equivalencia RESOLUBLE (sin tasa → bloqueo hasta configurarla) y
    # ≥ 1 USDT con aritmética decimal; guarda la valoración que respalda la
    # decisión. Sin esto, una solicitud creada sin tasa se acreditaba bajo
    # el mínimo.
    min_valuation = None
    if doc.get("method") == "crypto":
        from decimal import Decimal
        rates = await build_rate_lookup()
        eq_dec = usdt_equivalent_decimal(float(doc.get("amount") or 0),
                                         doc["currency"], rates)
        if eq_dec is None:
            raise HTTPException(
                status_code=409,
                detail=(f"No hay tasa para valorar {doc['currency']} en USDT "
                        "— configúrala antes de confirmar (mínimo "
                        f"{MIN_CRYPTO_USDT:g} USDT)."))
        if eq_dec < Decimal(str(MIN_CRYPTO_USDT)):
            raise HTTPException(
                status_code=409,
                detail=(f"Este depósito equivale a {eq_dec} USDT, por debajo "
                        f"del mínimo de {MIN_CRYPTO_USDT:g} USDT — recházalo."))
        min_valuation = {"usdt_equivalent": str(eq_dec), "at": now,
                         "rule": f"min_{MIN_CRYPTO_USDT:g}_usdt"}
    # DR02 — reserva DURABLE de la evidencia cripto ANTES de acreditar.
    req_mid = (evidence_movement_id or "").strip()
    crypto_evidence = bool(doc.get("method") == "crypto" and doc.get("tx_hash"))
    if crypto_evidence:
        await _claim_crypto_evidence(doc, evidence_movement_id)
        # DR02 v3 — la identidad RESERVADA y la finalmente CONFIRMADA quedan
        # vinculadas de forma indivisible: la reserva graba en el propio
        # depósito el movimiento que ESTE intento tomó. Una confirmación
        # concurrente que mueva la reserva a otro movimiento reescribe esta
        # marca; la confirmación final solo gana si su movimiento sigue siendo
        # el vigente (filtro `evidence_claim_movement`). Así una petición
        # anterior no puede confirmar con un movimiento que otra ya reasignó,
        # ni queda libre un movimiento que aquella aún podría consumir.
        await db.deposits.update_one(
            {"id": dep_id, "status": "pending"},
            {"$set": {"evidence_claim_movement": req_mid}})
    # Idempotency: flip status first so a double-click can't double-credit.
    # iter249 — la intención de abono viaja en el MISMO update atómico; si el
    # proceso muere antes de acreditar, el healer (credit_recovery) completa.
    from services.credit_recovery import pending_marker, apply_and_clear
    marker = pending_marker(doc["user_id"], doc["currency"],
                            float(doc["amount"]), "deposit-confirm")
    confirm_sets = {"status": "confirmed", "updated_at": now,
                    "reviewed_at": now, "reviewed_by": staff["user_id"],
                    "credit_pending": marker}
    if min_valuation:
        confirm_sets["min_crypto_valuation"] = min_valuation
    if req_mid:
        confirm_sets["evidence_movement_id"] = req_mid
    confirm_filter: dict = {"id": dep_id, "status": "pending"}
    if crypto_evidence:
        # DR02 v3 — la confirmación final exige que la identidad reservada por
        # ESTE intento siga vigente.
        confirm_filter["evidence_claim_movement"] = req_mid
    res = await db.deposits.update_one(
        confirm_filter,
        {"$set": confirm_sets},
    )
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail="Este depósito ya fue procesado.")
    await apply_and_clear("deposits", dep_id, marker)
    fresh = await db.deposits.find_one({"id": dep_id}, {"_id": 0})
    await log_action(
        db=db, actor=staff, action="deposit.confirm",
        entity_type="deposit", entity_id=dep_id,
        details={"user_id": doc["user_id"], "amount": doc["amount"],
                 "currency": doc["currency"]},
    )
    await _notify_client_decision(fresh, approved=True)
    # iter196 — success email "Depósito exitoso" mirroring the in-app +
    # push confirmation. Wrapped so email outages never fail the confirm
    # flow (funds are already credited at this point).
    try:
        from email_service import notify_deposit_confirmed
        client_row = await db.users.find_one(
            {"user_id": doc["user_id"]},
            {"_id": 0, "email": 1, "name": 1, "preferred_language": 1},
        )
        if client_row and client_row.get("email"):
            notify_deposit_confirmed(fresh, client_row)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[deposits] client confirmed-email failed: {e}")
    try:
        from services.live_bus import publish as live_publish
        await live_publish("balance_updated", {"reason": "deposit", "deposit_id": dep_id},
                           user_id=doc["user_id"])
        await live_publish("ledger_changed",
                           {"reason": "deposit", "deposit_id": dep_id,
                            "user_id": doc["user_id"]},
                           roles=("admin", "employee"))
    except Exception as e:  # noqa: BLE001
        logger.error(f"[deposits] SSE publish failed: {e}")
    return fresh


@router.post("/admin/deposits/{dep_id}/reject")
async def admin_reject_deposit(dep_id: str, payload: RejectPayload, request: Request) -> Any:
    staff = await require_permission(request, "withdrawals")
    doc = await db.deposits.find_one({"id": dep_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Depósito no encontrado.")
    # DR06 — alcance de monedas del empleado también al rechazar.
    _enforce_employee_currency_scope(staff, (doc.get("currency") or "").upper())
    if doc["status"] != "pending":
        raise HTTPException(status_code=409, detail="Este depósito ya fue procesado.")
    now = iso(now_utc())
    # iter260(E03) — claim atómico: una confirmación concurrente que ya
    # acreditó no puede ser sobrescrita por este rechazo.
    claim = await db.deposits.update_one(
        {"id": dep_id, "status": "pending"},
        {"$set": {"status": "rejected", "updated_at": now, "reviewed_at": now,
                  "reviewed_by": staff["user_id"],
                  "admin_note": payload.admin_note.strip() or None,
                  # N03 — la intención de cancelar la recogida viaja EN el
                  # mismo claim del rechazo: si la propagación falla, el
                  # healer la reintenta hasta cancelar o dejar incidencia.
                  "delivery_cancel_pending": {"at": now,
                                              "note": "depósito rechazado"}}},
    )
    if claim.matched_count == 0:
        raise HTTPException(status_code=409, detail="Este depósito ya fue procesado.")
    # MSG03 — el rechazo del depósito propaga a su recogida de mensajería:
    # se cancela si aún no hubo movimiento físico; si el mensajero ya
    # recogió, queda una incidencia visible para resolver el efectivo.
    try:
        from services.deliveries import handle_origin_rejected
        await handle_origin_rejected("deposit", dep_id,
                                     actor_id=staff["user_id"],
                                     note="depósito rechazado")
        await db.deposits.update_one(
            {"id": dep_id, "delivery_cancel_pending.at": now},
            {"$unset": {"delivery_cancel_pending": ""}})
    except Exception as e:
        logger.error(f"[deposits] pickup sync after reject failed (queda "
                     f"pendiente para el healer): {e}")
    fresh = await db.deposits.find_one({"id": dep_id}, {"_id": 0})
    await log_action(
        db=db, actor=staff, action="deposit.reject",
        entity_type="deposit", entity_id=dep_id,
        details={"user_id": doc["user_id"], "note": payload.admin_note.strip()},
    )
    await _notify_client_decision(fresh, approved=False, admin_note=payload.admin_note.strip())
    # iter197 — rejection email mirroring the confirm one. Best-effort.
    try:
        from email_service import notify_deposit_rejected
        client_row = await db.users.find_one(
            {"user_id": doc["user_id"]},
            {"_id": 0, "email": 1, "name": 1, "preferred_language": 1},
        )
        if client_row and client_row.get("email"):
            notify_deposit_rejected(fresh, client_row,
                                    admin_note=payload.admin_note.strip())
    except Exception as e:  # noqa: BLE001
        logger.error(f"[deposits] client rejected-email failed: {e}")
    return fresh


# Registro del handler de liquidación (rompe el ciclo services → routes).
from services.delivery_settlement import register_settlement_handler as _reg_settlement  # noqa: E402
_reg_settlement("deposit", confirm_deposit_from_delivery)
