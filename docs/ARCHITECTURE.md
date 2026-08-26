# ARCHITECTURE.md — Jay Fruits (as-built, Phase 0)

## Current flow

```
WhatsApp customer
      │
      ▼
Meta WhatsApp Cloud API
      │  (POST /webhook, HMAC-signed)
      ▼
FastAPI  (app/main.py)
      │
      ├── app/routers/webhook.py   — all conversation logic lives here (902 lines)
      ├── app/routers/dashboard.py — owner-facing web UI (orders/customers/analytics)
      └── app/routers/customer_page.py — customer's own order-history link
      │
      ▼
app/services/order_parser.py  ──▶  Groq (openai/gpt-oss-120b)
      │  (intent + items + language, JSON-mode, menu-grounded)
      ▼
app/services/orders.py  ──▶  Supabase/Postgres (products, customers, orders, order_items, shop_settings)
      │
      ▼
app/services/whatsapp.py  ──▶  Meta Cloud API (send text/buttons/list/image)
```

## What's notably absent vs. the master roadmap's target architecture

- No **Security Layer / Idempotency** box before the message processor — signature check exists, but no dedup.
- No **Conversation Engine** as a distinct layer — state lives as two nullable JSON-ish columns on `customers` (`pending_item`, `pending_order`), read/written inline throughout `webhook.py`.
- No **AI Router** with fallback — one direct call to Groq, uncaught on failure.
- No **Cart** as its own concept — `pending_order` is the closest thing, but it's a single dict per customer, not a persisted cart entity.
- No **Inventory** engine — `is_available` is a boolean, not a stock count.
- Dashboard already exists ahead of schedule relative to the roadmap (roadmap defers it to Phase 29) — this is fine, it's low-risk surface area, but means Milestone 8 is partially done already.

## File inventory (for reference)

| File | Lines | Purpose |
|---|---|---|
| `app/main.py` | 107 | App entrypoint, privacy policy route, daily summary trigger, debug route (to remove) |
| `app/config.py` | 38 | Env var loading |
| `app/db.py` | 11 | Supabase client singleton |
| `app/routers/webhook.py` | 902 | **All** conversation logic — candidate for splitting once Phase 2 (state engine) lands |
| `app/routers/dashboard.py` | 289 | Owner dashboard |
| `app/routers/customer_page.py` | 28 | Customer self-service page |
| `app/services/orders.py` | 541 | DB access layer for products/customers/orders |
| `app/services/order_parser.py` | 301 | Groq NLU + quantity/unit parsing |
| `app/services/whatsapp.py` | 105 | Outbound Meta API calls |
| `app/services/upi.py` | 24 | UPI deep link builder |
| `app/services/notifications.py` | 30 | Status-change messages |

`webhook.py` at 902 lines doing intent routing, all message templates (3 languages inline), and business logic is the single biggest structural risk right now — not a bug, but it's the file that will become unmanageable first as Phase 2+ features land. Worth planning a split (e.g. `conversation/`, `templates/`, `handlers/`) around when the state machine goes in, not before.
