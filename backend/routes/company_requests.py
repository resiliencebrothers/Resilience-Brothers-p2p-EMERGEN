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
from typing import Any, Optional, Awaitable, Callable
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, EmailStr, field_validator
from pymongo.errors import DuplicateKeyError

from db_client import db
from auth_utils import (
    require_user, require_permission, iso, now_utc,
    _hash_password, normalize_phone, assert_not_blocked,
)
from audit_log import log_action
from services.proof_upload import maybe_upload_proof

logger = logging.getLogger("company_requests")

router = APIRouter(tags=["Company Requests"])

REJECTION_COOLDOWN_DAYS = 7
BCRYPT_MAX_BYTES = 72
RESEND_COOLDOWN_SECONDS = 60


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


class CompanySignupCreate(BaseModel):
    """Alta PÚBLICA (sin sesión) de una cuenta Empresa en UN solo paso: datos de
    la empresa + credenciales + los 2 documentos del KYB (licencia operativa e
    ID del representante legal). El código fiscal sustituye al certificado
    fiscal, así que no se pide por separado."""
    model_config = ConfigDict(extra="ignore")
    company_name: str = Field(..., min_length=2, max_length=160)
    account_email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    password_confirm: str = Field(..., min_length=8, max_length=128)
    company_phone: str = Field(..., min_length=8, max_length=20)
    tax_id: str = Field(..., min_length=3, max_length=80)
    address: str = Field(..., min_length=5, max_length=400)
    operating_license: str = Field(..., description="data URL (imagen o PDF) de la licencia operativa")
    legal_rep_id: str = Field(..., description="data URL (imagen o PDF) del ID del representante legal")
    captcha_token: str = ""

    @field_validator("operating_license", "legal_rep_id")
    @classmethod
    def _must_be_data_url(cls, v: str) -> str:
        if not v or not (v.startswith("data:image/") or v.startswith("data:application/pdf")):
            raise ValueError("Debe ser una imagen o un PDF en formato data:...;base64.")
        return v


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
                "url": "/admin/users?tab=company-kyb",
            })
        except Exception as e:  # noqa: BLE001
            logger.error(f"[company_requests] staff notify {uid} failed: {e}")


async def _notify_client_decision(req: dict, approved: bool, admin_note: str = "") -> bool:
    """Notifica al solicitante sobre la aprobación / rechazo.

    P02-R — devuelve un RESULTADO DE ÉXITO explícito. El aviso en-app (campana)
    es el canal PERSISTENTE y su fallo NO se absorbe: si no se pudo insertar,
    retorna `False` para que el canal NO se selle y el recuperador lo reintente.
    El push es best-effort (se intenta solo si la campana quedó registrada) y su
    fallo no invalida el canal. Como la inserción es lo único persistente y es
    atómica, reintentar tras un fallo no duplica (nada quedó escrito)."""
    try:
        from routes.notifications import _insert_notification
        from push_service import send_push_to_user
    except Exception as e:  # noqa: BLE001
        logger.error(f"[company_requests] notify import failed: {e}")
        return False
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
            dedup_key=(f"company-decision:{req['id']}:"
                       f"{'approved' if approved else 'rejected'}:{uid}"),
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"[company_requests] client notify {uid} bell insert failed: {e}")
        return False  # persistente: NO entregado → el canal no se sella y se reintenta
    try:
        await send_push_to_user(db, uid, {
            "title": title,
            "body": message[:140],
            "icon": "/icons/icon-192.png",
            "tag": f"company-decision-{req['id']}",
            "url": "/dashboard/profile",
        })
    except Exception as e:  # noqa: BLE001
        logger.error(f"[company_requests] client push {uid} failed (best-effort): {e}")
    return True


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


