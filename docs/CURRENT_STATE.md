# CURRENT_STATE.md — Jay Fruits WhatsApp Bot

Last audited: 2026-08-25 (Phase 0 audit, against actual repo code, not memory/summary)

This is the single source of truth for "what does the bot actually do right now."
Anything not listed here as ✅ should be treated as NOT working until re-verified.

---

## Feature status

| Feature | Status | Location |
|---|---|---|
| Webhook receive (POST /webhook) | ✅ | `app/routers/webhook.py` |
| Meta webhook verify (GET /webhook) | ✅ | `app/routers/webhook.py` |
| HMAC signature verification | ✅ | `_verify_signature()` |
| Groq NLU parsing (intent + items + language) | ✅ | `app/services/order_parser.py::parse_message` |
| Quantity/unit parser (safe, never-guess) | ✅ | `order_parser.py::parse_quantity_only` |
| Unit conversion (kg↔g, litre↔ml, dozen↔piece) | ✅ | `order_parser.py::_convert` |
| Product variants (e.g. "apple" → variant list) | ✅ | confirmed live — `variant_group`/`image_url` columns exist in Supabase (not yet in tracked schema.sql — see DATABASE.md) |
| Cart / pending-order confirm-edit step | ✅ | confirmed live — `pending_item`/`pending_order` columns exist in Supabase |
| Customer onboarding (language then name) | ✅ | `handle_text_message` |
| "hi" as first message ≠ accidentally saved as name | ✅ | fixed, see PROGRESS.md |
| Delivery/pickup buttons + address reuse | ✅ | `_ask_fulfillment_or_address`, `_apply_pickup` |
| Order editing (add/remove items on open order) | ✅ | `_handle_edit` |
| Reorder ("same as last time") | ✅ | `_handle_reorder`, skips unavailable items |
| Duplicate order detection (5-min window) | ✅ | non-blocking — flags, doesn't prevent |
| Payment: UPI deep link | ✅ | `app/services/upi.py` — stays PENDING, no auto-confirm |
| Payment: Cash on delivery | ✅ | auto-marks order confirmed |
| Business hours gate | ✅ | `is_within_business_hours` |
| Minimum order value gate | ✅ | |
| Shopkeeper-style AI replies for off-menu chat | ✅ | `generate_shopkeeper_reply` — never states prices/totals (enforced by prompt) |
| Dashboard: orders/customers/analytics/CSV/products/settings | ✅ | `app/routers/dashboard.py`, more complete than earlier summary suggested |
| Daily summary WhatsApp message | 🟡 | code exists (`/tasks/daily-summary`), needs an external cron pointed at it — not scheduled automatically |
| Rate limiting (per-customer / global) | 🔴 | **Not present in code**, despite earlier summary. No limiter anywhere in webhook.py |
| Idempotency (duplicate Meta webhook delivery) | 🔴 | No message-id dedup. A Meta retry will double-process a message |
| Explicit conversation state machine | 🔴 | Implicit only, via `pending_item`/`pending_order` flags — not the state enum Phase 2 calls for |
| Error boundary (generic try/except around handler) | 🟡 | Only catches `KeyError`/`IndexError` at the top level; a Groq timeout, Supabase error, or WhatsApp API error is **unhandled** and will 500 |
| Groq failover / multiple keys | 🔴 | Single `GROQ_API_KEY`, no fallback |
| Deterministic fallback parser (if Groq is down) | 🔴 | None — `parse_message` failing means the customer gets nothing |
| Correlation/trace IDs across a message's lifecycle | 🔴 | Not present |
| Audit log of business events (ITEM_ADDED, ORDER_CONFIRMED, etc.) | 🔴 | Not present — only ad hoc `print()` statements on errors |
| Product search / alias / typo matching beyond Groq | 🟡 | `match_products()` does substring matching as a backstop; no alias table |
| Inventory/stock concurrency handling | 🔴 | Not present — no stock quantity field at all currently, only `is_available` boolean |
| Human handoff | 🔴 | Not present |

---

## Known contradictions resolved by this audit

- **Resolved:** address collection IS implemented (`_handle_address`, `_ask_fulfillment_or_address`) — PROGRESS.md's "deferred" note was stale.
- **Resolved:** `pending_item`/`pending_order`/`variant_group`/`image_url` columns exist live in Supabase but are **not** in `schema.sql` or `migration_v2.sql`. Tracked schema is behind reality. Action: write `migration_v3.sql` to close this gap (see DATABASE.md).

## Known unresolved risk

- `/debug/secret-check` route in `app/main.py` is unauthenticated and returns partial Meta access token. Marked `# TEMPORARY` in code but still present. **Remove before publishing the Meta app.**
- No rate limiting despite this being assumed "done" in earlier planning — a burst of messages (or an abusive/looping sender) hits Groq and Supabase with zero throttling.
