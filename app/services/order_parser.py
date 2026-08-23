"""
Turns a customer's free-text WhatsApp message into a structured intent + order,
matched against the shop's actual product list (so it can't invent items or
prices — it can only pick from what's really on the menu).
"""
import json
import re
from groq import Groq
from app.config import GROQ_API_KEY, GROQ_MODEL

client = Groq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = """You are the message-understanding brain for an Indian fruit shop's WhatsApp line.
You will be given the shop's current menu and a customer's free-text message (English, Hindi, or Hinglish).

First, classify the message's INTENT into exactly one of:
- "new_order": customer is placing a fresh order (e.g. "2kg mango, 1 dozen banana")
- "edit_order": customer wants to add/remove something from their existing open order
  (e.g. "add 1kg banana", "remove mango", "make it 3kg instead")
- "cancel_order": customer wants to cancel their order (e.g. "cancel my order", "cancel please")
- "reorder": customer wants to repeat a previous order (e.g. "same as last time", "repeat my last order")
- "address": customer is providing or changing their delivery address
  (e.g. "deliver to Shop 12, Kandivali", "change my address to ...")
- "greeting": hi/hello/menu/namaste type message with no order content
- "other": anything else (questions, chit-chat, unclear)

Also detect the LANGUAGE the customer is writing in: "hi" for Hindi/Hinglish (Devanagari or
romanized Hindi), "en" for English.

For new_order or edit_order intents, extract items:
- Only match items that exist in the given menu. Anything not on the menu goes in "unavailable_items".
- Quantities: interpret common Indian phrasing — "1 kg", "2 dozen", "adha kilo" (0.5 kg), "ek dozen"
  (1 dozen), "5 pieces", "2 packets", "1 litre", "500 ml", "1 bunch".
- IMPORTANT: if the customer names a product WITHOUT stating any quantity at all (e.g. just "mango",
  "banana chahiye", "I want apple"), set "quantity" to null. Do NOT assume or default a quantity —
  the shop will ask the customer how much they want. Only fill in a quantity when the customer
  actually stated one (a number, "half", "dozen", "some pieces", etc.).
- For edit_order, each item needs an "action": "add" or "remove".
- Never invent a price — prices come from the menu, not from you.

For "address" intent, extract the address text itself into "address_text".

Respond with ONLY valid JSON, no markdown, no explanation, in this exact shape:
{
  "intent": "new_order",
  "language": "en",
  "items": [
    {"product_name": "Mango", "quantity": 2, "unit": "kg", "action": "add"}
  ],
  "unavailable_items": ["strawberry"],
  "address_text": "",
  "note": "short plain-English note if message had a question mixed in, else empty string"
}
"""

# Simple regex fallback for parsing a bare quantity reply like "2kg", "1 dozen", "3", "adha kilo"
_QTY_PATTERNS = [
    (re.compile(r"adha|आधा"), 0.5),
    (re.compile(r"paun|पौन"), 0.75),
    (re.compile(r"sava|सवा"), 1.25),
]
_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")


def parse_message(customer_message: str, menu: list[dict]) -> dict:
    menu_text = "\n".join(
        f"- {p['name_en']} ({p.get('name_hi','')}) — {p['unit']} — ₹{p['price']}"
        for p in menu
        if p.get("is_available", True)
    )

    user_prompt = f"MENU:\n{menu_text}\n\nCUSTOMER MESSAGE:\n{customer_message}"

    resp = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    raw = resp.choices[0].message.content
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return _fallback()

    # defensive defaults in case the model omits a field
    parsed.setdefault("intent", "other")
    parsed.setdefault("language", "en")
    parsed.setdefault("items", [])
    parsed.setdefault("unavailable_items", [])
    parsed.setdefault("address_text", "")
    parsed.setdefault("note", "")
    return parsed


