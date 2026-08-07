"""iter150 — QR Poster global settings.

Backend storage for the heading + promo displayed on the printable QR poster
that stores hang in their physical locations. Previously the heading/promo
lived only in each browser's `localStorage`, which meant:
  * every device saw a different value (or none at all on a fresh browser),
  * a public visitor could edit their own local copy and print a poster
    with misleading promo text under the Resilience Brothers brand.

Now the heading/promo are persisted under `db.settings` with id="qr_poster"
and served publicly (read-only) so every device — including anonymous
landing visitors — sees the same in-store promo the admin configured. Only
admin / employee roles can PUT changes.
"""
from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from db_client import db
from auth_utils import require_staff
from audit_log import log_action


router = APIRouter(tags=["QR Poster"])

_MAX_HEADING = 60
_MAX_PROMO = 80


class QrPosterPayload(BaseModel):
    heading: Optional[str] = Field(default=None, max_length=_MAX_HEADING)
    promo: Optional[str] = Field(default=None, max_length=_MAX_PROMO)


def _serialize(doc: Optional[dict]) -> dict:
    if not doc:
        return {"heading": "", "promo": ""}
    return {
        "heading": (doc.get("heading") or "")[:_MAX_HEADING],
        "promo": (doc.get("promo") or "")[:_MAX_PROMO],
    }


@router.get("/qr-poster")
async def get_qr_poster() -> Any:
    """Public read — everyone (including anonymous landing visitors) must
    see the same promo. Returns empty strings when nothing has been
    configured yet, which the frontend renders as the default poster."""
    doc = await db.settings.find_one({"id": "qr_poster"}, {"_id": 0})
    return _serialize(doc)


@router.put("/qr-poster")
async def update_qr_poster(payload: QrPosterPayload, request: Request) -> Any:
    """Admin / employee only — persists the poster's heading and promo
    globally so every device sees the same in-store offer."""
    actor = await require_staff(request)
    heading = (payload.heading or "").strip()[:_MAX_HEADING]
    promo = (payload.promo or "").strip()[:_MAX_PROMO]
    data = {"id": "qr_poster", "heading": heading, "promo": promo}
    await db.settings.update_one({"id": "qr_poster"}, {"$set": data}, upsert=True)
    await log_action(
        db, actor, "qr_poster.update", "settings", "qr_poster",
        summary="Póster QR actualizado",
        details={"heading": heading, "promo": promo},
    )
    return _serialize(data)
