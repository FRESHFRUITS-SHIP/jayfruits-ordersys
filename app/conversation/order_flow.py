"""Order lifecycle: new order -> confirm -> finalize, plus edit/cancel/reorder.
Pulled out of webhook.py, pure move — no behavior change."""
from app.services.whatsapp import send_text, send_buttons, send_image, send_list_menu
from app.services import orders as svc
from app.services.audit import log_event
from app.services.order_parser import convert_unit
from app.conversation.validation import validate_quantity
from app.conversation.messages import _t, _fmt_qty, _name_bit
from app.conversation.fulfillment import ask_fulfillment_or_address
from app.conversation.state import ConversationState, set_state


async def finalize_order(
    to: str, customer: dict, items_for_order: list[dict], lines: list[str],
    unavailable: list[str], raw_text: str, lang: str,
) -> None:
    """Actually creates the order in the DB (called only after Confirm is tapped)
    and walks the customer into delivery/pickup + payment."""
    order = svc.create_order(
        customer["id"], items_for_order, raw_message=raw_text,
        source="whatsapp", delivery_address=customer.get("address") or "",
    )
    log_event("ORDER_CONFIRMED", customer_id=customer["id"], details={
        "order_id": order["id"], "total": order["total"],
        "items": [{"name": i["product"]["name_en"], "qty": i["quantity"]} for i in items_for_order],
    })
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
    await ask_fulfillment_or_address(to, customer, lang)


async def handle_new_order(to: str, customer: dict, parsed: dict, raw_text: str, lang: str) -> None:
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
            set_state(customer["id"], ConversationState.SELECTING_VARIANT)
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
            set_state(customer["id"], ConversationState.WAITING_QUANTITY)
            return

    items_for_order = []
    lines = []
    unit_mismatch_items = []
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

        # CRITICAL SAFETY CHECK, two parts:
        #
        # 1) Groq may extract a unit ("piece") that differs from how this
        #    product is actually sold ("dozen"). Never apply the raw number
        #    directly against the product's price without checking — that's
        #    exactly how "6 piece kela" silently became "6 dozen"
        #    (₹360 instead of ~₹30).
        #
        # 2) A BARE number with NO unit word at all ("7 sev", "3 apple") is
        #    only safe to assume in the product's own unit when that unit is
        #    itself a count (piece/packet/bunch) — a bare "7" naturally means
        #    "7 of them". For weight/volume/dozen units (kg, gram, litre, ml,
        #    dozen), a bare number is genuinely ambiguous: "7 sev" almost
        #    certainly means 7 individual apples, not 7 kilograms, and
        #    silently assuming kg produced a real ₹1260 order for what the
        #    customer meant as a handful of apples. Ask instead of guessing.
        stated_unit = item.get("unit")
        BARE_COUNT_SAFE_UNITS = {"piece", "packet", "bunch"}

        if not stated_unit:
            if product["unit"] not in BARE_COUNT_SAFE_UNITS:
                unit_mismatch_items.append(f"{product['name_en']} ({item.get('quantity')}, unit unclear)")
                continue
            # bare count against a genuinely count-based unit — safe as-is
        elif stated_unit != product["unit"]:
            converted = convert_unit(qty, stated_unit, product["unit"])
            if converted is None:
                unit_mismatch_items.append(f"{product['name_en']} ({item.get('quantity')} {stated_unit})")
                continue
            qty = converted

        # BUSINESS-RULE VALIDATION — separate layer from the unit-matching
        # above. Even after the unit is confirmed correct, the number itself
        # could still be wrong: a stray negative/zero from a parsing slip, or
        # a typo/misheard-voice-note that turned "1kg" into "10kg"/"100kg".
        # Never let a raw number reach a real order without this check.
        is_valid, reason = validate_quantity(qty, product["unit"])
        if not is_valid:
            if reason == "zero_or_negative":
                # Customer almost certainly meant "don't add this" — omit
                # silently rather than error, matching the prompt's own
                # zero/negative-quantity rule (it shouldn't reach here often,
                # this is the code-side backstop for when it does).
                continue
            elif reason == "too_large":
                unit_mismatch_items.append(
                    f"{product['name_en']} ({_fmt_qty(qty)} {product['unit']} — that's a lot, please confirm)"
                )
                continue
            else:  # unknown_unit — shouldn't normally happen, fail safe
                unit_mismatch_items.append(f"{product['name_en']} ({_fmt_qty(qty)} {product['unit']})")
                continue

        items_for_order.append({"product": product, "quantity": qty})
        line_total = product["price"] * qty
        lines.append(f"• {product['name_en']} — {_fmt_qty(qty)} {product['unit']} × ₹{product['price']} = ₹{line_total:.0f}")

    if unit_mismatch_items:
        await send_text(to, _t(
            lang,
            f"Not sure how much you meant for: {', '.join(unit_mismatch_items)}. "
            f"We sell these by weight — could you say it like '1kg' or '500g'?",
            f"समझ नहीं आया कितना चाहिए: {', '.join(unit_mismatch_items)}। "
            f"हम इन्हें वज़न के हिसाब से बेचते हैं — कृपया '1kg' या '500g' जैसे बताएं",
            f"Samajh nahi aaya kitna chahiye: {', '.join(unit_mismatch_items)}. "
            f"Hum wajan ke hisaab se bechte hain — '1kg' ya '500g' jaise batao",
        ))
        return

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
    set_state(customer["id"], ConversationState.CART_REVIEW)


async def handle_edit(to: str, customer: dict, parsed: dict, lang: str) -> None:
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
            log_event("ITEM_REMOVED", customer_id=customer["id"], details={"order_id": order["id"], "product": product["name_en"]})
            changes.append(_t(lang, f"Removed {product['name_en']}", f"{product['name_en']} हटाया गया", f"{product['name_en']} hataya gaya"))
        else:
            new_total = svc.add_item_to_order(order["id"], product, qty)
            log_event("ITEM_ADDED", customer_id=customer["id"], details={"order_id": order["id"], "product": product["name_en"], "qty": qty})
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


async def handle_cancel(to: str, customer: dict, lang: str) -> None:
    order = svc.get_latest_open_order_for_customer(customer["id"])
    if not order:
        await send_text(to, _t(lang, "You don't have an active order to cancel.", "आपका कोई सक्रिय ऑर्डर नहीं है।", "Aapka koi active order nahi hai."))
        return
    svc.cancel_order(order["id"])
    log_event("ORDER_CANCELLED", customer_id=customer["id"], details={"order_id": order["id"]})
    await send_text(to, _t(
        lang, f"Order #{order['id']} has been cancelled. No charge.",
        f"ऑर्डर #{order['id']} रद्द कर दिया गया है। कोई शुल्क नहीं।",
        f"Order #{order['id']} cancel kar diya gaya hai. Koi charge nahi.",
    ))


async def handle_reorder(to: str, customer: dict, lang: str) -> None:
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
    await ask_fulfillment_or_address(to, customer, lang)