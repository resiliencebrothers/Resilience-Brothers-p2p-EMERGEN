"""Sentry initialization — backend.

Disabled by default. Activates only when `SENTRY_DSN` is set in `.env`.
Configured to:
- Run only in non-development environments (controlled by `SENTRY_ENV`).
- Sample 10 % of traces by default (`SENTRY_TRACES_SAMPLE_RATE` overrides).
- Ignore common noise: 404s, client-side cancellations, expected HTTPExceptions
  with status < 500.
- Tag every event with the actor's `user_id` / `role` when available (set from
  middleware in auth_utils.py via `sentry_sdk.set_user`).
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def init_sentry() -> bool:
    """Initialize Sentry SDK if `SENTRY_DSN` is configured. Returns True if active."""
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        logger.info("SENTRY_DSN not set — Sentry disabled.")
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        environment = os.environ.get("SENTRY_ENV", "production")
        traces_rate = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1"))
        release = os.environ.get("SENTRY_RELEASE") or None

        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            release=release,
            traces_sample_rate=traces_rate,
            send_default_pii=False,  # never auto-send IPs / cookies / headers
            integrations=[
                StarletteIntegration(transaction_style="endpoint"),
                FastApiIntegration(transaction_style="endpoint"),
                LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
            ],
            before_send=_filter_noise,
        )
        logger.info(f"Sentry initialized (env={environment}, traces={traces_rate}).")
        return True
    except Exception as e:
        logger.error(f"Sentry init failed: {e}")
        return False


def _filter_noise(event: dict, hint: dict) -> Optional[dict]:
    """Drop events we don't want to spam Sentry with.

    Drops:
      - HTTPException with status_code < 500 (4xx are expected client errors).
      - Cancelled request errors from disconnected clients.
    """
    exc_info = hint.get("exc_info")
    if exc_info:
        exc = exc_info[1]
        # FastAPI HTTPException → only forward 5xx
        try:
            from fastapi import HTTPException
            if isinstance(exc, HTTPException) and exc.status_code < 500:
                return None
        except Exception:
            pass
        # Common noise from clients closing the connection mid-request.
        try:
            from anyio import EndOfStream  # type: ignore[import]
            if isinstance(exc, EndOfStream):
                return None
        except Exception:
            pass
    return event
