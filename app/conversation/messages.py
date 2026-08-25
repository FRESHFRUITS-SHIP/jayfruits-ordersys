"""
Shared 3-language reply formatting + canned message templates.
Pulled out of webhook.py (Phase 0 restructure) — pure move, no behavior change.
"""
from app.config import SHOP_NAME, SHOP_WHATSAPP_DISPLAY_NUMBER
from app.services.whatsapp import send_text


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


async def send_about_message(to: str, lang: str) -> None:
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