async def notify_requester_company_active(empresa_user: dict) -> None:
    """Avisa al SOLICITANTE (cuenta personal) que su cuenta Empresa ya está
    activa. Se llama desde el flujo de staff `verify-phone` cuando una cuenta
    Empresa (con `parent_user_id`) pasa a `active`."""
    parent_id = empresa_user.get("parent_user_id")
    if not parent_id:
        return
    try:
        from routes.notifications import _insert_notification
        from push_service import send_push_to_user
    except Exception as e:  # noqa: BLE001
        logger.error(f"[company_requests] notify import failed: {e}")
        return
    company = empresa_user.get("company_name") or empresa_user.get("name") or "tu empresa"
    email = empresa_user.get("email", "")
    title = "¡Tu cuenta Empresa ya está activa!"
    message = (f"La cuenta Empresa «{company}» ({email}) fue verificada por el equipo. "
               "Inicia sesión y empieza a operar.")
    try:
        await _insert_notification(
            recipient_user_id=parent_id,
            type="company_account_activated",
            title=title,
            message=message,
            data={"company_user_id": empresa_user.get("user_id")},
        )
        await send_push_to_user(db, parent_id, {
            "title": title,
            "body": message[:140],
            "icon": "/icons/icon-192.png",
            "tag": f"company-active-{empresa_user.get('user_id')}",
            "url": "/dashboard/profile",
        })
    except Exception as e:  # noqa: BLE001
        logger.error(f"[company_requests] active notify {parent_id} failed: {e}")
    await _publish("company_account_activated",
                   {"company_user_id": empresa_user.get("user_id")}, user_id=parent_id)



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
    try:
        await db.company_requests.insert_one(doc)
    except DuplicateKeyError:
        # A04 — dos POST concurrentes del mismo usuario: el índice único parcial
        # (user_id + status=pending) deja pasar solo UNA pendiente; el perdedor
        # recibe el MISMO conflicto que la comprobación de lectura previa.
        raise HTTPException(status_code=409, detail="Ya tienes una solicitud de Empresa en revisión.")
    await log_action(
        db=db, actor=user, action="company_request.create",
        entity_type="company_request", entity_id=doc["id"],
        details={"company_name": doc["company_name"], "account_email": account_email},
    )
    await _notify_staff_new_request(doc)
    await _publish("company_request_created", {"request_id": doc["id"]}, admin=True)
    return _serialize(doc)


@router.post("/company-signup")
async def company_signup(payload: CompanySignupCreate, request: Request) -> Any:
    """Alta PÚBLICA (sin sesión) de una cuenta Empresa en UN paso: datos +
    documentos KYB. NO crea cuenta — crea una solicitud `pending` que el staff
    revisa en "KYB Empresas". Al aprobarse se crea la cuenta Empresa (activa,
    con el teléfono ya dado por aprobado), se envía la verificación de correo y
    el KYB queda verificado; al verificar el correo la cuenta puede operar."""
    from captcha import verify_captcha_token
    from services.balances import assert_not_defensive

    await verify_captcha_token(payload.captcha_token, request)
    await assert_not_defensive("nuevos registros")

    if payload.password != payload.password_confirm:
        raise HTTPException(status_code=422, detail="Las contraseñas no coinciden.")
    if len(payload.password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise HTTPException(status_code=422, detail="La contraseña es demasiado larga (máximo 72 bytes).")

    account_email = _normalize_email(str(payload.account_email))
    company_phone = normalize_phone(payload.company_phone)
    if payload.password.casefold() == account_email.casefold():
        raise HTTPException(status_code=422, detail="La contraseña no puede ser igual al email.")

    # Bloqueos + unicidad global (se revalida también al aprobar).
    await assert_not_blocked(email=account_email, phone=company_phone)
    if await db.users.find_one({"email": account_email}, {"_id": 0, "user_id": 1}):
        raise HTTPException(status_code=409, detail="Ya existe una cuenta con ese email.")
    if await db.users.find_one({"phone": company_phone}, {"_id": 0, "user_id": 1}):
        raise HTTPException(
            status_code=409,
            detail="Este número de teléfono ya está asociado a otra cuenta.")

    # Una solicitud pendiente por email (lectura previa; el índice único parcial
    # `account_email + status=pending` es la garantía real anti-carrera).
    if await db.company_requests.find_one(
            {"account_email": account_email, "status": "pending"}, {"_id": 0, "id": 1}):
        raise HTTPException(
            status_code=409,
            detail="Ya hay una solicitud de Empresa en revisión para ese email.")

    # Enfriamiento de 7 días tras el último rechazo (por email, sin sesión).
    last_rejected = await db.company_requests.find_one(
        {"account_email": account_email, "status": "rejected"},
        {"_id": 0, "reviewed_at": 1}, sort=[("reviewed_at", -1)])
    if last_rejected and last_rejected.get("reviewed_at"):
        remaining = _cooldown_remaining(last_rejected["reviewed_at"])
        if remaining > 0:
            raise HTTPException(
                status_code=429,
                detail=f"Debes esperar {remaining} día(s) antes de volver a solicitar.")

    # Subir los 2 documentos a almacenamiento (ref /api/files/... servida por el
    # proxy autenticado; el admin puede verlas al revisar el KYB).
    documents = []
    for doc_type, data_url in [("operating_license", payload.operating_license),
                               ("legal_rep_id", payload.legal_rep_id)]:
        try:
            ref = maybe_upload_proof(data_url, folder="kyc")
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[company_signup] upload {doc_type} failed: {e}")
            raise HTTPException(status_code=500, detail=f"No se pudo subir el documento ({doc_type}).")
        if not ref:
            raise HTTPException(status_code=400, detail=f"Documento inválido: {doc_type}.")
        documents.append({"doc_type": doc_type, "ref": ref})

    now = iso(now_utc())
    doc = {
        "id": f"coreq_{uuid.uuid4().hex[:12]}",
        # user_id sintético ÚNICO: no hay cuenta solicitante (alta pública). Evita
        # chocar con el índice único parcial `user_id + status=pending`.
        "user_id": f"anon_{uuid.uuid4().hex[:16]}",
        "requester_anonymous": True,
        "user_email": account_email,
        "user_name": payload.company_name.strip(),
        "company_name": payload.company_name.strip(),
        "account_email": account_email,
        "company_phone": company_phone,
        "tax_id": payload.tax_id.strip(),
        "address": payload.address.strip(),
        "documents": documents,
        "password_hash": _hash_password(payload.password),
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "reviewed_by": None,
        "reviewed_at": None,
        "admin_note": None,
        "new_user_id": None,
    }
    try:
        await db.company_requests.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="Ya hay una solicitud de Empresa en revisión para ese email.")
    await log_action(
        db=db, actor={"user_id": None}, action="company_request.signup",
        entity_type="company_request", entity_id=doc["id"],
        details={"company_name": doc["company_name"], "account_email": account_email})
    await _notify_staff_new_request(doc)
    await _publish("company_request_created", {"request_id": doc["id"]}, admin=True)
    return {"ok": True,
            "message": "Solicitud recibida. Te avisaremos por correo cuando el equipo la revise."}


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


