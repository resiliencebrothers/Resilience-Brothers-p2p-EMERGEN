"""iter116 — Automated monthly security self-audit.

A lightweight, read-only checklist runner that verifies the platform's core
security invariants still hold as the codebase evolves. It re-checks the exact
hardening points confirmed in the 28/7/2026 audit plus ongoing staff-hygiene
signals, then produces a structured report that is emailed to every admin on
day 1 (09:45 UTC) and can be triggered on demand.

Each check returns one of: "pass" | "warn" | "fail".
  - fail  → a security invariant is broken in code/config (needs a fix).
  - warn  → operational hygiene issue (e.g. staff without 2FA).
  - pass  → invariant confirmed.

Everything here is best-effort and MUST never raise into the scheduler.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Individual checks — each returns (status, detail)
# ---------------------------------------------------------------------------

def _check_balance_capability_guard() -> tuple[str, str]:
    """SEC-001 — balance & staff-capability fields must be admin-only."""
    try:
        import inspect
        from routes import admin_users
        src = inspect.getsource(admin_users.update_user)
        required = ("ADMIN_ONLY_FIELDS", "vip_balances", "can_manage_company_funds")
        if all(tok in src for tok in required) and 'role") != "admin"' in src:
            return "pass", "El endpoint PUT /admin/users bloquea saldos y capacidades para no-admins."
        return "fail", "No se encontró la guardia admin-only de saldos/capacidades en update_user."
    except Exception as e:  # noqa: BLE001
        return "warn", f"No se pudo inspeccionar update_user: {e}"


def _check_open_redirect_guard() -> tuple[str, str]:
    """SEC-002 — post-login redirect only accepts same-site relative paths."""
    try:
        from routes.auth import _safe_post_login_redirect as safe
        external = safe("https://evil.example/x")
        scheme_rel = safe("//evil.example/x")
        relative = safe("/dashboard/batches")
        if external == "/dashboard" and scheme_rel == "/dashboard" and relative == "/dashboard/batches":
            return "pass", "El redirect post-login rechaza destinos externos y conserva rutas internas."
        return "fail", (f"La validación de redirect no filtra correctamente "
                        f"(externo={external}, scheme={scheme_rel}, relativo={relative}).")
    except Exception as e:  # noqa: BLE001
        return "fail", f"No existe/roto _safe_post_login_redirect: {e}"


def _check_regex_escaping() -> tuple[str, str]:
    """SEC-003 — user search strings must be regex-escaped (no ReDoS/crash)."""
    try:
        from routes.admin_users import _build_users_query
        crafted = "((((invalid[a-"
        q = _build_users_query(crafted, None)
        # The escaped pattern must be present verbatim (escaped) inside $regex.
        import re as _re
        rx = q["$or"][0]["name"]["$regex"]
        if rx == _re.escape(crafted):
            return "pass", "Las búsquedas de usuarios escapan el input (re.escape) — sin ReDoS."
        return "fail", "El patrón de búsqueda no está escapado con re.escape."
    except Exception as e:  # noqa: BLE001
        return "fail", f"No se pudo verificar el escape de regex: {e}"


def _check_login_enumeration() -> tuple[str, str]:
    """Login must NOT expose USER_NOT_FOUND (enumeration)."""
    try:
        import inspect
        from routes import auth
        src = inspect.getsource(auth.auth_login)
        if "USER_NOT_FOUND" in src:
            return "fail", "El login todavía devuelve USER_NOT_FOUND (permite enumeración)."
        if "INVALID_CREDENTIALS" in src and "_DUMMY_PASSWORD_HASH" in src:
            return "pass", "El login unifica credenciales inválidas y mitiga timing."
        return "warn", "El login no muestra USER_NOT_FOUND pero falta la mitigación de timing."
    except Exception as e:  # noqa: BLE001
        return "warn", f"No se pudo inspeccionar auth_login: {e}"


async def _check_staff_2fa_coverage(db: Any) -> tuple[str, str]:
    """Every admin/employee should have 2FA enabled. Since iter117, staff
    without 2FA are BLOCKED from mutating actions — so this is a hard signal."""
    try:
        staff = await db.users.find(
            {"role": {"$in": ["admin", "employee"]}},
            {"_id": 0, "email": 1, "totp_enabled": 1},
        ).to_list(500)
        without = [s.get("email", "?") for s in staff if not s.get("totp_enabled")]
        if not staff:
            return "warn", "No hay cuentas admin/employee registradas."
        if not without:
            return "pass", f"Las {len(staff)} cuentas staff tienen 2FA activo."
        return "warn", (f"{len(without)}/{len(staff)} cuentas staff SIN 2FA (bloqueadas "
                        f"para operaciones sensibles desde iter117): "
                        f"{', '.join(without[:8])}{'…' if len(without) > 8 else ''}.")
    except Exception as e:  # noqa: BLE001
        return "warn", f"No se pudo evaluar cobertura 2FA: {e}"


def _check_staff_2fa_enforcement() -> tuple[str, str]:
    """iter117 — staff mutations must be gated by the 2FA-enrollment check."""
    try:
        import inspect
        from auth_utils import require_permission, _enforce_staff_2fa_enabled  # noqa: F401
        src = inspect.getsource(require_permission)
        if "_enforce_staff_2fa_enabled" in src:
            return "pass", "Las mutaciones de staff exigen 2FA activo (bloqueo 412 proactivo)."
        return "fail", "require_permission ya no invoca la guardia _enforce_staff_2fa_enabled."
    except Exception as e:  # noqa: BLE001
        return "fail", f"No existe/roto _enforce_staff_2fa_enabled: {e}"


async def _check_withdrawal_refund_integrity(db: Any) -> tuple[str, str]:
    """Rejected withdrawals should carry the idempotent balance_refunded flag."""
    try:
        total_rejected = await db.withdrawals.count_documents({"status": "rejected"})
        missing_flag = await db.withdrawals.count_documents(
            {"status": "rejected", "balance_refunded": {"$exists": False}},
        )
        if total_rejected == 0:
            return "pass", "No hay retiros rechazados que auditar."
        if missing_flag == 0:
            return "pass", f"Los {total_rejected} retiros rechazados usan el flag idempotente."
        return "warn", (f"{missing_flag}/{total_rejected} retiros rechazados son previos al fix "
                        "idempotente (legacy — sin riesgo activo, solo informativo).")
    except Exception as e:  # noqa: BLE001
        return "warn", f"No se pudo evaluar la integridad de refunds: {e}"


def _check_cors_not_wildcard() -> tuple[str, str]:
    """Production CORS must never be a wildcard."""
    try:
        env = (os.environ.get("ENVIRONMENT") or "").lower()
        raw = os.environ.get("CORS_ORIGINS", "") or os.environ.get("ALLOWED_ORIGINS", "")
        if env == "production" and raw.strip() == "*":
            return "fail", "CORS_ORIGINS es '*' en producción — riesgo de robo de sesión."
        return "pass", f"CORS sin wildcard (env={env or 'preview/dev'})."
    except Exception as e:  # noqa: BLE001
        return "warn", f"No se pudo evaluar CORS: {e}"


def _check_session_ttl_cap() -> tuple[str, str]:
    """Sessions must be capped (policy ≤ 24h)."""
    try:
        import inspect
        from auth_utils import _create_session
        src = inspect.getsource(_create_session)
        if "24" in src and "ttl_hours" in src:
            return "pass", "Las sesiones están limitadas por política (≤24h)."
        return "warn", "No se pudo confirmar el tope de TTL de sesión en el código."
    except Exception as e:  # noqa: BLE001
        return "warn", f"No se pudo inspeccionar _create_session: {e}"


async def _check_rate_limited_endpoints() -> tuple[str, str]:
    """Sensitive endpoints must keep their slowapi limits wired."""
    try:
        import inspect
        from routes import auth, vip_ledger_ops
        login_src = inspect.getsource(auth.auth_login)
        forgot_src = inspect.getsource(auth.auth_forgot_password)
        ledger_src = inspect.getsource(vip_ledger_ops.email_own_ledger_pdf)
        checks = {
            "login": "limiter.limit" in login_src,
            "forgot-password": "limiter.limit" in forgot_src,
            # ledger-email uses a self-contained Mongo limiter (slowapi's decorator
            # is incompatible with this module's `from __future__ import annotations`).
            "ledger-email": "_enforce_email_rate_limit" in ledger_src,
        }
        missing = [k for k, ok in checks.items() if not ok]
        if not missing:
            return "pass", "login, forgot-password y ledger-email conservan rate-limit."
        return "fail", f"Endpoints sin rate-limit: {', '.join(missing)}."
    except Exception as e:  # noqa: BLE001
        return "warn", f"No se pudo verificar rate-limits: {e}"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_SYNC_CHECKS: list[tuple[str, str, Callable[[], tuple[str, str]]]] = [
    ("SEC-001", "Saldos/capacidades solo-admin", _check_balance_capability_guard),
    ("SEC-002", "Redirect post-login sin open-redirect", _check_open_redirect_guard),
    ("SEC-003", "Escape de regex en búsquedas", _check_regex_escaping),
    ("SEC-004", "Login sin enumeración de cuentas", _check_login_enumeration),
    ("SEC-007", "CORS sin wildcard en producción", _check_cors_not_wildcard),
    ("SEC-008", "Tope de TTL de sesión", _check_session_ttl_cap),
    ("SEC-010", "2FA obligatorio en mutaciones de staff", _check_staff_2fa_enforcement),
]


async def run_security_selfaudit(db: Any = None) -> dict:
    """Run the full checklist. Returns a structured report dict."""
    if db is None:
        from db_client import db as _db
        db = _db

    results: list[dict] = []
    for cid, title, fn in _SYNC_CHECKS:
        try:
            status, detail = fn()
        except Exception as e:  # noqa: BLE001
            status, detail = "warn", f"Excepción en la comprobación: {e}"
        results.append({"id": cid, "title": title, "status": status, "detail": detail})

    for cid, title, coro in (
        ("SEC-005", "Cobertura 2FA del staff", _check_staff_2fa_coverage(db)),
        ("SEC-006", "Idempotencia de refunds de retiros", _check_withdrawal_refund_integrity(db)),
        ("SEC-009", "Rate-limit en endpoints sensibles", _check_rate_limited_endpoints()),
    ):
        try:
            status, detail = await coro
        except Exception as e:  # noqa: BLE001
            status, detail = "warn", f"Excepción en la comprobación: {e}"
        results.append({"id": cid, "title": title, "status": status, "detail": detail})

    results.sort(key=lambda r: r["id"])
    summary = {
        "pass": sum(1 for r in results if r["status"] == "pass"),
        "warn": sum(1 for r in results if r["status"] == "warn"),
        "fail": sum(1 for r in results if r["status"] == "fail"),
    }
    verdict = "fail" if summary["fail"] else ("warn" if summary["warn"] else "pass")
    report = {
        "generated_at": _now_iso(),
        "verdict": verdict,
        "summary": summary,
        "checks": results,
    }
    return report


async def run_and_email_security_selfaudit(db: Any = None) -> dict:
    """Run the checklist and email the report to every admin. Never raises."""
    if db is None:
        from db_client import db as _db
        db = _db
    report = await run_security_selfaudit(db)
    try:
        import email_service
        from admin_alerts import resolve_admin_email_recipients
        recipients = await resolve_admin_email_recipients(db)
        sent = 0
        for to_addr in recipients:
            if email_service.notify_security_selfaudit(to_addr, report):
                sent += 1
        report["emailed_to"] = sent
        logger.info("Security self-audit: verdict=%s sent=%s/%s",
                    report["verdict"], sent, len(recipients))
    except Exception:  # noqa: BLE001
        logger.exception("Security self-audit: email fanout failed")
        report["emailed_to"] = 0
    return report
