"""
Top-level conversation dispatcher. This is what app/routers/webhook.py calls
after unwrapping the Meta payload.

Phase 2: every branch below now also updates the explicit conversation_state
(see app/conversation/state.py) alongside the pending_item/pending_order
flags. The flags remain the actual data (what item, what draft order); the
state is the explicit label of "where in the flow is this customer" — used
for validation, debugging, and interruption handling (a customer asking an
unrelated question mid-flow now correctly resumes afterward).
"""
from app.config import SHOP_WHATSAPP_DISPLAY_NUMBER, SHOP_NAME
from app.services.whatsapp import send_text
from app.services.order_parser import parse_message, parse_quantity_only, generate_shopkeeper_reply
from app.services.upi import build_upi_link
from app.services import orders as svc
from app.services.audit import log_event

from app.conversation.messages import _t, _fmt_qty, _name_bit, ACKNOWLEDGEMENT_WORDS, ABOUT_TRIGGERS, PICKUP_WORDS, send_about_message
from app.conversation.onboarding import send_language_selection, greeting_and_menu
from app.conversation.fulfillment import send_payment_buttons, ask_fulfillment_or_address, apply_pickup, handle_address
from app.conversation.order_flow import handle_new_order, handle_edit, handle_cancel, handle_reorder, finalize_order
from app.conversation.state import (
    ConversationState, get_state, set_state,
    push_interruption, pop_interruption, clear_interruption,
)


# ---------- main conversation handler ----------
async def handle_text_message(from_number: str, text: str) -> None:
    customer = svc.get_or_create_customer(from_number)
    current_state = get_state(customer)
    stripped = text.strip().lower().strip(".!😊🙏👍")

    # Brand new customer — ask language before doing anything else.
    if customer.get("preferred_language") is None:
        await send_language_selection(from_number)
        set_state(customer["id"], ConversationState.LANGUAGE_SELECTION, current=current_state)
        return

    # Language chosen but name not yet captured — this message IS their name.
    if not customer.get("name") and not customer.get("pending_item") and not customer.get("pending_order"):
        lang0 = customer.get("preferred_language") or "en"
        name_text = text.strip()
        NON_NAME_WORDS = {"hi", "hello", "hey", "hii", "hlo", "menu", "namaste"} | ACKNOWLEDGEMENT_WORDS | ABOUT_TRIGGERS | PICKUP_WORDS
        if not (1 <= len(name_text) <= 40) or stripped in NON_NAME_WORDS:
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
        await greeting_and_menu(from_number, lang0, is_first_time=True)
        set_state(customer["id"], ConversationState.BROWSING, current=current_state)
        return

    if stripped in ("hi", "hello", "hey", "menu", "namaste", "hii", "hlo"):
        lang = customer.get("preferred_language") or "en"
        await greeting_and_menu(from_number, lang)
        return

    if stripped in ABOUT_TRIGGERS:
        lang = customer.get("preferred_language") or "en"
        await send_about_message(from_number, lang)
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
        await apply_pickup(from_number, customer, lang)
        return

    # ---- pending "kitna chahiye?" flow: this message is expected to be just a quantity ----
    pending_item = customer.get("pending_item")
    if pending_item:
        lang = customer.get("preferred_language") or "en"
        qty = parse_quantity_only(text, target_unit=pending_item["unit"])
        if qty:
            svc.clear_pending_item(customer["id"])
            clear_interruption(customer["id"])
            fake_parsed = {
                "intent": "new_order",
                "language": lang,
                "items": [{"product_name": pending_item["name_en"], "quantity": qty, "unit": pending_item["unit"], "action": "add"}],
                "unavailable_items": [],
                "address_text": "",
                "note": "",
            }
            await handle_new_order(from_number, customer, fake_parsed, text, lang)
            set_state(customer["id"], ConversationState.CART_REVIEW, current=ConversationState.WAITING_QUANTITY)
            return
        else:
            # Not a parseable quantity — could be a genuine side-quest ("apple ka price?")
            # rather than a garbled quantity. Ask Groq what this actually is; if it's a
            # real order/other intent, treat it as an interruption: answer it, then
            # remind the customer we're still waiting on their quantity, and stay
            # parked in WAITING_QUANTITY (pending_item is untouched) so their next
            # message is still interpreted as the quantity.
            menu = svc.get_available_menu()
            parsed = parse_message(text, menu)
            if parsed["intent"] == "other" and parsed.get("note"):
                push_interruption(customer["id"], ConversationState.WAITING_QUANTITY)
                shopkeeper_reply = generate_shopkeeper_reply(
                    f"Customer wrote: \"{text}\". Context: {parsed['note']}. "
                    f"After answering, remind them you're still waiting on the quantity for {pending_item['name_en']}.",
                    lang, SHOP_NAME,
                )
                if shopkeeper_reply:
                    await send_text(from_number, shopkeeper_reply)
                    return

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
        await greeting_and_menu(from_number, lang)
        set_state(customer["id"], ConversationState.BROWSING, current=current_state)
        return

    if intent == "address":
        await handle_address(from_number, customer, parsed, lang)
        set_state(customer["id"], ConversationState.PAYMENT_PENDING, current=ConversationState.ADDRESS_COLLECTION)
        return

    if intent == "cancel_order":
        await handle_cancel(from_number, customer, lang)
        set_state(customer["id"], ConversationState.BROWSING, current=current_state)
        return

    if intent == "reorder":
        await handle_reorder(from_number, customer, lang)
        set_state(customer["id"], ConversationState.DELIVERY_SELECTION, current=current_state)
        return

    if intent == "edit_order":
        await handle_edit(from_number, customer, parsed, lang)
        set_state(customer["id"], ConversationState.BROWSING, current=current_state)
        return

    if intent == "new_order":
        await handle_new_order(from_number, customer, parsed, text, lang)
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
            await send_payment_buttons(from_number, lang)
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


