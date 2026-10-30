"""Empresas de Servicios — Fase 1 (publicación, moderación y descubrimiento).

Una Empresa (rol `empresa`, aislada por `company_id = user_id`) puede publicar
SERVICIOS además de productos, sin crear cuentas nuevas ni migrar su catálogo.

Flujo de publicación: borrador → pendiente → (admin aprueba) publicado; también
pausado o rechazado con motivo. El formulario captura ya la configuración de
CALENDARIO (ventanas de disponibilidad, fechas bloqueadas) y de PAGO (tipo de
precio, anticipo, métodos), que la siguiente fase usará para reservas y cobros.
En esta fase NO se cobra la comisión del 1% (solo se muestra como política).

Endpoints:
  Público
    GET  /services                      catálogo publicado + filtros
    GET  /services/{id}                 ficha pública
    GET  /service-categories            categorías activas
  Empresa (require_company)
    GET    /company/services            mis servicios (todos los estados)
    POST   /company/services            crear (submit→pendiente, else borrador)
    PUT    /company/services/{id}        editar (rechazado→pendiente)
    POST   /company/services/{id}/submit    borrador→pendiente
    POST   /company/services/{id}/pause     publicado→pausado
    POST   /company/services/{id}/unpause   pausado→publicado
    DELETE /company/services/{id}
  Staff (permiso 'products')
    GET  /admin/services?status=
    POST /admin/services/{id}/approve
    POST /admin/services/{id}/reject    {reason}
    GET  /admin/service-categories
    POST /admin/service-categories      {name, slug?, active}
    PUT  /admin/service-categories/{id}
    DELETE /admin/service-categories/{id}
"""
import re
import math
import uuid
import logging
from datetime import date
from typing import Any, Optional, Literal
from zoneinfo import available_timezones

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from db_client import db
from auth_utils import (
    require_company, require_permission,
    now_utc, iso,
)
from audit_log import log_action
from admin_alerts import notify_all_admins
from services.proof_upload import maybe_upload_proof

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Services"])

MAX_SERVICES_PER_COMPANY = 50
MODALITIES = ("local", "domicilio", "remoto", "alquiler")
PRICING_TYPES = ("fixed", "hourly", "daily", "per_person", "quote")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

_DEFAULT_CATEGORIES = [
    ("barberia", "Barbería y peluquería"),
    ("limpieza", "Limpieza"),
    ("alquiler_casa", "Alquiler de casas"),
    ("alquiler_auto", "Alquiler de autos"),
    ("marketing", "Marketing y publicidad"),
    ("juridico", "Servicios jurídicos"),
    ("viajes", "Agencias de viajes"),
    ("mantenimiento", "Mantenimiento"),
    ("eventos", "Eventos y catering"),
    ("otros", "Otros"),
]
_CATEGORIES_SEEDED = False


async def _ensure_categories_seeded() -> None:
    global _CATEGORIES_SEEDED
    if _CATEGORIES_SEEDED:
        return
    try:
        if await db.service_categories.count_documents({}) == 0:
            now = iso(now_utc())
            await db.service_categories.insert_many([
                {"id": str(uuid.uuid4()), "slug": slug, "name": name,
                 "active": True, "created_at": now}
                for slug, name in _DEFAULT_CATEGORIES
            ])
        _CATEGORIES_SEEDED = True
    except Exception as e:  # noqa: BLE001
        logger.error(f"service categories seed failed, will retry: {e}")


async def _publish_services_changed(service_id: str) -> None:
    try:
        from services.live_bus import publish
        await publish("services_changed", {"service_id": service_id})
    except Exception as e:  # noqa: BLE001
        logger.error(f"services_changed publish failed: {e}")


# ============================================================
# Models
# ============================================================

class AvailWindow(BaseModel):
    model_config = ConfigDict(extra="ignore")
    day: int = Field(ge=0, le=6)          # 0=lunes … 6=domingo
    start: str = Field("09:00", max_length=5)
    end: str = Field("17:00", max_length=5)

    @model_validator(mode="after")
    def _check_times(self) -> "AvailWindow":
        if not _TIME_RE.match(self.start) or not _TIME_RE.match(self.end):
            raise ValueError("Horario inválido (use formato HH:MM de 24 h).")
        if self.start >= self.end:
            raise ValueError("La hora de inicio debe ser anterior a la de fin.")
        return self


