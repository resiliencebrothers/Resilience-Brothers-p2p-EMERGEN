"""Shared currency helpers — extracted from routes/admin_company_funds.py
(code review: break the module-level cross-import between the company-funds
route modules)."""
from typing import Any, Optional


def norm_code(c: Any) -> Optional[str]:
    """Normalise a currency code by stripping whitespace and upper-casing.
    Returns None for empty/non-string inputs so callers can skip corrupted
    rows without polluting aggregations."""
    return c.strip().upper() if isinstance(c, str) and c.strip() else None
