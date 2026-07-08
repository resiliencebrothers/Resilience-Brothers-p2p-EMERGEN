"""KYC verification routes — iter52.

Client-facing:
- POST /api/kyc/submit — client uploads 3 documents (id_front, id_back, selfie)
- GET  /api/kyc/my-status — client polls their verification status

Admin/staff:
- GET  /api/admin/kyc/queue — filtered list of verifications
- GET  /api/admin/kyc/{id} — full detail incl. documents + risk flags
- POST /api/admin/kyc/{id}/approve — mark verified
- POST /api/admin/kyc/{id}/reject — mark rejected with reasons
- POST /api/admin/kyc/{id}/request-more-info — ask user for better docs
- GET  /api/admin/kyc/funnel — dashboard stats

Documents are uploaded as base64 data URLs (same convention as
`services/proof_upload.py`) — the helper handles size limits, R2 upload, and
returns a `/api/files/...` reference we store on the verification doc.
"""
import logging
from typing import Any, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from db_client import db
from auth_utils import require_user, require_permission
from services import kyc as kyc_service
from services.proof_upload import maybe_upload_proof
from services.security_events import _client_ip

logger = logging.getLogger(__name__)
router = APIRouter(tags=["KYC"])


# ============================================================
# Payload models
# ============================================================

class _KYCSubmitPayload(BaseModel):
    id_front: str = Field(..., description="base64 data URL of ID front side")
    id_back: str = Field(..., description="base64 data URL of ID back side")
    selfie: str = Field(..., description="base64 selfie holding the ID")

    @field_validator("id_front", "id_back", "selfie")
    @classmethod
    def _must_be_data_url(cls, v: str) -> str:
        if not v or not v.startswith("data:image/"):
            raise ValueError("Debe ser una imagen en formato data:image/... (base64).")
        return v


class _KYCRejectPayload(BaseModel):
    reasons: List[str] = Field(default_factory=list)
    notes: str = ""


class _KYCApprovePayload(BaseModel):
    notes: str = ""


class _KYCMoreInfoPayload(BaseModel):
    notes: str = Field(..., min_length=5, description="Explica qué falta")


# ============================================================
# CLIENT endpoints
# ============================================================

@router.post("/kyc/submit")
async def submit_kyc(payload: _KYCSubmitPayload, request: Request) -> Any:
    """Client submits ID front + back + selfie for verification. Only one
    active (pending / verified) verification per user."""
    user = await require_user(request)

    # Upload the 3 base64 blobs to R2 (or keep base64 if storage disabled).
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")

    documents = []
    for doc_type, data_url in [
        ("id_front", payload.id_front),
        ("id_back", payload.id_back),
        ("selfie", payload.selfie),
    ]:
        try:
            ref = maybe_upload_proof(data_url, folder="kyc")
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception(f"KYC {doc_type} upload failed for user {user['user_id']}: {e}")
            raise HTTPException(500, detail=f"No se pudo subir el documento ({doc_type}).")
        if not ref:
            raise HTTPException(400, detail=f"Documento inválido: {doc_type}.")
        documents.append({"doc_type": doc_type, "ref": ref})

    try:
        v = await kyc_service.submit_verification(db, user, documents, ip, ua)
    except ValueError as e:
        code = str(e)
        if code.startswith("already_active_verification:"):
            status = code.split(":", 1)[1]
            raise HTTPException(
                409,
                detail=(
                    f"Ya tienes una verificación {status}. Espera la respuesta del equipo antes de enviar otra."
                ),
            )
        if code == "missing_documents":
            raise HTTPException(400, detail="Faltan documentos requeridos.")
        raise HTTPException(400, detail=code)

    return {
        "id": v["id"],
        "status": v["status"],
        "risk_score": v["risk_score"],
        "created_at": v["created_at"],
    }