def _default_payment_methods() -> list[Literal["balance", "cash"]]:
    return ["balance"]


class ServiceCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = Field(..., min_length=2, max_length=120)
    category: str = Field("otros", max_length=60)
    description: str = Field("", max_length=2000)
    images: list[str] = Field(default_factory=list, max_length=8)
    modality: Literal["local", "domicilio", "remoto", "alquiler"] = "local"
    pricing_type: Literal["fixed", "hourly", "daily", "per_person", "quote"] = "fixed"
    price_usdt: float = Field(0, ge=0)
    deposit_type: Literal["none", "percent", "fixed"] = "none"
    deposit_value: float = Field(0, ge=0)
    duration_minutes: int = Field(60, ge=0, le=100000)
    min_notice_hours: int = Field(0, ge=0, le=100000)
    capacity: int = Field(1, ge=1, le=100000)
    buffer_minutes: int = Field(0, ge=0, le=10000)
    coverage_zone: str = Field("", max_length=300)
    requirements: str = Field("", max_length=1000)
    inclusions: str = Field("", max_length=1000)
    exclusions: str = Field("", max_length=1000)
    cancellation_policy: str = Field("", max_length=1000)
    payment_methods: list[Literal["balance", "cash"]] = Field(default_factory=_default_payment_methods)
    availability: list[AvailWindow] = Field(default_factory=list)
    blocked_dates: list[str] = Field(default_factory=list, max_length=366)
    timezone: str = Field("America/Havana", max_length=60)
    submit: bool = True


class ServiceUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: Optional[str] = Field(None, min_length=2, max_length=120)
    category: Optional[str] = Field(None, max_length=60)
    description: Optional[str] = Field(None, max_length=2000)
    images: Optional[list[str]] = Field(None, max_length=8)
    modality: Optional[Literal["local", "domicilio", "remoto", "alquiler"]] = None
    pricing_type: Optional[Literal["fixed", "hourly", "daily", "per_person", "quote"]] = None
    price_usdt: Optional[float] = Field(None, ge=0)
    deposit_type: Optional[Literal["none", "percent", "fixed"]] = None
    deposit_value: Optional[float] = Field(None, ge=0)
    duration_minutes: Optional[int] = Field(None, ge=0, le=100000)
    min_notice_hours: Optional[int] = Field(None, ge=0, le=100000)
    capacity: Optional[int] = Field(None, ge=1, le=100000)
    buffer_minutes: Optional[int] = Field(None, ge=0, le=10000)
    coverage_zone: Optional[str] = Field(None, max_length=300)
    requirements: Optional[str] = Field(None, max_length=1000)
    inclusions: Optional[str] = Field(None, max_length=1000)
    exclusions: Optional[str] = Field(None, max_length=1000)
    cancellation_policy: Optional[str] = Field(None, max_length=1000)
    payment_methods: Optional[list[Literal["balance", "cash"]]] = None
    availability: Optional[list[AvailWindow]] = None
    blocked_dates: Optional[list[str]] = Field(None, max_length=366)
    timezone: Optional[str] = Field(None, max_length=60)


class RejectPayload(BaseModel):
    reason: str = Field("", max_length=300)


class CategoryPayload(BaseModel):
    name: str = Field(..., min_length=2, max_length=60)
    slug: Optional[str] = Field(None, max_length=60)
    active: bool = True


_SAFE_PUBLIC_FIELDS = {"_id": 0}

_VALID_TIMEZONES = available_timezones()


def _validate_price(pricing_type: Optional[str], price: Optional[float]) -> None:
    amount = float(price or 0)
    if not math.isfinite(amount):
        raise HTTPException(status_code=400, detail="El precio no es un número válido.")
    # Validamos el importe YA REDONDEADO a 2 decimales: así un precio como
    # 0.001 (que se guardaría como 0.00) se rechaza en vez de colarse (SV-02).
    if pricing_type != "quote" and round(amount, 2) <= 0:
        raise HTTPException(
            status_code=400,
            detail="Indica un precio mayor que 0 (o usa 'Presupuesto' si el precio depende del caso).")