# Unit detection patterns, checked in this priority order (kg before gram, litre
# before ml, since "kg"/"litre" text can otherwise get mis-caught by looser
# patterns). No leading \b — WhatsApp replies like "2kg" or "500gm" have the
# number glued directly to the unit.
_UNIT_PATTERNS = [
    ("kg", re.compile(r"kg\b|\bkilo(s)?\b|किलो")),
    ("gram", re.compile(r"gram(s)?\b|gm\b|g\b|ग्राम")),
    ("litre", re.compile(r"litre(s)?\b|liter(s)?\b|\bl\b|लीटर")),
    ("ml", re.compile(r"\bml\b|मिली")),
    ("dozen", re.compile(r"dozen|dzn\b|दर्जन")),
    ("piece", re.compile(r"piece(s)?\b|pcs?\b|पीस|नग")),
    ("packet", re.compile(r"packet(s)?\b|pkt\b|पैकेट")),
    ("bunch", re.compile(r"bunch(es)?\b|गुच्छा|गुच्छे")),
]


def _convert(val: float, from_unit: str, to_unit: str) -> float | None:
    """Converts between units the shop actually sells in. Returns None if the
    pair isn't a sensible conversion (e.g. someone said 'litre' for a kg product).
    Units without a natural conversion partner (packet, bunch, piece<->kg, etc.)
    simply aren't in this table — that's intentional, not an oversight."""
    if from_unit == to_unit:
        return val
    pair = {from_unit, to_unit}
    if pair == {"kg", "gram"}:
        return round(val / 1000, 3) if from_unit == "gram" else val * 1000
    if pair == {"litre", "ml"}:
        return round(val / 1000, 3) if from_unit == "ml" else val * 1000
    if pair == {"dozen", "piece"}:
        return round(val / 12, 3) if from_unit == "piece" else val * 12
    return None


def parse_quantity_only(text: str, target_unit: str = "kg") -> float | None:
    """
    Used when we've already asked 'kitna chahiye?' and are expecting just a
    quantity reply — e.g. '2kg', '500 gram', '1 dozen', '6 pieces', '3', 'adha kilo'.

    target_unit is the product's actual unit ('kg', 'dozen', or 'piece'). The
    returned number is always converted into THAT unit, so a customer can reply
    in whatever unit is natural to them (grams for a kg item, pieces for a dozen
    item, etc.) without silently mis-pricing the order.
    """
    t = text.strip().lower()

    for pattern, value in _QTY_PATTERNS:
        if pattern.search(t):
            # "adha kilo" etc. — these are a fraction of whatever the customer
            # is naming, and are already expressed in the target unit in normal
            # usage (e.g. "adha dozen" = half a dozen), so no conversion needed.
            return value

    match = _NUM_RE.search(t)
    if not match:
        return None
    try:
        val = float(match.group(1))
    except ValueError:
        return None
    if val <= 0:
        return None

    detected_unit = None
    for unit_name, pattern in _UNIT_PATTERNS:
        if pattern.search(t):
            detected_unit = unit_name
            break

    if detected_unit is None or detected_unit == target_unit:
        # No unit stated, or it matches the product's unit — use as-is.
        return val

    converted = _convert(val, detected_unit, target_unit)
    if converted is not None:
        return converted

    # Customer stated a unit that doesn't convert cleanly to this product's unit
    # (e.g. said "kg" for a piece-sold item like watermelon). Rather than silently
    # mis-price it, treat as unparseable so webhook.py re-asks instead of guessing.
    return None


def _fallback() -> dict:
    return {
        "intent": "other",
        "language": "en",
        "items": [],
        "unavailable_items": [],
        "address_text": "",
        "note": "",
    }


# Kept for any code that still imports the old name
def parse_order(customer_message: str, menu: list[dict]) -> dict:
    parsed = parse_message(customer_message, menu)
    return {
        "is_order": parsed["intent"] == "new_order",
        "items": parsed["items"],
        "unavailable_items": parsed["unavailable_items"],
        "customer_intent_note": parsed["note"],
    }