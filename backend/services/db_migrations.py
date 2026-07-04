"""Idempotent one-shot DB migrations that run on FastAPI startup.

iter55.3 + iter55.7 — strip whitespace and upper-case every currency code
across every collection that stores one. Data-entry typos like `"CUP "` or
`" USD"` would otherwise split accounting rows or break rate lookups.

Extracted from `server.py` during the iter45 refactor to keep the bootstrap
module small and focused on wiring routers + middleware.
"""
import logging
from typing import Any, Iterable

logger = logging.getLogger(__name__)

# (collection_attr, [field, field, ...]) — every string field on the collection
# that must be normalised. Keys resolve against `db.<attr>`.
_WHITESPACE_TARGETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("currencies", ("code",)),
    ("rates", ("from_code", "to_code")),
    ("orders", ("from_code", "to_code")),
    ("withdrawals", ("currency",)),
    ("company_withdrawals", ("currency",)),
    ("company_fund_adjustments", ("currency",)),
)


async def _clean_field(collection: Any, coll_name: str, field: str) -> int:
    """Trim + upper-case a single field on every row that has leading/trailing
    whitespace. Returns the count of updated rows."""
    updated = 0
    cursor = collection.find(
        {field: {"$regex": r"^\s|\s$"}},
        {"_id": 0, "id": 1, field: 1},
    )
    async for row in cursor:
        raw = row.get(field) or ""
        fixed = raw.strip().upper()
        if fixed and fixed != raw:
            await collection.update_one(
                {"id": row["id"]}, {"$set": {field: fixed}}
            )
            logger.info(
                f"Migrated {coll_name}.{field} {raw!r} → {fixed!r} on id={row['id']}"
            )
            updated += 1
    return updated


async def clean_currency_whitespace(
    db: Any, targets: Iterable[tuple[str, tuple[str, ...]]] = _WHITESPACE_TARGETS,
) -> int:
    """Iterate every (collection, fields) pair in `targets` and clean each field
    in place. Failures on one collection are logged but don't abort the rest.
    Returns the total number of rows updated across all targets."""
    total = 0
    for coll_attr, fields in targets:
        collection = getattr(db, coll_attr, None)
        if collection is None:
            continue
        for field in fields:
            try:
                total += await _clean_field(collection, coll_attr, field)
            except Exception as e:  # noqa: BLE001
                logger.error(f"Currency whitespace migration failed on {coll_attr}.{field}: {e}")
    return total