# ---------- button reply handler ----------
async def handle_button_reply(from_number: str, button_id: str) -> None:
    customer = svc.get_or_create_customer(from_number)
    current_state = get_state(customer)
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
        set_state(customer["id"], ConversationState.NAME_CAPTURE, current=current_state)
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
        set_state(customer["id"], ConversationState.WAITING_QUANTITY, current=current_state)
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
        await finalize_order(
            from_number, customer, items_for_order, lines,
            pending.get("unavailable_items", []), pending.get("raw_message", ""), lang,
        )
        set_state(customer["id"], ConversationState.DELIVERY_SELECTION, current=ConversationState.CART_REVIEW)
        return

    if button_id == "edit_order":
        svc.clear_pending_order(customer["id"])
        await send_text(from_number, _t(
            lang, "No problem — send the corrected order whenever you're ready 🙏",
            "कोई बात नहीं — सही ऑर्डर दोबारा भेजें 🙏",
            "Koi baat nahi — sahi order dobara bhejo 🙏",
        ))
        set_state(customer["id"], ConversationState.BROWSING, current=ConversationState.CART_REVIEW)
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
                await send_payment_buttons(from_number, lang)
                set_state(customer["id"], ConversationState.PAYMENT_PENDING, current=current_state)
        return

    if button_id == "change_address":
        await send_text(from_number, _t(
            lang, "Sure — what's the new delivery address?",
            "ठीक है — नया पता बताएं?",
            "Theek hai — naya address batao?",
        ))
        set_state(customer["id"], ConversationState.ADDRESS_COLLECTION, current=current_state)
        return

    if button_id == "want_delivery":
        await send_text(from_number, _t(
            lang, "📍 What's your delivery address?",
            "📍 आपका डिलीवरी पता क्या है?",
            "📍 Delivery address kya hai?",
        ))
        set_state(customer["id"], ConversationState.ADDRESS_COLLECTION, current=current_state)
        return

    if button_id == "choose_pickup":
        await apply_pickup(from_number, customer, lang)
        set_state(customer["id"], ConversationState.PAYMENT_PENDING, current=current_state)
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
        log_event("PAYMENT_STARTED", customer_id=customer["id"], details={"order_id": order["id"], "mode": "upi", "amount": order["total"]})
        link = build_upi_link(order["total"], order["id"])
        who = _name_bit(customer)
        await send_text(from_number, _t(
            lang,
            f"Tap to pay ₹{order['total']:.0f} via UPI:\n{link}\n\nOnce paid, we'll confirm and start preparing your order{who}. 🙏",
            f"₹{order['total']:.0f} UPI से भुगतान करने के लिए टैप करें:\n{link}\n\nभुगतान होते ही हम आपका ऑर्डर तैयार करना शुरू कर देंगे{who} 🙏",
            f"₹{order['total']:.0f} UPI se pay karne ke liye tap karo:\n{link}\n\nPayment hote hi order taiyar karna shuru kar denge{who} 🙏",
        ))
        set_state(customer["id"], ConversationState.ORDER_CONFIRMED, current=ConversationState.PAYMENT_PENDING)
    elif button_id == "pay_cod":
        svc.set_order_payment_mode(order["id"], "cod")
        log_event("PAYMENT_STARTED", customer_id=customer["id"], details={"order_id": order["id"], "mode": "cod", "amount": order["total"]})
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
        set_state(customer["id"], ConversationState.ORDER_CONFIRMED, current=ConversationState.PAYMENT_PENDING)