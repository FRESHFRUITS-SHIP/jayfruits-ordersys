# ERROR_HANDLING.md — Jay Fruits (Phase 0 audit)

## Current state: minimal, ad hoc

- `webhook.py::receive_message` catches only `KeyError`/`IndexError` around payload parsing — returns `{"status": "ok"}` and drops the message silently. Fine for malformed payloads, not fine as the *only* safety net.
- `order_parser.py::parse_message` — no try/except around the Groq API call itself. A Groq timeout, rate limit (429), or auth failure (401) will raise `groq.APIError` (or similar) uncaught, propagating up through `handle_text_message` → `receive_message` → FastAPI returns 500 to Meta. Customer gets nothing.
- `order_parser.py::generate_shopkeeper_reply` — DOES catch broad `Exception`, returns `None` on failure, caller falls back to a static message. This is the one place in the codebase that already follows the "AI can fail, business logic can't" rule properly. Use it as the template for the rest.
- Outbound WhatsApp calls (`whatsapp.py`) — logs the error body then calls `r.raise_for_status()`, which raises. Not caught by any caller. A failed outbound send (e.g. token expired) will 500 the whole request.
- Supabase calls throughout `orders.py` — no try/except anywhere. A transient Supabase error mid-conversation (e.g. during `create_order`) has no defined behavior.

## Gap vs. Phase 1 target

Phase 1 calls for:
- a global error boundary so customers never see raw errors (they currently see *nothing* — worse, since silence looks like the bot is broken/ignoring them)
- differentiated retry policy per failure type (429 → backoff, 500 → retry, 400 → don't retry, timeout → retry)
- correlation IDs threading a message through Groq → DB → response
- an audit log of business events

None of this exists yet. Recommended order to add it (within Milestone 1):
1. Wrap `handle_text_message`/`handle_button_reply` bodies in try/except at the call site in `receive_message`, log with a trace id, and send the static "technical problem, try again" message in the customer's language — this alone converts "silent 500" into "graceful degrade" for every failure mode at once.
2. Add retry-with-backoff specifically around the Groq call (highest-frequency external dependency).
3. Add the correlation id + audit log once the try/except boundary exists, since they slot into the same wrapper.
