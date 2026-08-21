import httpx
from app.config import META_ACCESS_TOKEN, WHATSAPP_API_URL

HEADERS = {
    "Authorization": f"Bearer {META_ACCESS_TOKEN}",
    "Content-Type": "application/json",
}


async def send_text(to: str, body: str) -> None:
    """Send a plain text WhatsApp message. `to` is the customer's number, e.g. 919876543210."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body, "preview_url": False},
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(WHATSAPP_API_URL, headers=HEADERS, json=payload)
        r.raise_for_status()


async def send_buttons(to: str, body: str, buttons: list[tuple[str, str]]) -> None:
    """
    Send up to 3 quick-reply buttons.
    buttons = [(id, title), ...]  e.g. [("pay_upi", "Pay via UPI"), ("pay_cod", "Cash on delivery")]
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": bid, "title": title[:20]}}
                    for bid, title in buttons
                ]
            },
        },
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(WHATSAPP_API_URL, headers=HEADERS, json=payload)
        r.raise_for_status()
async def send_text(to: str, body: str) -> None:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body, "preview_url": False},
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(WHATSAPP_API_URL, headers=HEADERS, json=payload)
        if r.status_code >= 400:
            print(f"WhatsApp API error {r.status_code}: {r.text}")
        r.raise_for_status()