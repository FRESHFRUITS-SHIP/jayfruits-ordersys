"""
Turns a customer's free-text WhatsApp message into a structured intent + order,
matched against the shop's actual product list (so it can't invent items or
prices — it can only pick from what's really on the menu).
"""
import json
import re
import time
from groq import Groq
from app.config import GROQ_API_KEY, GROQ_MODEL

client = Groq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = """You are the message-understanding brain for an Indian fruit shop's WhatsApp line.
You will be given the shop's current menu and a customer's free-text message (English, Hindi, or Hinglish).

Customers write casually — expect typos, spelling variants ("mango"/"mangoe"/"mangoo"/"aam"), missing
punctuation, emojis, mixed Devanagari + Roman script in the same message, and filler words ("bhaiya",
"please", "thoda", "jaldi"). Do your best to understand intent despite this; don't require exact spelling.

First, classify the message's INTENT into exactly one of:
- "new_order": customer is placing a fresh order (e.g. "2kg mango, 1 dozen banana")
- "edit_order": customer wants to add/remove something from their existing open order
  (e.g. "add 1kg banana", "remove mango", "make it 3kg instead", "mango mat bhejna" [don't send mango])
- "cancel_order": customer wants to cancel their order (e.g. "cancel my order", "cancel please")
- "reorder": customer wants to repeat a previous order (e.g. "same as last time", "repeat my last order")
- "address": customer is providing or changing their delivery address
  (e.g. "deliver to Shop 12, Kandivali", "change my address to ...")
- "greeting": hi/hello/menu/namaste type message with no order content
- "other": anything else (questions, chit-chat, price haggling, complaints, unclear messages)

Also detect the LANGUAGE the customer is writing in: "hi" for Hindi/Hinglish (Devanagari or
romanized Hindi), "en" for English.

For new_order or edit_order intents, extract items:
- Only match items that exist in the given menu, using fuzzy/typo-tolerant matching against the
  product names given. Anything you genuinely can't match goes in "unavailable_items" — but try hard
  before giving up on a near-miss spelling.
- Quantities: interpret common Indian phrasing — "1 kg", "2 dozen", "adha/aadha kilo" (0.5 kg),
  "ek dozen" (1 dozen), "5 pieces", "2 packets", "1 litre", "500 ml", "1 bunch", "sava kilo" (1.25 kg),
  "paune/pauna kilo" (0.75 kg), "dedh kilo" (1.5 kg), "dhai kilo" (2.5 kg), "saade teen kilo" (3.5 kg).
- IMPORTANT: if the customer names a product WITHOUT stating any quantity at all (e.g. just "mango",
  "banana chahiye", "I want apple"), set "quantity" to null. Do NOT assume or default a quantity —
  the shop will ask the customer how much they want. Only fill in a quantity when the customer
  actually stated one (a number, "half", "dozen", "some pieces", etc.).
- CRITICAL: if the customer gives a bare number with NO unit word at all (e.g. "7 sev", "2 aam",
  "3 apple" — just a count, no "kg"/"dozen"/"piece"/etc. attached), set "unit" to null. Do NOT
  default "unit" to the product's own selling unit. This matters a lot for fruits people naturally
  count individually (apples, mangoes, oranges) but the shop prices by weight — "7 sev" almost
  certainly means 7 individual apples, NOT 7 kilograms, and silently assuming kg has caused real
  pricing errors (a customer meaning ~7 apples got billed for 7kg — over 10x too much). Only set
  "unit" to a real value when the customer's message actually contains that unit word or a clear
  equivalent phrase (e.g. "half kilo", "dozen", "pieces").
- QUALITATIVE/APPROXIMATE quantities have NO deterministic number — "thoda", "thoda sa", "bahut",
  "zyada", "kam", "kuch", "jitna ho", "a little", "a lot", "some", "plenty", "around 2kg", "about 2kg",
  "roughly 2kg", "lagbhag 2 kilo", "2 kilo ke aas paas". For these, set "quantity" to null and put a
  short note like "customer gave an approximate/vague quantity for mango — ask for an exact amount" in
  "note". NEVER silently pick a number for these — that is guessing with money, which is forbidden.
- RANGES ("2-3 kg", "2 to 3 kg", "2 se 3 kilo", "at least 2 kg", "up to 3 kg") are ALSO ambiguous —
  set "quantity" to null and note that the customer gave a range, asking them to state one exact amount.
- ZERO OR NEGATIVE quantities ("0 mango", "zero mango", "-2 kg", "minus 2 kilo", "none", "don't add any")
  must NEVER become an order line. If the customer's overall intent for that product is clearly "don't
  add this", treat it as if they never mentioned the product at all (omit it from "items" entirely) —
  do not put quantity 0 or negative into the items array under any circumstance.
- SELF-CORRECTIONS within one message ("2kg mango, no wait 3kg", "1 dozen banana... actually 2",
  "2 kilo apple sorry 1 kilo", "make it 3", "wait make that 3", "2 nahi 3 kilo", "2 ki jagah 3"): use
  ONLY the customer's final corrected value. Produce ONE item line, not two — a correction is not a
  second purchase. The same applies to switching products mid-message ("mango nahi, orange de do" =
  "not mango, give orange instead" — this means ONLY orange, do not also include mango).
  IMPORTANT: if the customer restates only the number in their correction and does NOT repeat the
  unit (e.g. "1 dozen banana... actually 2" — the "2" has no unit word attached to it, but "dozen"
  was already stated earlier in the very same message for this same product), carry the earlier
  unit forward — the corrected item is "2 dozen banana", NOT a bare/unitless "2". Only treat a
  number as truly unit-less if no unit was stated anywhere in the message for that product.
- VARIANT / PRODUCT AMBIGUITY: if a term could plausibly match more than one catalog item and you
  cannot tell which one the customer means with real confidence, do NOT silently pick one — put the
  customer's own words in "unavailable_items" with a clarifying note instead.
  BUT — this only applies when the customer's term does NOT itself exactly (or near-exactly) match
  one specific catalog product name. If the menu contains a product literally named "Apple" AND ALSO
  separate products like "Shimla Apple"/"Kashmiri Apple"/"Fuji Apple", a customer saying plain "apple"
  should match the literal "Apple" catalog entry directly — that is NOT ambiguous, it's an exact match
  to its own distinct menu item. Reserve the ambiguity rule for terms that are only a MODIFIER or
  PARTIAL name with no exact standalone catalog match of their own — e.g. "Kashmiri" alone is ambiguous
  (it's not itself a full product name, only "Kashmiri Apple" is), but "apple" alone is not ambiguous
  when "Apple" is a real, separate, directly-listed menu item.
- GENERIC/CATEGORY REQUESTS ("fruit", "fruits", "phal", "kuch fruit de do", "fresh fruit", "seasonal
  fruits", "give me whatever is good", "surprise me", "send something healthy") are NOT a specific
  product. Do not guess an item — leave "items" empty and put a short note explaining the customer
  asked for a general/unspecified selection, so the shop can ask what they'd specifically like.
- For edit_order, each item needs an "action": "add" or "remove". Phrases like "mat bhejo", "hata do",
  "cancel this item", "no need X" mean "remove"; anything additive means "add". Distinguish "don't add
  X" (X was never in the cart — omit it, don't create a remove action for something never added) from
  "remove X" (X is presumably already in the cart — action "remove").
- Never invent a price — prices come from the menu, not from you.
- If the customer haggles on price ("kam karo", "discount do", "sasta karo"), do NOT change any price —
  set intent to "other" and put a short note like "customer is asking for a discount" in "note".

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
  "note": "short plain-English note if message had a question, complaint, or haggling mixed in, else empty string"
}
"""

