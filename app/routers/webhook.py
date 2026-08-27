"""
Meta webhook entrypoint: verification, signature check, payload unwrapping.
Phase 1: idempotency, global error boundary, and correlation IDs live here too —
this is the one place every incoming message passes through, so it's the right
place for cross-cutting safety nets. Conversation logic itself lives in
app/conversation/.
"""
import hashlib
import hmac
from fastapi import APIRouter, Request, Query, HTTPException, Response

from app.config import META_VERIFY_TOKEN, META_APP_SECRET
from app.services.whatsapp import send_text
from app.services.idempotency import claim_message, mark_done
from app.services.audit import new_trace_id, get_trace_id, log_event
from app.services import orders as svc
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


async def _send_graceful_failure(to: str) -> None:
    """Best-effort: try to tell the customer something went wrong, in a way that
    can't itself raise and mask the original error."""
    try:
        lang = "en"
        try:
            customer = svc.get_or_create_customer(to)
            lang = customer.get("preferred_language") or "en"
        except Exception:
            pass
        text = {
            "en": "Sorry bhai, abhi thodi technical problem aa rahi hai. Ek baar phir try karo 🙏",
            "hi": "माफ़ करें, अभी थोड़ी तकनीकी समस्या आ रही है। कृपया थोड़ी देर बाद फिर कोशिश करें 🙏",
            "hg": "Sorry bhai, abhi thodi technical problem aa rahi hai. Ek baar phir try karo 🙏",
        }.get(lang, "Sorry, something went wrong on our end. Please try again in a moment 🙏")
        await send_text(to, text)
    except Exception as e:
        print(f"[{get_trace_id()}] even the graceful-failure message failed to send: {e}")


# ---------- incoming messages ----------
@router.post("/webhook")
async def receive_message(request: Request):
    body_bytes = await request.body()
    if not _verify_signature(body_bytes, request.headers.get("x-hub-signature-256")):
        raise HTTPException(status_code=403, detail="Invalid signature")

    payload = await request.json()
    trace_id = new_trace_id()

    from_number = None
    message_id = None
    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]["value"]
        messages = change.get("messages")
        if not messages:
            return {"status": "ignored"}

        msg = messages[0]
        from_number = msg["from"]
        message_id = msg.get("id")

        # ---- idempotency: skip if we've already processed (or are processing) this exact message ----
        if message_id:
            if not claim_message(message_id):
                print(f"[{trace_id}] duplicate webhook delivery for message_id={message_id}, skipping")
                return {"status": "duplicate_ignored"}

        log_event("MESSAGE_RECEIVED", details={"type": msg.get("type"), "message_id": message_id})

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
            print(f"[{trace_id}] Unhandled WhatsApp message type: {msg['type']} — payload: {msg}")
            await send_text(from_number, "Please send your order as text, e.g. '2kg mango, 1 dozen banana'.")

        if message_id:
            mark_done(message_id, status="done")

    except (KeyError, IndexError) as e:
        # Malformed/unexpected payload shape — log and move on, nothing to reply to.
        print(f"[{trace_id}] malformed webhook payload: {e}")
        if message_id:
            mark_done(message_id, status="failed")

    except Exception as e:
        # Phase 1 global error boundary: anything else (Groq timeout, Supabase
        # error, WhatsApp send failure, etc.) lands here instead of 500-ing
        # silently. The customer gets a graceful message instead of nothing.
        print(f"[{trace_id}] unhandled error processing message: {e}")
        log_event("PROCESSING_ERROR", details={"error": str(e), "message_id": message_id})
        if message_id:
            mark_done(message_id, status="failed")
        if from_number:
            await _send_graceful_failure(from_number)

    return {"status": "ok"}
