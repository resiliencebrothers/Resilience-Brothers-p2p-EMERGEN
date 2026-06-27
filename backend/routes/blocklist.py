"""Blocklist router — iter30. Extracted from server.py.

Endpoints:
- GET    /admin/blocked-contacts
- POST   /admin/blocked-contacts
- DELETE /admin/blocked-contacts/{contact_id}
- POST   /admin/blocked-contacts/bulk-import
- POST   /admin/users/{user_id}/verify-phone
- POST   /admin/users/{user_id}/reject-phone

Dependencies imported lazily from server.py (only inside endpoints) to avoid
circular imports: `_enforce_totp_step_up`. Everything else is self-contained
or pulled from auth_utils / db_client / audit_log / routes.notifications.
"""
import re
import uuid
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from db_client import db
from auth_utils import require_staff, normalize_phone, now_utc, iso
from audit_log import log_action
from routes.notifications import (
    notify_user_phone_verified,
    notify_user_phone_rejected,
)


logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================
# Permission helper — admin OR staff with can_manage_blocklist=True
# ============================================================

async def _assert_can_manage_blocklist(actor: dict):
    if actor.get("role") == "admin":
        return
    if actor.get("role") == "employee" and actor.get("can_manage_blocklist"):
        return
    raise HTTPException(
        status_code=403,
        detail="No tienes permiso para gestionar la lista de bloqueos. Pídeselo a un administrador.",
    )


# ============================================================
# Models
# ============================================================

class BlockedContactPayload(BaseModel):
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[EmailStr] = None
    name: Optional[str] = Field(None, max_length=120)
    reason: str = Field(..., min_length=3, max_length=500)
    notes: Optional[str] = Field(None, max_length=2000)


class BulkImportPayload(BaseModel):
    text: str = Field(..., min_length=1, max_length=200_000)


class RejectPhonePayload(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)
    notes: Optional[str] = Field(None, max_length=2000)
    totp_code: Optional[str] = Field(None, max_length=11)


# ============================================================
# CRUD: list / add / remove
# ============================================================

@router.get("/admin/blocked-contacts")
async def list_blocked_contacts(request: Request, q: Optional[str] = None,
                                  limit: int = 100, skip: int = 0):
    actor = await require_staff(request)
    await _assert_can_manage_blocklist(actor)
    query: dict = {}
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        query = {"$or": [{"phone": rx}, {"email": rx}, {"name": rx},
                          {"reason": rx}, {"notes": rx}]}
    total = await db.blocked_contacts.count_documents(query)
    cursor = db.blocked_contacts.find(query, {"_id": 0}) \
        .sort("created_at", -1).skip(skip).limit(limit)
    items = await cursor.to_list(length=limit)
    return {"items": items, "total": total}


@router.post("/admin/blocked-contacts")
async def add_blocked_contact(payload: BlockedContactPayload, request: Request):
    actor = await require_staff(request)
    await _assert_can_manage_blocklist(actor)
    phone = normalize_phone(payload.phone) if payload.phone else None
    email = payload.email.lower().strip() if payload.email else None
    if not phone and not email:
        raise HTTPException(status_code=422, detail="Debes proporcionar teléfono y/o email")
    or_clauses = []
    if phone:
        or_clauses.append({"phone": phone})
    if email:
        or_clauses.append({"email": email})
    if await db.blocked_contacts.find_one({"$or": or_clauses}, {"_id": 0}):
        raise HTTPException(status_code=409, detail="Este contacto ya está bloqueado")
    doc = {
        "id": uuid.uuid4().hex,
        "phone": phone,
        "email": email,
        "name": (payload.name or "").strip() or None,
        "reason": payload.reason.strip(),
        "notes": (payload.notes or "").strip(),
        "created_at": iso(now_utc()),
        "created_by": actor["user_id"],
        "created_by_email": actor.get("email", ""),
    }
    await db.blocked_contacts.insert_one(doc)
    await log_action(
        db, actor, "blocked_contact.add", "blocked_contact", doc["id"],
        summary=f"Bloqueó contacto (phone={phone or '-'}, email={email or '-'})",
        details={"phone": phone, "email": email, "reason": payload.reason},
    )
    doc.pop("_id", None)
    return doc


