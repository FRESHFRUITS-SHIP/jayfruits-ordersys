"""
Turns a customer's free-text WhatsApp message into a structured order,
matched against the shop's actual product list (so it can't invent items
or prices — it can only pick from what's really on the menu).
"""
import json
from groq import Groq
from app.config import GROQ_API_KEY, GROQ_MODEL

client = Groq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = """You are an order-parsing assistant for an Indian fruit shop's WhatsApp line.
You will be given:
1. The shop's current product menu (name, unit, price).
2. A customer's free-text message, which may be in English, Hindi, Hinglish, or mixed.

Your job: extract the fruit order as structured JSON. Rules:
- Only match items that exist in the given menu. If the customer asks for something not on the
  menu, put it in "unavailable_items" instead of "items".
- Quantities: interpret common Indian phrasing — "1 kg", "2 dozen", "adha kilo" (0.5 kg),
  "ek dozen" (1 dozen), "5 pieces". If no unit is given but the product's menu unit is "kg",
  assume kg. If ambiguous, make your best reasonable guess.
- If the message is not an order at all (e.g. "hi", "what's your address", "hours?"), set
  "is_order" to false and leave items empty.
- Never invent a price — always use the exact price from the provided menu.

Respond with ONLY valid JSON, no markdown, no explanation, in this exact shape:
{
  "is_order": true,
  "items": [
    {"product_name": "Mango", "quantity": 2, "unit": "kg"}
  ],
  "unavailable_items": ["strawberry"],
  "customer_intent_note": "short plain-English note if message had a question mixed in, else empty string"
}
"""


def parse_order(customer_message: str, menu: list[dict]) -> dict:
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
        return json.loads(raw)
    except json.JSONDecodeError:
        # fail safe — treat as non-order rather than crashing the webhook
        return {
            "is_order": False,
            "items": [],
            "unavailable_items": [],
            "customer_intent_note": "",
        }
