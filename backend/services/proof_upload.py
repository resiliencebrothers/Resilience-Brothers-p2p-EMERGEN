"""Proof-image upload helper — iter35.

Used by:
- `POST /api/orders`   → field `proof_image` (transfer proof from client)
- `PUT  /api/admin/withdrawals/{id}/status` → field `payout_proof_image`
  (admin uploading proof of payout to client)
- `POST /api/admin/company-withdrawals`  → field `invoice_image`

Accepts either:
  a) A base64 data URL  → uploads to storage and returns `/api/files/<key>`.
  b) An already-uploaded reference (starts with `/api/files/` or `http`) →
     returned untouched.
  c) Anything else (empty / unrecognized) → returned untouched.

iter36 — oversize handling: when the decoded payload exceeds `MAX_UPLOAD_BYTES`
(8 MB) the helper raises `HTTPException(413)`. Previously it silently kept the
base64 inline which could push the order document past MongoDB's 16 MB limit.

If storage is disabled or upload fails, the function returns the input
verbatim so the existing base64 flow keeps working — no data loss.
"""
import base64
import logging
import re
import uuid
from typing import Optional

from fastapi import HTTPException

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

    # iter36 — validate size BEFORE checking storage status so the 8 MB cap
    # protects MongoDB even when storage is off (legacy / dev mode).
    mime = m.group("mime").lower()
    raw_b64 = re.sub(r"\s+", "", m.group("payload"))
    try:
        blob = base64.b64decode(raw_b64, validate=True)
    except Exception as e:
        logger.warning(f"[proof] invalid base64 — keeping as-is: {e}")
        return value
    if len(blob) > MAX_UPLOAD_BYTES:
        # iter36 — surface 413 to the client instead of silently keeping a multi-MB
        # blob inline (which would also blow past Mongo's 16 MB document limit).
        size_mb = len(blob) / (1024 * 1024)
        limit_mb = MAX_UPLOAD_BYTES / (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail={
                "code": "PROOF_TOO_LARGE",
                "message": (
                    f"La imagen del comprobante es demasiado grande "
                    f"({size_mb:.1f} MB). Máximo permitido: {limit_mb:.0f} MB. "
                    f"Comprime la imagen o tómala con menor resolución."
                ),
                "size_mb": round(size_mb, 2),
                "limit_mb": limit_mb,
            },
        )

    if not storage_service.is_enabled():
        return value  # storage off → keep base64 (legacy fallback, size-bounded)

    ext = _MIME_TO_EXT.get(mime, "bin")
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    key = f"{folder}/{now:%Y/%m/%d}/{uuid.uuid4().hex}.{ext}"
    stored = storage_service.put_object(key, blob, content_type=mime)
    if not stored:
        return value  # upload failed → keep base64
    return f"/api/files/{stored}"
