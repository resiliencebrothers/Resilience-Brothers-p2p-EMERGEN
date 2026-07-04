"""Cloudflare Firewall IP Access Rules client (iter50).

Wraps 3 REST operations against `zones/{zone_id}/firewall/access_rules/rules`:
- create_block_rule(ip, notes)  → POST
- delete_rule(rule_id)          → DELETE
- list_block_rules(ip=None)     → GET (paginated)

Auth: `Authorization: Bearer <CF_API_TOKEN>` (scoped token, NOT global key).
Required token permission: **Zone → Firewall Services → Edit** on the target zone.

Failure policy is "log-and-continue": every method catches its own exceptions
and returns a structured result — this lets the caller (security_alerts.py)
decide whether to persist a "pending" state instead of crashing the scan.
"""
import os
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


def _is_configured() -> bool:
    """True iff both CF_API_TOKEN and CF_ZONE_ID are set. Callers should
    short-circuit when this is False (no CF calls, no persistence)."""
    return bool(os.environ.get("CF_API_TOKEN")) and bool(os.environ.get("CF_ZONE_ID"))


def is_auto_block_enabled() -> bool:
    """Opt-in switch. Auto-blocking on scanner-detected floods is OFF by default.
    Turn on in .env with `CLOUDFLARE_AUTO_BLOCK_ENABLED=true`."""
    return (
        _is_configured()
        and os.environ.get("CLOUDFLARE_AUTO_BLOCK_ENABLED", "false").lower() == "true"
    )


def _base_url() -> str:
    zone_id = os.environ["CF_ZONE_ID"]
    return f"https://api.cloudflare.com/client/v4/zones/{zone_id}/firewall/access_rules/rules"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['CF_API_TOKEN']}",
        "Content-Type": "application/json",
    }


async def create_block_rule(ip: str, notes: str) -> dict:
    """Create a `mode=block` rule for a single IP. Returns:
      {ok: True,  rule_id: str, raw: {...}}
      {ok: False, error: str, status: int, existing_rule_id: Optional[str]}

    On duplicate-rule error Cloudflare returns success:false; we then look up
    the existing rule so the caller can still persist the linkage.
    """
    if not _is_configured():
        return {"ok": False, "error": "Cloudflare not configured", "status": 0}
    payload = {
        "mode": "block",
        "configuration": {"target": "ip", "value": ip},
        "notes": notes,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.post(_base_url(), headers=_headers(), json=payload)
            data = r.json()
    except Exception as e:  # noqa: BLE001
        logger.error(f"[cloudflare] create_block_rule({ip}) network error: {e}")
        return {"ok": False, "error": f"network: {e}", "status": 0}

    if r.status_code == 200 and data.get("success"):
        result = data.get("result") or {}
        return {"ok": True, "rule_id": result.get("id"), "raw": result}

    # Duplicate rule? Look it up so we can persist the existing rule_id.
    errors = data.get("errors") or []
    error_msg = ", ".join(e.get("message", "") for e in errors) or f"HTTP {r.status_code}"
    existing = None
    if any("already exists" in (e.get("message", "").lower()) for e in errors) or r.status_code == 409:
        found = await list_block_rules(ip=ip)
        if found.get("ok") and found.get("items"):
            existing = found["items"][0].get("id")
    logger.warning(f"[cloudflare] create_block_rule({ip}) failed status={r.status_code}: {error_msg}")
    return {
        "ok": False, "error": error_msg, "status": r.status_code,
        "existing_rule_id": existing,
    }


async def delete_rule(rule_id: str) -> dict:
    """Delete a rule by its Cloudflare id. 404 is treated as success (idempotent)."""
    if not _is_configured():
        return {"ok": False, "error": "Cloudflare not configured", "status": 0}
    try:
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.delete(f"{_base_url()}/{rule_id}", headers=_headers())
    except Exception as e:  # noqa: BLE001
        logger.error(f"[cloudflare] delete_rule({rule_id}) network error: {e}")
        return {"ok": False, "error": f"network: {e}", "status": 0}
    if r.status_code in (200, 204, 404):
        return {"ok": True, "status": r.status_code}
    try:
        data = r.json()
        errors = data.get("errors") or []
        error_msg = ", ".join(e.get("message", "") for e in errors) or f"HTTP {r.status_code}"
    except Exception:
        error_msg = f"HTTP {r.status_code}"
    logger.warning(f"[cloudflare] delete_rule({rule_id}) failed: {error_msg}")
    return {"ok": False, "error": error_msg, "status": r.status_code}


async def list_block_rules(ip: Optional[str] = None, per_page: int = 50) -> dict:
    """List block-mode rules, optionally filtered to a single IP.
    Returns {ok: True, items: list} or {ok: False, error, status}.
    """
    if not _is_configured():
        return {"ok": False, "error": "Cloudflare not configured", "status": 0}
    params: dict[str, Any] = {"mode": "block", "per_page": per_page}
    if ip is not None:
        params["configuration_target"] = "ip"
        params["configuration_value"] = ip
    try:
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(_base_url(), headers=_headers(), params=params)
            data = r.json()
    except Exception as e:  # noqa: BLE001
        logger.error(f"[cloudflare] list_block_rules network error: {e}")
        return {"ok": False, "error": f"network: {e}", "status": 0}
    if r.status_code == 200 and data.get("success"):
        return {"ok": True, "items": data.get("result") or []}
    errors = data.get("errors") or []
    return {
        "ok": False,
        "error": ", ".join(e.get("message", "") for e in errors) or f"HTTP {r.status_code}",
        "status": r.status_code,
    }
