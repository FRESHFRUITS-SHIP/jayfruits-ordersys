"""Delivery/pickup/address/payment-buttons flow. Pulled out of webhook.py, pure move."""
from app.services.whatsapp import send_text, send_buttons
from app.services import orders as svc
from app.conversation.messages import _t, _name_bit


async def send_payment_buttons(to: str, lang: str) -> None:
    await send_buttons(
        to,
        _t(lang, "How would you like to pay?", "भुगतान कैसे करेंगे?", "Payment kaise karoge?"),
        [("pay_upi", _t(lang, "Pay via UPI", "UPI से भुगतान", "UPI se Pay")),
         ("pay_cod", _t(lang, "Cash on delivery", "डिलीवरी पर नकद", "Cash on Delivery"))],
    )


async def ask_fulfillment_or_address(to: str, customer: dict, lang: str) -> None:
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


async def apply_pickup(to: str, customer: dict, lang: str) -> None:
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
        await send_payment_buttons(to, lang)


async def handle_address(to: str, customer: dict, parsed: dict, lang: str) -> None:
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
        await send_payment_buttons(to, lang)
