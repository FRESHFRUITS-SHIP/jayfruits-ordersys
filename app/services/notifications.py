"""Sends WhatsApp updates to customers when their order status changes."""
from app.services.whatsapp import send_text
from app.config import SHOP_NAME

STATUS_MESSAGES = {
    "confirmed": {
        "en": "✅ Your order #{id} is confirmed and being prepared!",
        "hi": "✅ आपका ऑर्डर #{id} कन्फ़र्म हो गया है और तैयार किया जा रहा है!",
    },
    "out_for_delivery": {
        "en": "🚴 Your order #{id} is out for delivery!",
        "hi": "🚴 आपका ऑर्डर #{id} डिलीवरी के लिए निकल चुका है!",
    },
    "delivered": {
        "en": "📦 Your order #{id} has been delivered. Thanks for shopping with {shop}! 🙏",
        "hi": "📦 आपका ऑर्डर #{id} डिलीवर हो गया है। {shop} से खरीदारी के लिए धन्यवाद! 🙏",
    },
    "cancelled": {
        "en": "❌ Your order #{id} has been cancelled.",
        "hi": "❌ आपका ऑर्डर #{id} रद्द कर दिया गया है।",
    },
}


async def notify_status_change(customer_wa_number: str, order_id: int, new_status: str, lang: str = "en") -> None:
    template = STATUS_MESSAGES.get(new_status)
    if not template:
        return
    text = template.get(lang, template["en"]).format(id=order_id, shop=SHOP_NAME)
    await send_text(customer_wa_number, text)
