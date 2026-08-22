import hashlib
import hmac
from fastapi import APIRouter, Request, Query, HTTPException, Response

from app.config import (
    META_VERIFY_TOKEN, META_APP_SECRET, SHOP_NAME,
    SHOP_WHATSAPP_DISPLAY_NUMBER, PUBLIC_BASE_URL,
)
from app.services.whatsapp import send_text, send_buttons
from app.services.order_parser import parse_message
from app.services.upi import build_upi_link
from app.services import orders as svc

router = APIRouter()


# ---------- webhook verification ----------
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
        return True
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
            return {"status": "ignored"}

        msg = messages[0]
        from_number = msg["from"]

        if msg["type"] == "text":
            await handle_text_message(from_number, msg["text"]["body"])
        elif msg["type"] == "interactive":
            reply = msg["interactive"].get("button_reply") or msg["interactive"].get("list_reply")
            if reply:
                await handle_button_reply(from_number, reply["id"])
        elif msg["type"] in ("audio", "voice", "image", "video", "document"):
            await send_text(
                from_number,
                "I can only read text messages right now — could you please type your order? 🙏\n"
                "उदाहरण: '2kg mango, 1 dozen banana'",
            )
        else:
            await send_text(from_number, "Please send your order as text, e.g. '2kg mango, 1 dozen banana'.")

    except (KeyError, IndexError):
        pass

    return {"status": "ok"}


# ---------- helpers ----------
def _t(lang: str, en: str, hi: str) -> str:
    return hi if lang == "hi" else en


def _fmt_qty(qty: float) -> str:
    """Formats 2.0 -> '2', 1.5 -> '1.5' — avoids the sloppy '2.0 kg' look."""
    return str(int(qty)) if qty == int(qty) else str(qty)


ACKNOWLEDGEMENT_WORDS = {
    "thank you", "thanks", "thankyou", "thnx", "ty", "tq",
    "ok", "okay", "k", "cool", "great", "nice", "good", "perfect",
    "dhanyavad", "shukriya", "theek hai", "thik hai",
}

PICKUP_WORDS = {
    "pickup", "pick up", "self pickup", "i'll pick up", "ill pick up",
    "i will pick up", "self pick up", "pick-up",
}


async def _greeting_and_menu(to: str, lang: str) -> None:
    menu = svc.get_available_menu()
    if lang == "hi":
        lines = [f"🍉 *{SHOP_NAME} में आपका स्वागत है!*\n"]
        for p in menu:
            hi_name = f" ({p['name_hi']})" if p.get("name_hi") else ""
            lines.append(f"• {p['name_en']}{hi_name} — ₹{p['price']}/{p['unit']}")
        lines.append("\nजो चाहिए वो लिखें, जैसे: '2kg mango, 1 dozen banana'")
        lines.append(f"अपना मेन्यू व ऑर्डर हिस्ट्री यहाँ देखें: {PUBLIC_BASE_URL}/me/<link नीचे भेजा जाएगा>")
    else:
        lines = [f"🍉 *Welcome to {SHOP_NAME}!*\n"]
        for p in menu:
            hi_name = f" ({p['name_hi']})" if p.get("name_hi") else ""
            lines.append(f"• {p['name_en']}{hi_name} — ₹{p['price']}/{p['unit']}")
        lines.append("\nJust reply with what you'd like, e.g. '2kg mango, 1 dozen banana'.")
    await send_text(to, "\n".join(lines))


async def _send_menu_link(to: str, customer: dict) -> None:
    link = f"{PUBLIC_BASE_URL}/me/{customer['page_token']}"
    await send_text(to, f"🔗 Your menu & order history: {link}")


async def _send_payment_buttons(to: str, lang: str) -> None:
    await send_buttons(
        to,
        _t(lang, "How would you like to pay?", "भुगतान कैसे करेंगे?"),
        [("pay_upi", _t(lang, "Pay via UPI", "UPI से भुगतान")),
         ("pay_cod", _t(lang, "Cash on delivery", "डिलीवरी पर नकद"))],
    )