@router.delete("/admin/blocked-contacts/{contact_id}")
async def remove_blocked_contact(contact_id: str, request: Request):
    actor = await require_staff(request)
    await _assert_can_manage_blocklist(actor)
    target = await db.blocked_contacts.find_one({"id": contact_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Contacto bloqueado no encontrado")
    await db.blocked_contacts.delete_one({"id": contact_id})
    await log_action(
        db, actor, "blocked_contact.remove", "blocked_contact", contact_id,
        summary=f"Desbloqueó contacto (phone={target.get('phone') or '-'}, email={target.get('email') or '-'})",
        details=target,
    )
    return {"ok": True}


# ============================================================
# Bulk import from WhatsApp chat
# ============================================================

PHONE_DETECT_RE = re.compile(r"\+[1-9][\d\-\s\(\)\.]{7,18}")


def _parse_whatsapp_blocklist(text: str):
    """Parse a WhatsApp-style block list into [{phone, name, reason}].
    See server.py original docstring + tests for full spec."""
    entries = []
    blocks = re.split(r"\n\s*\n", text.strip())
    for raw_block in blocks:
        lines = [ln.strip() for ln in raw_block.splitlines() if ln.strip()]
        if not lines:
            continue
        phones, name, reason_lines = [], None, []
        for ln in lines:
            phone_matches = PHONE_DETECT_RE.findall(ln)
            if phone_matches:
                cleaned = re.sub(r"[\s\-\(\)\.]", "", phone_matches[0])
                phones.append(cleaned)
                continue
            if re.fullmatch(r"[\W_]+", ln):
                continue
            if name is None:
                name = ln.lstrip("📌•·-—*").strip()
            else:
                reason_lines.append(ln.lstrip("📌•·-—*").strip())
        if not phones:
            continue
        reason = "\n".join(reason_lines).strip() or (name or "Importado de lista")
        for p in phones:
            entries.append({"phone": p, "name": name, "reason": reason})
    return entries


@router.post("/admin/blocked-contacts/bulk-import")
async def bulk_import_blocked_contacts(payload: BulkImportPayload, request: Request):
    actor = await require_staff(request)
    await _assert_can_manage_blocklist(actor)
    parsed = _parse_whatsapp_blocklist(payload.text)
    imported, skipped_duplicates, invalid = [], [], []
    for entry in parsed:
        raw_phone = entry["phone"]
        try:
            phone = normalize_phone(raw_phone)
        except HTTPException:
            invalid.append({"phone": raw_phone, "reason": "Formato de teléfono inválido"})
            continue
        if await db.blocked_contacts.find_one({"phone": phone}, {"_id": 0}):
            skipped_duplicates.append(phone)
            continue
        doc = {
            "id": uuid.uuid4().hex,
            "phone": phone,
            "email": None,
            "name": entry.get("name"),
            "reason": entry.get("reason") or "Importado de lista",
            "notes": "",
            "created_at": iso(now_utc()),
            "created_by": actor["user_id"],
            "created_by_email": actor.get("email", ""),
            "source": "bulk_import",
        }
        await db.blocked_contacts.insert_one(doc)
        imported.append(phone)
    affected_users = 0
    if imported:
        res = await db.users.update_many(
            {"phone": {"$in": imported}, "role": {"$in": ["normal", "vip"]}},
            {"$set": {"account_status": "under_review", "phone_verified": False}},
        )
        affected_users = res.modified_count
    await log_action(
        db, actor, "blocked_contact.bulk_import", "blocked_contact", "bulk",
        summary=f"Importó {len(imported)} contactos bloqueados "
                f"(saltó {len(skipped_duplicates)} duplicados, "
                f"{len(invalid)} inválidos, {affected_users} cuentas activas pasaron a revisión)",
        details={"imported_count": len(imported),
                 "skipped_count": len(skipped_duplicates),
                 "invalid_count": len(invalid),
                 "affected_active_accounts": affected_users},
    )
    return {
        "ok": True,
        "imported": imported,
        "imported_count": len(imported),
        "skipped_duplicates": skipped_duplicates,
        "skipped_count": len(skipped_duplicates),
        "invalid": invalid,
        "invalid_count": len(invalid),
        "affected_active_accounts": affected_users,
    }


# ============================================================
# Per-user verify / reject phone
# ============================================================

@router.post("/admin/users/{user_id}/verify-phone")
async def admin_verify_user_phone(user_id: str, request: Request):
    """Mark a user's phone as verified + move account to active. Requires
    can_manage_blocklist + TOTP step-up. Refuses if phone is on the blocklist."""
    requester = await require_staff(request)
    await _assert_can_manage_blocklist(requester)
    payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    # Lazy import: _enforce_totp_step_up lives in server.py and would create a
    # circular import at module load if imported at the top.
    from server import _enforce_totp_step_up
    await _enforce_totp_step_up(requester, payload.get("totp_code"), action_label="verificar teléfono manualmente")
    target = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if not target.get("phone"):
        raise HTTPException(status_code=400, detail="El usuario aún no ha proporcionado un teléfono")
    blocked = await db.blocked_contacts.find_one({"phone": target["phone"]}, {"_id": 0})
    if blocked:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PHONE_IS_BLOCKED",
                "message": f"Este número está en la lista de bloqueados (motivo: {blocked.get('reason', 'sin motivo')}). No se puede verificar.",
                "blocked_entry": blocked,
            },
        )
    if target.get("phone_verified") and target.get("account_status") == "active":
        return {"ok": True, "already_verified": True, "user": target}
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"phone_verified": True, "account_status": "active"}},
    )
    fresh = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    try:
        await notify_user_phone_verified(fresh)
    except Exception as e:
        logger.error(f"verify-phone notify failed: {e}")
    await log_action(
        db, requester, "user.verify_phone_manual", "user", user_id,
        summary=f"Teléfono verificado manualmente para {target.get('email','')} ({target.get('phone')})",
        details={"email": target.get("email"), "phone": target.get("phone")},
    )
    return {"ok": True, "already_verified": False, "user": fresh}


