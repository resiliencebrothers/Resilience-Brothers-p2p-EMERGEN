"""Programa Empresas — solicitud de alta de una cuenta Empresa INDEPENDIENTE.

Producto (jun 2026): igual que un cliente puede pedir ser VIP, cualquier
cliente (rol `normal` o `vip`) puede solicitar unirse al "Programa Empresas"
desde su perfil. A diferencia de VIP, la aprobación NO cambia el rol de su
cuenta personal: crea una cuenta Empresa NUEVA, SEPARADA e INDEPENDIENTE con
sus propias credenciales (email + contraseña distintos), que queda
`under_review` hasta que el staff verifique KYB/teléfono.

Colección: `company_requests`
    {
      id, user_id, user_email, user_name,     # cuenta personal solicitante
      company_name,                            # nombre comercial/legal
      account_email,                           # email de la nueva cuenta Empresa (único)
      company_phone,                           # teléfono de contacto (único, = phone de la cuenta)
      tax_id,                                  # identificación fiscal
      address,                                 # dirección
      password_hash,                           # bcrypt — NUNCA sale en la API; se borra al resolver
      status: pending | approved | rejected,
      created_at, updated_at,
      reviewed_by, reviewed_at, admin_note,
      new_user_id,                             # user_id de la cuenta Empresa creada (al aprobar)
    }

Endpoints:
    POST /api/company-requests                        (normal/vip → pending)
    GET  /api/company-requests/me                     (cliente consulta estado)
    GET  /api/admin/company-requests                  (staff w/ company_requests)
    GET  /api/admin/company-requests/pending-count    (badge)
    POST /api/admin/company-requests/{id}/approve     → crea cuenta Empresa nueva
    POST /api/admin/company-requests/{id}/reject      (con admin_note)

Reglas:
  - Solo rol `normal` o `vip` puede solicitar.
  - El email y el teléfono de la Empresa deben ser DISTINTOS a los personales
    y no estar en uso por otra cuenta ni bloqueados.
  - Una solicitud `pending` por usuario a la vez (409).
  - Tras un rechazo → 7 días de enfriamiento antes de volver a solicitar.
  - Al aprobar: se crea una cuenta `empresa` `under_review` reutilizando el
    hash bcrypt capturado en la solicitud (jamás se re-hashea), se revalidan
    unicidad/bloqueos, se envía verificación de email y se notifica al staff
    (cola de verificación de nuevos usuarios) y al solicitante.
"""
from __future__ import annotations

import uuid
import logging
from typing import Any, Optional
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, EmailStr

from db_client import db
from auth_utils import (
    require_user, require_permission, iso, now_utc,
    _hash_password, normalize_phone, assert_not_blocked,
)
from audit_log import log_action

logger = logging.getLogger("company_requests")

router = APIRouter(tags=["Company Requests"])

REJECTION_COOLDOWN_DAYS = 7
BCRYPT_MAX_BYTES = 72


# ============================================================
# Payloads
# ============================================================

class CompanyRequestCreate(BaseModel):
    """Solicitud del cliente para crear una cuenta Empresa independiente."""
    model_config = ConfigDict(extra="ignore")
    company_name: str = Field(..., min_length=2, max_length=160)
    account_email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    password_confirm: str = Field(..., min_length=8, max_length=128)
    company_phone: str = Field(..., min_length=8, max_length=20)
    tax_id: str = Field(..., min_length=3, max_length=80)
    address: str = Field(..., min_length=5, max_length=400)


class CompanyRequestReject(BaseModel):
    model_config = ConfigDict(extra="ignore")
    admin_note: str = Field(default="", max_length=500)


# ============================================================
# Helpers
# ============================================================

def _serialize(doc: Optional[dict]) -> Optional[dict]:
    """Nunca devolver `_id` ni el hash de la contraseña."""
    if not doc:
        return None
    d = dict(doc)
    d.pop("_id", None)
    d.pop("password_hash", None)
    return d


def _normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