SHOPKEEPER_SYSTEM_PROMPT = """You are Ravi, who runs {shop_name}, personally texting a customer back
on WhatsApp. Write the way a real, friendly Indian fruit-shop owner actually texts — warm, brief
(1-2 short sentences, occasionally 3), natural mixing of Hindi/English/Hinglish that matches the
customer's own language, a light emoji here and there but not overused.

Hard rules:
- Never sound like a bot, a customer-support script, or a company. No bullet points, no headers,
  no "Dear customer", no signing off with your name.
- Never state or imply a specific price, discount, total, or promise about delivery time — those come
  from the app separately and must stay exact. If the situation involves a discount request, gently
  decline without inventing a number ("bhai thoda tight hai rate pe, already best price hai" style is fine,
  but don't say a percentage or number unless it was explicitly given to you in the context).
- Keep it to plain text only — the app will send any buttons/menus/prices separately.
- Reply in the SAME language style given to you (en / hi / hg).
"""


def generate_shopkeeper_reply(situation: str, lang: str, shop_name: str) -> str | None:
    """
    Used for the conversational, non-transactional parts of the chat (small talk,
    unclear messages, haggling, "how are you" type chit-chat) — NOT for anything
    that states a price, total, or order confirmation. Those stay as deterministic
    templates in webhook.py so a model can never mis-state money.

    Returns None on any failure so callers can fall back to a static message —
    this must never be the only path to a reply.
    """
    lang_label = {"en": "English", "hi": "Hindi (Devanagari)", "hg": "Hinglish (romanized mix)"}.get(lang, "English")
    try:
        resp = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SHOPKEEPER_SYSTEM_PROMPT.format(shop_name=shop_name)},
                {"role": "user", "content": f"Reply in: {lang_label}\nSituation: {situation}\n\nWrite ONE short WhatsApp reply. No quotes around it, no markdown."},
            ],
            temperature=0.7,
            max_tokens=100,
        )
        text = (resp.choices[0].message.content or "").strip()
        # basic safety net — strip stray quote wrapping the model sometimes adds
        text = text.strip('"').strip()
        return text or None
    except Exception as e:
        print(f"Groq shopkeeper reply failed: {e}")
        return None

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

    # Phase 1: Groq is a single point of failure with no retry/fallback before this.
    # Retry transient errors (timeout, 5xx) with short backoff; a 4xx (bad request,
    # auth) won't succeed on retry, so fail straight to the deterministic fallback.
    last_err = None
    for attempt in range(3):
        try:
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

            parsed.setdefault("intent", "other")
            parsed.setdefault("language", "en")
            parsed.setdefault("items", [])
            parsed.setdefault("unavailable_items", [])
            parsed.setdefault("address_text", "")
            parsed.setdefault("note", "")
            return parsed
        except Exception as e:
            last_err = e
            status = getattr(e, "status_code", None)
            if status is not None and 400 <= status < 500 and status != 429:
                # Bad request / auth error — retrying won't help.
                break
            if attempt < 2:
                time.sleep(0.5 * (2 ** attempt))  # 0.5s, then 1s

    print(f"Groq parse_message failed after retries: {last_err}")
    return _fallback()


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