# ---------- main conversation handler ----------
async def handle_text_message(from_number: str, text: str) -> None:
    customer = svc.get_or_create_customer(from_number)
    stripped = text.strip().lower().strip(".!😊🙏👍")

    if stripped in ("hi", "hello", "hey", "menu", "namaste", "hii", "hlo"):
        lang = customer.get("preferred_language") or "en"
        await _greeting_and_menu(from_number, lang)
        return

    if stripped in ACKNOWLEDGEMENT_WORDS:
        lang = customer.get("preferred_language") or "en"
        await send_text(from_number, _t(lang, "You're welcome! 😊", "आपका स्वागत है! 😊"))
        return

    if stripped in PICKUP_WORDS:
        lang = customer.get("preferred_language") or "en"
        order = svc.get_latest_open_order_for_customer(customer["id"])
        if order:
            svc.set_order_fulfillment(order["id"], "pickup")
            await send_text(from_number, _t(
                lang,
                f"Got it — order #{order['id']} will be ready for you to pick up. See you soon! 🙏",
                f"ठीक है — ऑर्डर #{order['id']} पिकअप के लिए तैयार रहेगा। मिलते हैं! 🙏",
            ))
            if order.get("payment_mode", "unset") == "unset":
                await _send_payment_buttons(from_number, lang)
        else:
            await send_text(from_number, _t(
                lang, "You don't have an open order right now — send your order first!",
                "अभी आपका कोई खुला ऑर्डर नहीं है — पहले ऑर्डर भेजें!",
            ))
        return

    menu = svc.get_available_menu()
    parsed = parse_message(text, menu)
    lang = parsed.get("language", "en")

    # remember their language for future messages (menu, notifications, etc.)
    if customer.get("preferred_language") != lang:
        svc.set_customer_language(customer["id"], lang)
        customer["preferred_language"] = lang

    intent = parsed["intent"]

    # Backup net: if Groq still classifies a short acknowledgement/thanks as
    # "greeting", don't re-send the whole menu — a full menu reply to "thanks"
    # is exactly the kind of thing that makes a bot feel dumb.
    if intent == "greeting" and len(stripped.split()) <= 3 and stripped not in ("hi", "hello", "hey", "menu"):
        await send_text(from_number, _t(lang, "You're welcome! 😊", "आपका स्वागत है! 😊"))
        return

    if intent == "greeting":
        await _greeting_and_menu(from_number, lang)
        return

    if intent == "address":
        await _handle_address(from_number, customer, parsed, lang)
        return

    if intent == "cancel_order":
        await _handle_cancel(from_number, customer, lang)
        return

    if intent == "reorder":
        await _handle_reorder(from_number, customer, lang)
        return

    if intent == "edit_order":
        await _handle_edit(from_number, customer, parsed, lang)
        return

    if intent == "new_order":
        await _handle_new_order(from_number, customer, parsed, text, lang)
        return

    # "other" — unclear message. Before giving up, check: are we mid-conversation
    # waiting on this customer's delivery address? If so, treat their reply as
    # the address rather than making them re-phrase it as "deliver to ...".
    open_order = svc.get_latest_open_order_for_customer(customer["id"])
    if open_order and open_order.get("fulfillment") == "delivery" and not open_order.get("delivery_address") and not customer.get("address"):
        svc.set_customer_address(customer["id"], text.strip())
        from app.db import get_db
        get_db().table("orders").update({"delivery_address": text.strip()}).eq("id", open_order["id"]).execute()
        await send_text(from_number, _t(
            lang, f"Got it — saved your address: {text.strip()}",
            f"ठीक है — पता सेव कर लिया: {text.strip()}",
        ))
        if open_order.get("payment_mode", "unset") == "unset":
            await _send_payment_buttons(from_number, lang)
        return

    note = parsed.get("note") or ""
    reply = _t(
        lang,
        f"Not sure I understood that. Send your order like '2kg mango, 1 dozen banana', or type 'menu'.",
        "समझ नहीं आया 🙏 ऑर्डर ऐसे भेजें: '2kg mango, 1 dozen banana', या 'menu' लिखें।",
    )
    if note:
        reply += f"\n\n({note})"
    await send_text(from_number, reply)