async def _validate_service_config(
    *,
    pricing_type: Optional[str],
    price: Optional[float],
    deposit_type: Optional[str],
    deposit_value: Optional[float],
    timezone: Optional[str],
    blocked_dates: Optional[list[str]],
    category: Optional[str],
    check_category: bool = True,
) -> None:
    """Valida precio, anticipo, zona horaria, fechas bloqueadas y categoría
    (SV-02/SV-03). Se aplica al crear y editar; el precio además al aprobar."""
    _validate_price(pricing_type, price)
    dep = float(deposit_value or 0)
    if not math.isfinite(dep) or dep < 0:
        raise HTTPException(status_code=400, detail="El anticipo no es válido.")
    if deposit_type == "percent" and round(dep, 2) > 100:
        raise HTTPException(
            status_code=400,
            detail="El anticipo en porcentaje debe estar entre 0 y 100.")
    if deposit_type == "fixed" and pricing_type == "fixed":
        total = round(float(price or 0), 2)
        if total > 0 and round(dep, 2) > total:
            raise HTTPException(
                status_code=400,
                detail="El anticipo fijo no puede superar el precio total del servicio.")
    # SV-R1 — una cadena VACÍA (no omitida) es un valor inválido explícito, no
    # un "sin cambios": hay que rechazarla en vez de saltarse la comprobación.
    tz_val = (timezone or "").strip()
    if not tz_val or tz_val not in _VALID_TIMEZONES:
        raise HTTPException(
            status_code=400,
            detail="Zona horaria no válida. Usa una zona IANA, por ejemplo America/Havana.")
    for d in (blocked_dates or []):
        try:
            date.fromisoformat(str(d))
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400,
                detail=f"Fecha bloqueada no válida: «{d}». Usa el formato AAAA-MM-DD.")
    if check_category:
        cat_slug = (category or "").strip()
        if not cat_slug:
            raise HTTPException(
                status_code=400,
                detail="Selecciona una categoría válida para el servicio.")
        await _ensure_categories_seeded()
        cat = await db.service_categories.find_one({"slug": cat_slug})
        if not cat or not cat.get("active", False):
            raise HTTPException(
                status_code=400,
                detail="La categoría seleccionada no existe o no está activa.")


async def _eligible_owner_ids(owner_ids: list[str]) -> set[str]:
    """Propietarios con habilitación OPERATIVA vigente para ofertar: rol
    `empresa` y cuenta activa (SV-01). Es independiente del badge KYB
    (verificación documental). Una suspensión/bloqueo, cambio de rol o cuenta
    eliminada deja al propietario fuera y oculta su oferta del catálogo; los
    servicios y reservas históricas se conservan (no se borran)."""
    ids = list({o for o in owner_ids if o})
    if not ids:
        return set()
    eligible: set[str] = set()
    cursor = db.users.find(
        {"user_id": {"$in": ids}},
        {"_id": 0, "user_id": 1, "role": 1, "account_status": 1})
    async for u in cursor:
        if u.get("role") == "empresa" and u.get("account_status", "active") == "active":
            eligible.add(u["user_id"])
    return eligible


async def _attach_next_slots(rows: list[dict]) -> None:
    """Fase 2 — añade `next_slot` (próximo turno libre) a cada ficha para que
    el cliente vea de un vistazo cuándo puede reservar. Fallo aislado: una
    ficha sin horario o con error simplemente queda sin `next_slot`."""
    try:
        from services.booking_slots import next_free_slot
    except Exception as e:  # noqa: BLE001
        logger.error(f"next_slot import failed: {e}")
        return
    for r in rows:
        if not (r.get("availability") or []):
            continue
        try:
            r["next_slot"] = await next_free_slot(r)
        except Exception as e:  # noqa: BLE001
            logger.error(f"next_slot calc failed for {r.get('id')}: {e}")


def _upload_images(images: list[str]) -> list[str]:
    out: list[str] = []
    for img in (images or [])[:8]:
        if not img:
            continue
        uploaded = maybe_upload_proof(img, "services") or ""
        if uploaded:
            out.append(uploaded)
    return out


# ============================================================
# Público
# ============================================================

@router.get("/service-categories")
async def public_categories() -> Any:
    await _ensure_categories_seeded()
    return await db.service_categories.find(
        {"active": True}, {"_id": 0}).sort("name", 1).to_list(200)


