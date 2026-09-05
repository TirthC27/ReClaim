# Project Flow (ReClaim) — Technical Architecture

## 1. One-Paragraph Pitch
ReClaim is an agentic demand-recovery marketplace built on Shopify. Instead of simply sending a generic discount coupon to a single abandoned cart, ReClaim aggregates cart abandonment signals, intelligently groups them into unified demand pools, and forces multiple autonomous merchant AI agents into a competitive live bidding war. A final buyer-side AI agent then evaluates the offers based on pricing, platform policy, and fulfillment coverage, allocating the optimal deal back to the customer via a one-click Razorpay payment link that automatically fulfills the Shopify order.

---

## 2. Architecture Overview
```text
  [Shopify Store]
        │ (Checkout Abandoned Webhook)
        ▼
  [FastAPI Backend] -> [demand_signals table]
        │
        ▼
  [Abandonment Worker (APScheduler)]
        │ (Classifies cart as Single or Multi-Product)
        ├────────────────────────────────────┐
        ▼                                    ▼
  [Single-Product Pool]            [Multi-Product Cart Pool]
  (Aggregates across users)        (Aggregates basket signature)
        │                                    │
        ▼                                    ▼
  [Agent Negotiation Engine (Live SSE Dashboard)]
        │ (2-Round Competitive Bidding + RAG Pricing)
        ▼
  [Buyer Agent / AllocationBuilder]
        │ (Deterministic constraint validation)
        ▼
  [Razorpay Payment Link]
        │ (Customer completes purchase)
        ▼
  [Shopify Order Created (Fulfillment)]
```

---

## 3. Tech Stack

| Layer | Technology | Why it was chosen |
| --- | --- | --- |
| **Backend** | FastAPI | High-performance async support for concurrent LLM agent streams and SSE event pipelines. |
| **Database** | Supabase (Postgres + pgvector) | Instant real-time replication for dashboard subscriptions, and native vector storage for RAG embeddings. |
| **Frontend** | Vite + React | Fast HMR and lightweight component tree for real-time negotiation visualization. |
| **Agent LLMs** | OpenRouter (DeepSeek Chat, GPT-4o-mini) | DeepSeek provides state-of-the-art cost/performance ratio for complex JSON-schema reasoning. |
| **Embeddings** | `liquid/lfm-2.5-embedding-350m:free` | Optimized vector representations for precise row-level merchant quotation lookups. |
| **Payments** | Razorpay | Robust payment links API with expiry handling and payload-rich webhooks. |
| **Commerce** | Shopify Admin API & Webhooks | Native checkout abandonment detection and draft order/transaction finalization. |
| **Tasks** | APScheduler | Lightweight, in-process chron-based execution for cart abandonment aggregation. |

---

## 4. Demand Pooling — Two Architectures

### 4a. Single-Product Pool (original architecture)
When multiple customers abandon carts for the exact same single product, their demand is aggregated into a single `demand_pools` row. This allows merchants to compete on real bulk volume instead of offering one-off discounts, mimicking wholesale economics.
- **Trigger**: `aggregation.py` runs periodically, summing `demand_signals` until a volumetric threshold is hit.
- **Selection**: The `Section 9A` logic uses a two-formula system. Small pools rely on the best single offer (with a floor-of-2 merchants selected to guarantee competition). Massive pools allocate proportional volume across multiple merchants to respect stock limits.
- **Difference from Coupons**: It leverages bulk economics and live merchant bidding, guaranteeing the absolute floor price for the consumer rather than a static 10% off.

