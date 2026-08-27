"""
Pydantic v2 schemas for every table in Project Flow.

Convention
----------
*  `*Create` — request body for POST (server-generated fields omitted).
*  `*Update` — request body for PATCH (all fields optional).
*  `*Read`   — response model (includes id + timestamps).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ── helpers ──────────────────────────────────────────────────

class _TimestampMixin(BaseModel):
    created_at: datetime | None = None


# ── product_groups ───────────────────────────────────────────

class ProductGroupCreate(BaseModel):
    canonical_sku: str | None = None
    model_name: str


class ProductGroupRead(_TimestampMixin):
    id: UUID
    canonical_sku: str | None = None
    model_name: str


# ── products ─────────────────────────────────────────────────

class ProductCreate(BaseModel):
    shopify_product_id: str
    title: str
    price: float
    sku: str | None = None
    vendor: str | None = None
    category: str | None = None
    product_group_id: UUID | None = None
    raw_shopify_data: dict[str, Any] | None = None


class ProductRead(_TimestampMixin):
    id: UUID
    shopify_product_id: str
    title: str
    price: float
    sku: str | None = None
    vendor: str | None = None
    category: str | None = None
    product_group_id: UUID | None = None
    raw_shopify_data: dict[str, Any] | None = None
    updated_at: datetime | None = None


# ── merchants ────────────────────────────────────────────────

class MerchantCreate(BaseModel):
    name: str
    shopify_vendor_name: str
    margin_floor_pct: float | None = None
    stock_data: dict[str, Any] | None = None
    accessory_inventory: dict[str, Any] | None = None
    warranty_cost_data: dict[str, Any] | None = None
    is_active: bool = True


class MerchantUpdate(BaseModel):
    name: str | None = None
    margin_floor_pct: float | None = None
    stock_data: dict[str, Any] | None = None
    accessory_inventory: dict[str, Any] | None = None
    warranty_cost_data: dict[str, Any] | None = None
    is_active: bool | None = None


class MerchantRead(_TimestampMixin):
    id: UUID
    name: str
    shopify_vendor_name: str
    margin_floor_pct: float | None = None
    stock_data: dict[str, Any] | None = None
    accessory_inventory: dict[str, Any] | None = None
    warranty_cost_data: dict[str, Any] | None = None
    is_active: bool = True


# ── merchant_products ────────────────────────────────────────

class MerchantProductCreate(BaseModel):
    merchant_id: UUID
    shopify_product_id: str
    product_group_id: UUID | None = None


class MerchantProductRead(BaseModel):
    id: UUID
    merchant_id: UUID
    shopify_product_id: str
    product_group_id: UUID | None = None


# ── carts ────────────────────────────────────────────────────

class CartCreate(BaseModel):
    shopify_checkout_id: str
    customer_email: str | None = None
    status: str = "active"


class CartRead(_TimestampMixin):
    id: UUID
    shopify_checkout_id: str
    customer_email: str | None = None
    status: str
    abandoned_at: datetime | None = None
    converted_at: datetime | None = None


# ── demand_signals ───────────────────────────────────────────

class DemandSignalCreate(BaseModel):
    cart_id: UUID
    product_id: UUID
    product_group_id: UUID | None = None
    merchant_id: UUID | None = None
    quantity: int = 1
    status: str = "pending"


class DemandSignalRead(_TimestampMixin):
    id: UUID
    cart_id: UUID
    product_id: UUID
    product_group_id: UUID | None = None
    merchant_id: UUID | None = None
    quantity: int
    status: str


# ── demand_pools ─────────────────────────────────────────────

class DemandPoolCreate(BaseModel):
    product_group_id: UUID
    signal_count: int = 0
    status: str = "open"
    threshold: int = 1


class DemandPoolRead(_TimestampMixin):
    id: UUID
    product_group_id: UUID
    signal_count: int
    status: str
    threshold: int
    updated_at: datetime | None = None


# ── merchant_documents ───────────────────────────────────────

class MerchantDocumentCreate(BaseModel):
    merchant_id: UUID
    file_name: str | None = None
    file_url: str | None = None
    extracted_text: str | None = None


class MerchantDocumentRead(BaseModel):
    id: UUID
    merchant_id: UUID
    file_name: str | None = None
    file_url: str | None = None
    extracted_text: str | None = None
    uploaded_at: datetime | None = None


# ── product_embeddings ───────────────────────────────────────

class ProductEmbeddingCreate(BaseModel):
    product_id: UUID
    metadata: dict[str, Any] | None = None


class ProductEmbeddingRead(BaseModel):
    id: UUID
    product_id: UUID
    metadata: dict[str, Any] | None = None


# ── offer_archetypes ─────────────────────────────────────────

class OfferArchetypeCreate(BaseModel):
    description: str | None = None


class OfferArchetypeRead(BaseModel):
    id: UUID
    description: str | None = None


# ── offers ───────────────────────────────────────────────────

class OfferCreate(BaseModel):
    demand_pool_id: UUID
    merchant_id: UUID
    offer_type: str
    price: float | None = None
    bundled_items: dict[str, Any] | None = None
    description: str | None = None
    strategy_reasoning: dict[str, Any] | None = None
    status: str = "candidate"


class OfferRead(_TimestampMixin):
    id: UUID
    demand_pool_id: UUID
    merchant_id: UUID
    offer_type: str
    price: float | None = None
    bundled_items: dict[str, Any] | None = None
    description: str | None = None
    strategy_reasoning: dict[str, Any] | None = None
    status: str


# ── orders ───────────────────────────────────────────────────

class OrderCreate(BaseModel):
    offer_id: UUID
    shopify_order_id: str | None = None
    status: str = "pending_payment"


class OrderRead(_TimestampMixin):
    id: UUID
    offer_id: UUID
    shopify_order_id: str | None = None
    status: str
    updated_at: datetime | None = None


# ── payments ─────────────────────────────────────────────────

class PaymentCreate(BaseModel):
    order_id: UUID
    razorpay_payment_link_id: str | None = None
    razorpay_payment_id: str | None = None
    amount: float | None = None
    status: str = "created"
    raw_webhook_payload: dict[str, Any] | None = None


class PaymentRead(_TimestampMixin):
    id: UUID
    order_id: UUID
    razorpay_payment_link_id: str | None = None
    razorpay_payment_id: str | None = None
    amount: float | None = None
    status: str
    raw_webhook_payload: dict[str, Any] | None = None
