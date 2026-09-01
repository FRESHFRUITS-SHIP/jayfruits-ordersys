"""
Local chat-room test harness — connected to your ACTUAL bot code.

This imports the real app/services/order_parser.py (the exact code your
WhatsApp bot uses) and pulls your REAL live menu from Supabase. So whatever
you test here is exactly what a real customer message would produce —
no duplicate/drifted copy of the parsing logic.

Place this file in your project root (jayfruits-ordersys/), next to the
`app/` folder, then run it. It does NOT touch WhatsApp at all — it only
calls the parsing function directly and prints the result.

Usage:
    cd jayfruits-ordersys
    python chat_test.py
"""
import sys
import os
import json

# Make sure "app" is importable when running this from the project root.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.order_parser import parse_message
from app.services import orders as svc


def print_menu(menu: list[dict]) -> None:
    print("\n📋 Live menu (from Supabase):")
    if not menu:
        print("   (menu is empty — check your products table / is_available flags)")
    for p in menu:
        print(f"   {p['name_en']:18s} ₹{p['price']}/{p['unit']}  {'✅' if p.get('is_available', True) else '❌'}")
    print()


def main():
    print("=" * 64)
    print("  Jay Fruits — LIVE Order Parsing Test Room (real code + real menu)")
    print("=" * 64)
    print("Type a message like a customer would (e.g. '2kg mango, 1 dozen banana').")
    print("Commands: 'menu' to reload/see the live menu, 'quit' to exit.\n")

    try:
        menu = svc.get_available_menu()
    except Exception as e:
        print(f"⚠️  Couldn't fetch menu from Supabase: {e}")
        print("Check your .env has SUPABASE_URL / SUPABASE_KEY set correctly.")
        return

    print_menu(menu)

    while True:
        try:
            msg = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not msg:
            continue
        if msg.lower() == "quit":
            break
        if msg.lower() == "menu":
            menu = svc.get_available_menu()  # reload in case you changed products
            print_menu(menu)
            continue

        result = parse_message(msg, menu)
        print("\n🤖 Parsed result (from your real order_parser.py):")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print()


if __name__ == "__main__":
    main()