# ---------- intent handlers ----------

async def _handle_new_order(to: str, customer: dict, parsed: dict, raw_text: str, lang: str) -> None:
    if not svc.is_within_business_hours():
        settings = svc.get_shop_settings()
        await send_text(to, _t(
            lang,
            f"We're currently closed. Our hours are {settings['business_hours_start']}:00–{settings['business_hours_end']}:00. "
            "Send your order again once we're open and we'll get right on it! 🙏",
            f"अभी दुकान बंद है। हमारा समय {settings['business_hours_start']}:00–{settings['business_hours_end']}:00 है। "
            "कृपया दुकान खुलने पर दोबारा ऑर्डर भेजें 🙏",
        ))
        return

    menu = svc.get_available_menu()
    matched = svc.match_products([i["product_name"] for i in parsed["items"]], menu)
    items_for_order = []
    lines = []
    for item in parsed["items"]:
        product = matched.get(item["product_name"])
        if not product:
            continue
        qty = float(item["quantity"])
        items_for_order.append({"product": product, "quantity": qty})
        line_total = product["price"] * qty
        lines.append(f"• {product['name_en']} — {_fmt_qty(qty)} {product['unit']} × ₹{product['price']} = ₹{line_total:.0f}")

    unavailable = parsed.get("unavailable_items", [])

    if not items_for_order:
        await send_text(to, _t(
            lang,
            "Sorry, I couldn't match any items on our menu. Type 'menu' to see what's available today.",
            "माफ़ करें, कोई भी आइटम मेन्यू में नहीं मिला। आज का मेन्यू देखने के लिए 'menu' लिखें।",
        ))
        return

    total = sum(i["product"]["price"] * i["quantity"] for i in items_for_order)
    settings = svc.get_shop_settings()
    min_order = float(settings.get("minimum_order_value") or 0)
    if min_order > 0 and total < min_order:
        await send_text(to, _t(
            lang,
            f"Your order total is ₹{total:.0f}, but our minimum order is ₹{min_order:.0f}. "
            "Please add a bit more to your order!",
            f"आपका ऑर्डर ₹{total:.0f} का है, लेकिन न्यूनतम ऑर्डर ₹{min_order:.0f} है। "
            "कृपया थोड़ा और जोड़ें।",
        ))
        return

    address = customer.get("address") or ""
    order = svc.create_order(
        customer["id"], items_for_order, raw_message=raw_text,
        source="whatsapp", delivery_address=address,
    )

    summary = "\n".join(lines)
    header = _t(lang, "Order received! 🧾", "ऑर्डर मिल गया! 🧾")
    reply = f"{header}\n\n{summary}\n\n*{_t(lang,'Total','कुल')}: ₹{order['total']:.0f}*"
    if unavailable:
        reply += "\n\n" + _t(
            lang,
            f"(Sorry, not available right now: {', '.join(unavailable)})",
            f"(माफ़ करें, अभी उपलब्ध नहीं: {', '.join(unavailable)})",
        )
    if order.get("is_duplicate_flag"):
        reply += "\n\n" + _t(
            lang,
            "⚠️ Looks like you just ordered again — if this wasn't intentional, reply 'cancel' to cancel this one.",
            "⚠️ लगता है आपने अभी दोबारा ऑर्डर किया — अगर गलती से हुआ है तो 'cancel' लिखें।",
        )
    await send_text(to, reply)

    if not address:
        # Address is required before we move to payment — don't send payment
        # buttons yet. The next message from this customer (whether it looks
        # like an address or not) gets picked up by the address-capture logic
        # in handle_text_message, which then sends payment buttons itself.
        await send_text(to, _t(
            lang,
            "📍 What's your delivery address? (Or reply 'pickup' if you'll collect it yourself.)",
            "📍 आपका डिलीवरी पता क्या है? (खुद लेने आना है तो 'pickup' लिखें।)",
        ))
        return

    # Address already on file — mention it and go straight to payment.
    await send_text(to, _t(
        lang, f"📍 Delivering to: {address}\n(Reply 'change address' anytime to update this.)",
        f"📍 डिलीवरी पता: {address}\n(पता बदलने के लिए कभी भी 'change address' लिखें।)",
    ))
    eta = order.get("eta_minutes")
    if eta:
        await send_text(to, _t(
            lang, f"🚴 Estimated delivery: ~{eta} minutes.",
            f"🚴 अनुमानित डिलीवरी समय: ~{eta} मिनट।",
        ))

    await _send_payment_buttons(to, lang)