# ============================================================
# A03 — alta Empresa crash-safe: claim → ensure → seal → notify.
# Cada fase es idempotente y reanudable (por reintento del endpoint o por el
# recuperador del scheduler), con identidad ESTABLE `new_user_id` para que el
# insert nunca duplique, incluso si la respuesta de la inserción se pierde.
# ============================================================

def _build_company_user_doc(doc: dict, new_user_id: str, lang: str) -> dict:
    now = iso(now_utc())
    return {
        "user_id": new_user_id,
        "email": _normalize_email(doc["account_email"]),
        "name": doc["company_name"],
        "picture": "",
        "role": "empresa",
        "auth_provider": "password",
        "password_hash": doc["password_hash"],  # copiar el hash — NUNCA re-hashear
        "email_verified": False,
        "verification_token": uuid.uuid4().hex + uuid.uuid4().hex,
        "verification_expires_at": iso(now_utc() + timedelta(hours=24)),
        "vip_balance_usd": 0.0,
        "onboarding_completed": False,
        "phone": normalize_phone(doc["company_phone"]),
        "phone_verified": True,
        # El teléfono va en el formulario y el staff lo da por aprobado al
        # aprobar el KYB → la cuenta nace ACTIVA. El único gate restante es la
        # verificación de correo (el login sigue bloqueado hasta verificar).
        "account_status": "active",
        "under_review_since": None,
        "preferred_language": lang,
        "created_at": now,
        "account_type": "business",
        "company_name": doc["company_name"],
        "tax_id": doc["tax_id"],
        "address": doc["address"],
        # Alta pública/anónima: no hay cuenta personal solicitante → sin padre.
        "parent_user_id": None if doc.get("requester_anonymous") else doc["user_id"],
    }