@router.post("/admin/users/{user_id}/reject-phone")
async def admin_reject_user_phone(user_id: str, payload: RejectPhonePayload, request: Request):
    """Staff rejects a user's phone (scammer detected). Adds the number to the
    blocklist and keeps the user under_review. Requires can_manage_blocklist + TOTP."""
    requester = await require_staff(request)
    await _assert_can_manage_blocklist(requester)
    from server import _enforce_totp_step_up
    await _enforce_totp_step_up(requester, payload.totp_code, action_label="rechazar teléfono y bloquear")
    target = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    phone = target.get("phone")
    if not phone:
        raise HTTPException(status_code=400, detail="El usuario aún no ha proporcionado un teléfono")
    existing = await db.blocked_contacts.find_one({"phone": phone}, {"_id": 0})
    if not existing:
        doc = {
            "id": uuid.uuid4().hex,
            "phone": phone,
            "email": target.get("email"),
            "name": target.get("name"),
            "reason": payload.reason.strip(),
            "notes": (payload.notes or "").strip(),
            "created_at": iso(now_utc()),
            "created_by": requester["user_id"],
            "created_by_email": requester.get("email", ""),
            "source": "phone_reject",
        }
        await db.blocked_contacts.insert_one(doc)
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"phone_verified": False, "account_status": "under_review"}},
    )
    fresh = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    try:
        await notify_user_phone_rejected(fresh, payload.reason.strip())
    except Exception as e:
        logger.error(f"reject-phone notify failed: {e}")
    await log_action(
        db, requester, "user.reject_phone", "user", user_id,
        summary=f"Rechazó teléfono y bloqueó a {target.get('email','')} ({phone})",
        details={"phone": phone, "reason": payload.reason},
    )
    return {"ok": True, "user": fresh}