# Fallback classifier for typo'd/partial unit words (e.g. "gra" instead of
# "gram", "kge" instead of "kg"). This is intentionally the SAFE path: if a
# word is attached to the number and we genuinely can't classify it, we must
# NOT guess — we return None so the caller re-asks instead of silently
# mis-pricing an order (this is exactly the bug that let "658 gra," through
# as 658 kg instead of 0.658 kg).
_UNIT_WORD_RE = re.compile(r"[a-zA-Zऀ-ॿ]+")

_PREFIX_UNIT_MAP = [
    (("kg", "kilo", "किलो"), "kg"),
    (("g", "gm", "gr", "gra", "gram", "grams", "ग्राम"), "gram"),
    (("l", "li", "lit", "litre", "liter", "लीटर"), "litre"),
    (("ml", "मिली"), "ml"),
    (("doz", "dzn", "दर्जन"), "dozen"),
    (("pc", "pcs", "piece", "pieces", "पीस", "नग"), "piece"),
    (("pkt", "pk", "packet", "packets", "पैकेट"), "packet"),
    (("bun", "bunch", "bunches", "गुच्छा", "गुच्छे"), "bunch"),
]


def _classify_unit_word(word: str) -> str | None:
    """Best-effort match of a (possibly typo'd) unit word to a known unit.
    Returns None — deliberately — if it can't confidently classify it."""
    w = word.lower()
    if not w:
        return None
    for prefixes, unit in _PREFIX_UNIT_MAP:
        for p in prefixes:
            if w == p or w.startswith(p):
                return unit
    return None


def convert_unit(val: float, from_unit: str, to_unit: str) -> float | None:
    """Converts between units the shop actually sells in. Returns None if the
    pair isn't a sensible conversion (e.g. someone said 'litre' for a kg product).
    Units without a natural conversion partner (packet, bunch, piece<->kg, etc.)
    simply aren't in this table — that's intentional, not an oversight.
    Public (no leading underscore) — reused by order_flow.py's multi-item
    path so unit validation is consistent everywhere quantities are parsed,
    not just the single-item pending_item flow."""
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
    quantity reply — e.g. '2kg', '500 gram', '1 dozen', '6 pieces', '3',
    'adha kilo', or a typo like '658 gra,'.

    Safety rule: a BARE number (no unit word at all, e.g. "3") is assumed to be
    in the product's own unit. But if the customer DID attach a word and we
    can't confidently classify it, we return None so the caller re-asks —
    we never silently guess a unit, because guessing wrong on a kg-priced
    item can turn a ₹150 order into a ₹150,000 order.
    """
    t = text.strip().lower()

    for pattern, value in _QTY_PATTERNS:
        if pattern.search(t):
            return value

    num_match = _NUM_RE.search(t)
    if not num_match:
        return None
    try:
        val = float(num_match.group(1))
    except ValueError:
        return None
    if val <= 0:
        return None

    # Look for a unit word anywhere in the reply (handles "658 gra," / "2kg" /
    # "500 gram" alike), trying the exact patterns first, then the typo-tolerant
    # prefix classifier as a fallback.
    detected_unit = None
    for unit_name, pattern in _UNIT_PATTERNS:
        if pattern.search(t):
            detected_unit = unit_name
            break

    if detected_unit is None:
        word_match = _UNIT_WORD_RE.search(t[num_match.end():])
        if word_match:
            detected_unit = _classify_unit_word(word_match.group(0))
            if detected_unit is None:
                # There WAS a word attached but we couldn't classify it —
                # don't guess, force a re-ask.
                return None

    if detected_unit is None:
        # Genuinely bare number, no trailing word at all — assume target unit.
        return val

    if detected_unit == target_unit:
        return val

    converted = convert_unit(val, detected_unit, target_unit)
    if converted is not None:
        return converted

    # Stated a unit that doesn't convert cleanly to this product's unit
    # (e.g. said "kg" for a piece-sold item like watermelon) — re-ask instead
    # of mis-pricing.
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