async def _ensure_company_kyb_verified(doc: dict, acc: dict) -> None:
    """Al aprobar el alta unificada, el KYB queda VERIFICADO automáticamente:
    crea un expediente `kyc_verifications` (kind=company, status=verified) con
    los documentos y datos de la solicitud. Así la cuenta nunca tiene que
    re-hacer el KYB, y el gate de retiro + la insignia "Empresa verificada"
    siguen funcionando (usan el último expediente company). Idempotente."""
    if not doc.get("documents"):
        return  # solicitud heredada sin documentos → no hay KYB que sellar
    existing = await db.kyc_verifications.find_one(
        {"user_id": acc["user_id"], "kind": "company"}, {"_id": 0, "id": 1})
    if existing:
        return
    now = iso(now_utc())
    await db.kyc_verifications.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": acc["user_id"],
        "user_email": acc.get("email", ""),
        "user_name": doc.get("company_name") or acc.get("name", ""),
        "user_phone": acc.get("phone", ""),
        "kind": "company",
        "company_fields": {
            "company_name": doc.get("company_name", ""),
            "fiscal_code": doc.get("tax_id", ""),
            "legal_address": doc.get("address", ""),
        },
        "status": "verified",
        "documents": doc.get("documents", []),
        "risk_score": 0,
        "risk_flags": [],
        "submit_ip": "",
        "submit_user_agent": "",
        "reviewed_by": doc.get("reviewed_by"),
        "reviewed_by_email": None,
        "reviewed_at": now,
        "review_notes": "Verificada junto con el alta de la cuenta Empresa.",
        "rejection_reasons": [],
        "created_at": now,
        "updated_at": now,
    })
    await db.users.update_one(
        {"user_id": acc["user_id"]},
        {"$set": {"kyc_status": "verified", "kyc_verified_at": now}})


async def _complete_company_approval(req_id: str, staff_id: Optional[str]) -> Optional[dict]:
    """FASES 2-4 idempotentes para una solicitud ya reclamada ('approving'):
    (2) asegura la cuenta Empresa por `new_user_id` ESTABLE (upsert → nunca
        duplica, resuelve la inserción de respuesta perdida),
    (3) sella 'approving'→'approved' (CAS) borrando el hash, y
    (4) finaliza avisos una sola vez. Reanudable tras cualquier interrupción."""
    doc = await db.company_requests.find_one({"id": req_id}, {"_id": 0})
    if not doc or doc.get("status") not in ("approving", "approved"):
        return doc  # revertida a pending/rejected por otro camino → nada que hacer
    new_user_id = doc.get("new_user_id")
    if not new_user_id:
        return doc

    # FASE 2 — asegurar la cuenta (idempotente por user_id estable).
    acc = await db.users.find_one({"user_id": new_user_id}, {"_id": 0})
    if not acc:
        account_email = _normalize_email(doc["account_email"])
        company_phone = normalize_phone(doc["company_phone"])
        # Revalidar unicidad EXCLUYENDO nuestra propia cuenta (idempotente).
        clash = await db.users.find_one(
            {"user_id": {"$ne": new_user_id},
             "$or": [{"email": account_email}, {"phone": company_phone}]},
            {"_id": 0, "user_id": 1})
        if clash:
            # No podemos crear → revertir a pending para que el staff corrija/rechace.
            await db.company_requests.update_one(
                {"id": req_id, "status": "approving"},
                {"$set": {"status": "pending", "reviewed_at": None,
                          "reviewed_by": None, "new_user_id": None,
                          "updated_at": iso(now_utc())}})
            raise HTTPException(
                status_code=409,
                detail="El email o teléfono ya está en uso; rechaza o pide corregir la solicitud.")
        if not doc.get("password_hash"):
            raise HTTPException(
                status_code=409,
                detail="La solicitud no tiene credenciales válidas; pide al cliente que la reenvíe.")
        requester = await db.users.find_one(
            {"user_id": doc["user_id"]}, {"_id": 0, "preferred_language": 1})
        lang = (requester or {}).get("preferred_language") or "es"
        user_doc = _build_company_user_doc(doc, new_user_id, lang)
        try:
            await db.users.update_one(
                {"user_id": new_user_id}, {"$setOnInsert": user_doc}, upsert=True)
        except DuplicateKeyError:
            pass  # otro ejecutor la creó entre el find y el upsert → idempotente
        acc = await db.users.find_one({"user_id": new_user_id}, {"_id": 0})

    # KYB auto-verificado (idempotente): el alta unificada ya trae los
    # documentos, así que la cuenta queda verificada sin re-hacer el KYB.
    if acc:
        await _ensure_company_kyb_verified(doc, acc)

    # FASE 3 — sellar 'approving'→'approved' + borrar el hash (CAS idempotente).
    await db.company_requests.update_one(
        {"id": req_id, "status": "approving"},
        {"$set": {"status": "approved", "updated_at": iso(now_utc())},
         "$unset": {"password_hash": ""}})

    # FASE 4 — finalizar avisos exactamente una vez.
    await _finalize_company_approval(req_id, staff_id=staff_id)
    return await db.company_requests.find_one({"id": req_id}, {"_id": 0})


