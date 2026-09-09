"""iter246 — Cloudflare Turnstile (verificación "No soy un robot").

Se aplica al registro y login por email. Claves vía .env:
  TURNSTILE_SITE_KEY / TURNSTILE_SECRET_KEY (claves de PRUEBA de Cloudflare
  por defecto — siempre aprueban — hasta que el usuario configure las reales)
  TURNSTILE_ENFORCED=true → exige el token (sin él: 400). En false, el widget
  se muestra y el token se verifica cuando llega, pero su ausencia no bloquea
  (los tests backend y clientes antiguos siguen funcionando).
  TURNSTILE_EXPECTED_HOSTNAME → valida el hostname en producción (opcional).
Caída de Cloudflare → fail-open con log (no dejar fuera a usuarios legítimos).
"""
import logging
import os

import httpx
from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def turnstile_site_key() -> str:
    return (os.environ.get("TURNSTILE_SITE_KEY") or "").strip()


def turnstile_secret() -> str:
    return (os.environ.get("TURNSTILE_SECRET_KEY") or "").strip()


def turnstile_enforced() -> bool:
    return (os.environ.get("TURNSTILE_ENFORCED") or "").strip().lower() == "true"


def captcha_config() -> dict:
    enabled = bool(turnstile_site_key() and turnstile_secret())
    return {"enabled": enabled, "site_key": turnstile_site_key() if enabled else "",
            "enforced": enabled and turnstile_enforced()}


def _captcha_failed() -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"code": "CAPTCHA_FAILED",
                "message": "No pudimos verificar que no eres un robot. Recarga la página e inténtalo de nuevo."})


def _has_test_bypass(request: Request) -> bool:
    """Bypass para la suite de tests interna (header secreto de .env, nunca
    expuesto al cliente). Equivale a poseer acceso al servidor."""
    bypass = (os.environ.get("TURNSTILE_TEST_BYPASS") or "").strip()
    return bool(bypass) and request.headers.get("X-Captcha-Bypass") == bypass


def _client_ip(request: Request) -> str | None:
    return (request.headers.get("CF-Connecting-IP")
            or (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
            or None)


async def _siteverify(secret: str, token: str, remote_ip: str | None) -> dict | None:
    """POST a Cloudflare siteverify. None = servicio caído (fail-open)."""
    payload = {"secret": secret, "response": token[:2048]}
    if remote_ip:
        payload["remoteip"] = remote_ip
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.post(SITEVERIFY_URL, data=payload)
            r.raise_for_status()
            return r.json()
    except Exception as e:  # noqa: BLE001
        logger.error(f"Turnstile siteverify unavailable (fail-open): {e}")
        return None


def _check_verify_result(result: dict) -> None:
    if not result.get("success"):
        logger.warning(f"Turnstile rejected token: {result.get('error-codes')}")
        raise _captcha_failed()
    expected = (os.environ.get("TURNSTILE_EXPECTED_HOSTNAME") or "").strip()
    if expected and result.get("hostname") != expected:
        logger.warning(f"Turnstile hostname mismatch: {result.get('hostname')}")
        raise _captcha_failed()


async def verify_captcha_token(token: str | None, request: Request) -> None:
    """Valida el token contra siteverify. 400 si falta (enforced) o si
    Cloudflare lo rechaza. No-op si Turnstile no está configurado."""
    secret = turnstile_secret()
    if not secret:
        return
    if _has_test_bypass(request):
        return
    token = (token or "").strip()
    if not token:
        if turnstile_enforced():
            raise HTTPException(
                status_code=400,
                detail={"code": "CAPTCHA_REQUIRED",
                        "message": "Completa la verificación 'No soy un robot'."})
        return
    result = await _siteverify(secret, token, _client_ip(request))
    if result is None:
        return
    _check_verify_result(result)
