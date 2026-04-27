"""
PriceHound — entry point.

Start with:
    uvicorn main:app --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from database.connection import create_pool, init_db, close_pool
from services.scheduler import start_scheduler, stop_scheduler
from auth.routes import router as auth_router
from api.products import router as products_router, seed_demo_products
from api.alerts import router as alerts_router
from api.dashboard import router as dashboard_router
from api.debug import router as debug_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic for the FastAPI app."""
    # ── Startup ───────────────────────────────────────────────────────────────
    logger.info("Starting PriceHound …")
    pool = await create_pool()
    await init_db(pool)
    await seed_demo_products()
    start_scheduler()
    logger.info("PriceHound is ready.")

    yield  # app runs here

    # ── Shutdown ──────────────────────────────────────────────────────────────
    stop_scheduler()
    await close_pool()
    logger.info("PriceHound shut down cleanly.")


app = FastAPI(
    title="PriceHound",
    description="Price tracking with AI insights",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
# Permissive in development; tighten origins in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API routers ───────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(products_router)
app.include_router(alerts_router)
app.include_router(dashboard_router)
app.include_router(debug_router)


# ── HTML page routes (explicit, so they don't conflict with /static) ──────────

_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse("static/index.html", headers=_NO_CACHE)


@app.get("/product", include_in_schema=False)
async def product_page():
    return FileResponse("static/product.html", headers=_NO_CACHE)


@app.get("/dashboard", include_in_schema=False)
async def dashboard_page():
    return FileResponse("static/dashboard.html", headers=_NO_CACHE)


@app.get("/login", include_in_schema=False)
async def login_page():
    return FileResponse("static/login.html", headers=_NO_CACHE)


# ── Static assets ─────────────────────────────────────────────────────────────
# Mount last so API routes are matched first.
app.mount("/static", StaticFiles(directory="static"), name="static")
