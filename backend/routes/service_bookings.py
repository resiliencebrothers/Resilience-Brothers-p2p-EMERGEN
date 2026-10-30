"""Empresas de Servicios — Fase 2 (reserva de turnos con pago en USDT).

Un cliente autenticado reserva un TURNO concreto de un servicio publicado y se
le cobra YA el precio completo del servicio × cantidad desde su saldo USDT. El
dinero queda EN DEPÓSITO (retenido por la plataforma): ni el cliente lo tiene,
ni la empresa lo cobra todavía.

Ciclo de vida del booking:
  pending   → cobrado al cliente, espera decisión de la empresa
  accepted  → la empresa aceptó; el dinero sigue retenido hasta la cita
  rejected  → la empresa rechazó → REEMBOLSO automático al cliente
  cancelled → el cliente canceló antes de la cita → REEMBOLSO
  expired   → la empresa no decidió a tiempo → REEMBOLSO automático (cron)
  settled   → pasó la fecha de la cita (aceptada) → se ABONA a la empresa (cron)

Reglas de negocio confirmadas por el operador:
  - Se cobra el PRECIO COMPLETO del servicio al reservar.
  - La empresa recibe el dinero DESPUÉS de la fecha de la cita.
  - Si la empresa no acepta/rechaza a tiempo, se cancela y se devuelve solo.
  - TODOS los servicios se pueden reservar eligiendo la CANTIDAD.

Todos los movimientos de saldo usan los primitivos idempotentes por op_id
(`debit_balance_idempotent`/`credit_balance_idempotent`), de modo que un
reintento, el cron o una doble entrega NUNCA cobran ni devuelven dos veces.
"""
import os
import uuid
import hmac
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from db_client import db
from auth_utils import require_user, require_company, now_utc, iso
from services.balances import (
    debit_balance_idempotent, credit_balance_idempotent, op_was_applied,
    assert_account_active, assert_not_defensive,
)
from services.booking_slots import (
    free_slots_for_date, slot_start_utc, slot_end_utc, ACTIVE_BOOKING_STATES,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ServiceBookings"])

# La empresa tiene este margen para decidir; si la cita es antes, manda la cita.
ACCEPT_WINDOW_HOURS = 48
MAX_QUANTITY = 999
_BOOKING_CODE = "USDT"


class BookingCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    service_id: str = Field(..., min_length=1, max_length=80)
    slot_date: str = Field(..., min_length=10, max_length=10)   # YYYY-MM-DD
    slot_start: str = Field(..., min_length=4, max_length=5)    # HH:MM
    quantity: int = Field(1, ge=1, le=MAX_QUANTITY)
    note: str = Field("", max_length=500)


class RejectBody(BaseModel):
    reason: str = Field("", max_length=300)


class ReviewCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    rating: int = Field(..., ge=1, le=5)
    comment: str = Field("", max_length=1000)


def _parse(dt_iso: Optional[str]) -> Optional[datetime]:
    if not dt_iso:
        return None
    try:
        return datetime.fromisoformat(dt_iso)
    except (ValueError, TypeError):
        return None


async def _notify(user_id: str, *, ntype: str, title: str, message: str,
                  booking_id: str) -> None:
    try:
        from routes.notifications import _insert_notification
        await _insert_notification(
            recipient_user_id=user_id, type=ntype, title=title,
            message=message, data={"booking_id": booking_id})
    except Exception as e:  # noqa: BLE001
        logger.error(f"booking notify failed: {e}")


async def _bookable_service_or_404(service_id: str) -> dict:
    svc = await db.services.find_one(
        {"id": service_id, "status": "published", "is_active": True},
        {"_id": 0})
    if not svc:
        raise HTTPException(status_code=404, detail="Servicio no disponible.")
    from routes.services import _eligible_owner_ids
    eligible = await _eligible_owner_ids([svc.get("company_id")])
    if svc.get("company_id") not in eligible:
        raise HTTPException(status_code=404, detail="Servicio no disponible.")
    return svc


def _unit_price(svc: dict) -> float:
    if svc.get("pricing_type") == "quote":
        return 0.0
    return round(float(svc.get("price_usdt") or 0), 2)


def _deposit_now(svc: dict, total: float) -> float:
    """Importe que se COBRA al reservar. Si el servicio tiene un anticipo
    configurado, se cobra SOLO ese anticipo (el resto se cobra del saldo tras
    la cita); sin anticipo, se cobra el total completo (regla original)."""
    if total <= 0:
        return 0.0
    dt = svc.get("deposit_type")
    dv = float(svc.get("deposit_value") or 0)
    if dt == "percent" and dv > 0:
        return round(min(total, total * dv / 100.0), 2)
    if dt == "fixed" and dv > 0:
        return round(min(total, dv), 2)
    return total


def _public_booking(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


# ============================================================
# Cliente — disponibilidad y reserva
# ============================================================

@router.get("/services/{service_id}/slots")
async def service_slots(service_id: str, date: str, request: Request) -> Any:
    """Turnos LIBRES de una fecha concreta (para el calendario del cliente)."""
    await require_user(request)
    svc = await _bookable_service_or_404(service_id)
    slots = await free_slots_for_date(svc, date)
    return {"date": date, "timezone": svc.get("timezone"), "slots": slots}


@router.post("/bookings")
async def create_booking(payload: BookingCreate, request: Request) -> Any:
    user = await require_user(request)
    await assert_not_defensive("reservar un turno")
    await assert_account_active(user)
    svc = await _bookable_service_or_404(payload.service_id)
    if svc.get("company_id") == user["user_id"]:
        raise HTTPException(
            status_code=400, detail="No puedes reservar tu propio servicio.")

    # El turno pedido debe seguir LIBRE ahora mismo (horario, aviso mínimo,
    # fecha no bloqueada y cupo disponible): se recalcula contra la BD.
    free = await free_slots_for_date(svc, payload.slot_date)
    match = next((s for s in free if s["start"] == payload.slot_start), None)
    if not match:
        raise HTTPException(
            status_code=400,
            detail="Ese turno ya no está disponible. Elige otro horario.")

    qty = int(payload.quantity)
    amount = round(_unit_price(svc) * qty, 2)
    charge_now = _deposit_now(svc, amount)        # anticipo (o total si no hay)
    remainder = round(amount - charge_now, 2)
    now = now_utc()
    start_dt = slot_start_utc(svc, payload.slot_date, payload.slot_start)
    end_dt = slot_end_utc(svc, payload.slot_date, payload.slot_start)
    deadline = min(start_dt, now + timedelta(hours=ACCEPT_WINDOW_HOURS))
    booking_id = str(uuid.uuid4())
    pay_op = f"svcbk:{booking_id}:pay"
    doc = {
        "id": booking_id,
        "service_id": svc["id"],
        "service_title": svc.get("title", ""),
        "company_id": svc["company_id"],
        "company_name": svc.get("owner_name", ""),
        "customer_id": user["user_id"],
        "customer_name": user.get("name", ""),
        "slot_date": payload.slot_date,
        "slot_start": match["start"],
        "slot_end": match["end"],
        "slot_start_utc": iso(start_dt),
        "slot_end_utc": iso(end_dt),
        "accept_deadline_utc": iso(deadline),
        "timezone": svc.get("timezone"),
        "pricing_type": svc.get("pricing_type"),
        "unit_price_usdt": _unit_price(svc),
        "quantity": qty,
        "amount_usdt": amount,
        "deposit_usdt": charge_now,
        "remainder_usdt": remainder,
        "remainder_collected": False,
        "company_paid_usdt": 0.0,
        "currency": _BOOKING_CODE,
        "status": "pending",
        "note": payload.note.strip(),
        "reject_reason": "",
        "pay_op_id": pay_op,
        "rest_op_id": "",
        "refund_op_id": "",
        "settle_op_id": "",
        "reminded_24h": False,
        "created_at": iso(now),
        "updated_at": iso(now),
        "decided_at": "",
    }
    await db.service_bookings.insert_one(doc)

    # Anti-sobreventa determinista: ordenados por created_at, los primeros
    # `capacity` ganan el cupo del turno. Si mi reserva no entra, la borro.
    capacity = int(svc.get("capacity") or 1) or 1
    winners = await db.service_bookings.find(
        {"service_id": svc["id"], "slot_date": payload.slot_date,
         "slot_start": match["start"],
         "status": {"$in": list(ACTIVE_BOOKING_STATES)}},
        {"_id": 0, "id": 1}).sort([("created_at", 1), ("id", 1)]).to_list(capacity + 10)
    keep = {w["id"] for w in winners[:capacity]}
    if booking_id not in keep:
        await db.service_bookings.delete_one({"id": booking_id})
        raise HTTPException(
            status_code=409,
            detail="Ese turno se acaba de ocupar. Elige otro horario.")

    # Cobro al reservar: se descuenta el ANTICIPO (o el total si el servicio no
    # define anticipo) del saldo USDT del cliente y queda retenido por la
    # plataforma. El resto, si lo hay, se cobra automáticamente tras la cita.
    if charge_now > 0:
        res = await debit_balance_idempotent(
            user["user_id"], _BOOKING_CODE, charge_now, pay_op)
        if res == "insufficient":
            await db.service_bookings.delete_one({"id": booking_id})
            raise HTTPException(
                status_code=400,
                detail=f"Saldo USDT insuficiente para reservar ({charge_now} USDT).")

    extra = (f" Pagas ahora {charge_now} USDT; el resto ({remainder} USDT) tras la cita."
             if remainder > 0 else "")
    await _notify(
        svc["company_id"], ntype="service_booking_new",
        title="Nueva reserva de turno",
        message=(f"{user.get('name', 'Un cliente')} reservó «{svc.get('title','')}» "
                 f"el {payload.slot_date} a las {match['start']}. "
                 "Acéptala o recházala." + extra),
        booking_id=booking_id)
    return _public_booking(doc)


@router.get("/bookings/mine")
async def my_bookings(request: Request) -> Any:
    user = await require_user(request)
    return await db.service_bookings.find(
        {"customer_id": user["user_id"]}, {"_id": 0}) \
        .sort("created_at", -1).to_list(300)


@router.post("/bookings/{booking_id}/cancel")
async def cancel_booking(booking_id: str, request: Request) -> Any:
    user = await require_user(request)
    doc = await db.service_bookings.find_one(
        {"id": booking_id, "customer_id": user["user_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Reserva no encontrada.")
    if doc["status"] not in ("pending", "accepted"):
        raise HTTPException(
            status_code=400,
            detail="Esta reserva ya no se puede cancelar.")
    start_dt = _parse(doc.get("slot_start_utc"))
    if start_dt and start_dt <= now_utc():
        raise HTTPException(
            status_code=400,
            detail="El turno ya comenzó; no se puede cancelar.")
    res = await db.service_bookings.update_one(
        {"id": booking_id, "status": doc["status"]},
        {"$set": {"status": "cancelled", "decided_at": iso(now_utc()),
                  "updated_at": iso(now_utc())}})
    if res.matched_count == 0:
        raise HTTPException(status_code=409, detail="La reserva cambió de estado.")
    await _refund(doc)
    await _notify(
        doc["company_id"], ntype="service_booking_cancelled",
        title="Reserva cancelada",
        message=(f"{doc.get('customer_name','El cliente')} canceló su turno de "
                 f"«{doc.get('service_title','')}» del {doc['slot_date']}."),
        booking_id=booking_id)
    return await db.service_bookings.find_one({"id": booking_id}, {"_id": 0})


# ============================================================
# Empresa — gestión de reservas recibidas
# ============================================================

@router.get("/company/bookings")
async def company_bookings(request: Request, status: Optional[str] = None) -> Any:
    user = await require_company(request)
    q: dict = {"company_id": user["user_id"]}
    if status in ("pending", "accepted", "rejected", "cancelled",
                  "expired", "settled"):
        q["status"] = status
    return await db.service_bookings.find(q, {"_id": 0}) \
        .sort("created_at", -1).to_list(500)


async def _company_booking_or_404(booking_id: str, company_id: str) -> dict:
    doc = await db.service_bookings.find_one(
        {"id": booking_id, "company_id": company_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Reserva no encontrada.")
    return doc


@router.post("/company/bookings/{booking_id}/accept")
async def accept_booking(booking_id: str, request: Request) -> Any:
    user = await require_company(request)
    doc = await _company_booking_or_404(booking_id, user["user_id"])
    if doc["status"] != "pending":
        raise HTTPException(
            status_code=400, detail="Solo puedes aceptar reservas pendientes.")
    start_dt = _parse(doc.get("slot_start_utc"))
    if start_dt and start_dt <= now_utc():
        raise HTTPException(
            status_code=400,
            detail="El turno ya pasó; no se puede aceptar.")
    deadline = _parse(doc.get("accept_deadline_utc"))
    if deadline and deadline <= now_utc():
        raise HTTPException(
            status_code=400,
            detail=("El plazo para confirmar esta reserva venció; se cancelará "
                    "y reembolsará automáticamente."))
    res = await db.service_bookings.update_one(
        {"id": booking_id, "status": "pending"},
        {"$set": {"status": "accepted", "decided_at": iso(now_utc()),
                  "updated_at": iso(now_utc())}})
    if res.matched_count == 0:
        raise HTTPException(status_code=409, detail="La reserva cambió de estado.")
    await _notify(
        doc["customer_id"], ntype="service_booking_accepted",
        title="Reserva confirmada",
        message=(f"La empresa confirmó tu turno de «{doc.get('service_title','')}» "
                 f"el {doc['slot_date']} a las {doc['slot_start']}."),
        booking_id=booking_id)
    return await db.service_bookings.find_one({"id": booking_id}, {"_id": 0})


@router.post("/company/bookings/{booking_id}/reject")
async def reject_booking(booking_id: str, payload: RejectBody,
                         request: Request) -> Any:
    user = await require_company(request)
    doc = await _company_booking_or_404(booking_id, user["user_id"])
    if doc["status"] not in ("pending", "accepted"):
        raise HTTPException(
            status_code=400, detail="Esta reserva ya no se puede rechazar.")
    start_dt = _parse(doc.get("slot_start_utc"))
    if start_dt and start_dt <= now_utc():
        raise HTTPException(
            status_code=400,
            detail="La cita ya ocurrió; no se puede rechazar.")
    reason = payload.reason.strip()
    res = await db.service_bookings.update_one(
        {"id": booking_id, "status": doc["status"]},
        {"$set": {"status": "rejected", "reject_reason": reason,
                  "decided_at": iso(now_utc()), "updated_at": iso(now_utc())}})
    if res.matched_count == 0:
        raise HTTPException(status_code=409, detail="La reserva cambió de estado.")
    await _refund(doc)
    await _notify(
        doc["customer_id"], ntype="service_booking_rejected",
        title="Reserva rechazada — reembolso emitido",
        message=(f"La empresa no pudo tomar tu turno de «{doc.get('service_title','')}» "
                 f"del {doc['slot_date']}. Te devolvimos {_refund_amount(doc)} USDT."
                 + (f" Motivo: {reason}" if reason else "")),
        booking_id=booking_id)
    return await db.service_bookings.find_one({"id": booking_id}, {"_id": 0})


# ============================================================
# Reseñas de servicio (públicas; solo clientes con cita completada)
# ============================================================

async def _recompute_service_rating(service_id: str) -> None:
    agg = await db.service_reviews.aggregate([
        {"$match": {"service_id": service_id}},
        {"$group": {"_id": None, "avg": {"$avg": "$rating"},
                    "n": {"$sum": 1}}},
    ]).to_list(1)
    if agg:
        await db.services.update_one(
            {"id": service_id},
            {"$set": {"rating_avg": round(float(agg[0]["avg"]), 2),
                      "rating_count": int(agg[0]["n"])}})
    else:
        await db.services.update_one(
            {"id": service_id}, {"$set": {"rating_avg": 0, "rating_count": 0}})


@router.get("/services/{service_id}/reviews")
async def list_reviews(service_id: str) -> Any:
    return await db.service_reviews.find(
        {"service_id": service_id}, {"_id": 0, "customer_id": 0}) \
        .sort("created_at", -1).to_list(200)


@router.post("/services/{service_id}/reviews")
async def create_review(service_id: str, payload: ReviewCreate,
                        request: Request) -> Any:
    user = await require_user(request)
    completed = await db.service_bookings.find_one(
        {"service_id": service_id, "customer_id": user["user_id"],
         "status": "settled"}, {"_id": 0, "id": 1})
    if not completed:
        raise HTTPException(
            status_code=403,
            detail="Solo puedes valorar un servicio tras completar una cita.")
    now = iso(now_utc())
    existing = await db.service_reviews.find_one(
        {"service_id": service_id, "customer_id": user["user_id"]}, {"_id": 0})
    doc = {
        "id": existing["id"] if existing else str(uuid.uuid4()),
        "service_id": service_id,
        "customer_id": user["user_id"],
        "customer_name": user.get("name", "Cliente"),
        "rating": int(payload.rating),
        "comment": payload.comment.strip(),
        "created_at": existing["created_at"] if existing else now,
        "updated_at": now,
    }
    await db.service_reviews.update_one(
        {"service_id": service_id, "customer_id": user["user_id"]},
        {"$set": doc}, upsert=True)
    await _recompute_service_rating(service_id)
    doc.pop("customer_id", None)
    return doc


@router.get("/bookings/my-reviews")
async def my_reviews(request: Request) -> Any:
    """Reseñas del cliente, indexadas por service_id, para pre-rellenar el
    formulario de valoración en «Mis reservas»."""
    user = await require_user(request)
    rows = await db.service_reviews.find(
        {"customer_id": user["user_id"]},
        {"_id": 0, "service_id": 1, "rating": 1, "comment": 1}).to_list(300)
    return {r["service_id"]: {"rating": r["rating"], "comment": r.get("comment", "")}
            for r in rows}


# ============================================================
# Empresa — panel de ingresos de reservas
# ============================================================

@router.get("/company/bookings/earnings")
async def company_earnings(request: Request) -> Any:
    user = await require_company(request)
    cid = user["user_id"]
    held_pending = 0.0
    upcoming_release = 0.0
    settled_total = 0.0
    upcoming: list[dict] = []
    async for b in db.service_bookings.find(
            {"company_id": cid,
             "status": {"$in": ["pending", "accepted", "settled"]}}, {"_id": 0}):
        st = b["status"]
        if st == "pending":
            held_pending += float(b.get("deposit_usdt", b.get("amount_usdt", 0)) or 0)
        elif st == "accepted":
            total = float(b.get("amount_usdt", 0) or 0)
            upcoming_release += total
            upcoming.append({
                "id": b["id"], "service_title": b.get("service_title", ""),
                "slot_date": b.get("slot_date"), "slot_start": b.get("slot_start"),
                "amount_usdt": total,
                "already_collected": float(b.get("deposit_usdt", 0) or 0),
                "release_after": b.get("slot_end_utc")})
        elif st == "settled":
            settled_total += float(b.get("company_paid_usdt", b.get("amount_usdt", 0)) or 0)
    upcoming.sort(key=lambda x: x.get("slot_date") or "")
    return {
        "currency": _BOOKING_CODE,
        "held_pending": round(held_pending, 2),
        "upcoming_release": round(upcoming_release, 2),
        "settled_total": round(settled_total, 2),
        "upcoming": upcoming,
    }


# ============================================================
# Movimientos de saldo (idempotentes por op_id)
# ============================================================

async def _refund(doc: dict) -> None:
    """Devuelve al cliente lo que se le COBRÓ al reservar (el anticipo, o el
    total si no había anticipo). Idempotente."""
    amount = round(float(doc.get("deposit_usdt", doc.get("amount_usdt")) or 0), 2)
    if amount <= 0:
        return
    # Robustez: solo devolvemos si el COBRO llegó a aplicarse. Si una caída
    # entre el insert y el débito dejó una reserva sin pagar, un rechazo/cron
    # posterior NUNCA debe acreditar dinero que jamás se cobró.
    pay_op = doc.get("pay_op_id")
    if pay_op and not await op_was_applied(doc["customer_id"], pay_op):
        return
    op = f"svcbk:{doc['id']}:refund"
    ok = await credit_balance_idempotent(
        doc["customer_id"], doc.get("currency", _BOOKING_CODE), amount, op)
    if ok:
        await db.service_bookings.update_one(
            {"id": doc["id"]}, {"$set": {"refund_op_id": op,
                                         "updated_at": iso(now_utc())}})


def _refund_amount(doc: dict) -> float:
    return round(float(doc.get("deposit_usdt", doc.get("amount_usdt")) or 0), 2)


async def _settle(doc: dict) -> None:
    """Liquida una reserva ya cumplida (idempotente):
      1) cobra el RESTO pendiente del saldo del cliente (si hay anticipo);
      2) ABONA a la empresa lo realmente cobrado (anticipo + resto recaudado).
    Simetría del depósito: la empresa solo recibe dinero que se cobró de verdad;
    si el cliente ya no tiene saldo para el resto, la empresa recibe el anticipo
    y la reserva queda marcada como resto no recaudado."""
    deposit = round(float(doc.get("deposit_usdt", doc.get("amount_usdt")) or 0), 2)
    remainder = round(float(doc.get("remainder_usdt") or 0), 2)
    pay_op = doc.get("pay_op_id")
    deposit_paid = (not pay_op) or await op_was_applied(doc["customer_id"], pay_op)
    collected = deposit if deposit_paid else 0.0
    rest_collected = False
    if remainder > 0 and deposit_paid:
        rest_op = f"svcbk:{doc['id']}:rest"
        res = await debit_balance_idempotent(
            doc["customer_id"], doc.get("currency", _BOOKING_CODE), remainder, rest_op)
        if res in ("applied", "duplicate"):
            collected = round(collected + remainder, 2)
            rest_collected = True
            await db.service_bookings.update_one(
                {"id": doc["id"]}, {"$set": {"rest_op_id": rest_op}})
    company_amount = round(collected, 2)
    settle_op = f"svcbk:{doc['id']}:settle"
    if company_amount > 0:
        await credit_balance_idempotent(
            doc["company_id"], doc.get("currency", _BOOKING_CODE),
            company_amount, settle_op)
    await db.service_bookings.update_one(
        {"id": doc["id"]}, {"$set": {"settle_op_id": settle_op,
                                     "remainder_collected": rest_collected,
                                     "company_paid_usdt": company_amount,
                                     "updated_at": iso(now_utc())}})


# ============================================================
# Procesamiento programado (expirar pendientes + liquidar cumplidas)
# ============================================================

async def process_due_bookings(now: Optional[datetime] = None) -> dict:
    """Idempotente: (1) expira+reembolsa las PENDIENTES cuyo plazo venció;
    (2) liquida (abona a la empresa) las ACEPTADAS cuya cita ya terminó."""
    now = now or now_utc()
    expired = 0
    settled = 0

    # (1) Expirar pendientes vencidas → reembolso.
    async for doc in db.service_bookings.find(
            {"status": "pending"}, {"_id": 0}):
        deadline = _parse(doc.get("accept_deadline_utc"))
        if deadline and deadline <= now:
            res = await db.service_bookings.update_one(
                {"id": doc["id"], "status": "pending"},
                {"$set": {"status": "expired", "decided_at": iso(now),
                          "updated_at": iso(now)}})
            if res.matched_count:
                await _refund(doc)
                expired += 1
                await _notify(
                    doc["customer_id"], ntype="service_booking_expired",
                    title="Reserva no confirmada — reembolso emitido",
                    message=(f"La empresa no confirmó tu turno de "
                             f"«{doc.get('service_title','')}» a tiempo. "
                             f"Te devolvimos {_refund_amount(doc)} USDT."),
                    booking_id=doc["id"])

    # (2) Liquidar aceptadas cuya cita ya terminó → abono a la empresa.
    async for doc in db.service_bookings.find(
            {"status": "accepted"}, {"_id": 0}):
        end_dt = _parse(doc.get("slot_end_utc"))
        if end_dt and end_dt <= now:
            res = await db.service_bookings.update_one(
                {"id": doc["id"], "status": "accepted"},
                {"$set": {"status": "settled", "updated_at": iso(now)}})
            if res.matched_count:
                await _settle(doc)
                settled += 1
                fresh = await db.service_bookings.find_one(
                    {"id": doc["id"]}, {"_id": 0, "company_paid_usdt": 1,
                                        "remainder_collected": 1})
                paid = (fresh or {}).get("company_paid_usdt", doc.get("amount_usdt", 0))
                await _notify(
                    doc["company_id"], ntype="service_booking_settled",
                    title="Pago de reserva liberado",
                    message=(f"La cita de «{doc.get('service_title','')}» del "
                             f"{doc['slot_date']} se completó. Te abonamos "
                             f"{paid} USDT."),
                    booking_id=doc["id"])

    return {"expired": expired, "settled": settled}


REMINDER_LEAD_HOURS = 24


async def _user_contact(user_id: str) -> tuple:
    u = await db.users.find_one(
        {"user_id": user_id},
        {"_id": 0, "email": 1, "name": 1, "language": 1}) or {}
    return u.get("email"), u.get("name"), (u.get("language") or "es")


async def send_due_reminders(now: Optional[datetime] = None) -> dict:
    """Recordatorio ~24 h antes de cada cita CONFIRMADA (una sola vez), por
    notificación en la app Y por correo, al cliente y a la empresa."""
    now = now or now_utc()
    horizon = now + timedelta(hours=REMINDER_LEAD_HOURS)
    reminded = 0
    async for doc in db.service_bookings.find(
            {"status": "accepted", "reminded_24h": {"$ne": True}}, {"_id": 0}):
        start_dt = _parse(doc.get("slot_start_utc"))
        if not start_dt or start_dt <= now or start_dt > horizon:
            continue
        res = await db.service_bookings.update_one(
            {"id": doc["id"], "status": "accepted", "reminded_24h": {"$ne": True}},
            {"$set": {"reminded_24h": True, "updated_at": iso(now)}})
        if not res.matched_count:
            continue
        reminded += 1
        when = (f"{doc['slot_date']} {doc['slot_start']}–{doc['slot_end']} "
                f"({doc.get('timezone', '')})")
        title = doc.get("service_title", "")
        await _notify(
            doc["customer_id"], ntype="service_booking_reminder",
            title="Recordatorio de cita",
            message=(f"Tu cita de «{title}» es el {doc['slot_date']} a las "
                     f"{doc['slot_start']}."),
            booking_id=doc["id"])
        await _notify(
            doc["company_id"], ntype="service_booking_reminder",
            title="Recordatorio de cita",
            message=(f"Próxima cita de «{title}»: {doc['slot_date']} a las "
                     f"{doc['slot_start']}."),
            booking_id=doc["id"])
        try:
            import email_service
            ce, cn, cl = await _user_contact(doc["customer_id"])
            oe, on, ol = await _user_contact(doc["company_id"])
            if ce:
                await asyncio.to_thread(
                    email_service.notify_booking_reminder, ce, cn, title, when,
                    "customer", cl)
            if oe:
                await asyncio.to_thread(
                    email_service.notify_booking_reminder, oe, on, title, when,
                    "company", ol)
        except Exception as e:  # noqa: BLE001
            logger.error(f"booking reminder email failed: {e}")
    return {"reminded": reminded}


async def run_booking_jobs(now: Optional[datetime] = None) -> dict:
    now = now or now_utc()
    r1 = await process_due_bookings(now)
    r2 = await send_due_reminders(now)
    return {**r1, **r2}


def _cron_authorized(request: Request) -> bool:
    secret = os.environ.get("WEBHOOK_CRON_SECRET") or ""
    header = request.headers.get("authorization") or ""
    if not secret or not header.lower().startswith("bearer "):
        return False
    token = header.split(" ", 1)[1].strip()
    return hmac.compare_digest(token, secret)


@router.post("/cron/bookings-tick")
async def bookings_cron(request: Request, background: BackgroundTasks) -> Any:
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    if not _cron_authorized(request):
        raise HTTPException(status_code=401, detail="unauthorized")
    background.add_task(run_booking_jobs)
    return {"ok": True, "queued": True}
