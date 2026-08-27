# Project Flow — Backend Skeleton

Multi-vendor agentic demand-recovery marketplace on Shopify.  
**This layer covers the data schema and CRUD API only — no business logic.**

---

## Quick start

### 1. Environment

```bash
cp .env.example .env
# Fill in your Supabase, Shopify, Razorpay, and OpenRouter credentials.
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run database migrations

Open the **Supabase SQL Editor** (Dashboard → SQL Editor) and execute, in order:

```
app/migrations/001_init_schema.sql
app/migrations/002_enable_pgvector.sql
```

> **Note:** `pgvector` must be enabled on your Supabase project. Free-tier projects
> include it by default. The migration runs `CREATE EXTENSION IF NOT EXISTS vector;`.

### 4. Start the server

```bash
uvicorn app.main:app --reload --port 8000
```

Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)

### 5. Docker

```bash
docker build -t project-flow .
docker run -p 8000:8000 --env-file .env project-flow
```

---

## Project structure

```
app/
├── main.py                  # FastAPI app + router registration
├── config.py                # pydantic-settings (reads .env)
├── db/
│   └── client.py            # Supabase client singleton
├── models/
│   └── schemas.py           # Pydantic v2 models (Create/Read/Update)
├── routers/
│   ├── health.py            # GET /health
│   ├── products.py          # GET/POST /products, GET /products/{id}
│   ├── merchants.py         # GET/POST /merchants, PATCH /merchants/{id}
│   ├── product_groups.py    # GET/POST /product-groups, GET /product-groups/{id}/merchants
│   ├── demand.py            # GET /demand-pools, GET /demand-pools/{id}/eligible-merchants
│   ├── offers.py            # GET /offers?pool_id=, GET /offers/{id}
│   ├── orders.py            # GET /orders/{id}
│   ├── payments.py          # GET /payments/{id}
│   └── shopify.py           # GET /shopify/vendors
├── services/
│   ├── products.py          # CRUD for products
│   ├── merchants.py         # CRUD for merchants
│   ├── product_groups.py    # CRUD + merchant resolution
│   ├── demand.py            # CRUD for demand signals/pools
│   ├── offers.py            # CRUD for offers
│   ├── orders.py            # CRUD for orders
│   ├── payments.py          # CRUD for payments
│   └── shopify.py           # Shopify Admin API proxy
└── migrations/
    ├── 001_init_schema.sql  # Full relational schema
    └── 002_enable_pgvector.sql  # pgvector extension + vector columns + HNSW indexes
```

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/products` | List products |
| POST | `/products` | Create product |
| GET | `/products/{id}` | Get product by ID |
| GET | `/merchants` | List merchants |
| POST | `/merchants` | Create merchant |
| PATCH | `/merchants/{id}` | Partial update merchant |
| GET | `/product-groups` | List product groups |
| POST | `/product-groups` | Create product group |
| GET | `/product-groups/{id}/merchants` | Competing merchants for a model |
| GET | `/shopify/vendors` | Distinct Shopify vendor names |
| GET | `/demand-pools` | List demand pools |
| GET | `/demand-pools/{id}` | Get demand pool |
| GET | `/demand-pools/{id}/eligible-merchants` | Merchants who can bid |
| GET | `/offers?pool_id=` | List offers (optional pool filter) |
| GET | `/offers/{id}` | Get offer by ID |
| GET | `/orders/{id}` | Get order by ID |
| GET | `/payments/{id}` | Get payment by ID |

---

## pgvector similarity query — test snippet

After running both migrations, test that pgvector works in the Supabase SQL Editor:

```sql
-- Insert a test embedding
INSERT INTO product_embeddings (product_id, embedding, metadata)
VALUES (
  (SELECT id FROM products LIMIT 1),
  -- 1024-dim vector (truncated here for readability; use a real embedding in practice)
  '[' || array_to_string(array(SELECT random() FROM generate_series(1, 1024)), ',') || ']',
  '{"source": "test"}'
);

-- Cosine-similarity search: find the 5 nearest product embeddings
SELECT
    pe.id,
    pe.product_id,
    1 - (pe.embedding <=> '[' || array_to_string(array(SELECT random() FROM generate_series(1, 1024)), ',') || ']'::vector) AS similarity
FROM product_embeddings pe
ORDER BY pe.embedding <=> '[' || array_to_string(array(SELECT random() FROM generate_series(1, 1024)), ',') || ']'::vector
LIMIT 5;
```

The `<=>` operator uses the **cosine distance** metric — `1 - cosine_distance` gives
you similarity in `[0, 1]`. The HNSW index created in `002_enable_pgvector.sql`
accelerates this query automatically.

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | ✅ | Supabase project URL |
| `SUPABASE_KEY` | ✅ | Supabase anon/service-role key |
| `RAZORPAY_KEY_ID` | | Razorpay API key ID |
| `RAZORPAY_KEY_SECRET` | | Razorpay API key secret |
| `OPENROUTER_API_KEY` | | OpenRouter API key (LLM gateway) |
| `SHOPIFY_STORE_URL` | | Shopify store URL (e.g. `https://store.myshopify.com`) |
| `SHOPIFY_ADMIN_TOKEN` | | Shopify Admin API access token |
| `PORT` | | Server port (default: 8000) |
