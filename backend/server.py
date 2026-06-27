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


app = FastAPI(title="Resilience Brothers P2P")
api_router = APIRouter(prefix="/api")


@api_router.get("/", tags=["System"])
async def root():
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
async def start_background_jobs():
    """Wire up APScheduler. Wrap build_revenue_timeseries to expose it to
    scheduler.py without importing server.py (which would be circular)."""
    from scheduler import start_scheduler

    async def _build_timeseries(granularity, year=None, month=None, days=None):
        return await build_revenue_timeseries(
            granularity, days=days, year=year, month=month
        )

    start_scheduler(db, _build_timeseries)


@app.on_event("shutdown")
async def shutdown_db_client():
    from scheduler import stop_scheduler
    stop_scheduler()
    client.close()
