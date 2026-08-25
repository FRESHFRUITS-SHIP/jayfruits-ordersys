"""Language selection + greeting/menu. Pulled out of webhook.py, pure move."""
from datetime import datetime

try:
    from app.config import SHOP_BANNER_IMAGE_URL
except ImportError:
    SHOP_BANNER_IMAGE_URL = None
from app.config import SHOP_NAME
from app.services.whatsapp import send_text, send_buttons, send_image, send_list_menu
from app.services import orders as svc
from app.conversation.messages import _t, _name_bit


def _time_based_greeting_emoji() -> tuple[str, str, str]:
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning", "सुप्रभात", "Good morning"
    if hour < 17:
        return "Good afternoon", "नमस्ते", "Good afternoon"
    return "Good evening", "शुभ संध्या", "Good evening"


async def send_language_selection(to: str) -> None:
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


async def greeting_and_menu(to: str, lang: str, is_first_time: bool = False) -> None:
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
