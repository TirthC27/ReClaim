"""
Project Flow — FastAPI application entry-point.

Registers all routers and configures CORS for local dev.
"""

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
)

app = FastAPI(
    title="Project Flow",
    description="Multi-vendor agentic demand-recovery marketplace — backend skeleton",
    version="0.1.0",
)

# ── CORS (permissive for local dev) ──────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