async def _finalize_company_approval(req_id: str, staff_id: Optional[str] = None) -> None:
    """FASE 4 — correo de verificación + cola de verificación de nuevos usuarios
    + aviso al cliente + SSE + auditoría.

    P02 — recuperable y con idempotencia POR CANAL. `notified_at` NO es la
    prueba de reclamo sino la CONFIRMACIÓN final: se sella solo DESPUÉS de que
    todos los canales persistentes se completaron. El reclamo es un LEASE
    (`notify_claimed_at`) que el recuperador puede re-tomar si quedó obsoleto
    (crash entre el reclamo y los envíos), y cada canal se marca en
    `notify_channels` para no reenviarse. Así un proceso interrumpido se
    completa en una pasada posterior sin duplicar avisos ni perder la cola."""
    now = now_utc()
    lease_cutoff = iso(now - timedelta(seconds=120))
    # Reclamo RECUPERABLE (lease): solo si NO está confirmado y no hay lease vivo.
    claim = await db.company_requests.update_one(
        {"id": req_id, "status": "approved", "notified_at": {"$exists": False},
         "$or": [{"notify_claimed_at": {"$exists": False}},
                 {"notify_claimed_at": {"$lt": lease_cutoff}}]},
        {"$set": {"notify_claimed_at": iso(now)}})
    if claim.modified_count != 1:
        return  # ya confirmado, aún no 'approved', o reclamado por otro ejecutor vivo
    doc = await db.company_requests.find_one({"id": req_id}, {"_id": 0})
    acc = await db.users.find_one({"user_id": doc.get("new_user_id")}, {"_id": 0})
    if not acc:
        return  # la cuenta se asegura antes; si falta, el lease expira y se reintenta
    lang = acc.get("preferred_language") or "es"
    done = set(doc.get("notify_channels") or [])

    async def _run_channel(name: str, fn: Callable[[], Awaitable[Any]]) -> None:
        """Ejecuta un canal y lo sella SOLO ante éxito EXPLÍCITO. El canal se
        considera entregado si `fn()` no lanza Y no devuelve `False`. Un `False`
        (p. ej. correo rechazado o entrega parcial al personal) deja el canal
        SIN sellar para que el recuperador lo reintente (patrón outbox)."""
        if name in done:
            return
        try:
            ok = await fn()
        except Exception as e:  # noqa: BLE001
            logger.error(f"[company_requests] notify channel '{name}' failed: {e}")
            return  # NO se marca → el recuperador lo reintenta (outbox)
        if ok is False:
            logger.warning(
                f"[company_requests] notify channel '{name}' incompleto; se reintentará")
            return  # entrega fallida/parcial → no sellar
        await db.company_requests.update_one(
            {"id": req_id}, {"$addToSet": {"notify_channels": name}})
        done.add(name)

    async def _audit() -> None:
        await log_action(
            db=db, actor={"user_id": staff_id or doc.get("reviewed_by")},
            action="company_request.approve", entity_type="company_request",
            entity_id=req_id,
            details={"requester": doc["user_id"], "new_user_id": acc["user_id"],
                     "account_email": acc.get("email")})

    async def _email() -> bool:
        import email_service
        # notify_email_verification devuelve bool: False = envío fallido (p. ej.
        # sin API key o error de Resend). Se comprueba para NO sellar en fallo.
        return bool(email_service.notify_email_verification(
            acc["email"], acc.get("name", ""), acc.get("verification_token", ""), lang=lang))

    # Alta unificada: el teléfono ya va aprobado en el formulario, así que NO hay
    # cola de "verificación de teléfono por staff" → se elimina el canal `staff`.
    is_anon = bool(doc.get("requester_anonymous"))

    await _run_channel("audit", _audit)
    await _run_channel("email", _email)
    # El aviso in-app al solicitante solo aplica cuando hay una cuenta personal
    # solicitante (flujo heredado). En el alta pública/anónima el correo de
    # verificación ES la notificación.
    if not is_anon:
        await _run_channel("client", lambda: _notify_client_decision(doc, approved=True))
    # SSE efímero (barato e idempotente): se publica siempre, no es canal persistente.
    await _publish("company_request_approved", {"request_id": req_id}, user_id=doc["user_id"])
    await _publish("company_request_updated", {"request_id": req_id}, admin=True)

    # CONFIRMACIÓN: solo cuando TODOS los canales persistentes requeridos se completaron.
    required = {"audit", "email"} if is_anon else {"audit", "email", "client"}
    if required.issubset(done):
        await db.company_requests.update_one(
            {"id": req_id}, {"$set": {"notified_at": iso(now_utc())}})


