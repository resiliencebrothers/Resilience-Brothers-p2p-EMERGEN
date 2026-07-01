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
import os
from pathlib import Path

from fastapi import APIRouter, FastAPI
from starlette.middleware.cors import CORSMiddleware
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

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


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

    # iter55.3 — one-shot idempotent migration: strip whitespace from currency
    # codes so data-entry typos ("CUP ") don't break catalog lookups.
    try:
        async for row in db.currencies.find(
            {"code": {"$regex": r"^\s|\s$"}},
            {"_id": 0, "id": 1, "code": 1},
        ):
            fixed = (row.get("code") or "").strip().upper()
            if fixed and fixed != row.get("code"):
                await db.currencies.update_one(
                    {"id": row["id"]}, {"$set": {"code": fixed}}
                )
                logger.info(f"Migrated currency code {row['code']!r} → {fixed!r}")
    except Exception as e:  # noqa: BLE001
        logger.error(f"Currency code migration failed: {e}")

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
