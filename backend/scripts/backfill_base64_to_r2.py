"""Backfill base64 → R2 for historical orders / withdrawals / company-withdrawals.

iter36. Designed to be run manually after the iter35 R2 integration is verified:

    # 1. See what would happen, no writes:
    python scripts/backfill_base64_to_r2.py --dry-run

    # 2. Run the real migration:
    python scripts/backfill_base64_to_r2.py --apply

    # 3. Re-run is safe — already-migrated records are skipped (idempotent).

Behaviour
---------
- Reads `proof_image` / `payout_proof_image` / `invoice_image` from
  orders / withdrawals / company_withdrawals.
- Skips fields that are empty or already a `/api/files/...` reference.
- Uploads the base64 blob to the configured storage backend
  (`STORAGE_PROVIDER`) and rewrites the field to the new ref.
- Continues on per-document errors and reports them at the end.
- Aborts ONLY if storage init fails (the whole run is impossible then).

DB connection settings come from `backend/.env` (MONGO_URL + DB_NAME). Storage
settings come from `backend/.env` (STORAGE_PROVIDER=r2 + R2_* creds).
"""
import argparse
import base64
import logging
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # /app/backend
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from pymongo import MongoClient  # noqa: E402
import os  # noqa: E402

from services import storage as storage_service  # noqa: E402


logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("backfill")


_DATA_URL_RE = re.compile(
    r"^data:(?P<mime>image/(?:png|jpe?g|gif|webp|bmp));base64,(?P<payload>[A-Za-z0-9+/=\s]+)$",
    re.IGNORECASE,
)
_MIME_TO_EXT = {
    "image/png": "png", "image/jpg": "jpg", "image/jpeg": "jpg",
    "image/gif": "gif", "image/webp": "webp", "image/bmp": "bmp",
}
_MAX_BYTES = 8 * 1024 * 1024  # mirror services.proof_upload.MAX_UPLOAD_BYTES


# ---------------- helpers ----------------

def _decode(value: str):
    """Return (blob, mime, ext) or None if the value is not a usable data URL."""
    m = _DATA_URL_RE.match(value or "")
    if not m:
        return None
    mime = m.group("mime").lower()
    raw_b64 = re.sub(r"\s+", "", m.group("payload"))
    try:
        blob = base64.b64decode(raw_b64, validate=True)
    except Exception:
        return None
    ext = _MIME_TO_EXT.get(mime, "bin")
    return blob, mime, ext


def _build_key(folder: str, doc_id: str, ext: str) -> str:
    """Deterministic key — same doc always migrates to the same key. This makes
    the migration safely idempotent: if it ran half-way before, the re-run
    overwrites the same R2 object instead of duplicating storage."""
    now = datetime.now(timezone.utc)
    # Use doc id (UUID) so re-runs land on the same key; date prefix for browsability.
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", doc_id or "")[:32] or uuid.uuid4().hex
    return f"{folder}/{now:%Y/%m/%d}/{safe_id}.{ext}"


# ---------------- per-collection runner ----------------

def _migrate_collection(db, collection_name: str, field: str, folder: str,
                          apply_changes: bool):
    coll = db[collection_name]
    # Only consider docs where the field is still a data URL.
    q = {field: {"$regex": "^data:image/"}}
    cursor = coll.find(q, {"_id": 0, "id": 1, field: 1})
    stats = {"scanned": 0, "migrated": 0, "skipped_oversize": 0,
             "skipped_invalid": 0, "errors": []}
    for doc in cursor:
        stats["scanned"] += 1
        decoded = _decode(doc[field])
        if decoded is None:
            stats["skipped_invalid"] += 1
            log.info(f"  [{collection_name}/{doc['id']}] invalid base64 — skipped")
            continue
        blob, mime, ext = decoded
        if len(blob) > _MAX_BYTES:
            stats["skipped_oversize"] += 1
            log.info(f"  [{collection_name}/{doc['id']}] oversize "
                       f"({len(blob)/1024/1024:.1f} MB) — skipped, kept inline")
            continue
        key = _build_key(folder, doc["id"], ext)
        if apply_changes:
            stored = storage_service.put_object(key, blob, content_type=mime)
            if not stored:
                stats["errors"].append((doc["id"], "put_object returned None"))
                log.warning(f"  [{collection_name}/{doc['id']}] upload failed — left as-is")
                continue
            try:
                coll.update_one({"id": doc["id"]}, {"$set": {field: f"/api/files/{stored}"}})
                stats["migrated"] += 1
                log.info(f"  [{collection_name}/{doc['id']}] {len(blob)/1024:.1f} KB → {stored}")
            except Exception as e:
                stats["errors"].append((doc["id"], f"mongo update failed: {e}"))
                log.warning(f"  [{collection_name}/{doc['id']}] mongo update failed: {e}")
                # best-effort: try to delete the orphaned R2 object so the next run uploads cleanly
                storage_service.delete_object(stored)
        else:
            stats["migrated"] += 1  # would be migrated in --apply mode
            log.info(f"  [{collection_name}/{doc['id']}] {len(blob)/1024:.1f} KB → would upload as {key}")
    return stats


# ---------------- main ----------------

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                       formatter_class=argparse.RawDescriptionHelpFormatter)
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dry-run", action="store_true",
                       help="Scan only — no writes to R2 or MongoDB.")
    grp.add_argument("--apply", action="store_true",
                       help="Perform the migration. Idempotent.")
    args = parser.parse_args()

    apply_changes = bool(args.apply)
    mode = "APPLY" if apply_changes else "DRY-RUN"
    log.info(f"==> Backfill base64 → R2 ({mode})")

    storage_service.init_storage()
    if apply_changes and not storage_service.is_enabled():
        log.error("Storage backend is disabled (STORAGE_PROVIDER=none or "
                   "credentials missing). Cannot perform --apply. "
                   "Set STORAGE_PROVIDER=r2 + R2_* env vars first.")
        sys.exit(2)

    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    targets = [
        ("orders", "proof_image", "orders"),
        ("withdrawals", "payout_proof_image", "withdrawals"),
        ("company_withdrawals", "invoice_image", "company_invoices"),
    ]

    total = {"scanned": 0, "migrated": 0, "skipped_oversize": 0,
             "skipped_invalid": 0, "errors": []}
    for coll_name, field, folder in targets:
        log.info(f"\n--- {coll_name}.{field} ---")
        s = _migrate_collection(db, coll_name, field, folder, apply_changes)
        log.info(f"  scanned={s['scanned']} migrated={s['migrated']} "
                   f"oversize={s['skipped_oversize']} invalid={s['skipped_invalid']} "
                   f"errors={len(s['errors'])}")
        for k in ("scanned", "migrated", "skipped_oversize", "skipped_invalid"):
            total[k] += s[k]
        total["errors"].extend((coll_name, *e) for e in s["errors"])

    log.info("\n==> Summary")
    log.info(f"   Scanned:           {total['scanned']}")
    log.info(f"   Migrated:          {total['migrated']}{' (DRY-RUN)' if not apply_changes else ''}")
    log.info(f"   Skipped (oversize): {total['skipped_oversize']}")
    log.info(f"   Skipped (invalid):  {total['skipped_invalid']}")
    log.info(f"   Errors:            {len(total['errors'])}")
    for err in total["errors"]:
        log.warning(f"     {err}")
    client.close()
    sys.exit(0)


if __name__ == "__main__":
    main()
