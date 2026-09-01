"""
Phase 2 — Conversation State Engine.

Replaces the previously-implicit state model (just pending_item/pending_order
flags checked ad hoc) with an explicit state enum, a validated transition
table, and formal interruption handling (a customer can be asked "kitna
chahiye?", ask an unrelated question, get answered, and correctly resume
right where they left off).

Design choice: invalid transitions are LOGGED, not blocked. A hard block on
an unexpected transition would mean a bug in our own transition table could
freeze a real customer's conversation entirely — worse than the bug itself.
So this stays observability-first: every transition is validated and
recorded, but a customer message is never dropped because the state machine
disagreed with reality.
"""
from enum import Enum
from app.db import get_db
from app.services.audit import log_event


class ConversationState(str, Enum):
    NEW = "NEW"                            # never messaged before
    LANGUAGE_SELECTION = "LANGUAGE_SELECTION"  # language buttons sent, awaiting choice
    NAME_CAPTURE = "NAME_CAPTURE"          # awaiting first name
    BROWSING = "BROWSING"                  # idle / menu shown / between actions
    SELECTING_VARIANT = "SELECTING_VARIANT"  # variant list sent, awaiting choice
    WAITING_QUANTITY = "WAITING_QUANTITY"  # "kitna chahiye?" asked, awaiting a quantity
    CART_REVIEW = "CART_REVIEW"            # order summary shown, awaiting Confirm/Edit
    DELIVERY_SELECTION = "DELIVERY_SELECTION"  # delivery/pickup buttons shown
    ADDRESS_COLLECTION = "ADDRESS_COLLECTION"  # awaiting a delivery address
    PAYMENT_PENDING = "PAYMENT_PENDING"    # payment buttons shown, awaiting choice
    ORDER_CONFIRMED = "ORDER_CONFIRMED"    # terminal-ish: order placed, back to browsing next message
    HUMAN_HANDOFF = "HUMAN_HANDOFF"        # escalated to a human (not yet built — reserved)


# Which states are valid to move TO from a given current state.
# Not exhaustive of every real-world path (Groq-driven conversation is fuzzy
# by nature) — this is a validation net, not a rigid FSM that blocks input.
ALLOWED_TRANSITIONS: dict[ConversationState, set[ConversationState]] = {
    ConversationState.NEW: {ConversationState.LANGUAGE_SELECTION},
    ConversationState.LANGUAGE_SELECTION: {ConversationState.NAME_CAPTURE},
    ConversationState.NAME_CAPTURE: {ConversationState.BROWSING},
    ConversationState.BROWSING: {
        ConversationState.BROWSING, ConversationState.SELECTING_VARIANT,
        ConversationState.WAITING_QUANTITY, ConversationState.CART_REVIEW,
        ConversationState.ADDRESS_COLLECTION, ConversationState.DELIVERY_SELECTION,
    },
    ConversationState.SELECTING_VARIANT: {
        ConversationState.WAITING_QUANTITY, ConversationState.BROWSING,
    },
    ConversationState.WAITING_QUANTITY: {
        ConversationState.CART_REVIEW, ConversationState.BROWSING,
        ConversationState.WAITING_QUANTITY,  # re-ask on unparseable quantity
    },
    ConversationState.CART_REVIEW: {
        ConversationState.DELIVERY_SELECTION, ConversationState.BROWSING,
    },
    ConversationState.DELIVERY_SELECTION: {
        ConversationState.ADDRESS_COLLECTION, ConversationState.PAYMENT_PENDING,
    },
    ConversationState.ADDRESS_COLLECTION: {
        ConversationState.PAYMENT_PENDING, ConversationState.DELIVERY_SELECTION,
    },
    ConversationState.PAYMENT_PENDING: {ConversationState.ORDER_CONFIRMED},
    ConversationState.ORDER_CONFIRMED: {ConversationState.BROWSING},
    ConversationState.HUMAN_HANDOFF: {ConversationState.BROWSING},
}


def get_state(customer: dict) -> ConversationState:
    raw = customer.get("conversation_state") or "NEW"
    try:
        return ConversationState(raw)
    except ValueError:
        # Unknown/corrupted value in the DB — fail safe to BROWSING rather than crash.
        return ConversationState.BROWSING


def set_state(customer_id: int, new_state: ConversationState, current: ConversationState | None = None) -> None:
    """
    Moves a customer to new_state. If `current` is provided, validates the
    transition against ALLOWED_TRANSITIONS and logs (but does not block) any
    transition outside that table — this is how we catch state-machine bugs
    over time without ever freezing a real conversation.
    """
    if current is not None:
        allowed = ALLOWED_TRANSITIONS.get(current, set())
        if new_state not in allowed and new_state != current:
            log_event("INVALID_STATE_TRANSITION", customer_id=customer_id, details={
                "from": current.value, "to": new_state.value,
            })

    try:
        get_db().table("customers").update({
            "conversation_state": new_state.value,
        }).eq("id", customer_id).execute()
    except Exception as e:
        print(f"set_state failed for customer {customer_id} -> {new_state.value}: {e}")


def push_interruption(customer_id: int, state_to_resume: ConversationState) -> None:
    """Call when a side-quest (e.g. a price query mid-flow) interrupts the
    current flow — stashes the state to return to once the side-quest is answered."""
    try:
        get_db().table("customers").update({
            "interrupted_state": state_to_resume.value,
        }).eq("id", customer_id).execute()
    except Exception as e:
        print(f"push_interruption failed for customer {customer_id}: {e}")


def pop_interruption(customer: dict) -> ConversationState | None:
    """Returns the stashed state to resume, if any, and does NOT clear it —
    caller should clear explicitly via clear_interruption() once actually resumed."""
    raw = customer.get("interrupted_state")
    if not raw:
        return None
    try:
        return ConversationState(raw)
    except ValueError:
        return None


def clear_interruption(customer_id: int) -> None:
    try:
        get_db().table("customers").update({
            "interrupted_state": None,
        }).eq("id", customer_id).execute()
    except Exception as e:
        print(f"clear_interruption failed for customer {customer_id}: {e}")