async def _handle_edit(to: str, customer: dict, parsed: dict, lang: str) -> None:
    order = svc.get_latest_open_order_for_customer(customer["id"])
    if not order:
        await send_text(to, _t(
            lang,
            "You don't have an open order to edit. Send a new order anytime!",
            "आपका कोई खुला ऑर्डर नहीं है। नया ऑर्डर कभी भी भेजें!",
        ))
        return

    menu = svc.get_available_menu()
    matched = svc.match_products([i["product_name"] for i in parsed["items"]], menu)
    changes = []
    new_total = order["total"]

    for item in parsed["items"]:
        product = matched.get(item["product_name"])
        if not product:
            continue
        qty = float(item["quantity"])
        action = item.get("action", "add")
        if action == "remove":
            new_total = svc.remove_item_from_order(order["id"], product["name_en"])
            changes.append(_t(lang, f"Removed {product['name_en']}", f"{product['name_en']} हटाया गया"))
        else:
            new_total = svc.add_item_to_order(order["id"], product, qty)
            changes.append(_t(lang, f"Added {_fmt_qty(qty)} {product['unit']} {product['name_en']}",
                               f"{_fmt_qty(qty)} {product['unit']} {product['name_en']} जोड़ा गया"))

    if not changes:
        await send_text(to, _t(lang, "Couldn't match that item to your order.", "वह आइटम ऑर्डर में नहीं मिला।"))
        return

    reply = "\n".join(f"✅ {c}" for c in changes)
    reply += f"\n\n*{_t(lang,'New total','नया कुल')}: ₹{new_total:.0f}*"
    await send_text(to, reply)


async def _handle_cancel(to: str, customer: dict, lang: str) -> None:
    order = svc.get_latest_open_order_for_customer(customer["id"])
    if not order:
        await send_text(to, _t(lang, "You don't have an active order to cancel.", "आपका कोई सक्रिय ऑर्डर नहीं है।"))
        return
    svc.cancel_order(order["id"])
    await send_text(to, _t(
        lang, f"Order #{order['id']} has been cancelled. No charge.",
        f"ऑर्डर #{order['id']} रद्द कर दिया गया है। कोई शुल्क नहीं।",
    ))


