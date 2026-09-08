# PROJECT_CONTEXT Snapshot
## 1. Directory Tree
```├── .env.example
├── .gitignore
├── Dockerfile
├── README.md
├── app
│   ├── __init__.py
│   ├── config.py
│   ├── db
│   │   ├── __init__.py
│   │   └── client.py
│   ├── main.py
│   ├── migrations
│   │   ├── 001_init_schema.sql
│   │   ├── 002_enable_pgvector.sql
│   │   ├── 003_add_selected_merchants.sql
│   │   ├── 004_offer_engine_schema.sql
│   │   ├── 005_orders_payment_columns.sql
│   │   └── 005_orders_payment_sync.sql
│   ├── models
│   │   ├── __init__.py
│   │   └── schemas.py
│   ├── routers
│   │   ├── __init__.py
│   │   ├── demand.py
│   │   ├── health.py
│   │   ├── merchant_documents.py
│   │   ├── merchant_onboarding.py
│   │   ├── merchants.py
│   │   ├── offer_generation.py
│   │   ├── offers.py
│   │   ├── orders.py
│   │   ├── payments.py
│   │   ├── product_groups.py
│   │   ├── products.py
│   │   ├── razorpay_webhooks.py
│   │   ├── shopify.py
│   │   └── webhooks.py
│   └── services
│       ├── __init__.py
│       ├── abandonment_worker.py
│       ├── aggregation.py
│       ├── allocation.py
│       ├── demand.py
│       ├── embeddings.py
│       ├── llm_client.py
│       ├── merchant_documents.py
│       ├── merchant_onboarding.py
│       ├── merchants.py
│       ├── offer_engine.py
│       ├── offer_selection.py
│       ├── offers.py
│       ├── order_sync.py
│       ├── orders.py
│       ├── payments.py
│       ├── product_groups.py
│       ├── products.py
│       ├── rag_retrieval.py
│       ├── razorpay_payments.py
│       ├── shopify.py
│       ├── shopify_auth.py
│       ├── shopify_orders.py
│       └── webhooks.py
├── merchant-dashboard
│   ├── .gitignore
│   ├── .oxlintrc.json
│   ├── README.md
│   ├── index.html
│   ├── package-lock.json
│   ├── package.json
│   ├── public
│   │   ├── favicon.svg
│   │   └── icons.svg
│   ├── src
│   │   ├── App.css
│   │   ├── App.jsx
│   │   ├── api.js
│   │   ├── assets
│   │   │   ├── hero.png
│   │   │   ├── react.svg
│   │   │   └── vite.svg
│   │   ├── components
│   │   │   ├── DocumentUpload.jsx
│   │   │   ├── ProductLinking.jsx
│   │   │   └── SignupForm.jsx
│   │   ├── contexts
│   │   │   └── DemoSessionContext.jsx
│   │   ├── index.css
│   │   ├── main.jsx
│   │   ├── pages
│   │   │   ├── AllocationView.jsx
│   │   │   ├── DemandDashboard.jsx
│   │   │   ├── MerchantCompetition.jsx
│   │   │   ├── MerchantOnboarding.jsx
│   │   │   ├── OfferMarketplace.jsx
│   │   │   └── PaymentSuccess.jsx
│   │   └── supabaseClient.js
│   └── vite.config.js
└── requirements.txt
```
## 2. Schema / Migration Files
### 001_init_schema.sql
```sql
-- =============================================================
-- 001_init_schema.sql  –  Project Flow: full relational schema
-- Run against your Supabase Postgres instance.
-- =============================================================

-- ── product_groups ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS product_groups (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_sku   TEXT UNIQUE,
    model_name      TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ── products ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS products (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shopify_product_id  TEXT UNIQUE NOT NULL,
    title               TEXT NOT NULL,
    price               NUMERIC(10,2) NOT NULL,
    sku                 TEXT UNIQUE,
    vendor              TEXT,
    category            TEXT,
    product_group_id    UUID REFERENCES product_groups(id) ON DELETE SET NULL,
    raw_shopify_data    JSONB,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

-- ── merchants ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS merchants (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                 TEXT NOT NULL,
    shopify_vendor_name  TEXT UNIQUE NOT NULL,
    margin_floor_pct     NUMERIC(5,2),
    stock_data           JSONB,
    accessory_inventory  JSONB,
    warranty_cost_data   JSONB,
    is_active            BOOLEAN DEFAULT true,
    created_at           TIMESTAMPTZ DEFAULT now()
);

-- ── merchant_products (join table) ──────────────────────────
CREATE TABLE IF NOT EXISTS merchant_products (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id         UUID NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    shopify_product_id  TEXT NOT NULL,
    product_group_id    UUID REFERENCES product_groups(id) ON DELETE SET NULL,
    UNIQUE (merchant_id, shopify_product_id)
);

-- ── carts ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS carts (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shopify_checkout_id  TEXT UNIQUE NOT NULL,
    customer_email       TEXT,
    created_at           TIMESTAMPTZ DEFAULT now(),
    abandoned_at         TIMESTAMPTZ,
    converted_at         TIMESTAMPTZ,
    status               TEXT DEFAULT 'active'
                         CHECK (status IN ('active','abandoned','converted'))
);

-- ── demand_signals ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS demand_signals (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cart_id           UUID NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
    product_id        UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    product_group_id  UUID REFERENCES product_groups(id) ON DELETE SET NULL,
    merchant_id       UUID REFERENCES merchants(id) ON DELETE SET NULL,
    quantity          INT DEFAULT 1,
    status            TEXT DEFAULT 'pending'
                      CHECK (status IN ('pending','abandoned','pooled','expired')),
    created_at        TIMESTAMPTZ DEFAULT now()
);

-- ── demand_pools ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS demand_pools (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_group_id  UUID NOT NULL REFERENCES product_groups(id) ON DELETE CASCADE,
    signal_count      INT DEFAULT 0,
    status            TEXT DEFAULT 'open'
                      CHECK (status IN ('open','offers_generated','closed')),
    threshold         INT DEFAULT 1,
    created_at        TIMESTAMPTZ DEFAULT now(),
    updated_at        TIMESTAMPTZ DEFAULT now()
);

-- ── merchant_documents ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS merchant_documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id     UUID NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    file_name       TEXT,
    file_url        TEXT,
    extracted_text  TEXT,
    -- embedding column created in 002_enable_pgvector.sql
    uploaded_at     TIMESTAMPTZ DEFAULT now()
);

-- ── product_embeddings ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS product_embeddings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id  UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    -- embedding column created in 002_enable_pgvector.sql
    metadata    JSONB
);

-- ── offer_archetypes ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS offer_archetypes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    description TEXT
    -- embedding column created in 002_enable_pgvector.sql
);

-- ── offers ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS offers (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    demand_pool_id      UUID NOT NULL REFERENCES demand_pools(id) ON DELETE CASCADE,
    merchant_id         UUID NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    offer_type          TEXT CHECK (offer_type IN (
                            'discount','gift','bundle','warranty',
                            'upgrade','service','hybrid'
                        )),
    price               NUMERIC(10,2),
    bundled_items       JSONB,
    description         TEXT,
    strategy_reasoning  JSONB,
    status              TEXT DEFAULT 'candidate'
                        CHECK (status IN (
                            'candidate','validated','rejected',
                            'selected','expired'
                        )),
    created_at          TIMESTAMPTZ DEFAULT now()
);

-- ── orders ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS orders (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    offer_id          UUID NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
    shopify_order_id  TEXT,
    status            TEXT CHECK (status IN (
                          'pending_payment','paid','order_created','failed'
                      )),
    created_at        TIMESTAMPTZ DEFAULT now(),
    updated_at        TIMESTAMPTZ DEFAULT now()
);

-- ── payments ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS payments (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id                  UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    razorpay_payment_link_id  TEXT,
    razorpay_payment_id       TEXT,
    amount                    NUMERIC(10,2),
    status                    TEXT DEFAULT 'created'
                              CHECK (status IN ('created','paid','failed')),
    raw_webhook_payload       JSONB,
    created_at                TIMESTAMPTZ DEFAULT now()
);

-- ── Indexes ─────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_carts_status           ON carts(status);
CREATE INDEX IF NOT EXISTS idx_demand_signals_status   ON demand_signals(status);
CREATE INDEX IF NOT EXISTS idx_demand_pools_status     ON demand_pools(status);
CREATE INDEX IF NOT EXISTS idx_offers_status           ON offers(status);
CREATE INDEX IF NOT EXISTS idx_merchant_products_group ON merchant_products(product_group_id);

```
### 002_enable_pgvector.sql
```sql
-- =============================================================
-- 002_enable_pgvector.sql  –  pgvector extension + columns + indexes
-- Run AFTER 001_init_schema.sql
-- =============================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- ── Add vector columns ──────────────────────────────────────
ALTER TABLE merchant_documents
    ADD COLUMN IF NOT EXISTS embedding vector(1024);

ALTER TABLE product_embeddings
    ADD COLUMN IF NOT EXISTS embedding vector(1024);

ALTER TABLE offer_archetypes
    ADD COLUMN IF NOT EXISTS embedding vector(1024);

-- ── HNSW indexes for cosine similarity ──────────────────────
-- HNSW is preferred over IVFFlat for most workloads (no training step).
CREATE INDEX IF NOT EXISTS idx_merchant_docs_embedding
    ON merchant_documents
    USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_product_embeddings_embedding
    ON product_embeddings
    USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_offer_archetypes_embedding
    ON offer_archetypes
    USING hnsw (embedding vector_cosine_ops);

```
### 003_add_selected_merchants.sql
```sql
-- =============================================================
-- 003_add_selected_merchants.sql
-- Adds selected_merchant_ids column to demand_pools for
-- Section 9A merchant selection results.
-- =============================================================

ALTER TABLE demand_pools
    ADD COLUMN IF NOT EXISTS selected_merchant_ids JSONB;

```
### 004_offer_engine_schema.sql
```sql
-- =============================================================
-- 004_offer_engine_schema.sql
-- Adds columns/tables for the RAG offer engine + 9A.2 fairness
-- =============================================================

-- ── offers: add RAG context + value score ───────────────────
ALTER TABLE offers
    ADD COLUMN IF NOT EXISTS rag_context_used JSONB,
    ADD COLUMN IF NOT EXISTS value_score NUMERIC(10,4);

-- ── demand_pools: add rotation order for 9A.2 ──────────────
ALTER TABLE demand_pools
    ADD COLUMN IF NOT EXISTS rotation_order JSONB;

-- ── order_allocations (9A.2 round-robin assignments) ────────
CREATE TABLE IF NOT EXISTS order_allocations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    demand_pool_id      UUID NOT NULL REFERENCES demand_pools(id) ON DELETE CASCADE,
    demand_signal_id    UUID NOT NULL REFERENCES demand_signals(id) ON DELETE CASCADE,
    merchant_id         UUID NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    rotation_position   INT,
    created_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_order_allocations_pool
    ON order_allocations(demand_pool_id);

```
### 005_orders_payment_columns.sql
```sql
-- =============================================================
-- 005_orders_payment_columns.sql
-- Adds columns to orders for allocation tracking and retry logic
-- =============================================================

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS demand_signal_id UUID REFERENCES demand_signals(id),
    ADD COLUMN IF NOT EXISTS merchant_id UUID REFERENCES merchants(id),
    ADD COLUMN IF NOT EXISTS order_creation_failed BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS last_shopify_error TEXT;

```
### 005_orders_payment_sync.sql
```sql
-- =============================================================
-- 005_orders_payment_sync.sql
-- Adds order linkage + retry flags for Razorpay → Shopify sync
-- =============================================================

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS demand_signal_id UUID REFERENCES demand_signals(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS merchant_id UUID REFERENCES merchants(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS order_creation_failed BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS last_shopify_error TEXT;

CREATE INDEX IF NOT EXISTS idx_orders_status_retry
    ON orders(status, order_creation_failed);


```
## 3. Pydantic Models (Schemas)
### schemas.py
```python
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
    selected_merchant_ids: list[str] | None = None
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

class OfferSelectRequest(BaseModel):
    demand_signal_id: UUID


class OfferSelectResponse(BaseModel):
    order_id: UUID
    payment_link_url: str


class OrderCreate(BaseModel):
    offer_id: UUID
    demand_signal_id: UUID | None = None
    merchant_id: UUID | None = None
    shopify_order_id: str | None = None
    status: str = "pending_payment"
    order_creation_failed: bool | None = None
    last_shopify_error: str | None = None


class OrderRead(_TimestampMixin):
    id: UUID
    offer_id: UUID
    demand_signal_id: UUID | None = None
    merchant_id: UUID | None = None
    shopify_order_id: str | None = None
    status: str
    order_creation_failed: bool | None = None
    last_shopify_error: str | None = None
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

```
## 4. API Routes
### demand.py
```python
@router.get("")
def list_demand_pools(limit, offset):

@router.get("/{pool_id}")
def get_demand_pool(pool_id):

@router.get("/{pool_id}/eligible-merchants")
def eligible_merchants(pool_id):

@router.get("/{pool_id}/selected-merchants")
def selected_merchants(pool_id):
```
### health.py
```python
@router.get("/health")
def health_check():
```
### merchant_documents.py
```python
@router.post("/{merchant_id}/documents")
def upload_document(merchant_id, file):

@router.get("/{merchant_id}/documents")
def list_documents(merchant_id):
```
### merchant_onboarding.py
```python
@router.post("/onboard")
def onboard_merchant(body):

@router.get("/{merchant_id}/shopify-products")
def get_shopify_products(merchant_id):

@router.post("/{merchant_id}/link-products")
def link_products(merchant_id, body):
```
### merchants.py
```python
@router.get("")
def list_merchants(limit, offset):

@router.post("")
def create_merchant(body):

@router.patch("/{merchant_id}")
def update_merchant(merchant_id, body):
```
### offer_generation.py
```python
@router.post("/demand-pools/{pool_id}/generate-offers")
def generate_offers(pool_id):

@router.get("/demand-pools/{pool_id}/allocations")
def get_allocations(pool_id):
```
### offers.py
```python
@router.get("")
def list_offers(pool_id, status, limit, offset):

@router.get("/{offer_id}")
def get_offer(offer_id):

@router.post("/{offer_id}/select")
def select_offer(offer_id, body):
```
### orders.py
```python
@router.get("/{order_id}")
def get_order(order_id):
```
### payments.py
```python
@router.get("/{payment_id}")
def get_payment(payment_id):
```
### product_groups.py
```python
@router.get("")
def list_product_groups(limit, offset):

@router.post("")
def create_product_group(body):

@router.get("/{group_id}/merchants")
def get_merchants_for_group(group_id):
```
### products.py
```python
@router.get("")
def list_products(limit, offset):

@router.get("/{product_id}")
def get_product(product_id):

@router.post("")
def create_product(body):
```
### razorpay_webhooks.py
```python
@router.post("/payment-link-paid")
def payment_link_paid(request):
```
### shopify.py
```python
@router.get("/vendors")
def get_vendors():
```
### webhooks.py
```python
@router.post("/checkout-create")
def webhook_checkout_create(request):

@router.post("/order-create")
def webhook_order_create(request):
```
## 5. .env.example
```bash
# Project Flow (ReClaim) — Full .env template
# ──────────────────────────────────────────────────────────────

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-anon-or-service-role-key

# Razorpay (Test Mode)
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxx
RAZORPAY_KEY_SECRET=your-razorpay-key-secret
RAZORPAY_WEBHOOK_SECRET=your-razorpay-webhook-signing-secret

# Frontend base URL (for Razorpay callback_url)
FRONTEND_BASE_URL=http://localhost:5173

# OpenRouter (LLM gateway + embeddings)
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxx

# Shopify
SHOPIFY_STORE_URL=https://your-store.myshopify.com
SHOPIFY_ADMIN_TOKEN=shpat_xxxxxxxxxxxx
SHOPIFY_CLIENT_ID=your-shopify-client-id
SHOPIFY_CLIENT_SECRET=shpss_xxxxxxxxxxxx
SHOPIFY_WEBHOOK_SECRET=your-shopify-webhook-signing-secret

# Abandonment detection (minutes — 1-2 for demo, 10+ for production)
ABANDONMENT_TIMEOUT_MINUTES=2

# Section 9A merchant selection
SMALL_POOL_THRESHOLD=5
DEMAND_PER_MERCHANT=5
TIE_TOLERANCE_PCT=3.0

# Server
PORT=8000

```
## 6. Dependencies
### requirements.txt
```text
fastapi>=0.111,<1
uvicorn[standard]>=0.30,<1
supabase>=2.5,<3
pydantic>=2,<3
pydantic-settings>=2,<3
python-dotenv>=1,<2
requests>=2.31,<3
python-multipart>=0.0.9
pypdf>=4,<5
python-docx>=1,<2
apscheduler>=3.10,<4
razorpay>=1.4,<2
tenacity>=8.2,<10

```
### merchant-dashboard/package.json
```json
{
  "name": "merchant-dashboard",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "lint": "oxlint",
    "preview": "vite preview"
  },
  "dependencies": {
    "@supabase/supabase-js": "^2.112.4",
    "react": "^19.2.8",
    "react-dom": "^19.2.8",
    "react-router-dom": "^7.18.2"
  },
  "devDependencies": {
    "@types/react": "^19.2.18",
    "@types/react-dom": "^19.2.4",
    "@vitejs/plugin-react": "^6.1.0",
    "oxlint": "^1.79.0",
    "vite": "^8.2.2"
  }
}

```
## 7. Implementation Status

