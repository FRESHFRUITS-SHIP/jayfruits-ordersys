import hashlib
import hmac
from datetime import datetime
from fastapi import APIRouter, Request, Query, HTTPException, Response

from app.config import (
    META_VERIFY_TOKEN, META_APP_SECRET, SHOP_NAME,
    SHOP_WHATSAPP_DISPLAY_NUMBER, PUBLIC_BASE_URL,
)
# Add SHOP_BANNER_IMAGE_URL to app/config.py — a public https:// image URL
# (e.g. your shop's storefront/logo). If you don't want a banner image yet,
# leave it unset; the code below just skips it.
try:
    from app.config import SHOP_BANNER_IMAGE_URL
except ImportError:
    SHOP_BANNER_IMAGE_URL = None
from app.services.whatsapp import send_text, send_buttons, send_list_menu, send_image
from app.services.order_parser import parse_message, parse_quantity_only, generate_shopkeeper_reply
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
        elif msg["type"] in ("sticker", "reaction"):
            pass  # not worth replying to — avoids a confusing "send as text" message for a 👍 or sticker
        elif msg["type"] in ("audio", "voice", "image", "video", "document"):
            await send_text(
                from_number,
                "I can only read text messages right now — could you please type your order? 🙏\n"
                "उदाहरण: '2kg mango, 1 dozen banana'",
            )
        else:
            print(f"Unhandled WhatsApp message type: {msg['type']} — payload: {msg}")
            await send_text(from_number, "Please send your order as text, e.g. '2kg mango, 1 dozen banana'.")

    except (KeyError, IndexError):
        pass

    return {"status": "ok"}


# ---------- helpers ----------
def _t(lang: str, en: str, hi: str, hg: str | None = None) -> str:
    """
    lang: 'en' (English), 'hi' (Hindi/Devanagari), or 'hg' (Hinglish — romanized mix).
    If a string hasn't been given a dedicated Hinglish version yet, falls back to English.
    """
    if lang == "hi":
        return hi
    if lang == "hg":
        return hg if hg is not None else en
    return en


def _fmt_qty(qty: float) -> str:
    """Formats 2.0 -> '2', 1.5 -> '1.5' — avoids the sloppy '2.0 kg' look."""
    return str(int(qty)) if qty == int(qty) else str(qty)


def _time_based_greeting_emoji() -> tuple[str, str, str]:
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning", "सुप्रभात", "Good morning"
    if hour < 17:
        return "Good afternoon", "नमस्ते", "Good afternoon"
    return "Good evening", "शुभ संध्या", "Good evening"


def _name_bit(customer: dict, leading_space: bool = True) -> str:
    """Returns ', Name' (or ' Name' etc.) if we know the customer's name, else ''."""
    name = customer.get("name")
    if not name:
        return ""
    return f"{' ' if leading_space else ''}{name}"


ACKNOWLEDGEMENT_WORDS = {
    "thank you", "thanks", "thankyou", "thnx", "ty", "tq",
    "ok", "okay", "k", "cool", "great", "nice", "good", "perfect",
    "dhanyavad", "shukriya", "theek hai", "thik hai",
}

ABOUT_TRIGGERS = {
    "about", "help", "what is this", "who are you", "what are you",
    "kaun ho", "yeh kya hai", "ye kya hai", "kya hai yeh", "info",
    "how does this work", "how to order",
}

PICKUP_WORDS = {
    "pickup", "pick up", "self pickup", "i'll pick up", "ill pick up",
    "i will pick up", "self pick up", "pick-up",
}