async def recover_company_approvals() -> int:
    """Recuperador (scheduler): completa altas Empresa interrumpidas. (1) las
    'approving' cuyo claim supera el cutoff (crash entre claim e insert/seal) →
    asegura cuenta + sella + finaliza; (2) las 'approved' sin `notified_at` →
    finaliza avisos. Idempotente; el cutoff evita tocar una aprobación en vuelo."""
    cutoff = iso(now_utc() - timedelta(seconds=120))
    healed = 0
    stuck = [r["id"] async for r in db.company_requests.find(
        {"status": "approving", "reviewed_at": {"$lt": cutoff}}, {"_id": 0, "id": 1})]
    for rid in stuck:
        try:
            await _complete_company_approval(rid, staff_id=None)
            healed += 1
        except HTTPException:
            pass  # clash de email/teléfono → revertida a pending; el staff decidirá
        except Exception as e:  # noqa: BLE001
            logger.error(f"[company_requests] recover approving {rid} failed: {e}")
    pend = [r["id"] async for r in db.company_requests.find(
        {"status": "approved", "notified_at": {"$exists": False}}, {"_id": 0, "id": 1})]
    for rid in pend:
        try:
            await _finalize_company_approval(rid)
            healed += 1
        except Exception as e:  # noqa: BLE001
            logger.error(f"[company_requests] recover notify {rid} failed: {e}")
    return healed