### What's Implemented:
- Prompt 1: Database schema (tables for merchants, demand pools, offers, etc.) and basic FastAPI setup.
- Prompt 2: Merchant onboarding API, Shopify vendor syncing, document uploads, and product mapping logic.
- Prompt 3: Shopify webhooks (checkout-create and order-create) integration, demand aggregation (bundling abandoned carts), and the APScheduler background job for checking abandonment timeout.
- Prompt 4: Multi-Agent LLM Offer Engine (Strategy + Composer), PGVector RAG integration, and Section 9A.2 fair round-robin allocation logic for resolving tied offers.
- Prompt 5: Razorpay payment links generation, idempotent webhook handling for `payment_link.paid`, Shopify order auto-creation post payment, and a full React Router frontend (Dashboard, Competition View, Marketplace, Allocation transparency, Payment Success).

### What's Stubbed/Incomplete:
- All 5 prompts have been fully implemented according to the specifications. 
- While production deployment details (e.g. Supabase Edge Functions instead of APScheduler, or a true Celery queue) are stubbed out in favor of in-process task queues for hackathon scope, the core logic as requested is fully intact and functional.
- The only manual steps remaining are setting the external API keys (Shopify, Razorpay, OpenRouter, Supabase) and registering the Shopify webhook in the store admin.
