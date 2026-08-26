# DATABASE.md — Jay Fruits

## Tables per tracked schema.sql + migration_v2.sql

- **products**: id, name_en, name_hi, unit, price, cost_price, is_available, created_at
- **customers**: id, wa_number, name, address, preferred_language, page_token, created_at
- **shop_settings**: id, minimum_order_value, business_hours_start, business_hours_end, updated_at
- **orders**: id, customer_id, status, fulfillment, payment_mode, payment_status, total, notes, raw_message, source, eta_minutes, delivery_address, is_duplicate_flag, created_at, updated_at
- **order_items**: id, order_id, product_id, product_name, quantity, unit, unit_price, cost_price, line_total

## ⚠️ Drift: live Supabase has columns not in tracked SQL

Confirmed live and in use by the code, but **missing from `schema.sql`/`migration_v2.sql`**:

- `customers.pending_item` (jsonb) — holds `{product_id, name_en, unit}` while awaiting a quantity reply
- `customers.pending_order` (jsonb) — holds the parsed-but-unconfirmed order awaiting Confirm/Edit
- `products.variant_group` (text) — groups variants under one generic name (e.g. "Mango" for Alphonso/Kesar/Dasheri)
- `products.image_url` (text) — product photo shown during variant selection

**Action item:** write `migration_v3.sql` that adds these with `if not exists`, so a fresh environment (or a teammate, or a disaster-recovery restore) reproduces the real schema. Right now, running `schema.sql` on a clean database would NOT produce a working bot — several handlers would throw on the first `.update()` call touching these columns. This is a real deploy risk, not just a documentation nicety.

## Notable schema gaps relative to the 30-phase roadmap

- No `stock_quantity` on products — only a boolean `is_available`. Phase 9 (Inventory Engine) will need this, plus a reservation mechanism.
- No `order_status_history` / audit trail table — Phase 1 (audit log) and Phase 19 (order lifecycle) will want an append-only log rather than only overwriting `orders.status`.
- No `processed_webhook_events` table — needed for Phase 1 idempotency (dedup by Meta's message id).
- No `product_aliases` table — needed for Phase 4 (search/alias/typo resolution); currently alias-like matching is just substring matching in `match_products()`.
- `pending_order`/`pending_item` as single-slot jsonb columns on `customers` work for one-cart-at-a-time but don't extend cleanly to a persisted, addressable Cart entity (Phase 7) — worth a real `carts`/`cart_items` table when that phase starts, rather than growing the jsonb blob further.