### 4b. Multi-Product Cart Pool (newer architecture)
A single customer's cart often contains multiple different products. Naive pooling-by-product fragments one customer's basket across unrelated pools and disparate checkout links.
- **Classification**: `classify_cart()` evaluates if a cart has single or multiple unique product groups.
- **Basket Signature**: Generates a canonical sorted `product_group_id` join, allowing identical multi-item carts to form unified `multi_product_pools`.
- **Ranking**: The platform calculates coverage percentages—how many items in the basket a merchant's inventory can successfully fulfill.
- **Basket Co-occurrences**: By logging `basket_co_occurrences`, the platform builds intelligence on which SKUs are frequently abandoned together.
- **Why Two Architectures?**: There is a structural tension between per-product demand aggregation (which requires cross-customer volume) and per-cart basket coherence (which requires keeping a single user's checkout intact). Building two parallel state machines guarantees optimal pricing logic for both scenarios.

---

## 5. The Agent Stack

### 5a. Merchant Strategy Agent (Step 1)
Determines the pricing strategy. It sees the `demand_pool` volume and outputs a high-level strategy (e.g., "aggressive volume acquisition" vs. "margin preservation").

### 5b. Merchant Offer Composer Agent (Step 2, RAG-augmented)
Composes the actual numerical offer. It reads the Strategy Agent's output, retrieves precise wholesale cost constraints from the RAG pipeline (`quotation_chunks`), checks live Shopify inventory, and outputs a JSON offer with line items.

### 5c. Deterministic Validator (Step 3)
Explicitly NOT an LLM. It guarantees math correctness (subtotal == sum of lines), stock availability, and margin floors, protecting against LLM hallucination before any price is shown to a customer.

### 5d. Buyer Agent (single-product path)
Evaluates validated single-product offers and allocates the aggregated demand volume according to the Section 9A rules.

### 5e. Bundle Seller Agent (multi-product path)
Negotiates the price for an entire basket during a live 2-round bidding war. It sees competitor prices in Round 2, but its actions ("undercut" or "hold") are constrained deterministically by the backend's `absolute_floor_price`.

### 5f. Bundle Buyer Agent (multi-product path)
Evaluates the final multi-merchant bundle offers. It reads the RAG fulfillment policies to apply priority rules (e.g. single-merchant fulfillment bonus vs. split penalty). It outputs an assignment plan which is then processed by a deterministic `AllocationBuilder` to calculate the final math.

---

## 6. RAG Pipeline
The platform ingests CSV vendor quotations, splitting them via row-level chunking into `quotation_chunks`. Documents are embedded using `liquid/lfm-2.5-embedding-350m:free` and stored in a `pgvector` column. Queries execute cosine similarity searches scoped tightly by `merchant_id` and `sku`. Scoping by SKU is critical—an early bug caused cross-contamination where a merchant's pricing for an iPhone influenced their laptop discount simply due to vector proximity. Adding exact-match metadata filters fixed this.

---

## 7. Payment & Fulfillment
Customer allocation generates a Draft Order in Shopify and a Razorpay Payment Link with an 8-hour expiry. When Razorpay confirms the transaction via webhook, the backend uses the Shopify Admin API to inject a transaction array and trigger `send_receipt`, converting the Draft Order to a fully paid Order natively within Shopify. The cart-recovery layer ensures that multi-product carts produce a single consolidated payment link, abstracting the split-merchant complexity away from the buyer.

---

## 8. What's Still Evolving
- **HMAC Verification Hardening**: Razorpay webhook signatures are currently accepted; tightening the timestamp-drift tolerance is required for production.
- **Allocation Constraint Unification**: Enforcing unique index constraints on `order_allocations` to handle edge-case race conditions during simultaneous payment completions.
- **Unified Payment Tracking**: Consolidating single-product and multi-product payment tracking architectures into a single `payment_intents` ledger table.

---

## 9. Demo Script
- **Add to Cart & Abandon**: Add a laptop and a mouse to the Shopify cart, enter an email, and close the tab.
- **Pool Formation**: The webhook fires, the APScheduler `abandonment_worker` classifies it as a multi-product cart, and a `multi_product_pools` row appears.
- **Live Negotiation**: On the merchant dashboard, click "Enter Negotiation Room". Watch the live SSE feed as multiple AI agents debate pricing across 2 rounds.
- **Buyer Decision**: The Buyer Agent evaluates the finalized ladder, selects the winning allocation, and updates the UI.
- **Payment & Fulfillment**: An email arrives with a Razorpay link. Complete the test payment, and verify the Shopify dashboard shows a confirmed, paid order.