async def _handle_reorder(to: str, customer: dict, lang: str) -> None:
    last = svc.get_latest_order_for_customer(customer["id"])
    if not last or not last.get("order_items"):
        await send_text(to, _t(lang, "You don't have a previous order to repeat.", "आपका कोई पिछला ऑर्डर नहीं मिला।"))
        return

    menu = svc.get_available_menu()
    available_ids = {p["id"] for p in menu}
    items_for_order = []
    lines = []
    skipped = []
    for it in last["order_items"]:
        if it["product_id"] not in available_ids:
            skipped.append(it["product_name"])
            continue
        product = next(p for p in menu if p["id"] == it["product_id"])
        qty = float(it["quantity"])
        items_for_order.append({"product": product, "quantity": qty})
        lines.append(f"• {product['name_en']} — {_fmt_qty(qty)} {product['unit']} × ₹{product['price']} = ₹{product['price']*qty:.0f}")

    if not items_for_order:
        await send_text(to, _t(lang, "Sorry, those items aren't available today.", "माफ़ करें, वे आइटम आज उपलब्ध नहीं हैं।"))
        return

    order = svc.create_order(
        customer["id"], items_for_order, raw_message="(reorder)",
        source="whatsapp", delivery_address=customer.get("address") or "",
    )
    summary = "\n".join(lines)
    reply = f"{_t(lang,'Repeating your last order! 🔁','आपका पिछला ऑर्डर दोहराया जा रहा है! 🔁')}\n\n{summary}\n\n*{_t(lang,'Total','कुल')}: ₹{order['total']:.0f}*"
    if skipped:
        reply += "\n\n" + _t(lang, f"(No longer available: {', '.join(skipped)})", f"(अब उपलब्ध नहीं: {', '.join(skipped)})")
    await send_text(to, reply)

    address = customer.get("address") or ""
    if not address:
        await send_text(to, _t(
            lang,
            "📍 What's your delivery address? (Or reply 'pickup' if you'll collect it yourself.)",
            "📍 आपका डिलीवरी पता क्या है? (खुद लेने आना है तो 'pickup' लिखें।)",
        ))
        return

    await send_text(to, _t(
        lang, f"📍 Delivering to: {address}",
        f"📍 डिलीवरी पता: {address}",
    ))
    await _send_payment_buttons(to, lang)


async def _handle_address(to: str, customer: dict, parsed: dict, lang: str) -> None:
    address = parsed.get("address_text", "").strip()
    if not address:
        await send_text(to, _t(lang, "Please share your delivery address.", "कृपया अपना डिलीवरी पता भेजें।"))
        return
    svc.set_customer_address(customer["id"], address)

    # if they have an open order without an address snapshot yet, attach it
    # and — if payment hasn't been chosen yet — move them straight to payment.
    order = svc.get_latest_open_order_for_customer(customer["id"])
    was_missing_address = order and not order.get("delivery_address")
    if order and was_missing_address:
        from app.db import get_db
        get_db().table("orders").update({"delivery_address": address}).eq("id", order["id"]).execute()

    await send_text(to, _t(lang, f"Got it — saved your address: {address}", f"ठीक है — पता सेव कर लिया: {address}"))

    if order and was_missing_address and order.get("payment_mode", "unset") == "unset":
        await _send_payment_buttons(to, lang)


async def handle_button_reply(from_number: str, button_id: str) -> None:
    customer = svc.get_or_create_customer(from_number)
    lang = customer.get("preferred_language") or "en"
    order = svc.get_latest_open_order_for_customer(customer["id"])
    if not order:
        await send_text(from_number, _t(lang, "Couldn't find an open order — please send your order again.", "कोई खुला ऑर्डर नहीं मिला — कृपया दोबारा भेजें।"))
        return

    if button_id == "pay_upi":
        svc.set_order_payment_mode(order["id"], "upi")
        link = build_upi_link(order["total"], order["id"])
        await send_text(from_number, _t(
            lang,
            f"Tap to pay ₹{order['total']:.0f} via UPI:\n{link}\n\nOnce paid, we'll confirm and start preparing your order. 🙏",
            f"₹{order['total']:.0f} UPI से भुगतान करने के लिए टैप करें:\n{link}\n\nभुगतान होते ही हम आपका ऑर्डर तैयार करना शुरू कर देंगे 🙏",
        ))
    elif button_id == "pay_cod":
        svc.set_order_payment_mode(order["id"], "cod")
        await send_text(from_number, _t(
            lang,
            f"Got it — pay cash or UPI on delivery. Your order (₹{order['total']:.0f}) is confirmed! "
            f"For anything urgent, call {SHOP_WHATSAPP_DISPLAY_NUMBER}.",
            f"ठीक है — डिलीवरी पर नकद/UPI भुगतान करें। आपका ऑर्डर (₹{order['total']:.0f}) कन्फ़र्म हो गया है! "
            f"किसी भी ज़रूरी बात के लिए कॉल करें: {SHOP_WHATSAPP_DISPLAY_NUMBER}.",
        ))
        svc.set_order_status(order["id"], "confirmed")