@router.get("/kyc/my-status")
async def my_kyc_status(request: Request) -> Any:
    """Return the client's latest verification (any status) or {status: 'unverified'}."""
    user = await require_user(request)
    v = await kyc_service.get_latest_verification(db, user["user_id"])
    if not v:
        return {"status": "unverified", "verification": None}
    return {
        "status": v["status"],
        "verification": {
            "id": v["id"],
            "status": v["status"],
            "created_at": v["created_at"],
            "reviewed_at": v.get("reviewed_at"),
            "review_notes": v.get("review_notes", ""),
            "rejection_reasons": v.get("rejection_reasons", []),
        },
    }


# ============================================================
# ADMIN / STAFF endpoints
# ============================================================

@router.get("/admin/kyc/queue")
async def admin_kyc_queue(
    request: Request,
    status: Optional[Literal["pending", "verified", "rejected", "needs_more_info"]] = None,
    search: str = "",
    min_risk: int = 0,
    limit: int = 100,
) -> Any:
    await require_permission(request, "kyc")
    if limit > 500:
        limit = 500
    items = await kyc_service.list_queue(db, status=status, search=search, min_risk=min_risk, limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/admin/kyc/funnel")
async def admin_kyc_funnel(request: Request) -> Any:
    await require_permission(request, "kyc")
    return await kyc_service.compute_funnel(db)


@router.get("/admin/kyc/{verification_id}")
async def admin_kyc_detail(verification_id: str, request: Request) -> Any:
    await require_permission(request, "kyc")
    v = await db.kyc_verifications.find_one({"id": verification_id}, {"_id": 0})
    if not v:
        raise HTTPException(404, detail="Verificación no encontrada.")
    return v


@router.post("/admin/kyc/{verification_id}/approve")
async def admin_kyc_approve(
    verification_id: str, payload: _KYCApprovePayload, request: Request,
) -> Any:
    staff = await require_permission(request, "kyc")
    v = await kyc_service.approve_verification(db, verification_id, staff, payload.notes)
    if not v:
        raise HTTPException(
            409,
            detail="No se pudo aprobar (la verificación ya no está pendiente o no existe).",
        )
    # Notify the user via in-app notification.
    try:
        from routes.notifications import notify_user_kyc_verified
        await notify_user_kyc_verified(db, v["user_id"])
    except Exception:  # noqa: BLE001
        logger.exception(f"notify_user_kyc_verified failed for {v['user_id']}")
    return v


@router.post("/admin/kyc/{verification_id}/reject")
async def admin_kyc_reject(
    verification_id: str, payload: _KYCRejectPayload, request: Request,
) -> Any:
    staff = await require_permission(request, "kyc")
    if not payload.reasons:
        raise HTTPException(400, detail="Selecciona al menos un motivo de rechazo.")
    v = await kyc_service.reject_verification(
        db, verification_id, staff, payload.reasons, payload.notes,
    )
    if not v:
        raise HTTPException(
            409,
            detail="No se pudo rechazar (la verificación ya no está pendiente o no existe).",
        )
    try:
        from routes.notifications import notify_user_kyc_rejected
        await notify_user_kyc_rejected(db, v["user_id"], payload.reasons, payload.notes)
    except Exception:  # noqa: BLE001
        logger.exception(f"notify_user_kyc_rejected failed for {v['user_id']}")
    return v


@router.post("/admin/kyc/{verification_id}/request-more-info")
async def admin_kyc_request_more(
    verification_id: str, payload: _KYCMoreInfoPayload, request: Request,
) -> Any:
    staff = await require_permission(request, "kyc")
    v = await kyc_service.request_more_info(db, verification_id, staff, payload.notes)
    if not v:
        raise HTTPException(
            409,
            detail="No se pudo solicitar más info (la verificación ya no está pendiente).",
        )
    try:
        from routes.notifications import notify_user_kyc_needs_more_info
        await notify_user_kyc_needs_more_info(db, v["user_id"], payload.notes)
    except Exception:  # noqa: BLE001
        logger.exception(f"notify_user_kyc_needs_more_info failed for {v['user_id']}")
    return v