async def _send_about_message(to: str, lang: str) -> None:
    text = _t(
        lang,
        f"ℹ️ *About {SHOP_NAME}*\n\n"
        f"I'm an automated ordering assistant 🤖🍉 — I take fruit orders here on WhatsApp, "
        f"round the clock, on behalf of {SHOP_NAME}.\n\n"
        "*How to order:*\n"
        "• Type a fruit name (e.g. 'mango') and I'll ask how much\n"
        "• Or send it all at once: '2kg mango, 1 dozen banana'\n"
        "• Type 'menu' anytime to browse everything\n"
        "• Type 'cancel' to cancel an open order, or 'same as last time' to reorder\n\n"
        f"For anything I can't handle, call the shop directly: {SHOP_WHATSAPP_DISPLAY_NUMBER} 🙏",
        f"ℹ️ *{SHOP_NAME} के बारे में*\n\n"
        f"मैं एक ऑटोमेटेड ऑर्डरिंग असिस्टेंट हूं 🤖🍉 — {SHOP_NAME} की तरफ से यहां WhatsApp पर "
        "24 घंटे ऑर्डर लेता हूं।\n\n"
        "*ऑर्डर कैसे करें:*\n"
        "• किसी फल का नाम लिखें (जैसे 'mango') और मैं मात्रा पूछूंगा\n"
        "• या एक साथ भेजें: '2kg mango, 1 dozen banana'\n"
        "• पूरा मेन्यू देखने के लिए कभी भी 'menu' लिखें\n"
        "• खुला ऑर्डर रद्द करने के लिए 'cancel' लिखें\n\n"
        f"किसी और मदद के लिए सीधे दुकान पर कॉल करें: {SHOP_WHATSAPP_DISPLAY_NUMBER} 🙏",
        f"ℹ️ *{SHOP_NAME} ke baare mein*\n\n"
        f"Main ek automated ordering assistant hoon 🤖🍉 — {SHOP_NAME} ki taraf se WhatsApp pe "
        "24x7 order leta hoon.\n\n"
        "*Order kaise karein:*\n"
        "• Kisi fruit ka naam likho (jaise 'mango'), main quantity pooch lunga\n"
        "• Ya ek saath bhejo: '2kg mango, 1 dozen banana'\n"
        "• Poora menu dekhne ke liye kabhi bhi 'menu' likho\n"
        "• Khula order cancel karne ke liye 'cancel' likho\n\n"
        f"Kisi bhi aur madad ke liye seedha shop ko call karo: {SHOP_WHATSAPP_DISPLAY_NUMBER} 🙏",
    )
    await send_text(to, text)


async def _send_language_selection(to: str) -> None:
    # One-time heads-up for people who know this number personally (friends/family)
    # and are messaging expecting a normal reply, not an ordering bot — since this
    # number is currently wired to the WhatsApp Cloud API for testing, the native
    # "Away Message" feature in the regular WhatsApp Business app won't fire here.
    await send_text(
        to,
        "👋 Hey! This number is currently being used to test an automated fruit-ordering "
        "system (Jay Fruit's) — so replies here are from a bot, not me personally, for now. "
        "If this is time-sensitive, please reach me another way. Thanks for bearing with the testing! 🙏",
    )
    await send_buttons(
        to,
        "🍉 Welcome! Please choose your language / भाषा चुनें:",
        [("lang_en", "English"), ("lang_hi", "हिंदी"), ("lang_hg", "Hinglish")],
    )


async def _greeting_and_menu(to: str, lang: str, is_first_time: bool = False) -> None:
    customer = svc.get_or_create_customer(to)
    if customer.get("pending_item"):
        svc.clear_pending_item(customer["id"])
    if customer.get("pending_order"):
        svc.clear_pending_order(customer["id"])

    if SHOP_BANNER_IMAGE_URL:
        await send_image(to, SHOP_BANNER_IMAGE_URL, caption=f"🍇🍊🍎 {SHOP_NAME}")

    top_items = svc.get_top_selling_or_seasonal(limit=4)
    names = ", ".join(p["name_en"] for p in top_items)
    greet_en, greet_hi, greet_hg = _time_based_greeting_emoji()
    who = _name_bit(customer)

    if is_first_time:
        intro = _t(
            lang,
            f"{greet_en}{who}! 🍉 Welcome to {SHOP_NAME} — fresh fruits, delivered daily. 🍎🍌🍇\n"
            f"Aaj {names} bahut accha hai. What can I get you today?\n\n"
            "_(Type 'help' anytime to see how ordering works.)_",
            f"{greet_hi}{who}! 🍉 {SHOP_NAME} में आपका स्वागत है — रोज़ ताज़े फल। 🍎🍌🍇\n"
            f"आज {names} बहुत अच्छा है। आज क्या चाहिए?\n\n"
            "_(ऑर्डर कैसे करें जानने के लिए कभी भी 'help' लिखें।)_",
            f"{greet_hg}{who}! 🍉 Welcome to {SHOP_NAME} — fresh fruits, daily. 🍎🍌🍇\n"
            f"Aaj {names} bahut accha hai. Aapko kya chahiye?\n\n"
            "_(Kabhi bhi 'help' likho order karne ka tarika jaanne ke liye.)_",
        )
    else:
        intro = _t(
            lang,
            f"{greet_en}{who}! 🍉 Good to see you again. Aaj {names} bahut accha hai — what would you like?",
            f"{greet_hi}{who}! 🍉 आपको फिर से देखकर अच्छा लगा। आज {names} बहुत अच्छा है — क्या चाहिए?",
            f"{greet_hg}{who}! 🍉 Wapas aane ke liye shukriya. Aaj {names} bahut accha hai — kya loge?",
        )
    await send_text(to, intro)

    sections = svc.build_menu_sections()
    if sections:
        await send_list_menu(
            to,
            body_text=_t(
                lang,
                "Tap below for today's full menu 👇",
                "आज का पूरा मेन्यू देखने के लिए नीचे टैप करें 👇",
                "Neeche tap karke aaj ka pura menu dekho 👇",
            ),
            button_text=_t(lang, "View Menu", "मेन्यू देखें", "Menu Dekho"),
            sections=sections,
            footer=_t(
                lang,
                "Or just type what you'd like",
                "या सीधे लिख कर बताएं",
                "Ya seedha type karke bata do",
            ),
        )