@router.get("/services")
async def list_services(
    request: Request,
    category: Optional[str] = None,
    modality: Optional[str] = None,
    q: Optional[str] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    zone: Optional[str] = None,
) -> Any:
    query: dict = {"status": "published", "is_active": True}
    if category:
        query["category"] = category
    if modality in MODALITIES:
        query["modality"] = modality
    if zone:
        query["coverage_zone"] = {"$regex": re.escape(zone), "$options": "i"}
    price_q: dict = {}
    if price_min is not None:
        price_q["$gte"] = float(price_min)
    if price_max is not None:
        price_q["$lte"] = float(price_max)
    if price_q:
        query["price_usdt"] = price_q
    if q:
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"title": rx}, {"description": rx}, {"coverage_zone": rx}]
    rows = await db.services.find(query, _SAFE_PUBLIC_FIELDS) \
        .sort("created_at", -1).to_list(500)
    # SV-01 — solo mostramos ofertas de propietarios habilitados (rol empresa
    # + cuenta activa). La suspensión oculta la oferta sin borrar el servicio.
    eligible = await _eligible_owner_ids([r.get("company_id") for r in rows])
    rows = [r for r in rows if r.get("company_id") in eligible]
    try:
        from services.user_verification import verified_company_owner_ids
        verified = await verified_company_owner_ids(
            db, [r.get("company_id") for r in rows if r.get("company_id")])
        for r in rows:
            r["owner_verified"] = bool(r.get("company_id")) and r["company_id"] in verified
    except Exception as e:  # noqa: BLE001
        logger.error(f"service verified-badge failed: {e}")
    await _attach_next_slots(rows)
    return rows


@router.get("/services/{service_id}")
async def service_detail(service_id: str) -> Any:
    doc = await db.services.find_one(
        {"id": service_id, "status": "published", "is_active": True},
        _SAFE_PUBLIC_FIELDS)
    if not doc:
        raise HTTPException(status_code=404, detail="Servicio no disponible.")
    # SV-01 — oculta la ficha si el propietario ya no está habilitado.
    eligible = await _eligible_owner_ids([doc.get("company_id")])
    if doc.get("company_id") not in eligible:
        raise HTTPException(status_code=404, detail="Servicio no disponible.")
    try:
        from services.user_verification import verified_company_owner_ids
        verified = await verified_company_owner_ids(db, [doc.get("company_id")])
        doc["owner_verified"] = bool(doc.get("company_id")) and doc["company_id"] in verified
    except Exception as e:  # noqa: BLE001
        logger.error(f"service detail badge failed: {e}")
    await _attach_next_slots([doc])
    return doc


# ============================================================
# Empresa (self-service)
# ============================================================