async def _dedup_pending_requests() -> None:
    """A04 — colapsa solicitudes `pending` duplicadas por usuario ANTES de crear
    el índice único parcial (si no, su creación fallaría). Conserva la MÁS
    reciente (`created_at`) y elimina las pendientes sobrantes; borrar una
    pending nunca procesada no tiene efectos aguas abajo (no hay cuenta creada)."""
    dupes = db.company_requests.aggregate([
        {"$match": {"status": "pending"}},
        {"$group": {"_id": "$user_id", "ids": {"$addToSet": "$id"}, "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
    ])
    async for grp in dupes:
        rows = await db.company_requests.find(
            {"user_id": grp["_id"], "status": "pending"},
            {"_id": 0, "id": 1, "created_at": 1},
        ).sort("created_at", -1).to_list(length=None)
        keep = rows[0]["id"]  # el más reciente
        drop = [r["id"] for r in rows[1:]]
        if drop:
            await db.company_requests.delete_many({"id": {"$in": drop}})
            logger.warning(
                f"[company_requests] A04 dedup user={grp['_id']} kept={keep} dropped={drop}")


async def ensure_indexes() -> None:
    """A03 — unicidad de identidad para altas idempotentes: `users.user_id`
    único garantiza que un reintento/recuperador concurrente nunca cree una
    segunda cuenta Empresa con el mismo id estable.
    A04 — índice único PARCIAL por `user_id` con `status=pending` garantiza a
    nivel de BD una única solicitud pendiente por usuario (dos POST concurrentes
    ya no pueden crear dos pendientes)."""
    try:
        await db.users.create_index("user_id", unique=True, name="uniq_user_id")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[company_requests] user_id unique index skipped: {e}")
    try:
        await db.company_requests.create_index("id", unique=True, name="uniq_company_request_id")
        await db.company_requests.create_index(
            [("status", 1), ("reviewed_at", 1)], name="company_requests_recovery")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[company_requests] company_requests indexes skipped: {e}")
    try:
        await _dedup_pending_requests()
        await db.company_requests.create_index(
            [("user_id", 1)], unique=True,
            partialFilterExpression={"status": "pending"},
            name="uniq_company_request_pending_user")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[company_requests] pending-unique index skipped: {e}")
    try:
        # Alta pública: una única solicitud pendiente por email de empresa
        # (dos envíos anónimos concurrentes del mismo email ya no crean dos).
        await db.company_requests.create_index(
            [("account_email", 1)], unique=True,
            partialFilterExpression={"status": "pending"},
            name="uniq_company_request_pending_email")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[company_requests] pending-email-unique index skipped: {e}")
    try:
        # A04 — único PARCIAL por `dedup_key`: garantiza a nivel de BD un solo
        # aviso persistente por (solicitud, decisión, destinatario) aunque el
        # recuperador re-ejecute el canal tras un crash entre insert y sellado.
        await db.notifications.create_index(
            "dedup_key", unique=True,
            partialFilterExpression={"dedup_key": {"$exists": True}},
            name="uniq_notification_dedup_key")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[company_requests] notification dedup index skipped: {e}")



@router.post("/admin/company-requests/{req_id}/approve")
async def admin_approve_company_request(req_id: str, request: Request) -> Any:
    """Aprueba una solicitud → crea una cuenta Empresa NUEVA e independiente."""
    staff = await require_permission(request, "company_requests")
    doc = await db.company_requests.find_one({"id": req_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Solicitud de Empresa no encontrada.")
    status = doc.get("status")
    if status == "approving":
        # A03 — aprobación INTERRUMPIDA (claim hecho, cuenta sin sellar):
        # reanuda idempotentemente hasta dejar cuenta creada + estado 'approved'.
        return _serialize(await _complete_company_approval(req_id, staff["user_id"]))
    if status == "approved":
        # Ya resuelta; sana avisos pendientes (sin duplicar) y marca conflicto.
        await _finalize_company_approval(req_id)
        raise HTTPException(status_code=409, detail="La solicitud ya fue procesada.")
    if status != "pending":
        raise HTTPException(status_code=409, detail="La solicitud ya fue procesada.")

    if not doc.get("password_hash"):
        raise HTTPException(
            status_code=409,
            detail="La solicitud no tiene credenciales válidas; pide al cliente que la reenvíe.",
        )

    account_email = _normalize_email(doc["account_email"])
    company_phone = normalize_phone(doc["company_phone"])
    # Revalidar unicidad + bloqueos antes de reclamar (la solicitud pudo quedar
    # pendiente días). La creación real (fase 2) revalida de nuevo EXCLUYENDO la
    # propia cuenta, por si un intento anterior la creó parcialmente.
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

    now = iso(now_utc())
    new_user_id = f"coacct_{uuid.uuid4().hex[:12]}"
    # FASE 1 — CLAIM atómico pending→approving con identidad ESTABLE persistida.
    # El estado definitivo 'approved' NO se sella hasta que la cuenta exista
    # (fase 3), así una interrupción jamás deja 'approved' sin cuenta: queda
    # 'approving' (recuperable por el reintento del endpoint o el scheduler).
    cas = await db.company_requests.update_one(
        {"id": req_id, "status": "pending"},
        {"$set": {"status": "approving", "updated_at": now, "reviewed_at": now,
                  "reviewed_by": staff["user_id"], "admin_note": None,
                  "new_user_id": new_user_id}},
    )
    if cas.modified_count != 1:
        other = await db.company_requests.find_one({"id": req_id}, {"_id": 0, "status": 1})
        if other and other.get("status") == "approving":
            return _serialize(await _complete_company_approval(req_id, staff["user_id"]))
        raise HTTPException(status_code=409, detail="La solicitud ya fue procesada.")

    return _serialize(await _complete_company_approval(req_id, staff["user_id"]))


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
    # A02 — DECISIÓN ATÓMICA: transición CAS pending→rejected (mismo protocolo
    # que approve). Si otro revisor ya APROBÓ (y creó la cuenta Empresa) o
    # rechazó entre nuestra lectura y esta escritura, perdemos la carrera:
    # modified_count=0 → 409 SIN tocar el estado ni notificar éxito. El filtro
    # por id solo (sin status) permitía pisar un 'approved' con cuenta ya creada.
    cas = await db.company_requests.update_one(
        {"id": req_id, "status": "pending"},
        {"$set": {
            "status": "rejected",
            "updated_at": now,
            "reviewed_at": now,
            "reviewed_by": staff["user_id"],
            "admin_note": note,
        }, "$unset": {"password_hash": ""}},
    )
    if cas.modified_count != 1:
        raise HTTPException(status_code=409, detail="La solicitud ya fue procesada.")

    fresh = await db.company_requests.find_one({"id": req_id}, {"_id": 0})
    await log_action(
        db=db, actor=staff, action="company_request.reject",
        entity_type="company_request", entity_id=req_id,
        details={"requester": doc["user_id"], "note": note},
    )
    # Alta pública/anónima: el solicitante no tiene cuenta/campana → se le avisa
    # por correo del rechazo. Flujo heredado (con cuenta solicitante): aviso in-app.
    if doc.get("requester_anonymous"):
        try:
            import email_service
            email_service.notify_company_kyb_rejected(
                _normalize_email(doc.get("account_email", "")),
                doc.get("company_name", ""), note or "", lang="es")
        except Exception as e:  # noqa: BLE001
            logger.error(f"[company_requests] anon reject email failed: {e}")
    else:
        await _notify_client_decision(fresh, approved=False, admin_note=note or "")
    await _publish("company_request_rejected", {"request_id": req_id}, user_id=doc["user_id"])
    await _publish("company_request_updated", {"request_id": req_id}, admin=True)
    return _serialize(fresh)



# ============================================================
# Reenvío de verificación de email de la cuenta Empresa (solicitante)
# ============================================================

@router.post("/company-requests/resend-verification")
async def resend_company_verification(request: Request) -> Any:
    """El SOLICITANTE (cuenta personal) reenvía el correo de verificación de
    SU cuenta Empresa aprobada. Autenticado + acotado por propiedad
    (`parent_user_id`), con enfriamiento de 60s. Regenera el token (invalida el
    anterior) y lo manda al email de la cuenta Empresa."""
    user = await require_user(request)
    doc = await db.company_requests.find_one(
        {"user_id": user["user_id"], "status": "approved"},
        {"_id": 0, "new_user_id": 1},
        sort=[("reviewed_at", -1), ("created_at", -1)],
    )
    if not doc or not doc.get("new_user_id"):
        raise HTTPException(status_code=404, detail="No tienes una cuenta Empresa aprobada.")

    acc = await db.users.find_one({"user_id": doc["new_user_id"]}, {"_id": 0})
    # Cadena de propiedad: la cuenta debe apuntar de vuelta al solicitante.
    if (not acc or acc.get("parent_user_id") != user["user_id"]
            or acc.get("role") != "empresa"):
        raise HTTPException(status_code=404, detail="No tienes una cuenta Empresa aprobada.")

    if acc.get("email_verified"):
        return {"ok": True, "status": "already_verified"}

    last = acc.get("last_resend_at")
    if last:
        try:
            last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
            elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
            if elapsed < RESEND_COOLDOWN_SECONDS:
                wait = int(RESEND_COOLDOWN_SECONDS - elapsed)
                raise HTTPException(
                    status_code=429,
                    detail=f"Espera {wait}s antes de reenviar el correo.",
                )
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001
            pass

    new_token = uuid.uuid4().hex + uuid.uuid4().hex
    await db.users.update_one(
        {"user_id": acc["user_id"]},
        {"$set": {
            "verification_token": new_token,
            "verification_expires_at": iso(now_utc() + timedelta(hours=24)),
            "last_resend_at": iso(now_utc()),
        }},
    )
    try:
        import email_service
        email_service.notify_email_verification(
            acc["email"], acc.get("name", ""), new_token,
            lang=acc.get("preferred_language") or "es",
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"[company_requests] resend verification email failed: {e}")
        raise HTTPException(
            status_code=503,
            detail="No se pudo enviar el correo. Inténtalo más tarde.",
        )
    await log_action(
        db=db, actor=user, action="company_request.resend_verification",
        entity_type="user", entity_id=acc["user_id"],
        details={"account_email": acc.get("email")},
    )
    return {"ok": True, "status": "sent"}
