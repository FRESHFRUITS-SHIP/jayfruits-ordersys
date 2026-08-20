from urllib.parse import quote
from app.config import SHOP_UPI_ID, SHOP_UPI_PAYEE_NAME


def build_upi_link(amount: float, order_id: int) -> str:
    """
    Builds a upi://pay deep link. Tapping it on a phone opens the customer's
    UPI app (GPay/PhonePe/Paytm) with amount pre-filled.

    NOTE: this does NOT auto-confirm payment on your side — there's no webhook
    for a plain UPI intent link. The bot marks the order 'payment_status=pending'
    and you confirm manually from the dashboard once you see the payment land.
    For automatic confirmation later, swap this for a Razorpay/Cashfree UPI
    payment link, which does support server-side webhooks.
    """
    note = f"Jay Fruits Order {order_id}"
    params = (
        f"pa={quote(SHOP_UPI_ID)}"
        f"&pn={quote(SHOP_UPI_PAYEE_NAME)}"
        f"&am={amount:.2f}"
        f"&cu=INR"
        f"&tn={quote(note)}"
    )
    return f"upi://pay?{params}"