async def _owned_service_or_404(sid: str, company_id: str) -> dict:
    doc = await db.services.find_one(
        {"id": sid, "company_id": company_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    return doc


@router.get("/company/services")
async def list_my_services(request: Request) -> Any:
    user = await require_company(request)
    return await db.services.find(
        {"company_id": user["user_id"]}, {"_id": 0}) \
        .sort("created_at", -1).to_list(300)


@router.post("/company/services")
async def create_my_service(payload: ServiceCreate, request: Request) -> Any:
    user = await require_company(request)
    count = await db.services.count_documents({"company_id": user["user_id"]})
    if count >= MAX_SERVICES_PER_COMPANY:
        raise HTTPException(
            status_code=400,
            detail=f"Límite de {MAX_SERVICES_PER_COMPANY} servicios alcanzado")
    await _validate_service_config(
        pricing_type=payload.pricing_type, price=payload.price_usdt,
        deposit_type=payload.deposit_type, deposit_value=payload.deposit_value,
        timezone=payload.timezone, blocked_dates=payload.blocked_dates,
        category=(payload.category.strip() or "otros"))
    now = iso(now_utc())
    status = "pending" if payload.submit else "draft"
    doc = {
        "id": str(uuid.uuid4()),
        "company_id": user["user_id"],
        "owner_name": user.get("name", ""),
        "title": payload.title.strip(),
        "category": payload.category.strip() or "otros",
        "description": payload.description.strip(),
        "images": _upload_images(payload.images),
        "modality": payload.modality,
        "pricing_type": payload.pricing_type,
        "price_usdt": round(float(payload.price_usdt), 2),
        "deposit_type": payload.deposit_type,
        "deposit_value": round(float(payload.deposit_value), 2),
        "duration_minutes": payload.duration_minutes,
        "min_notice_hours": payload.min_notice_hours,
        "capacity": payload.capacity,
        "buffer_minutes": payload.buffer_minutes,
        "coverage_zone": payload.coverage_zone.strip(),
        "requirements": payload.requirements.strip(),
        "inclusions": payload.inclusions.strip(),
        "exclusions": payload.exclusions.strip(),
        "cancellation_policy": payload.cancellation_policy.strip(),
        "payment_methods": payload.payment_methods or ["balance"],
        "availability": [w.model_dump() for w in payload.availability],
        "blocked_dates": payload.blocked_dates,
        "timezone": payload.timezone,
        "status": status,
        "rejection_reason": "",
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "approved_at": "",
    }
    await db.services.insert_one(doc)
    # "Cualquier empresa aprobada se activa sola": al publicar su primer
    # servicio la empresa queda marcada como que ofrece servicios.
    if not user.get("offers_services"):
        await db.users.update_one(
            {"user_id": user["user_id"]}, {"$set": {"offers_services": True}})
    if status == "pending":
        try:
            await notify_all_admins(
                db, title="Nuevo servicio Empresa por aprobar",
                body=f"{user.get('name','')} envió «{doc['title']}» a revisión.",
                url_path="/admin/products")
        except Exception as e:  # noqa: BLE001
            logger.error(f"service notify failed: {e}")
    doc.pop("_id", None)
    return doc


@router.put("/company/services/{service_id}")
async def update_my_service(service_id: str, payload: ServiceUpdate,
                            request: Request) -> Any:
    user = await require_company(request)
    doc = await _owned_service_or_404(service_id, user["user_id"])
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "images" in updates:
        updates["images"] = _upload_images(updates["images"])
    if "availability" in updates:
        updates["availability"] = [
            w if isinstance(w, dict) else w.model_dump()
            for w in updates["availability"]]
    if "price_usdt" in updates:
        updates["price_usdt"] = round(float(updates["price_usdt"]), 2)
    if "deposit_value" in updates:
        updates["deposit_value"] = round(float(updates["deposit_value"]), 2)
    for s in ("title", "description", "coverage_zone", "requirements",
              "inclusions", "exclusions", "cancellation_policy", "category"):
        if s in updates and isinstance(updates[s], str):
            updates[s] = updates[s].strip()
    await _validate_service_config(
        pricing_type=updates.get("pricing_type", doc.get("pricing_type")),
        price=updates.get("price_usdt", doc.get("price_usdt")),
        deposit_type=updates.get("deposit_type", doc.get("deposit_type")),
        deposit_value=updates.get("deposit_value", doc.get("deposit_value")),
        timezone=updates.get("timezone", doc.get("timezone")),
        blocked_dates=updates.get("blocked_dates", doc.get("blocked_dates")),
        category=updates.get("category", doc.get("category")),
        check_category="category" in updates)
    if not updates:
        return doc
    # Un servicio rechazado vuelve a la cola al corregirlo.
    resubmitted = doc.get("status") == "rejected"
    if resubmitted:
        updates["status"] = "pending"
        updates["rejection_reason"] = ""
    updates["updated_at"] = iso(now_utc())
    await db.services.update_one(
        {"id": service_id, "company_id": user["user_id"]}, {"$set": updates})
    if resubmitted:
        try:
            await notify_all_admins(
                db, title="Servicio Empresa re-enviado",
                body=f"{user.get('name','')} corrigió «{doc['title']}» y espera aprobación.",
                url_path="/admin/products")
        except Exception as e:  # noqa: BLE001
            logger.error(f"service resubmit notify failed: {e}")
    await _publish_services_changed(service_id)
    return await db.services.find_one(
        {"id": service_id, "company_id": user["user_id"]}, {"_id": 0})


@router.post("/company/services/{service_id}/submit")
async def submit_my_service(service_id: str, request: Request) -> Any:
    user = await require_company(request)
    doc = await _owned_service_or_404(service_id, user["user_id"])
    if doc.get("status") not in ("draft", "rejected"):
        raise HTTPException(status_code=400,
                            detail="Solo puedes enviar borradores o servicios rechazados.")
    await _validate_service_config(
        pricing_type=doc.get("pricing_type"), price=doc.get("price_usdt"),
        deposit_type=doc.get("deposit_type"), deposit_value=doc.get("deposit_value"),
        timezone=doc.get("timezone"), blocked_dates=doc.get("blocked_dates"),
        category=doc.get("category"), check_category=True)
    await db.services.update_one(
        {"id": service_id, "company_id": user["user_id"]},
        {"$set": {"status": "pending", "rejection_reason": "",
                  "updated_at": iso(now_utc())}})
    try:
        await notify_all_admins(
            db, title="Servicio Empresa por aprobar",
            body=f"{user.get('name','')} envió «{doc['title']}» a revisión.",
            url_path="/admin/products")
    except Exception as e:  # noqa: BLE001
        logger.error(f"service submit notify failed: {e}")
    return await db.services.find_one(
        {"id": service_id, "company_id": user["user_id"]}, {"_id": 0})


@router.post("/company/services/{service_id}/pause")
async def pause_my_service(service_id: str, request: Request) -> Any:
    user = await require_company(request)
    doc = await _owned_service_or_404(service_id, user["user_id"])
    if doc.get("status") != "published":
        raise HTTPException(status_code=400,
                            detail="Solo puedes pausar servicios publicados.")
    await db.services.update_one(
        {"id": service_id, "company_id": user["user_id"]},
        {"$set": {"is_active": False, "updated_at": iso(now_utc())}})
    await _publish_services_changed(service_id)
    return await db.services.find_one(
        {"id": service_id, "company_id": user["user_id"]}, {"_id": 0})


@router.post("/company/services/{service_id}/unpause")
async def unpause_my_service(service_id: str, request: Request) -> Any:
    user = await require_company(request)
    doc = await _owned_service_or_404(service_id, user["user_id"])
    if doc.get("status") != "published":
        raise HTTPException(status_code=400,
                            detail="Solo puedes reactivar servicios publicados.")
    await db.services.update_one(
        {"id": service_id, "company_id": user["user_id"]},
        {"$set": {"is_active": True, "updated_at": iso(now_utc())}})
    await _publish_services_changed(service_id)
    return await db.services.find_one(
        {"id": service_id, "company_id": user["user_id"]}, {"_id": 0})


@router.delete("/company/services/{service_id}")
async def delete_my_service(service_id: str, request: Request) -> Any:
    user = await require_company(request)
    await _owned_service_or_404(service_id, user["user_id"])
    await db.services.delete_one(
        {"id": service_id, "company_id": user["user_id"]})
    await _publish_services_changed(service_id)
    return {"ok": True}


# ============================================================
# Staff (moderación) — permiso 'products'
# ============================================================

async def _service_or_404(sid: str) -> dict:
    doc = await db.services.find_one({"id": sid}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    return doc


async def _notify_owner(doc: dict, *, ntype: str, title: str, message: str) -> None:
    try:
        from routes.notifications import _insert_notification
        await _insert_notification(
            recipient_user_id=doc["company_id"], type=ntype, title=title,
            message=message, data={"service_id": doc["id"]})
    except Exception as e:  # noqa: BLE001
        logger.error(f"service owner notify failed: {e}")


@router.get("/admin/services")
async def admin_list_services(request: Request, status: Optional[str] = None) -> Any:
    await require_permission(request, "products")
    q: dict = {}
    if status in ("draft", "pending", "published", "rejected"):
        q["status"] = status
    return await db.services.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)


@router.post("/admin/services/{service_id}/approve")
async def admin_approve_service(service_id: str, request: Request) -> Any:
    actor = await require_permission(request, "products")
    doc = await _service_or_404(service_id)
    if doc.get("status") not in ("pending", "rejected"):
        raise HTTPException(
            status_code=400,
            detail="Solo puedes aprobar servicios enviados a revisión (pendientes o rechazados).")
    # SV-R2 — revalidamos TODA la configuración almacenada (no solo el precio)
    # sobre la revisión EXACTA que se va a publicar: un registro creado antes
    # de las correcciones (anticipo 250 %, zona o categoría inválida) no debe
    # publicarse sin corregirse. Si falla, el admin lo devuelve a corrección.
    await _validate_service_config(
        pricing_type=doc.get("pricing_type"), price=doc.get("price_usdt"),
        deposit_type=doc.get("deposit_type"), deposit_value=doc.get("deposit_value"),
        timezone=doc.get("timezone"), blocked_dates=doc.get("blocked_dates"),
        category=doc.get("category"), check_category=True)
    # Publicamos SOLO la revisión que acabamos de validar: si una edición
    # concurrente cambió el documento (otro `updated_at`), abortamos para no
    # publicar campos sin revisar; el admin reintenta sobre la nueva revisión.
    res = await db.services.update_one(
        {"id": service_id, "status": doc.get("status"),
         "updated_at": doc.get("updated_at")},
        {"$set": {"status": "published", "rejection_reason": "",
                  "is_active": True, "approved_at": iso(now_utc()),
                  "updated_at": iso(now_utc())}})
    if res.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail="El servicio cambió mientras lo revisabas. Vuelve a abrirlo y apruébalo de nuevo.")
    await log_action(db, actor, "service.approve", "service", service_id,
                     summary=f"Servicio aprobado: {doc['title']} ({doc.get('owner_name','')})")
    await _notify_owner(
        doc, ntype="service_approved", title="Servicio aprobado",
        message=f"Tu servicio «{doc['title']}» ya está publicado en el mercado.")
    await _publish_services_changed(service_id)
    return await db.services.find_one({"id": service_id}, {"_id": 0})


@router.post("/admin/services/{service_id}/reject")
async def admin_reject_service(service_id: str, payload: RejectPayload,
                               request: Request) -> Any:
    actor = await require_permission(request, "products")
    doc = await _service_or_404(service_id)
    reason = payload.reason.strip()
    await db.services.update_one(
        {"id": service_id},
        {"$set": {"status": "rejected", "rejection_reason": reason,
                  "updated_at": iso(now_utc())}})
    await log_action(db, actor, "service.reject", "service", service_id,
                     summary=f"Servicio rechazado: {doc['title']}",
                     details={"reason": reason})
    await _notify_owner(
        doc, ntype="service_rejected", title="Servicio rechazado",
        message=(f"Tu servicio «{doc['title']}» fue rechazado."
                 + (f" Motivo: {reason}" if reason else "")
                 + " Puedes editarlo y se re-enviará a revisión."))
    await _publish_services_changed(service_id)
    return await db.services.find_one({"id": service_id}, {"_id": 0})


# ============================================================
# Staff — categorías de servicios
# ============================================================

@router.get("/admin/service-categories")
async def admin_list_categories(request: Request) -> Any:
    await require_permission(request, "products")
    await _ensure_categories_seeded()
    return await db.service_categories.find({}, {"_id": 0}).sort("name", 1).to_list(200)


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return s or uuid.uuid4().hex[:8]


@router.post("/admin/service-categories")
async def admin_create_category(payload: CategoryPayload, request: Request) -> Any:
    actor = await require_permission(request, "products")
    slug = _slugify(payload.slug or payload.name)
    if await db.service_categories.find_one({"slug": slug}):
        raise HTTPException(status_code=400, detail="Ya existe una categoría con ese identificador.")
    doc = {"id": str(uuid.uuid4()), "slug": slug, "name": payload.name.strip(),
           "active": payload.active, "created_at": iso(now_utc())}
    await db.service_categories.insert_one(doc)
    await log_action(db, actor, "service_category.create", "service_category",
                     doc["id"], summary=f"Categoría de servicio creada: {doc['name']}")
    doc.pop("_id", None)
    return doc


@router.put("/admin/service-categories/{cat_id}")
async def admin_update_category(cat_id: str, payload: CategoryPayload,
                                request: Request) -> Any:
    actor = await require_permission(request, "products")
    existing = await db.service_categories.find_one({"id": cat_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    await db.service_categories.update_one(
        {"id": cat_id},
        {"$set": {"name": payload.name.strip(), "active": payload.active}})
    await log_action(db, actor, "service_category.update", "service_category",
                     cat_id, summary=f"Categoría de servicio actualizada: {payload.name}")
    return await db.service_categories.find_one({"id": cat_id}, {"_id": 0})


@router.delete("/admin/service-categories/{cat_id}")
async def admin_delete_category(cat_id: str, request: Request) -> Any:
    actor = await require_permission(request, "products")
    existing = await db.service_categories.find_one({"id": cat_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    in_use = await db.services.count_documents({"category": existing["slug"]})
    if in_use > 0:
        # No borramos categorías en uso: las desactivamos para no romper fichas.
        await db.service_categories.update_one(
            {"id": cat_id}, {"$set": {"active": False}})
        return {"ok": True, "deactivated": True, "in_use": in_use}
    await db.service_categories.delete_one({"id": cat_id})
    await log_action(db, actor, "service_category.delete", "service_category",
                     cat_id, summary=f"Categoría de servicio eliminada: {existing['name']}")
    return {"ok": True, "deactivated": False}
