# BOT_BEHAVIOR.md — Jay Fruits

Answers: "what does the bot do when a customer sends any particular message?"
Traced directly from `app/routers/webhook.py::handle_text_message` and `handle_button_reply`.

## Message routing order (first match wins)

1. **No `preferred_language` set** → send language-selection buttons. Nothing else happens.
2. **Language set but no `name`, and no pending item/order** → treat the raw text AS the customer's name (1–40 chars), save it, send first-time greeting + menu.
3. **Exact match** to `hi/hello/hey/menu/namaste/hii/hlo` → greeting + menu.
4. **Exact match** to an about/help trigger phrase → send About message.
5. **Exact match** to an acknowledgement word (thanks/ok/cool/etc.) → "You're welcome" reply.
6. **Exact match** to a pickup phrase → apply pickup to latest open order.
7. **`pending_item` is set** (bot previously asked "kitna chahiye?") → treat message as a bare quantity via `parse_quantity_only`. If it parses, complete the order add. If not, re-ask — never guesses.
8. **Otherwise** → send to Groq (`parse_message`) with the live menu, get back `{intent, language, items, unavailable_items, address_text, note}`.
   - `intent == greeting` (and message is short, not exactly "hi/hello/hey/menu") → treated as acknowledgement instead, to avoid re-blasting the menu for something like "thanks so much".
   - `intent == address` → save address, may trigger payment buttons if an order was waiting on it.
   - `intent == cancel_order` → cancel latest open order.
   - `intent == reorder` → repeat last order, skipping now-unavailable items, then ask fulfillment.
   - `intent == edit_order` → add/remove items on latest open order (not the pending/unconfirmed one).
   - `intent == new_order` → main path, see below.
   - `intent == other` → if the customer has an open delivery order with no address yet, treat this message as the address. Otherwise, generate a shopkeeper-style AI chit-chat reply (never states price/total — enforced by system prompt) with static-text fallback if Groq fails.

## New order path (`_handle_new_order`)

1. Reject if outside business hours.
2. Match parsed item names against the live menu (`match_products`).
3. If exactly one item was named with no quantity → check for variants:
   - Multiple variants exist → send photos + a List Message to choose one; conversation pauses here.
   - Exactly one variant → set as `pending_item`, ask "kitna chahiye?"; conversation pauses here.
4. Otherwise, for each item: if any item is missing a quantity, ask the customer to restate with quantities (does not proceed item-by-item in a multi-item message).
5. Check minimum order value; if under, ask for more, do not proceed.
6. **Does NOT create the order yet.** Stashes items in `pending_order`, shows an itemized summary + total, and sends Confirm/Edit buttons.
7. Only on `confirm_order` button tap does `_finalize_order` actually insert into `orders`/`order_items`, then ask delivery/pickup, then payment.
8. `edit_order` button tap just clears the pending order and asks the customer to resend — it does NOT let them edit inline at this stage (that's separate from `_handle_edit`, which only works on an already-confirmed open order).

## Duplicate detection

Non-blocking: if a new order is created within `DUPLICATE_ORDER_WINDOW_MINUTES` (5 min) of another order from the same customer, `is_duplicate_flag` is set true and a warning line is appended to the confirmation message. The order is still created — the customer must explicitly say "cancel" if it was accidental.

## What happens on unhandled exceptions

Currently: nothing graceful. The top-level `try/except` in the webhook route only catches `KeyError`/`IndexError` from malformed payloads (returns `{"status": "ok"}` silently). Any exception from Groq, Supabase, or the WhatsApp send call itself is **not caught anywhere in this path** and will surface as a 500 to Meta, with the customer receiving no reply at all and no indication anything went wrong. This is the top Phase 1 gap.