async def _send_payment_buttons(to: str, lang: str) -> None:
    await send_buttons(
        to,
        _t(lang, "How would you like to pay?", "भुगतान कैसे करेंगे?", "Payment kaise karoge?"),
        [("pay_upi", _t(lang, "Pay via UPI", "UPI से भुगतान", "UPI se Pay")),
         ("pay_cod", _t(lang, "Cash on delivery", "डिलीवरी पर नकद", "Cash on Delivery"))],
    )


async def _ask_fulfillment_or_address(to: str, customer: dict, lang: str) -> None:
    """
    After an order is created, ask how the customer wants it — via buttons.
    If we already have an address on file, offer to reuse it, change it, or
    switch to pickup. If not, ask delivery-vs-pickup first.
    """
    address = customer.get("address") or ""
    if address:
        body = _t(
            lang,
            f"📍 Deliver to: {address}?",
            f"📍 इस पते पर डिलीवर करें: {address}?",
            f"📍 Is address pe deliver karu: {address}?",
        )
        await send_buttons(to, body, [
            ("deliver_here", _t(lang, "✅ Yes, deliver", "✅ हां", "✅ Haan")),
            ("change_address", _t(lang, "✏️ Change address", "✏️ पता बदलें", "✏️ Address badlo")),
            ("choose_pickup", _t(lang, "🏪 I'll pickup", "🏪 खुद लूंगा", "🏪 Khud le lunga")),
        ])
    else:
        body = _t(
            lang,
            "📍 How would you like to get this order?",
            "📍 ऑर्डर कैसे चाहिए?",
            "📍 Order kaise chahiye?",
        )
        await send_buttons(to, body, [
            ("want_delivery", _t(lang, "🚴 Deliver to me", "🚴 डिलीवर करें", "🚴 Deliver karo")),
            ("choose_pickup", _t(lang, "🏪 I'll pickup", "🏪 खुद लूंगा", "🏪 Khud le lunga")),
        ])


async def _apply_pickup(to: str, customer: dict, lang: str) -> None:
    order = svc.get_latest_open_order_for_customer(customer["id"])
    if not order:
        await send_text(to, _t(
            lang, "You don't have an open order right now — send your order first!",
            "अभी आपका कोई खुला ऑर्डर नहीं है — पहले ऑर्डर भेजें!",
            "Abhi koi khula order nahi hai — pehle order bhejo!",
        ))
        return
    svc.set_order_fulfillment(order["id"], "pickup")
    who = _name_bit(customer)
    await send_text(to, _t(
        lang,
        f"Got it{who} — order #{order['id']} will be ready for you to pick up. See you soon! 🙏",
        f"ठीक है{who} — ऑर्डर #{order['id']} पिकअप के लिए तैयार रहेगा। मिलते हैं! 🙏",
        f"Theek hai{who} — order #{order['id']} pickup ke liye ready rahega. Milte hain! 🙏",
    ))
    if order.get("payment_mode", "unset") == "unset":
        await _send_payment_buttons(to, lang)


async def _finalize_order(
    to: str, customer: dict, items_for_order: list[dict], lines: list[str],
    unavailable: list[str], raw_text: str, lang: str,
) -> None:
    """Actually creates the order in the DB (called only after Confirm is tapped)
    and walks the customer into delivery/pickup + payment."""
    order = svc.create_order(
        customer["id"], items_for_order, raw_message=raw_text,
        source="whatsapp", delivery_address=customer.get("address") or "",
    )
    who = _name_bit(customer)
    summary = "\n".join(lines)
    header = _t(
        lang, f"Order confirmed{who}! 🧾✅", f"ऑर्डर पक्का हो गया{who}! 🧾✅", f"Order confirm ho gaya{who}! 🧾✅",
    )
    reply = f"{header}\n\n{summary}\n\n*{_t(lang,'Total','कुल','Total')}: ₹{order['total']:.0f}*\n_Order #{order['id']}_"
    if unavailable:
        reply += "\n\n" + _t(
            lang,
            f"(Sorry, not available right now: {', '.join(unavailable)})",
            f"(माफ़ करें, अभी उपलब्ध नहीं: {', '.join(unavailable)})",
            f"(Maaf karo, abhi available nahi: {', '.join(unavailable)})",
        )
    if order.get("is_duplicate_flag"):
        reply += "\n\n" + _t(
            lang,
            "⚠️ Looks like you just ordered again — if this wasn't intentional, reply 'cancel' to cancel this one.",
            "⚠️ लगता है आपने अभी दोबारा ऑर्डर किया — अगर गलती से हुआ है तो 'cancel' लिखें।",
            "⚠️ Lagta hai abhi dobara order kiya — galti se hua hai toh 'cancel' likho.",
        )
    await send_text(to, reply)
    await _ask_fulfillment_or_address(to, customer, lang)


