import hashlib
import hmac
from fastapi import APIRouter, Request, Query, HTTPException, Response

from app.config import META_VERIFY_TOKEN, META_APP_SECRET, SHOP_NAME, SHOP_WHATSAPP_DISPLAY_NUMBER
from app.services.whatsapp import send_text, send_buttons
from app.services.order_parser import parse_order
from app.services.upi import build_upi_link
from app.services.orders import (
    get_available_menu,
    get_or_create_customer,
    match_products,
    create_order,
    set_order_payment_mode,
    get_latest_open_order_for_customer,
)

router = APIRouter()


# ---------- webhook verification (Meta calls this once when you set up the webhook URL) ----------
@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == META_VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


def _verify_signature(body: bytes, signature_header: str | None) -> bool:
    if not META_APP_SECRET:
        return True  # skip check if not configured (fine for local dev, NOT for production)
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(META_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.split("=", 1)[1])


# ---------- incoming messages ----------
@router.post("/webhook")
async def receive_message(request: Request):
    body_bytes = await request.body()
    if not _verify_signature(body_bytes, request.headers.get("x-hub-signature-256")):
        raise HTTPException(status_code=403, detail="Invalid signature")

    payload = await request.json()

    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]["value"]
        messages = change.get("messages")
        if not messages:
            return {"status": "ignored"}  # delivery/read receipts etc.

        msg = messages[0]
        from_number = msg["from"]

        if msg["type"] == "text":
            text = msg["text"]["body"]
            await handle_text_message(from_number, text)
        elif msg["type"] == "interactive":
            button_id = msg["interactive"]["button_reply"]["id"]
            await handle_button_reply(from_number, button_id)
        else:
            await send_text(from_number, "Please send your order as text, e.g. '2kg mango, 1 dozen banana'.")

    except (KeyError, IndexError):
        pass  # malformed/unsupported payload shape — don't crash the webhook

    return {"status": "ok"}


# ---------- conversation logic ----------
async def handle_text_message(from_number: str, text: str) -> None:
    customer = get_or_create_customer(from_number)
    stripped = text.strip().lower()

    if stripped in ("hi", "hello", "hey", "menu", "namaste", "hii"):
        await send_menu(from_number)
        return

    menu = get_available_menu()
    parsed = parse_order(text, menu)

    if not parsed.get("is_order"):
        note = parsed.get("customer_intent_note") or ""
        reply = (
            f"Namaste! Welcome to {SHOP_NAME}. 🍊🥭\n\n"
            "Send your order like: '2kg mango, 1 dozen banana'\n"
            "Or type 'menu' to see today's fruits & prices."
        )
        if note:
            reply += f"\n\n(Note: {note})"
        await send_text(from_number, reply)
        return

    matched = match_products([i["product_name"] for i in parsed["items"]], menu)
    items_for_order = []
    lines = []
    for item in parsed["items"]:
        product = matched.get(item["product_name"])
        if not product:
            continue
        qty = float(item["quantity"])
        items_for_order.append({"product": product, "quantity": qty})
        line_total = product["price"] * qty
        lines.append(f"• {product['name_en']} — {qty} {product['unit']} × ₹{product['price']} = ₹{line_total:.0f}")

    unavailable = parsed.get("unavailable_items", [])

    if not items_for_order:
        msg = "Sorry, I couldn't match any items on our menu. Type 'menu' to see what's available today."
        await send_text(from_number, msg)
        return

    order = create_order(customer["id"], items_for_order, raw_message=text)

    summary = "\n".join(lines)
    reply = f"Order received! 🧾\n\n{summary}\n\n*Total: ₹{order['total']:.0f}*"
    if unavailable:
        reply += f"\n\n(Sorry, not available right now: {', '.join(unavailable)})"
    await send_text(from_number, reply)

    await send_buttons(
        from_number,
        "How would you like to pay?",
        [("pay_upi", "Pay via UPI"), ("pay_cod", "Cash/UPI on delivery")],
    )


async def handle_button_reply(from_number: str, button_id: str) -> None:
    customer = get_or_create_customer(from_number)
    order = get_latest_open_order_for_customer(customer["id"])
    if not order:
        await send_text(from_number, "I couldn't find an open order — please send your order again.")
        return

    if button_id == "pay_upi":
        set_order_payment_mode(order["id"], "upi")
        link = build_upi_link(order["total"], order["id"])
        await send_text(
            from_number,
            f"Tap to pay ₹{order['total']:.0f} via UPI:\n{link}\n\n"
            "Once paid, we'll confirm and start preparing your order. 🙏",
        )
    elif button_id == "pay_cod":
        set_order_payment_mode(order["id"], "cod")
        await send_text(
            from_number,
            f"Got it — pay cash or UPI on delivery. Your order (₹{order['total']:.0f}) is confirmed! "
            f"We'll deliver between 7 AM – 10 PM. For anything urgent, call {SHOP_WHATSAPP_DISPLAY_NUMBER}.",
        )


async def send_menu(to: str) -> None:
    menu = get_available_menu()
    lines = [f"🍉 *{SHOP_NAME} — Today's Menu*\n"]
    for p in menu:
        hi = f" ({p['name_hi']})" if p.get("name_hi") else ""
        lines.append(f"• {p['name_en']}{hi} — ₹{p['price']}/{p['unit']}")
    lines.append("\nJust reply with what you'd like, e.g. '2kg mango, 1 dozen banana'.")
    await send_text(to, "\n".join(lines))
