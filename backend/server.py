"""Resilience Brothers P2P — FastAPI entry point.

After the iter27 → iter33 refactor, this module is intentionally tiny. It owns:
- Application bootstrap (`app`, `api_router`)
- Router wiring (every domain lives under `routes/*`)
- CORS middleware
- Startup / shutdown hooks (APScheduler wiring)

All business logic lives in `routes/*` and `services/*`. Shared auth helpers
live in `auth_utils.py`; the Mongo client in `db_client.py`.
"""
import logging
from pathlib import Path

from fastapi import APIRouter, FastAPI
from dotenv import load_dotenv
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# Init Sentry BEFORE creating the FastAPI app so exceptions in startup are captured.
from sentry_config import init_sentry  # noqa: E402
init_sentry()

from db_client import db, client  # noqa: E402

# Modular routers (extracted from server.py during iter27 → iter33 refactor)
from routes.auth import router as auth_router  # noqa: E402
from routes.notifications import router as notifications_router  # noqa: E402
from routes.blocklist import router as blocklist_router  # noqa: E402
from routes.market import router as market_router  # noqa: E402
from routes.push import router as push_router  # noqa: E402
from routes.me import router as me_router  # noqa: E402
from routes.orders import router as orders_router  # noqa: E402
from routes.admin import router as admin_router, build_revenue_timeseries  # noqa: E402
from routes.admin_withdrawals import router as admin_withdrawals_router  # noqa: E402
from routes.admin_users import router as admin_users_router  # noqa: E402
from routes.admin_audit import router as admin_audit_router  # noqa: E402
from routes.admin_company_funds import router as admin_company_funds_router  # noqa: E402
from routes.admin_revenue import router as admin_revenue_router  # noqa: E402
from routes.files import router as files_router  # noqa: E402
from routes.appeals import router as appeals_router  # noqa: E402
from routes.admin_security import router as admin_security_router  # noqa: E402
from routes.kyc import router as kyc_router  # noqa: E402
from routes.profile import router as profile_router  # noqa: E402
from routes.capital_requests import router as capital_requests_router  # noqa: E402
from services import storage as storage_service  # noqa: E402

storage_service.init_storage()


app = FastAPI(
    title="Resilience Brothers P2P",
    # iter36 — expose the schema + docs under /api/* so the public ingress (which only
    # proxies /api/*) can reach them. Internal /openapi.json keeps working on :8001.
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)
api_router = APIRouter(prefix="/api")


@api_router.get("/", tags=["System"])
async def root() -> dict:
    return {"service": "Resilience Brothers P2P", "status": "ok"}


# Wire up domain routers
api_router.include_router(auth_router)
api_router.include_router(notifications_router)
api_router.include_router(blocklist_router)
api_router.include_router(market_router)
api_router.include_router(push_router)
api_router.include_router(me_router)
api_router.include_router(orders_router)
api_router.include_router(admin_router)
api_router.include_router(admin_withdrawals_router)
api_router.include_router(admin_users_router)
api_router.include_router(admin_audit_router)
api_router.include_router(admin_company_funds_router)
api_router.include_router(admin_revenue_router)
api_router.include_router(files_router)
api_router.include_router(appeals_router)
api_router.include_router(admin_security_router)
api_router.include_router(kyc_router)
api_router.include_router(profile_router)
api_router.include_router(capital_requests_router)

app.include_router(api_router)

# iter47 — Security middleware: strict CORS, rate limiting (slowapi),
# security headers (HSTS/CSP/X-Frame/etc). Wire once here so `server.py` stays
# a thin bootstrap.
from security_middleware import install_security_middleware  # noqa: E402
install_security_middleware(app)

# iter50b — App-level IP blocklist enforcement. Added LAST so it runs FIRST
# for incoming requests (Starlette middleware is LIFO). Blocked IPs are
# rejected before slowapi consumes a rate-limit slot.
from middleware.ip_blocklist import install_ip_blocklist_middleware  # noqa: E402
install_ip_blocklist_middleware(app)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@app.on_event("startup")
async def start_background_jobs() -> None:
    """Wire up APScheduler. Wrap build_revenue_timeseries to expose it to
    scheduler.py without importing server.py (which would be circular)."""
    from scheduler import start_scheduler
    from services.db_migrations import clean_currency_whitespace
    from services.security_events import ensure_indexes as security_events_indexes
    from services.security_alerts import ensure_indexes as security_alerts_indexes
    from services.cloudflare_blocks import ensure_indexes as cloudflare_blocks_indexes

    # iter55.3 + iter55.7 — one-shot idempotent migration: strip whitespace
    # (and uppercase) currency codes across ALL collections that store them so
    # data-entry typos never split accounting rows or break rate lookups.
    try:
        await clean_currency_whitespace(db)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Currency code migration failed: {e}")

    # iter48 — security_events collection indexes (idempotent).
    try:
        await security_events_indexes()
    except Exception as e:  # noqa: BLE001
        logger.error(f"security_events index setup failed: {e}")

    # iter49 — security_alerts_sent (dedup log) TTL 7d.
    try:
        await security_alerts_indexes()
    except Exception as e:  # noqa: BLE001
        logger.error(f"security_alerts_sent index setup failed: {e}")

    # iter50 — cloudflare_ip_blocks collection indexes (idempotent).
    try:
        await cloudflare_blocks_indexes(db)
    except Exception as e:  # noqa: BLE001
        logger.error(f"cloudflare_ip_blocks index setup failed: {e}")

    # iter52 — kyc_verifications indexes (idempotent).
    try:
        from services.kyc import ensure_indexes as kyc_indexes
        await kyc_indexes(db)
    except Exception as e:  # noqa: BLE001
        logger.error(f"kyc_verifications index setup failed: {e}")

    async def _build_timeseries(
        granularity: str,
        year: int | None = None,
        month: int | None = None,
        days: int | None = None,
    ) -> list:
        return await build_revenue_timeseries(
            granularity, days=days, year=year, month=month
        )

    start_scheduler(db, _build_timeseries)


@app.on_event("shutdown")
async def shutdown_db_client() -> None:
    from scheduler import stop_scheduler
    stop_scheduler()
    client.close()