def _cooldown_remaining(rejected_at_iso: str) -> int:
    try:
        rejected_at = datetime.fromisoformat(rejected_at_iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return 0
    elapsed = (datetime.now(timezone.utc) - rejected_at).days
    return max(0, REJECTION_COOLDOWN_DAYS - elapsed)


async def _notify_staff_new_request(req: dict) -> None:
    """In-app + push a cada staff con permiso `company_requests`."""
    try:
        from routes.notifications import _insert_notification
        from push_service import send_push_to_user
    except Exception as e:  # noqa: BLE001
        logger.error(f"[company_requests] notify import failed: {e}")
        return
    cursor = db.users.find(
        {"$or": [
            {"role": "admin"},
            {"role": "employee", "allowed_permissions": "company_requests"},
            {"role": "employee", "allowed_permissions": {"$in": [[], None]}},
        ]},
        {"_id": 0, "user_id": 1},
    )
    recipients = [r async for r in cursor]
    name = req.get("user_name") or req.get("user_email") or "Cliente"
    company = req.get("company_name") or "—"
    for r in recipients:
        uid = r["user_id"]
        try:
            await _insert_notification(
                recipient_user_id=uid,
                type="new_company_request",
                title="Nueva solicitud de Empresa",
                message=f"{name} solicita registrar la empresa «{company}».",
                data={"request_id": req["id"], "user_id": req["user_id"]},
            )
            await send_push_to_user(db, uid, {
                "title": "Nueva solicitud de Empresa",
                "body": f"{name} — {company}",
                "icon": "/icons/icon-192.png",
                "tag": f"company-req-{req['id']}",
                "url": "/admin/users?tab=company-requests",
            })
        except Exception as e:  # noqa: BLE001
            logger.error(f"[company_requests] staff notify {uid} failed: {e}")


async def _notify_client_decision(req: dict, approved: bool, admin_note: str = "") -> None:
    """Notifica al solicitante sobre la aprobación / rechazo."""
    try:
        from routes.notifications import _insert_notification
        from push_service import send_push_to_user
    except Exception as e:  # noqa: BLE001
        logger.error(f"[company_requests] notify import failed: {e}")
        return
    uid = req["user_id"]
    if approved:
        title = "¡Solicitud de Empresa aprobada!"
        message = (
            f"Tu cuenta Empresa fue creada. Inicia sesión con {req.get('account_email')} "
            "y revisa ese correo para verificar el email. Un miembro del staff debe "
            "verificar el teléfono antes de que puedas operar."
        )
    else:
        title = "Solicitud de Empresa rechazada"
        message = admin_note or "Tu solicitud fue rechazada. Podrás volver a solicitarla en 7 días."
    try:
        await _insert_notification(
            recipient_user_id=uid,
            type="company_request_approved" if approved else "company_request_rejected",
            title=title,
            message=message,
            data={"request_id": req["id"]},
        )
        await send_push_to_user(db, uid, {
            "title": title,
            "body": message[:140],
            "icon": "/icons/icon-192.png",
            "tag": f"company-decision-{req['id']}",
            "url": "/dashboard/profile",
        })
    except Exception as e:  # noqa: BLE001
        logger.error(f"[company_requests] client notify {uid} failed: {e}")


async def _publish(event_type: str, data: dict, *, user_id: Optional[str] = None,
                   admin: bool = False) -> None:
    try:
        from services.live_bus import publish as live_publish
        if admin:
            await live_publish(event_type, data, roles=("admin", "employee"))
        else:
            await live_publish(event_type, data, user_id=user_id)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[company_requests] live publish {event_type} failed: {e}")


# ============================================================
# Client endpoints
# ============================================================

@router.post("/company-requests")
async def create_company_request(payload: CompanyRequestCreate, request: Request) -> Any:
    """Un cliente `normal`/`vip` solicita crear una cuenta Empresa nueva e
    independiente. 403 para otros roles, 409 si ya tiene una pendiente o si el
    email/teléfono no están disponibles, 429 si está en enfriamiento."""
    user = await require_user(request)
    if user.get("role") not in ("normal", "vip"):
        raise HTTPException(
            status_code=403,
            detail="Solo los clientes pueden solicitar unirse al Programa Empresas.",
        )

    if payload.password != payload.password_confirm:
        raise HTTPException(status_code=422, detail="Las contraseñas no coinciden.")
    if len(payload.password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise HTTPException(
            status_code=422,
            detail="La contraseña es demasiado larga (máximo 72 bytes).",
        )

    account_email = _normalize_email(str(payload.account_email))
    company_phone = normalize_phone(payload.company_phone)
    personal_email = _normalize_email(user.get("email", ""))

    if account_email == personal_email:
        raise HTTPException(
            status_code=409,
            detail="El email de la Empresa debe ser distinto al de tu cuenta personal.",
        )
    if company_phone == user.get("phone"):
        raise HTTPException(
            status_code=409,
            detail="El teléfono de la Empresa debe ser distinto al de tu cuenta personal.",
        )
    if payload.password.casefold() == account_email.casefold():
        raise HTTPException(
            status_code=422,
            detail="La contraseña no puede ser igual al email.",
        )

    # Bloqueos + unicidad global (se revalida también al aprobar).
    await assert_not_blocked(email=account_email, phone=company_phone)
    if await db.users.find_one({"email": account_email}, {"_id": 0, "user_id": 1}):
        raise HTTPException(status_code=409, detail="Ya existe una cuenta con ese email.")
    if await db.users.find_one({"phone": company_phone}, {"_id": 0, "user_id": 1}):
        raise HTTPException(
            status_code=409,
            detail="Este número de teléfono ya está asociado a otra cuenta.",
        )

    # Una solicitud pendiente a la vez.
    existing = await db.company_requests.find_one(
        {"user_id": user["user_id"], "status": "pending"}, {"_id": 0, "id": 1},
    )
    if existing:
        raise HTTPException(status_code=409, detail="Ya tienes una solicitud de Empresa en revisión.")

    # Enfriamiento de 7 días tras el último rechazo.
    last_rejected = await db.company_requests.find_one(
        {"user_id": user["user_id"], "status": "rejected"},
        {"_id": 0, "reviewed_at": 1},
        sort=[("reviewed_at", -1)],
    )
    if last_rejected and last_rejected.get("reviewed_at"):
        remaining = _cooldown_remaining(last_rejected["reviewed_at"])
        if remaining > 0:
            raise HTTPException(
                status_code=429,
                detail=f"Debes esperar {remaining} día(s) antes de volver a solicitar.",
            )

    now = iso(now_utc())
    doc = {
        "id": f"coreq_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "user_email": user.get("email", ""),
        "user_name": user.get("name", ""),
        "company_name": payload.company_name.strip(),
        "account_email": account_email,
        "company_phone": company_phone,
        "tax_id": payload.tax_id.strip(),
        "address": payload.address.strip(),
        # Solo el hash bcrypt — nunca la contraseña en claro. Se borra al resolver.
        "password_hash": _hash_password(payload.password),
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "reviewed_by": None,
        "reviewed_at": None,
        "admin_note": None,
        "new_user_id": None,
    }
    await db.company_requests.insert_one(doc)
    await log_action(
        db=db, actor=user, action="company_request.create",
        entity_type="company_request", entity_id=doc["id"],
        details={"company_name": doc["company_name"], "account_email": account_email},
    )
    await _notify_staff_new_request(doc)
    await _publish("company_request_created", {"request_id": doc["id"]}, admin=True)
    return _serialize(doc)


@router.get("/company-requests/me")
async def get_my_company_request(request: Request) -> Any:
    """Última solicitud del cliente (cualquier estado) para la tarjeta de perfil.

    Si la solicitud fue aprobada, adjunta el estado KYB básico de la cuenta
    Empresa creada (account_status + verificación de email/teléfono) para que
    el solicitante vea qué falta antes de poder operar."""
    user = await require_user(request)
    doc = await db.company_requests.find_one(
        {"user_id": user["user_id"]}, {"_id": 0}, sort=[("created_at", -1)],
    )
    cooldown_days_left = 0
    if doc and doc.get("status") == "rejected" and doc.get("reviewed_at"):
        cooldown_days_left = _cooldown_remaining(doc["reviewed_at"])

    company_account = None
    if doc and doc.get("status") == "approved" and doc.get("new_user_id"):
        acc = await db.users.find_one(
            {"user_id": doc["new_user_id"]},
            {"_id": 0, "account_status": 1, "email_verified": 1, "phone_verified": 1},
        )
        if acc:
            company_account = {
                "account_status": acc.get("account_status"),
                "email_verified": bool(acc.get("email_verified")),
                "phone_verified": bool(acc.get("phone_verified")),
            }

    return {
        "request": _serialize(doc) if doc else None,
        "company_account": company_account,
        "cooldown_days_left": cooldown_days_left,
        "can_submit": (
            user.get("role") in ("normal", "vip")
            and (not doc or doc.get("status") != "pending")
            and cooldown_days_left == 0
        ),
    }


# ============================================================
# Admin endpoints
# ============================================================

@router.get("/admin/company-requests/pending-count")
async def admin_company_requests_pending_count(request: Request) -> Any:
    await require_permission(request, "company_requests")
    pending = await db.company_requests.count_documents({"status": "pending"})
    return {"pending": pending}


@router.get("/admin/company-requests")
async def admin_list_company_requests(
    request: Request,
    status: Optional[str] = None,
    limit: int = 200,
) -> Any:
    await require_permission(request, "company_requests")
    q: dict[str, Any] = {}
    if status and status in ("pending", "approved", "rejected"):
        q["status"] = status
    cursor = (db.company_requests.find(q, {"_id": 0})
              .sort("created_at", -1)
              .limit(min(max(1, limit), 500)))
    items = [_serialize(d) async for d in cursor]
    pending = await db.company_requests.count_documents({"status": "pending"})
    return {"items": items, "pending": pending}


@router.post("/admin/company-requests/{req_id}/approve")
async def admin_approve_company_request(req_id: str, request: Request) -> Any:
    """Aprueba una solicitud → crea una cuenta Empresa NUEVA e independiente."""
    staff = await require_permission(request, "company_requests")
    doc = await db.company_requests.find_one({"id": req_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Solicitud de Empresa no encontrada.")
    if doc["status"] != "pending":
        raise HTTPException(status_code=409, detail="La solicitud ya fue procesada.")

    password_hash = doc.get("password_hash")
    if not password_hash:
        raise HTTPException(
            status_code=409,
            detail="La solicitud no tiene credenciales válidas; pide al cliente que la reenvíe.",
        )

    account_email = _normalize_email(doc["account_email"])
    company_phone = normalize_phone(doc["company_phone"])

    # Revalidar unicidad + bloqueos (la solicitud pudo quedar pendiente días).
    await assert_not_blocked(email=account_email, phone=company_phone)
    if await db.users.find_one({"email": account_email}, {"_id": 0, "user_id": 1}):
        raise HTTPException(
            status_code=409,
            detail="Ese email ya está en uso por otra cuenta; rechaza o pide corregir la solicitud.",
        )
    if await db.users.find_one({"phone": company_phone}, {"_id": 0, "user_id": 1}):
        raise HTTPException(
            status_code=409,
            detail="Ese teléfono ya está en uso por otra cuenta; rechaza o pide corregir la solicitud.",
        )

    requester = await db.users.find_one(
        {"user_id": doc["user_id"]}, {"_id": 0, "preferred_language": 1})
    lang = (requester or {}).get("preferred_language") or "es"

    now = iso(now_utc())
    new_user_id = f"user_{uuid.uuid4().hex[:12]}"

    # CAS: solo UN aprobador puede marcar pending→approved (evita doble alta).
    cas = await db.company_requests.update_one(
        {"id": req_id, "status": "pending"},
        {"$set": {
            "status": "approved",
            "updated_at": now,
            "reviewed_at": now,
            "reviewed_by": staff["user_id"],
            "admin_note": None,
            "new_user_id": new_user_id,
        }},
    )
    if cas.modified_count != 1:
        raise HTTPException(status_code=409, detail="La solicitud ya fue procesada.")

    verification_token = uuid.uuid4().hex + uuid.uuid4().hex
    user_doc = {
        "user_id": new_user_id,
        "email": account_email,
        "name": doc["company_name"],
        "picture": "",
        "role": "empresa",
        "auth_provider": "password",
        "password_hash": password_hash,  # copiar el hash — NUNCA re-hashear
        "email_verified": False,
        "verification_token": verification_token,
        "verification_expires_at": iso(now_utc() + timedelta(hours=24)),
        "vip_balance_usd": 0.0,
        "onboarding_completed": False,
        "phone": company_phone,
        "phone_verified": False,
        "account_status": "under_review",
        "under_review_since": now,
        "preferred_language": lang,
        "created_at": now,
        # Metadatos de empresa + traza a la cuenta personal solicitante.
        "account_type": "business",
        "company_name": doc["company_name"],
        "tax_id": doc["tax_id"],
        "address": doc["address"],
        "parent_user_id": doc["user_id"],
    }
    try:
        await db.users.insert_one(user_doc)
    except Exception as e:  # noqa: BLE001
        # Revertir la solicitud a pendiente para no dejarla aprobada sin cuenta.
        await db.company_requests.update_one(
            {"id": req_id},
            {"$set": {"status": "pending", "reviewed_at": None,
                      "reviewed_by": None, "new_user_id": None, "updated_at": iso(now_utc())}},
        )
        logger.error(f"[company_requests] account creation failed for {req_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail="No se pudo crear la cuenta Empresa. Inténtalo de nuevo.",
        )

    # Éxito → borrar el hash de la solicitud (ya vive en la cuenta nueva).
    await db.company_requests.update_one({"id": req_id}, {"$unset": {"password_hash": ""}})

    fresh = await db.company_requests.find_one({"id": req_id}, {"_id": 0})
    await log_action(
        db=db, actor=staff, action="company_request.approve",
        entity_type="company_request", entity_id=req_id,
        details={"requester": doc["user_id"], "new_user_id": new_user_id,
                 "account_email": account_email},
    )

    # Verificación de email de la cuenta nueva (best-effort).
    try:
        import email_service
        email_service.notify_email_verification(
            account_email, doc["company_name"], verification_token, lang=lang)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[company_requests] verification email failed: {e}")

    # La cuenta Empresa entra a la cola de verificación de nuevos usuarios.
    try:
        from routes.notifications import notify_staff_new_pending_user
        await notify_staff_new_pending_user(user_doc)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[company_requests] pending-user notify failed: {e}")

    await _notify_client_decision(fresh, approved=True)
    await _publish("company_request_approved", {"request_id": req_id}, user_id=doc["user_id"])
    await _publish("company_request_updated", {"request_id": req_id}, admin=True)
    return _serialize(fresh)


@router.post("/admin/company-requests/{req_id}/reject")
async def admin_reject_company_request(
    req_id: str, payload: CompanyRequestReject, request: Request) -> Any:
    staff = await require_permission(request, "company_requests")
    doc = await db.company_requests.find_one({"id": req_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Solicitud de Empresa no encontrada.")
    if doc["status"] != "pending":
        raise HTTPException(status_code=409, detail="La solicitud ya fue procesada.")

    now = iso(now_utc())
    note = (payload.admin_note or "").strip() or None
    # Rechazar y borrar el hash (ya no se usará).
    await db.company_requests.update_one(
        {"id": req_id},
        {"$set": {
            "status": "rejected",
            "updated_at": now,
            "reviewed_at": now,
            "reviewed_by": staff["user_id"],
            "admin_note": note,
        }, "$unset": {"password_hash": ""}},
    )
    fresh = await db.company_requests.find_one({"id": req_id}, {"_id": 0})
    await log_action(
        db=db, actor=staff, action="company_request.reject",
        entity_type="company_request", entity_id=req_id,
        details={"requester": doc["user_id"], "note": note},
    )
    await _notify_client_decision(fresh, approved=False, admin_note=note or "")
    await _publish("company_request_rejected", {"request_id": req_id}, user_id=doc["user_id"])
    await _publish("company_request_updated", {"request_id": req_id}, admin=True)
    return _serialize(fresh)
