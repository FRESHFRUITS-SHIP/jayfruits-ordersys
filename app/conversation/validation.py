"""
Business-rule validation — deliberately separate from order_parser.py (NLP)
and from order_flow.py (conversation flow). Groq's job is to understand
language; this module's job is to decide whether an extracted number is
SAFE to apply to a real order, regardless of how confident the parser was.

Never let language-layer ambiguity or a parsing mistake silently become a
wrong price. A "1kg" vs "10kg" typo, or a stray negative sign, is a business
risk regardless of how the number got there.
"""

# Anything above these, per unit, gets a "please confirm" clarification
# instead of silently creating the order — catches the "1kg became 10kg"
# class of error (typo, misheard voice note, Groq slip) before it becomes
# a real bill. These are deliberately generous (a genuine bulk/wholesale
# order is plausible) — the goal is to catch clear mistakes, not annoy
# ordinary large-but-real orders.
MAX_SANE_QTY = {
    "kg": 25,
    "gram": 25000,
    "litre": 25,
    "ml": 25000,
    "dozen": 10,
    "piece": 50,
    "packet": 20,
    "bunch": 20,
}


def validate_quantity(qty: float, unit: str) -> tuple[bool, str | None]:
    """
    Returns (is_valid, reason). reason is None when valid, otherwise a short
    machine-readable tag the caller can turn into a customer-facing message:
    'zero_or_negative' | 'too_large' | 'unknown_unit'.
    """
    if qty is None:
        return False, "zero_or_negative"
    if qty <= 0:
        return False, "zero_or_negative"

    ceiling = MAX_SANE_QTY.get(unit)
    if ceiling is None:
        # Unit not in our table at all — fail safe to "needs confirmation"
        # rather than silently allowing an unbounded quantity through.
        return False, "unknown_unit"
    if qty > ceiling:
        return False, "too_large"

    return True, None