# ---------- main conversation handler ----------
async def handle_text_message(from_number: str, text: str) -> None:
    customer = svc.get_or_create_customer(from_number)
    stripped = text.strip().lower().strip(".!😊🙏👍")

    # Brand new customer — ask language before doing anything else.
    if customer.get("preferred_language") is None:
        await _send_language_selection(from_number)
        return

    # Language chosen but name not yet captured — this message IS their name.
    if not customer.get("name") and not customer.get("pending_item") and not customer.get("pending_order"):
        lang0 = customer.get("preferred_language") or "en"
        name_text = text.strip()
        if not (1 <= len(name_text) <= 40):
            await send_text(from_number, _t(
                lang0,
                "Please share just your first name 🙂",
                "कृपया अपना नाम बताएं 🙂",
                "Apna naam batao 🙂",
            ))
            return
        clean_name = name_text.title()
        svc.set_customer_name(customer["id"], clean_name)
        customer["name"] = clean_name
        await _greeting_and_menu(from_number, lang0, is_first_time=True)
        return

    if stripped in ("hi", "hello", "hey", "menu", "namaste", "hii", "hlo"):
        lang = customer.get("preferred_language") or "en"
        await _greeting_and_menu(from_number, lang)
        return

    if stripped in ABOUT_TRIGGERS:
        lang = customer.get("preferred_language") or "en"
        await _send_about_message(from_number, lang)
        return

    if stripped in ACKNOWLEDGEMENT_WORDS:
        lang = customer.get("preferred_language") or "en"
        who = _name_bit(customer)
        await send_text(from_number, _t(
            lang, f"You're welcome{who}! 😊", f"आपका स्वागत है{who}! 😊", f"Koi baat nahi{who}! 😊",
        ))
        return

    if stripped in PICKUP_WORDS:
        lang = customer.get("preferred_language") or "en"
        await _apply_pickup(from_number, customer, lang)
        return

    # ---- pending "kitna chahiye?" flow: this message is expected to be just a quantity ----
    pending_item = customer.get("pending_item")
    if pending_item:
        lang = customer.get("preferred_language") or "en"
        qty = parse_quantity_only(text, target_unit=pending_item["unit"])
        if qty:
            svc.clear_pending_item(customer["id"])
            fake_parsed = {
                "intent": "new_order",
                "language": lang,
                "items": [{"product_name": pending_item["name_en"], "quantity": qty, "unit": pending_item["unit"], "action": "add"}],
                "unavailable_items": [],
                "address_text": "",
                "note": "",
            }
            await _handle_new_order(from_number, customer, fake_parsed, text, lang)
            return
        else:
            await send_text(from_number, _t(
                lang,
                f"Sorry, didn't catch that — how much {pending_item['name_en']} would you like? (e.g. 2 {pending_item['unit']})",
                f"माफ़ करें, समझ नहीं आया — कितना {pending_item['name_en']} चाहिए? (जैसे 2 {pending_item['unit']})",
                f"Maaf karo, samajh nahi aaya — kitna {pending_item['name_en']} chahiye? (jaise 2 {pending_item['unit']})",
            ))
            return

    menu = svc.get_available_menu()
    parsed = parse_message(text, menu)
    # Language stays whatever the customer explicitly chose during onboarding —
    # we don't let Groq's per-message guess silently overwrite it.
    lang = customer.get("preferred_language") or parsed.get("language", "en")

    intent = parsed["intent"]

    # Backup net: if Groq still classifies a short acknowledgement/thanks as
    # "greeting", don't re-send the whole menu.
    if intent == "greeting" and len(stripped.split()) <= 3 and stripped not in ("hi", "hello", "hey", "menu"):
        who = _name_bit(customer)
        await send_text(from_number, _t(
            lang, f"You're welcome{who}! 😊", f"आपका स्वागत है{who}! 😊", f"Koi baat nahi{who}! 😊",
        ))
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

    # "other" — unclear message, chit-chat, question, or price haggling. Before
    # giving up, check: are we mid-conversation waiting on this customer's
    # delivery address? If so, treat their reply as the address.
    open_order = svc.get_latest_open_order_for_customer(customer["id"])
    if open_order and open_order.get("fulfillment") == "delivery" and not open_order.get("delivery_address") and not customer.get("address"):
        svc.set_customer_address(customer["id"], text.strip())
        from app.db import get_db
        get_db().table("orders").update({"delivery_address": text.strip()}).eq("id", open_order["id"]).execute()
        await send_text(from_number, _t(
            lang, f"Got it — saved your address: {text.strip()}",
            f"ठीक है — पता सेव कर लिया: {text.strip()}",
            f"Theek hai — address save kar liya: {text.strip()}",
        ))
        if open_order.get("payment_mode", "unset") == "unset":
            await _send_payment_buttons(from_number, lang)
        return

    note = parsed.get("note") or ""
    situation = f"Customer wrote: \"{text}\"."
    if note:
        situation += f" Context: {note}."
    else:
        situation += " Their message wasn't a clear order — gently ask them to name what they want, e.g. '2kg mango, 1 dozen banana', or mention they can type 'menu'."

    shopkeeper_reply = generate_shopkeeper_reply(situation, lang, SHOP_NAME)
    if shopkeeper_reply:
        await send_text(from_number, shopkeeper_reply)
        return

    reply = _t(
        lang,
        "Not sure I understood that. Send your order like '2kg mango, 1 dozen banana', or type 'menu'.",
        "समझ नहीं आया 🙏 ऑर्डर ऐसे भेजें: '2kg mango, 1 dozen banana', या 'menu' लिखें।",
        "Samajh nahi aaya 🙏 Order aise bhejo: '2kg mango, 1 dozen banana', ya 'menu' likho.",
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
            f"Abhi dukaan band hai. Hamara time {settings['business_hours_start']}:00–{settings['business_hours_end']}:00 hai. "
            "Dukaan khulne par dobara order bhejo 🙏",
        ))
        return

    menu = svc.get_available_menu()
    matched = svc.match_products([i["product_name"] for i in parsed["items"]], menu)

    # ---- single item named, no quantity given: check for variants first ----
    items_missing_qty = [i for i in parsed["items"] if i.get("quantity") in (None, "", 0)]
    if items_missing_qty and len(parsed["items"]) == 1:
        item = items_missing_qty[0]
        variants = svc.find_variant_options(item["product_name"], menu)

        if len(variants) > 1:
            for v in variants[:8]:
                if v.get("image_url"):
                    await send_image(to, v["image_url"], caption=f"{v['name_en']} — ₹{v['price']}/{v['unit']}")
            sections = svc.build_variant_list_section(variants, title=item["product_name"].title())
            await send_list_menu(
                to,
                body_text=_t(
                    lang,
                    f"We've got a few kinds of {item['product_name']} — which one would you like?",
                    f"{item['product_name']} में कई तरह हैं — कौन सा चाहिए?",
                    f"{item['product_name']} ke kai variants hain — kaunsa loge?",
                ),
                button_text=_t(lang, "Choose Variant", "चुनें", "Choose Karo"),
                sections=sections,
            )
            return

        product = matched.get(item["product_name"]) or (variants[0] if variants else None)
        if product:
            svc.set_pending_item(customer["id"], product)
            await send_text(to, _t(
                lang,
                f"{product['name_en']} — kitna chahiye? (e.g. 2 {product['unit']})",
                f"{product['name_en']} — कितना चाहिए? (जैसे 2 {product['unit']})",
                f"{product['name_en']} — kitna chahiye? (jaise 2 {product['unit']})",
            ))
            return

    items_for_order = []
    lines = []
    for item in parsed["items"]:
        product = matched.get(item["product_name"])
        if not product:
            continue
        qty = item.get("quantity")
        if qty in (None, "", 0):
            await send_text(to, _t(
                lang,
                "Could you tell me the quantity for each item? e.g. '2kg mango, 1 dozen banana'",
                "कृपया हर आइटम की मात्रा बताएं, जैसे: '2kg mango, 1 dozen banana'",
                "Har item ki quantity batao, jaise: '2kg mango, 1 dozen banana'",
            ))
            return
        qty = float(qty)
        items_for_order.append({"product": product, "quantity": qty})
        line_total = product["price"] * qty
        lines.append(f"• {product['name_en']} — {_fmt_qty(qty)} {product['unit']} × ₹{product['price']} = ₹{line_total:.0f}")

    unavailable = parsed.get("unavailable_items", [])

    if not items_for_order:
        await send_text(to, _t(
            lang,
            "Sorry, I couldn't match any items on our menu. Type 'menu' to see what's available today.",
            "माफ़ करें, कोई भी आइटम मेन्यू में नहीं मिला। आज का मेन्यू देखने के लिए 'menu' लिखें।",
            "Maaf karo, koi bhi item menu mein nahi mila. Aaj ka menu dekhne ke liye 'menu' likho.",
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
            f"Aapka order ₹{total:.0f} ka hai, lekin minimum order ₹{min_order:.0f} hai. "
            "Thoda aur jodo!",
        ))
        return

    # ---- stash pending order and ask for explicit confirmation before creating it ----
    svc.set_pending_order(customer["id"], {
        "raw_message": raw_text,
        "items": [{"product_id": i["product"]["id"], "quantity": i["quantity"]} for i in items_for_order],
        "unavailable_items": unavailable,
    })
    who = _name_bit(customer)
    summary = "\n".join(lines)
    header = _t(lang, f"Please confirm{who} 🧾", f"कृपया कन्फ़र्म करें{who} 🧾", f"Confirm karo{who} 🧾")
    reply = f"{header}\n\n{summary}\n\n*{_t(lang,'Total','कुल','Total')}: ₹{total:.0f}*"
    if unavailable:
        reply += "\n\n" + _t(
            lang,
            f"(Sorry, not available right now: {', '.join(unavailable)})",
            f"(माफ़ करें, अभी उपलब्ध नहीं: {', '.join(unavailable)})",
            f"(Maaf karo, abhi available nahi: {', '.join(unavailable)})",
        )
    await send_text(to, reply)
    await send_buttons(
        to,
        _t(lang, "Looks good?", "सही है?", "Sahi hai?"),
        [
            ("confirm_order", _t(lang, "✅ Confirm", "✅ पक्का करें", "✅ Confirm")),
            ("edit_order", _t(lang, "✏️ Edit", "✏️ बदलें", "✏️ Edit")),
        ],
    )


