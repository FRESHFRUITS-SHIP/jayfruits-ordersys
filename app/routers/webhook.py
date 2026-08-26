"""
Meta webhook entrypoint: verification, signature check, payload unwrapping.
All conversation logic now lives in app/conversation/ (Phase 0 restructure —
pure move, no behavior change).
"""
import hashlib
import hmac
from fastapi import APIRouter, Request, Query, HTTPException, Response

from app.config import META_VERIFY_TOKEN, META_APP_SECRET
from app.services.whatsapp import send_text
from app.conversation.router import handle_text_message, handle_button_reply

router = APIRouter()


# ---------- webhook verification ----------
@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == META_VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


def _verify_signature(body: bytes, signature_header: str | None) -> bool:
    if not META_APP_SECRET:
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(META_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.split("=", 1)[1])


# ---------- incoming messages ----------
@router.post("/webhook")
async def receive_message(request: Request):
    body_bytes = await request.body()
    if not _verify_signature(body_bytes, request.headers.get("x-hub-signature-256")):
        raise HTTPException(status_code=403, detail="Invalid signature")

    payload = await request.json()

    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]["value"]
        messages = change.get("messages")
        if not messages:
            return {"status": "ignored"}

        msg = messages[0]
        from_number = msg["from"]

        if msg["type"] == "text":
            await handle_text_message(from_number, msg["text"]["body"])
        elif msg["type"] == "interactive":
            reply = msg["interactive"].get("button_reply") or msg["interactive"].get("list_reply")
            if reply:
                await handle_button_reply(from_number, reply["id"])
        elif msg["type"] in ("sticker", "reaction"):
            pass  # not worth replying to — avoids a confusing "send as text" message for a 👍 or sticker
        elif msg["type"] in ("audio", "voice", "image", "video", "document"):
            await send_text(
                from_number,
                "I can only read text messages right now — could you please type your order? 🙏\n"
                "उदाहरण: '2kg mango, 1 dozen banana'",
            )
        else:
            print(f"Unhandled WhatsApp message type: {msg['type']} — payload: {msg}")
            await send_text(from_number, "Please send your order as text, e.g. '2kg mango, 1 dozen banana'.")

    except (KeyError, IndexError):
        pass

    return {"status": "ok"}