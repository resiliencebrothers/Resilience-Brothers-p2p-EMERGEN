"""Proof-image upload helper — iter35.

Used by:
- `POST /api/orders`   → field `proof_image` (transfer proof from client)
- `PUT  /api/admin/withdrawals/{id}/status` → field `payout_proof_image`
  (admin uploading proof of payout to client)

Accepts either:
  a) A base64 data URL  → uploads to storage and returns `/api/files/<key>`.
  b) An already-uploaded reference (starts with `/api/files/` or `http`) →
     returned untouched.
  c) Anything else (empty / unrecognized) → returned untouched.

If storage is disabled or upload fails, the function returns the input
verbatim so the existing base64 flow keeps working — no data loss.
"""
import base64
import logging
import re
import uuid
from typing import Optional

from services import storage as storage_service

logger = logging.getLogger(__name__)

_DATA_URL_RE = re.compile(
    r"^data:(?P<mime>image/(?:png|jpe?g|gif|webp|bmp));base64,(?P<payload>[A-Za-z0-9+/=\s]+)$",
    re.IGNORECASE,
)

_MIME_TO_EXT = {
    "image/png": "png",
    "image/jpg": "jpg",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/bmp": "bmp",
}

MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MB hard limit per file


def maybe_upload_proof(value: Optional[str], folder: str) -> Optional[str]:
    """Convert a base64 data URL into a stored object key under `folder/`.

    Returns the new field value to persist in MongoDB. Caller should overwrite
    `proof_image` (or equivalent) with whatever this function returns.

    Examples
    --------
    >>> maybe_upload_proof("data:image/png;base64,iVBOR...", "orders")
    "/api/files/orders/2026/02/27/<uuid>.png"
    >>> maybe_upload_proof("/api/files/orders/...", "orders")
    "/api/files/orders/..."      # already a stored reference, untouched
    >>> maybe_upload_proof("", "orders")
    ""                            # no proof, untouched
    """
    if not value:
        return value
    if value.startswith("/api/files/") or value.startswith("http://") or value.startswith("https://"):
        return value  # already-uploaded reference, leave alone
    m = _DATA_URL_RE.match(value)
    if not m:
        return value  # unrecognized format → keep as-is (defensive)
    if not storage_service.is_enabled():
        return value  # storage off → keep base64 (legacy fallback)

    mime = m.group("mime").lower()
    raw_b64 = re.sub(r"\s+", "", m.group("payload"))
    try:
        blob = base64.b64decode(raw_b64, validate=True)
    except Exception as e:
        logger.warning(f"[proof] invalid base64 — keeping as-is: {e}")
        return value
    if len(blob) > MAX_UPLOAD_BYTES:
        # Reject silently — caller could surface a 413 if it wants stricter UX.
        logger.warning(f"[proof] upload too large ({len(blob)} bytes) — keeping base64")
        return value

    ext = _MIME_TO_EXT.get(mime, "bin")
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    key = f"{folder}/{now:%Y/%m/%d}/{uuid.uuid4().hex}.{ext}"
    stored = storage_service.put_object(key, blob, content_type=mime)
    if not stored:
        return value  # upload failed → keep base64
    return f"/api/files/{stored}"
