from datetime import datetime, timezone
from app.db import get_db


def get_available_menu() -> list[dict]:
    db = get_db()
    res = db.table("products").select("*").eq("is_available", True).execute()
    return res.data or []


def get_or_create_customer(wa_number: str) -> dict:
    db = get_db()
    existing = db.table("customers").select("*").eq("wa_number", wa_number).execute()
    if existing.data:
        return existing.data[0]
    created = db.table("customers").insert({"wa_number": wa_number}).execute()
    return created.data[0]


def match_products(item_names: list[str], menu: list[dict]) -> dict[str, dict]:
    """Case-insensitive match of parsed item names against the real menu."""
    by_name = {}
    for p in menu:
        by_name[p["name_en"].lower()] = p
        if p.get("name_hi"):
            by_name[p["name_hi"].lower()] = p
    matched = {}
    for name in item_names:
        key = name.lower().strip()
        if key in by_name:
            matched[name] = by_name[key]
        else:
            # loose contains-match fallback
            for k, v in by_name.items():
                if k in key or key in k:
                    matched[name] = v
                    break
    return matched


def create_order(customer_id: int, items: list[dict], raw_message: str) -> dict:
    """
    items: [{"product": <product row dict>, "quantity": float}]
    """
    db = get_db()
    total = sum(i["product"]["price"] * i["quantity"] for i in items)

    order = db.table("orders").insert({
        "customer_id": customer_id,
        "status": "new",
        "payment_mode": "unset",
        "payment_status": "pending",
        "total": total,
        "raw_message": raw_message,
    }).execute().data[0]

    rows = [
        {
            "order_id": order["id"],
            "product_id": i["product"]["id"],
            "product_name": i["product"]["name_en"],
            "quantity": i["quantity"],
            "unit": i["product"]["unit"],
            "unit_price": i["product"]["price"],
            "line_total": i["product"]["price"] * i["quantity"],
        }
        for i in items
    ]
    db.table("order_items").insert(rows).execute()
    return order


def set_order_payment_mode(order_id: int, mode: str) -> None:
    db = get_db()
    db.table("orders").update({
        "payment_mode": mode,
        "payment_status": "na" if mode == "cod" else "pending",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", order_id).execute()


def set_order_status(order_id: int, status: str) -> None:
    db = get_db()
    db.table("orders").update({
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", order_id).execute()


def get_latest_open_order_for_customer(customer_id: int) -> dict | None:
    db = get_db()
    res = (
        db.table("orders")
        .select("*")
        .eq("customer_id", customer_id)
        .in_("status", ["new", "confirmed"])
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None
