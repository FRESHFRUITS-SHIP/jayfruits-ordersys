"""
Phase 1 — webhook idempotency. Meta can and does redeliver the same webhook
event (e.g. if our server is slow to respond). Without this, a retry would
re-run the full conversation logic and could double-charge, double-send, or
duplicate an order.
"""
from datetime import datetime
from app.db import get_db


def claim_message(message_id: str) -> bool:
    """
    Attempts to claim this message id as 'we are processing it now'.
    Returns True if this is the first time we've seen it (safe to process),
    False if we've already seen it (skip — this is a Meta retry of a message
    we already handled or are currently handling).

    Uses the primary key constraint on processed_webhook_events.message_id as
    the actual dedup mechanism — the insert simply fails if it already exists.
    """
    try:
        get_db().table("processed_webhook_events").insert({
            "message_id": message_id,
            "status": "processing",
        }).execute()
        return True
    except Exception:
        # Primary key violation (or any other insert failure) => already claimed,
        # or the table isn't reachable. Fail closed: treat as a duplicate/skip
        # rather than risk double-processing a real duplicate delivery.
        return False


def mark_done(message_id: str, status: str = "done") -> None:
    try:
        get_db().table("processed_webhook_events").update({
            "status": status,
            "processed_at": datetime.utcnow().isoformat(),
        }).eq("message_id", message_id).execute()
    except Exception as e:
        print(f"idempotency mark_done failed for {message_id}: {e}")
