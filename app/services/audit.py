"""
Phase 1 — correlation IDs + business-event audit log.

Trace ID is stored in a contextvar rather than threaded through every function
signature in app/conversation/* — each incoming webhook request gets its own
async task, so the contextvar stays correctly scoped per-request with zero
changes needed to existing function signatures (pure addition, no behavior change).

Usage:
    from app.services.audit import new_trace_id, get_trace_id, log_event

    # once per incoming webhook request, in webhook.py:
    new_trace_id()

    # anywhere else in the call chain (order_flow.py, router.py, etc.):
    log_event("ORDER_CONFIRMED", customer_id=customer["id"], details={"order_id": order["id"]})
"""
import uuid
import contextvars
from app.db import get_db

_trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


def new_trace_id() -> str:
    """Call once per incoming webhook request. Returns the id it set, e.g. for logging."""
    tid = f"JF-{uuid.uuid4().hex[:10].upper()}"
    _trace_id_var.set(tid)
    return tid


def get_trace_id() -> str:
    """Returns the current request's trace id, or '' if none was set (e.g. a background task)."""
    return _trace_id_var.get()


def log_event(event_type: str, customer_id: int | None = None, details: dict | None = None) -> None:
    """
    Records a business event. Never raises — a logging failure must never break
    the customer-facing flow. Falls back to a plain print if the DB write fails.
    """
    trace_id = get_trace_id() or "NO-TRACE"
    try:
        get_db().table("audit_log").insert({
            "trace_id": trace_id,
            "customer_id": customer_id,
            "event_type": event_type,
            "details": details or {},
        }).execute()
    except Exception as e:
        # Logging must be best-effort only — never propagate.
        print(f"[{trace_id}] audit_log write failed ({event_type}): {e}")