async def _handle_edit(to: str, customer: dict, parsed: dict, lang: str) -> None:
    order = svc.get_latest_open_order_for_customer(customer["id"])
    if not order:
        await send_text(to, _t(
            lang,
            "You don't have an open order to edit. Send a new order anytime!",
            "आपका कोई खुला ऑर्डर नहीं है। नया ऑर्डर कभी भी भेजें!",
            "Aapka koi khula order nahi hai. Naya order kabhi bhi bhejo!",
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
        qty = float(item.get("quantity") or 1)
        action = item.get("action", "add")
        if action == "remove":
            new_total = svc.remove_item_from_order(order["id"], product["name_en"])
            changes.append(_t(lang, f"Removed {product['name_en']}", f"{product['name_en']} हटाया गया", f"{product['name_en']} hataya gaya"))
        else:
            new_total = svc.add_item_to_order(order["id"], product, qty)
            changes.append(_t(
                lang,
                f"Added {_fmt_qty(qty)} {product['unit']} {product['name_en']}",
                f"{_fmt_qty(qty)} {product['unit']} {product['name_en']} जोड़ा गया",
                f"{_fmt_qty(qty)} {product['unit']} {product['name_en']} add ho gaya",
            ))

    if not changes:
        await send_text(to, _t(lang, "Couldn't match that item to your order.", "वह आइटम ऑर्डर में नहीं मिला।", "Wo item order mein nahi mila."))
        return

    reply = "\n".join(f"✅ {c}" for c in changes)
    reply += f"\n\n*{_t(lang,'New total','नया कुल','Naya total')}: ₹{new_total:.0f}*"
    await send_text(to, reply)


async def _handle_cancel(to: str, customer: dict, lang: str) -> None:
    order = svc.get_latest_open_order_for_customer(customer["id"])
    if not order:
        await send_text(to, _t(lang, "You don't have an active order to cancel.", "आपका कोई सक्रिय ऑर्डर नहीं है।", "Aapka koi active order nahi hai."))
        return
    svc.cancel_order(order["id"])
    await send_text(to, _t(
        lang, f"Order #{order['id']} has been cancelled. No charge.",
        f"ऑर्डर #{order['id']} रद्द कर दिया गया है। कोई शुल्क नहीं।",
        f"Order #{order['id']} cancel kar diya gaya hai. Koi charge nahi.",
    ))


async def _handle_reorder(to: str, customer: dict, lang: str) -> None:
    last = svc.get_latest_order_for_customer(customer["id"])
    if not last or not last.get("order_items"):
        await send_text(to, _t(lang, "You don't have a previous order to repeat.", "आपका कोई पिछला ऑर्डर नहीं मिला।", "Aapka koi pichla order nahi mila."))
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
        await send_text(to, _t(lang, "Sorry, those items aren't available today.", "माफ़ करें, वे आइटम आज उपलब्ध नहीं हैं।", "Maaf karo, wo items aaj available nahi hain."))
        return

    order = svc.create_order(
        customer["id"], items_for_order, raw_message="(reorder)",
        source="whatsapp", delivery_address=customer.get("address") or "",
    )
    who = _name_bit(customer)
    summary = "\n".join(lines)
    reply = (
        f"{_t(lang,'Repeating your last order','आपका पिछला ऑर्डर दोहराया जा रहा है','Aapka pichla order repeat kiya jaa raha hai')}"
        f"{who}! 🔁\n\n{summary}\n\n*{_t(lang,'Total','कुल','Total')}: ₹{order['total']:.0f}*"
    )
    if skipped:
        reply += "\n\n" + _t(
            lang,
            f"(No longer available: {', '.join(skipped)})",
            f"(अब उपलब्ध नहीं: {', '.join(skipped)})",
            f"(Ab available nahi: {', '.join(skipped)})",
        )
    await send_text(to, reply)
    await _ask_fulfillment_or_address(to, customer, lang)


async def _handle_address(to: str, customer: dict, parsed: dict, lang: str) -> None:
    address = parsed.get("address_text", "").strip()
    if not address:
        await send_text(to, _t(lang, "Please share your delivery address.", "कृपया अपना डिलीवरी पता भेजें।", "Apna delivery address bhejo."))
        return
    svc.set_customer_address(customer["id"], address)

    order = svc.get_latest_open_order_for_customer(customer["id"])
    was_missing_address = order and not order.get("delivery_address")
    if order and was_missing_address:
        from app.db import get_db
        get_db().table("orders").update({"delivery_address": address}).eq("id", order["id"]).execute()

    await send_text(to, _t(
        lang, f"Got it — saved your address: {address}",
        f"ठीक है — पता सेव कर लिया: {address}",
        f"Theek hai — address save kar liya: {address}",
    ))

    if order and was_missing_address and order.get("payment_mode", "unset") == "unset":
        await _send_payment_buttons(to, lang)


async def handle_button_reply(from_number: str, button_id: str) -> None:
    customer = svc.get_or_create_customer(from_number)
    lang = customer.get("preferred_language") or "en"

    # ---- tapped a language choice ----
    if button_id.startswith("lang_"):
        chosen = button_id.split("_", 1)[1]  # 'en' | 'hi' | 'hg'
        svc.set_customer_language(customer["id"], chosen)
        customer["preferred_language"] = chosen
        await send_text(from_number, _t(
            chosen,
            "Great! What should I call you? 😊 (just your first name)",
            "बढ़िया! आपको किस नाम से बुलाऊं? 😊 (सिर्फ पहला नाम)",
            "Great! Aapka naam kya bataun? 😊 (bas pehla naam)",
        ))
        return

    # ---- tapped a product row from the List Message ----
    if button_id.startswith("prod_"):
        try:
            product_id = int(button_id.split("_", 1)[1])
        except ValueError:
            return
        product = svc.get_product_by_id(product_id)
        if not product:
            await send_text(from_number, _t(lang, "Sorry, that item isn't available anymore.", "माफ़ करें, वह आइटम अब उपलब्ध नहीं है।", "Maaf karo, wo item ab available nahi hai."))
            return
        svc.set_pending_item(customer["id"], product)
        await send_text(from_number, _t(
            lang,
            f"{product['name_en']} — kitna chahiye? (e.g. 2 {product['unit']})",
            f"{product['name_en']} — कितना चाहिए? (जैसे 2 {product['unit']})",
            f"{product['name_en']} — kitna chahiye? (jaise 2 {product['unit']})",
        ))
        return

    # ---- order confirmation ----
    if button_id == "confirm_order":
        pending = customer.get("pending_order")
        if not pending:
            await send_text(from_number, _t(
                lang, "Nothing to confirm — send your order again.",
                "कन्फ़र्म करने के लिए कुछ नहीं — दोबारा ऑर्डर भेजें।",
                "Confirm karne ko kuch nahi — dobara order bhejo.",
            ))
            return
        items_for_order = []
        lines = []
        for it in pending.get("items", []):
            product = svc.get_product_by_id(it["product_id"])
            if not product:
                continue
            qty = float(it["quantity"])
            items_for_order.append({"product": product, "quantity": qty})
            lines.append(f"• {product['name_en']} — {_fmt_qty(qty)} {product['unit']} × ₹{product['price']} = ₹{product['price']*qty:.0f}")
        svc.clear_pending_order(customer["id"])
        if not items_for_order:
            await send_text(from_number, _t(
                lang, "Sorry, something went wrong — please resend your order.",
                "माफ़ करें, कुछ गड़बड़ हुई — दोबारा ऑर्डर भेजें।",
                "Maaf karo, kuch gadbad hui — dobara order bhejo.",
            ))
            return
        await _finalize_order(
            from_number, customer, items_for_order, lines,
            pending.get("unavailable_items", []), pending.get("raw_message", ""), lang,
        )
        return

    if button_id == "edit_order":
        svc.clear_pending_order(customer["id"])
        await send_text(from_number, _t(
            lang, "No problem — send the corrected order whenever you're ready 🙏",
            "कोई बात नहीं — सही ऑर्डर दोबारा भेजें 🙏",
            "Koi baat nahi — sahi order dobara bhejo 🙏",
        ))
        return

    # ---- delivery / pickup / address buttons (post-order) ----
    if button_id == "deliver_here":
        order = svc.get_latest_open_order_for_customer(customer["id"])
        if order:
            eta = order.get("eta_minutes")
            if eta:
                await send_text(from_number, _t(
                    lang, f"🚴 Estimated delivery: ~{eta} minutes.",
                    f"🚴 अनुमानित डिलीवरी समय: ~{eta} मिनट।",
                    f"🚴 Delivery ~{eta} minute mein ho jayegi.",
                ))
            if order.get("payment_mode", "unset") == "unset":
                await _send_payment_buttons(from_number, lang)
        return

    if button_id == "change_address":
        await send_text(from_number, _t(
            lang, "Sure — what's the new delivery address?",
            "ठीक है — नया पता बताएं?",
            "Theek hai — naya address batao?",
        ))
        return

    if button_id == "want_delivery":
        await send_text(from_number, _t(
            lang, "📍 What's your delivery address?",
            "📍 आपका डिलीवरी पता क्या है?",
            "📍 Delivery address kya hai?",
        ))
        return

    if button_id == "choose_pickup":
        await _apply_pickup(from_number, customer, lang)
        return

    # ---- payment ----
    order = svc.get_latest_open_order_for_customer(customer["id"])
    if not order:
        await send_text(from_number, _t(
            lang, "Couldn't find an open order — please send your order again.",
            "कोई खुला ऑर्डर नहीं मिला — कृपया दोबारा भेजें।",
            "Koi khula order nahi mila — dobara bhejo.",
        ))
        return

    if button_id == "pay_upi":
        svc.set_order_payment_mode(order["id"], "upi")
        link = build_upi_link(order["total"], order["id"])
        who = _name_bit(customer)
        await send_text(from_number, _t(
            lang,
            f"Tap to pay ₹{order['total']:.0f} via UPI:\n{link}\n\nOnce paid, we'll confirm and start preparing your order{who}. 🙏",
            f"₹{order['total']:.0f} UPI से भुगतान करने के लिए टैप करें:\n{link}\n\nभुगतान होते ही हम आपका ऑर्डर तैयार करना शुरू कर देंगे{who} 🙏",
            f"₹{order['total']:.0f} UPI se pay karne ke liye tap karo:\n{link}\n\nPayment hote hi order taiyar karna shuru kar denge{who} 🙏",
        ))
    elif button_id == "pay_cod":
        svc.set_order_payment_mode(order["id"], "cod")
        who = _name_bit(customer)
        await send_text(from_number, _t(
            lang,
            f"Got it{who} — pay cash or UPI on delivery. Your order (₹{order['total']:.0f}) is confirmed! "
            f"For anything urgent, call {SHOP_WHATSAPP_DISPLAY_NUMBER}.",
            f"ठीक है{who} — डिलीवरी पर नकद/UPI भुगतान करें। आपका ऑर्डर (₹{order['total']:.0f}) कन्फ़र्म हो गया है! "
            f"किसी भी ज़रूरी बात के लिए कॉल करें: {SHOP_WHATSAPP_DISPLAY_NUMBER}.",
            f"Theek hai{who} — delivery par cash/UPI se pay karo. Order (₹{order['total']:.0f}) confirm ho gaya hai! "
            f"Kisi bhi zaroori baat ke liye call karo: {SHOP_WHATSAPP_DISPLAY_NUMBER}.",
        ))
        svc.set_order_status(order["id"], "confirmed")