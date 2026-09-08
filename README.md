# ReClaim

ReClaim is a multi-vendor, Shopify-connected cart-recovery marketplace. It detects abandoned carts, groups similar customer demand, asks participating merchants to produce competitive offers, allocates demand fairly, collects payment through Razorpay, and creates the final order in Shopify.

This repository contains:

- A FastAPI backend in `app/`.
- A Supabase/PostgreSQL database schema with pgvector support.
- A React/Vite merchant dashboard in `merchant-dashboard/`.
- Integrations for Shopify, Razorpay, OpenRouter, and Supabase Storage.

> Important: this is currently a hackathon/demo-oriented application. It does not yet provide production-grade authentication, authorization, rate limiting, distributed job processing, or complete automated test coverage. Review [Production readiness](#production-readiness) before deploying it publicly.

## How the system works

```text
Shopify checkout
      |
      | checkout/order webhooks
      v
FastAPI + Uvicorn
      |
      +--> Supabase/PostgreSQL
      |       carts, signals, pools, merchants, offers, orders, payments
      |
      +--> Abandonment scheduler
      |       marks old carts abandoned and aggregates demand
      |
      +--> Offer engine
      |       RAG retrieval + OpenRouter LLMs + offer validation
      |
      +--> Buyer agent / allocation
      |       assigns demand signals to selected merchants
      |
      +--> Razorpay
      |       creates payment links and receives payment webhooks
      |
      +--> Shopify Admin API
              creates the paid merchant order
```

### Core business flow

1. Shopify sends a `checkouts/create` webhook.
2. The backend stores or updates a cart and creates demand signals for its line items.
3. The abandonment worker finds carts inactive longer than `ABANDONMENT_TIMEOUT_MINUTES`.
4. Signals are marked abandoned and grouped into a demand pool by product group.
5. Eligible merchants are selected for the pool.
6. The offer engine uses merchant data, uploaded documents, vector search, and OpenRouter to generate offers.
7. Offers are validated and the buyer agent creates an allocation plan.
8. Customer demand signals are assigned to merchants. Depending on the flow, a Razorpay payment link is created immediately or after a cart recovery is ready.
9. Razorpay sends a signed `payment_link.paid` webhook.
10. The backend records payment success and creates a paid order in Shopify.

## Repository structure

```text
.
├── app/
│   ├── main.py                    # FastAPI app, CORS, routers, scheduler lifecycle
│   ├── config.py                  # Environment-backed settings
│   ├── db/client.py               # Lazy Supabase client singleton
│   ├── models/schemas.py          # Pydantic v2 request/response models
│   ├── routers/                   # HTTP endpoints
│   ├── services/                  # Business logic and external integrations
│   └── migrations/                # SQL schema and function migrations
├── merchant-dashboard/            # React/Vite frontend
├── scripts/                       # Demo/seed scripts
├── Dockerfile                     # Container image for the backend
├── requirements.txt               # Python dependencies
├── API.md                         # Expanded API reference and examples
├── .env.example                   # Environment variable template
```

### Backend layers

The backend mostly follows this structure:

```text
HTTP request -> router -> service -> Supabase or external API -> HTTP response
```

Routers handle HTTP concerns such as path parameters, request parsing, status codes, and expected errors. Services contain business rules and integration logic. Supabase is accessed through `app/db/client.py`, although some workflow-specific routers also query it directly.

## Requirements

- Python 3.11 or newer.
- A Supabase project with PostgreSQL and pgvector enabled.
- Node.js and npm for the merchant dashboard.
- Optional integrations: Shopify Admin API, Razorpay, and OpenRouter.

The backend dependency ranges are defined in [requirements.txt](requirements.txt). The project uses FastAPI 0.111+, Uvicorn 0.30+, Pydantic 2+, Supabase Python client 2.5+, APScheduler 3.10+, and Razorpay 1.4+.

## Backend setup

### 1. Create the environment file

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Fill in `.env`. Never commit `.env` or put real credentials in source code.

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate       # macOS/Linux
```

Windows PowerShell:

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Apply database migrations

Apply these files to the Supabase SQL editor in this dependency order:

```text
001_init_schema.sql
002_enable_pgvector.sql
003_add_selected_merchants.sql
004_offer_engine_schema.sql
005_orders_payment_columns.sql
005_orders_payment_sync.sql
006_buyer_agent.sql
006_vector_search_rpcs.sql
007_cart_recovery.sql
007_demand_signals_traceability.sql
008_negotiation_rounds.sql
```

The duplicate numeric prefixes are historical. Most statements use `IF NOT EXISTS`, but a future cleanup should rename migrations to a unique sequence and introduce migration tracking.

The application expects tables including `products`, `product_groups`, `merchants`, `merchant_products`, `carts`, `demand_signals`, `demand_pools`, `merchant_documents`, `product_embeddings`, `offer_archetypes`, `offers`, `order_allocations`, `orders`, `payments`, `cart_recoveries`, `cart_recovery_items`, and `offer_negotiation_rounds`.

### 5. Start the API

```bash
uvicorn app.main:app --reload --port 8000
```

The API will be available at:

- Application: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- Liveness endpoint: `http://localhost:8000/health`

The server starts an APScheduler worker during application startup. This is convenient locally; see [Background processing](#background-processing) for deployment limitations.

## Environment variables

`app/config.py` reads these values from `.env` using Pydantic Settings.

| Variable | Required | Purpose |
|---|---:|---|
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_KEY` | Yes | Supabase API key; choose permissions carefully |
| `RAZORPAY_KEY_ID` | No | Razorpay API key ID |
| `RAZORPAY_KEY_SECRET` | No | Razorpay API secret |
| `RAZORPAY_WEBHOOK_SECRET` | No* | Razorpay webhook signing secret |
| `FRONTEND_BASE_URL` | No | Frontend URL used in payment callbacks |
| `OPENROUTER_API_KEY` | No | OpenRouter LLM and embedding access |
| `SHOPIFY_STORE_URL` | No | Shopify store base URL |
| `SHOPIFY_ADMIN_TOKEN` | No | Static Shopify Admin API token fallback |
| `SHOPIFY_CLIENT_ID` | No | Shopify client-credentials OAuth ID |
| `SHOPIFY_CLIENT_SECRET` | No | Shopify client-credentials OAuth secret |
| `SHOPIFY_WEBHOOK_SECRET` | No* | Shopify HMAC signing secret |
| `ABANDONMENT_TIMEOUT_MINUTES` | No | Cart timeout; default is 2 minutes for demo use |
| `SMALL_POOL_THRESHOLD` | No | Merchant-selection threshold; default is 5 |
| `DEMAND_PER_MERCHANT` | No | Demand-to-merchant ratio for larger pools |
| `TIE_TOLERANCE_PCT` | No | Offer score tie tolerance; default is 3% |
| `PAYMENT_EXPIRY_HOURS` | No | Payment link lifetime; default is 8 hours |
| `PORT` | No | Configured application port; default is 8000 |

`*` These secrets are optional in the current code, but that is only suitable for a controlled local demo. Production webhook verification must fail closed when a secret is missing.

## API overview

The complete reference is in [API.md](API.md).

### Health

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Returns a basic liveness response |

### Catalog and merchants

| Method | Path | Description |
|---|---|---|
| GET | `/products` | List products |
| POST | `/products` | Create a product |
| GET | `/products/{product_id}` | Get a product |
| GET | `/product-groups` | List product groups |
| GET | `/product-groups/search?q=...` | Search product groups |
| POST | `/product-groups` | Create a product group |
| GET | `/product-groups/{group_id}/merchants` | List competing merchants |
| GET | `/merchants` | List merchants |
| POST | `/merchants` | Create a merchant |
| PATCH | `/merchants/{merchant_id}` | Update a merchant |
| POST | `/merchants/onboard` | Create an onboarded merchant |
| GET | `/merchants/{merchant_id}/shopify-products` | Load Shopify products |
| POST | `/merchants/{merchant_id}/link-products` | Link products to groups |
| POST | `/merchants/{merchant_id}/documents` | Upload a merchant document |
| GET | `/merchants/{merchant_id}/documents` | List merchant documents |

### Demand and offers

| Method | Path | Description |
|---|---|---|
| GET | `/demand-pools` | List demand pools |
| GET | `/demand-pools/{pool_id}` | Get a demand pool |
| GET | `/demand-pools/{pool_id}/signals` | View signals and allocations |
| GET | `/demand-pools/{pool_id}/eligible-merchants` | Resolve eligible merchants |
| GET | `/demand-pools/{pool_id}/selected-merchants` | View selected merchants |
| POST | `/demand-pools/{pool_id}/generate-offers` | Generate offers and allocate demand |
| GET | `/demand-pools/{pool_id}/allocations` | View allocations |
| POST | `/demand-pools/{pool_id}/negotiate` | Run multi-round negotiation |
| GET | `/demand-pools/{pool_id}/negotiation-rounds` | View negotiation rounds |
| GET | `/offers` | List offers with optional filters |
| GET | `/offers/{offer_id}` | Get an offer |
| POST | `/offers/{offer_id}/select` | Create an order and payment link |
| GET | `/demand-signals/{signal_id}/offer` | Get the allocated offer |

### Orders, recovery, and payments

| Method | Path | Description |
|---|---|---|
| GET | `/orders/{order_id}` | Get an order |
| GET | `/payments/{payment_id}` | Get a payment |
| GET | `/cart-recoveries/{recovery_id}/summary` | Get a recovery summary |
| POST | `/cart-recoveries/{recovery_id}/checkout` | Create a recovery payment link |

### Webhooks and integrations

| Method | Path | Description |
|---|---|---|
| GET | `/shopify/vendors` | List distinct Shopify vendors |
| POST | `/webhooks/shopify/checkout-create` | Receive Shopify checkout events |
| POST | `/webhooks/shopify/order-create` | Mark a cart converted |
| POST | `/webhooks/razorpay/payment-link-paid` | Process a paid Razorpay link |

### Demo endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/demo/simulate-bulk-demand` | Generate synthetic carts and demand |
| DELETE | `/demo/cleanup-bulk-demand` | Delete synthetic demo data |

The demo endpoints should not be enabled on a public production deployment.

## Request examples

Create a product group:

```bash
curl -X POST http://localhost:8000/product-groups \
  -H "Content-Type: application/json" \
  -d '{"model_name":"Example Phone","canonical_sku":"example-phone-001"}'
```

Generate offers:

```bash
curl -X POST http://localhost:8000/demand-pools/<POOL_ID>/generate-offers
```

Select an allocated offer:

```bash
curl -X POST http://localhost:8000/offers/<OFFER_ID>/select \
  -H "Content-Type: application/json" \
  -d '{"demand_signal_id":"<SIGNAL_ID>"}'
```

The selection response contains an internal order ID and a Razorpay payment-link URL.

## Data model

```text
product_groups
  └── products

merchants
  └── merchant_products ── product_groups / Shopify listings

carts
  └── demand_signals ── products / product_groups
        └── demand_pools
              ├── offers ── merchants
              └── order_allocations ── demand_signals / merchants

offers
  └── orders
        └── payments

carts
  └── cart_recoveries
        └── cart_recovery_items ── demand_signals / offers
```

PostgreSQL foreign keys and check constraints provide basic integrity. Additional constraints are still needed for idempotency, ownership, money values, and valid state transitions.

## Background processing

[app/services/abandonment_worker.py](app/services/abandonment_worker.py) schedules:

1. `check_abandoned_carts`: marks stale active carts abandoned and aggregates signals.
2. `retry_failed_shopify_orders`: retries paid orders whose Shopify order creation failed.
3. `expire_unpaid_offers`: expires old pending-payment orders and marks payments failed.

The scheduler is started from FastAPI’s lifespan handler in `app/main.py`. This is acceptable for one local process, but unsafe with multiple web workers because every worker may start its own scheduler. Production should use a separate worker or scheduler with durable state and distributed locking.

## External services

### Supabase

Supabase provides PostgreSQL access, document storage, and PostgreSQL functions for vector similarity search. The client is created lazily by `get_supabase()` in `app/db/client.py`.

### Shopify

Shopify is used for product/vendor reads, product metafields, checkout/order webhooks, and final paid-order creation. The code uses client-credentials OAuth when configured and a static admin-token fallback otherwise.

### Razorpay

Razorpay is used to create payment links and verify payment webhooks. Successful payment webhooks update internal payment/order state and start Shopify order creation.

### OpenRouter

OpenRouter supplies LLM and embedding calls for the offer engine. The current code has model fallback and timeouts, but production should add stronger rate-limit handling, usage limits, and observability.

## Merchant documents and RAG

```text
Upload file
  -> Supabase Storage
  -> text extraction
  -> CSV section-aware chunking
  -> embedding generation
  -> merchant_documents row + vector
  -> similarity retrieval during offer generation
```

The current implementation accepts PDF, DOCX/DOC, TXT, CSV, and Markdown extensions. File-size limits, content validation, filename sanitization, malware scanning, cleanup on failure, and authorization still need production hardening.

## Frontend dashboard

The dashboard is a React/Vite application in `merchant-dashboard/`.

```bash
cd merchant-dashboard
npm install
npm run dev
```

Build a production bundle with:

```bash
npm run build
```

The frontend uses the Supabase JavaScript client and calls the FastAPI backend through `merchant-dashboard/src/api.js`. Ensure its API base URL matches the backend and that browser origins match the CORS configuration.

## Docker

Build and run the backend container:

```bash
docker build -t reclaim-api .
docker run --rm -p 8000:8000 --env-file .env reclaim-api
```

The [Dockerfile](Dockerfile) uses Python 3.11, installs `requirements.txt`, copies the repository, and starts Uvicorn on port 8000. The current image does not include a reverse proxy, TLS termination, separate worker, migration runner, or production secret manager.

## Testing and verification

The repository does not yet contain a complete automated test suite. Recommended test priorities are:

1. Shopify and Razorpay signature verification.
2. Offer-selection ownership and cross-pool authorization.
3. Duplicate order/payment prevention.
4. Allocation rules.
5. Payment webhook state transitions.
6. Shopify/Razorpay failure and retry behavior.
7. File upload validation.
8. Database integration tests with a disposable test database.

## Production readiness

Before exposing the API to real customers:

- Add authentication and authorization to all non-webhook routes.
- Restrict access to orders, payments, customer emails, merchant data, and uploaded documents.
- Make Shopify webhook verification fail closed when the secret is missing.
- Rotate credentials that have ever been stored in source files.
- Remove demo endpoints from production.
- Add rate limiting to LLM, payment, upload, and expensive workflow endpoints.
- Add database uniqueness constraints and idempotency keys for order/payment creation.
- Validate webhook event IDs, payment amount, currency, payment-link ID, and replay behavior.
- Move recurring jobs out of the web process or add distributed locking.
- Add structured logging, request IDs, metrics, and error monitoring.
- Avoid returning raw provider exceptions or sensitive payloads to clients.
- Add file-size limits, safe generated filenames, MIME validation, and malware scanning.
- Use a migration tool with a tracked, uniquely ordered migration history.
- Add readiness checks for Supabase and required integrations.
- Review Supabase key permissions and database Row Level Security policies.

## Security note

`.env` is ignored by Git, but secrets can still leak through shell history, logs, backups, screenshots, or helper scripts. Never paste real API keys into issues or documentation. If a credential appears in a tracked file or was shared accidentally, revoke and rotate it immediately.

## Development conventions

- Keep HTTP parsing and response behavior in routers.
- Keep business rules in services.
- Use Pydantic models for public request and response contracts.
- Use bounded validation for money, quantities, statuses, and IDs.
- Use timeouts on every external HTTP request.
- Treat webhook delivery as at-least-once and make processing idempotent.
- Keep demo data and production data separate.
- Add a regression test whenever a business rule or state transition changes.

## Further documentation

- [API.md](API.md): detailed endpoint reference and workflow examples.
- [app/main.py](app/main.py): application initialization and router registration.
- [app/config.py](app/config.py): environment-backed configuration.
- [app/models/schemas.py](app/models/schemas.py): Pydantic schemas.
- [app/migrations/](app/migrations/): database schema history.
