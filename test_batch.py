"""
Batch test runner — runs a whole list of test messages against your REAL
bot code (order_parser.py, order_flow.py, router.py) in one shot, printing
input -> output for each. No browser clicking, no manual pacing.

Between each test case, it resets the test customer's pending_item,
pending_order, and any open unconfirmed order — so every test starts from
a clean BROWSING state, and one test's leftover state can't contaminate
the next one's result.

Place this file in your project root (jayfruits-ordersys/), next to app/.

Usage:
    cd jayfruits-ordersys
    python test_batch.py
"""
import sys
import os
import asyncio
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FAKE_NUMBER = "911234599999"  # separate from the manual fake-chat-ui number, so they don't collide

outbox: list[dict] = []


async def mock_send_text(to, body):
    outbox.append({"type": "text", "body": body})


async def mock_send_buttons(to, body, buttons):
    outbox.append({"type": "buttons", "body": body, "buttons": [b[1] for b in buttons]})


async def mock_send_image(to, image_url, caption=None):
    outbox.append({"type": "image", "caption": caption})


async def mock_send_list_menu(to, body_text, button_text, sections, footer=None):
    rows = []
    for s in sections:
        rows.extend(r["title"] for r in s.get("rows", []))
    outbox.append({"type": "list", "body": body_text, "rows": rows})


import app.services.whatsapp as _wa
_wa.send_text = mock_send_text
_wa.send_buttons = mock_send_buttons
_wa.send_image = mock_send_image
_wa.send_list_menu = mock_send_list_menu

from app.conversation.router import handle_text_message
from app.services import orders as svc
from app.db import get_db


def ensure_test_customer_ready():
    """Create the test customer if needed, and make sure language+name are
    already set so every test skips onboarding and starts at BROWSING."""
    customer = svc.get_or_create_customer(FAKE_NUMBER)
    if not customer.get("preferred_language") or not customer.get("name"):
        get_db().table("customers").update({
            "preferred_language": "en",
            "name": "Tester",
        }).eq("id", customer["id"]).execute()
    return svc.get_or_create_customer(FAKE_NUMBER)


def reset_state(customer_id: int):
    """Clear pending_item/pending_order/conversation_state and cancel any
    open order, so each test case starts from a known-clean BROWSING state."""
    get_db().table("customers").update({
        "pending_item": None,
        "pending_order": None,
        "pending_item_set_at": None,
        "pending_order_set_at": None,
        "conversation_state": "BROWSING",
        "interrupted_state": None,
    }).eq("id", customer_id).execute()
    open_order = svc.get_latest_open_order_for_customer(customer_id)
    if open_order:
        svc.cancel_order(open_order["id"])


TEST_CASES = [
    "2kg mango no wait 3kg",
    "1 dozen banana... actually 2",
    "2 kilo apple sorry 1 kilo",
    "mango nahi, orange de do",
    "thoda mango de do",
    "around 2kg banana",
    "2-3 kg mango",
    "0 mango",
    "-2 kg banana",
    "100kg mango",
    "7 sev",
    "3 apple",
    "do aam",
    "6 piece kela",
    "500g mango",
    "2 litre mango",
    "fruit",
    "phal",
    "kuch fruit de do",
    "surprise me",
    "Kashmiri",
]


async def run_all():
    customer = ensure_test_customer_ready()
    print(f"Testing as customer id={customer['id']} ({FAKE_NUMBER})\n")
    print("=" * 70)

    for i, msg in enumerate(TEST_CASES, 1):
        reset_state(customer["id"])
        outbox.clear()
        try:
            await handle_text_message(FAKE_NUMBER, msg)
        except Exception as e:
            outbox.append({"type": "error", "body": f"EXCEPTION: {e}"})

        print(f"[{i}] YOU: {msg}")
        if not outbox:
            print("     BOT: (no reply)")
        for item in outbox:
            if item["type"] == "text":
                print(f"     BOT: {item['body']}")
            elif item["type"] == "buttons":
                print(f"     BOT (buttons): {item['body']}  [{', '.join(item['buttons'])}]")
            elif item["type"] == "list":
                print(f"     BOT (list): {item['body']}  [{', '.join(item['rows'][:6])}{'...' if len(item['rows'])>6 else ''}]")
            elif item["type"] == "image":
                print(f"     BOT (image): {item.get('caption','')}")
            elif item["type"] == "error":
                print(f"     BOT: ⚠️ {item['body']}")
        print("-" * 70)

    print("\nDone. Review the BOT replies above against expected behavior.")


if __name__ == "__main__":
    asyncio.run(run_all())
