"""
Project Flow — FastAPI application entry-point.

Registers all routers, configures CORS, and starts the
abandonment detection scheduler on startup.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import (
    health,
    products,
    merchants,
    product_groups,
    demand,
    offers,
    orders,
    payments,
    shopify,
    merchant_onboarding,
    merchant_documents,
    webhooks,
    razorpay_webhooks,
    offer_generation,
    demand_signals,
)
from app.services.abandonment_worker import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the abandonment scheduler on startup, stop on shutdown."""
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="Project Flow",
    description="Multi-vendor agentic demand-recovery marketplace",
    version="0.2.0",
    lifespan=lifespan,
)

# ── CORS (permissive for local dev) ──────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://reclaim-t5ldhxld.myshopify.com", "http://localhost:5173", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(products.router)
app.include_router(merchants.router)
app.include_router(product_groups.router)
app.include_router(demand.router)
app.include_router(offers.router)
app.include_router(orders.router)
app.include_router(payments.router)
app.include_router(shopify.router)
app.include_router(merchant_onboarding.router)
app.include_router(merchant_documents.router)
app.include_router(webhooks.router)
app.include_router(razorpay_webhooks.router)
app.include_router(offer_generation.router)
app.include_router(demand_signals.router)
