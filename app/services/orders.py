import secrets
from datetime import datetime, timezone, timedelta
from app.db import get_db
from app.config import DEFAULT_DELIVERY_ETA_MINUTES, DUPLICATE_ORDER_WINDOW_MINUTES


# ---------- products / menu ----------

def get_available_menu() -> list[dict]:
    db = get_db()
    res = db.table("products").select("*").eq("is_available", True).order("id").execute()
    return res.data or []


def get_all_products() -> list[dict]:
    db = get_db()
    res = db.table("products").select("*").order("id").execute()
    return res.data or []


def set_product_availability(product_id: int, is_available: bool) -> None:
    db = get_db()
    db.table("products").update({"is_available": is_available}).eq("id", product_id).execute()


def update_product(product_id: int, fields: dict) -> None:
    db = get_db()
    db.table("products").update(fields).eq("id", product_id).execute()


# ---------- shop settings ----------

def get_shop_settings() -> dict:
    db = get_db()
    res = db.table("shop_settings").select("*").limit(1).execute()
    if res.data:
        return res.data[0]
    return {"minimum_order_value": 0, "business_hours_start": 7, "business_hours_end": 22}


def update_shop_settings(fields: dict) -> None:
    db = get_db()
    settings = get_shop_settings()
    if "id" in settings:
        db.table("shop_settings").update(fields).eq("id", settings["id"]).execute()


def is_within_business_hours(now: datetime | None = None) -> bool:
    settings = get_shop_settings()
    now = now or datetime.now()
    hour = now.hour
    start = settings.get("business_hours_start", 7)
    end = settings.get("business_hours_end", 22)
    return start <= hour < end


# ---------- customers ----------

def get_or_create_customer(wa_number: str) -> dict:
    db = get_db()
    existing = db.table("customers").select("*").eq("wa_number", wa_number).execute()
    if existing.data:
        return existing.data[0]
    token = secrets.token_urlsafe(16)
    created = db.table("customers").insert({"wa_number": wa_number, "page_token": token}).execute()
    return created.data[0]


def get_customer_by_token(token: str) -> dict | None:
    db = get_db()
    res = db.table("customers").select("*").eq("page_token", token).execute()
    return res.data[0] if res.data else None


def update_customer(customer_id: int, fields: dict) -> None:
    db = get_db()
    db.table("customers").update(fields).eq("id", customer_id).execute()


def set_customer_address(customer_id: int, address: str) -> None:
    update_customer(customer_id, {"address": address})


def set_customer_language(customer_id: int, lang: str) -> None:
    update_customer(customer_id, {"preferred_language": lang})


def get_all_customers_with_stats() -> list[dict]:
    """Customer list with order count + total spend, for the dashboard."""
    db = get_db()
    customers = db.table("customers").select("*").order("created_at", desc=True).execute().data or []
    orders = db.table("orders").select("customer_id, total, status").execute().data or []

    stats: dict[int, dict] = {}
    for o in orders:
        cid = o["customer_id"]
        if cid not in stats:
            stats[cid] = {"order_count": 0, "total_spend": 0.0}
        stats[cid]["order_count"] += 1
        if o["status"] != "cancelled":
            stats[cid]["total_spend"] += float(o["total"])

    for c in customers:
        s = stats.get(c["id"], {"order_count": 0, "total_spend": 0.0})
        c["order_count"] = s["order_count"]
        c["total_spend"] = s["total_spend"]
    return customers


# ---------- product matching (used by both bot + manual dashboard entry) ----------

def match_products(item_names: list[str], menu: list[dict]) -> dict[str, dict]:
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
            for k, v in by_name.items():
                if k in key or key in k:
                    matched[name] = v
                    break
    return matched


# ---------- orders: create / read ----------

def create_order(
    customer_id: int,
    items: list[dict],
    raw_message: str = "",
    source: str = "whatsapp",
    notes: str = "",
    delivery_address: str = "",
    fulfillment: str = "delivery",
) -> dict:
    """
    items: [{"product": <product row dict>, "quantity": float}]
    """
    db = get_db()
    total = sum(i["product"]["price"] * i["quantity"] for i in items)

    is_dup = _check_duplicate(customer_id)

    order = db.table("orders").insert({
        "customer_id": customer_id,
        "status": "new",
        "fulfillment": fulfillment,
        "payment_mode": "unset",
        "payment_status": "pending",
        "total": total,
        "raw_message": raw_message,
        "source": source,
        "notes": notes,
        "delivery_address": delivery_address,
        "eta_minutes": DEFAULT_DELIVERY_ETA_MINUTES if fulfillment == "delivery" else None,
        "is_duplicate_flag": is_dup,
    }).execute().data[0]

    rows = [
        {
            "order_id": order["id"],
            "product_id": i["product"]["id"],
            "product_name": i["product"]["name_en"],
            "quantity": i["quantity"],
            "unit": i["product"]["unit"],
            "unit_price": i["product"]["price"],
            "cost_price": i["product"].get("cost_price"),
            "line_total": i["product"]["price"] * i["quantity"],
        }
        for i in items
    ]
    db.table("order_items").insert(rows).execute()
    order["is_duplicate_flag"] = is_dup
    return order


def _check_duplicate(customer_id: int) -> bool:
    db = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=DUPLICATE_ORDER_WINDOW_MINUTES)).isoformat()
    recent = (
        db.table("orders")
        .select("id")
        .eq("customer_id", customer_id)
        .gte("created_at", cutoff)
        .execute()
    )
    return len(recent.data or []) > 0


def get_order(order_id: int) -> dict | None:
    db = get_db()
    res = db.table("orders").select("*, order_items(*)").eq("id", order_id).execute()
    return res.data[0] if res.data else None


def get_latest_open_order_for_customer(customer_id: int) -> dict | None:
    """'Open' = still editable/cancellable: not delivered, not cancelled."""
    db = get_db()
    res = (
        db.table("orders")
        .select("*, order_items(*)")
        .eq("customer_id", customer_id)
        .in_("status", ["new", "confirmed", "out_for_delivery"])
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def get_latest_order_for_customer(customer_id: int) -> dict | None:
    """Most recent order regardless of status — used for 'reorder same as last time'."""
    db = get_db()
    res = (
        db.table("orders")
        .select("*, order_items(*)")
        .eq("customer_id", customer_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def get_orders_for_customer(customer_id: int, limit: int = 20) -> list[dict]:
    db = get_db()
    res = (
        db.table("orders")
        .select("*, order_items(*)")
        .eq("customer_id", customer_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


def list_orders(
    limit: int = 100,
    status: str | None = None,
    source: str | None = None,
    search: str | None = None,
) -> list[dict]:
    db = get_db()
    q = db.table("orders").select("*, customers(wa_number, name, address), order_items(*)")
    if status:
        q = q.eq("status", status)
    if source:
        q = q.eq("source", source)
    q = q.order("created_at", desc=True).limit(limit)
    orders = q.execute().data or []
    if search:
        s = search.lower()
        orders = [
            o for o in orders
            if (o.get("customers") and s in (o["customers"].get("wa_number") or "").lower())
            or str(o["id"]) == s
        ]
    return orders


# ---------- orders: mutate ----------

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


def cancel_order(order_id: int) -> None:
    set_order_status(order_id, "cancelled")


def _recompute_total(order_id: int) -> float:
    db = get_db()
    items = db.table("order_items").select("line_total").eq("order_id", order_id).execute().data or []
    total = sum(float(i["line_total"]) for i in items)
    db.table("orders").update({
        "total": total,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", order_id).execute()
    return total


def add_item_to_order(order_id: int, product: dict, quantity: float) -> float:
    """Adds a line item, or increases quantity if that product is already on the order. Returns new total."""
    db = get_db()
    existing = (
        db.table("order_items")
        .select("*")
        .eq("order_id", order_id)
        .eq("product_id", product["id"])
        .execute()
    )
    if existing.data:
        row = existing.data[0]
        new_qty = float(row["quantity"]) + quantity
        db.table("order_items").update({
            "quantity": new_qty,
            "line_total": new_qty * float(row["unit_price"]),
        }).eq("id", row["id"]).execute()
    else:
        db.table("order_items").insert({
            "order_id": order_id,
            "product_id": product["id"],
            "product_name": product["name_en"],
            "quantity": quantity,
            "unit": product["unit"],
            "unit_price": product["price"],
            "cost_price": product.get("cost_price"),
            "line_total": product["price"] * quantity,
        }).execute()
    return _recompute_total(order_id)


def remove_item_from_order(order_id: int, product_name: str) -> float:
    """Removes a line item by product name (case-insensitive match). Returns new total."""
    db = get_db()
    items = db.table("order_items").select("*").eq("order_id", order_id).execute().data or []
    for item in items:
        if item["product_name"].lower() == product_name.lower():
            db.table("order_items").delete().eq("id", item["id"]).execute()
            break
    return _recompute_total(order_id)


def update_order_notes(order_id: int, notes: str) -> None:
    db = get_db()
    db.table("orders").update({"notes": notes}).eq("id", order_id).execute()


# ---------- analytics ----------

def get_analytics(days: int = 30) -> dict:
    db = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    orders = (
        db.table("orders")
        .select("*, order_items(*)")
        .gte("created_at", cutoff)
        .neq("status", "cancelled")
        .execute()
        .data or []
    )

    total_revenue = sum(float(o["total"]) for o in orders)
    total_orders = len(orders)
    total_cost = 0.0
    item_counts: dict[str, float] = {}
    item_revenue: dict[str, float] = {}
    daily_revenue: dict[str, float] = {}

    for o in orders:
        day = o["created_at"][:10]
        daily_revenue[day] = daily_revenue.get(day, 0) + float(o["total"])
        for it in o.get("order_items", []):
            name = it["product_name"]
            qty = float(it["quantity"])
            item_counts[name] = item_counts.get(name, 0) + qty
            item_revenue[name] = item_revenue.get(name, 0) + float(it["line_total"])
            if it.get("cost_price") is not None:
                total_cost += float(it["cost_price"]) * qty

    best_sellers = sorted(item_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    daily_series = sorted(daily_revenue.items())

    return {
        "total_revenue": total_revenue,
        "total_orders": total_orders,
        "total_cost": total_cost,
        "total_profit": total_revenue - total_cost,
        "best_sellers": best_sellers,
        "item_revenue": item_revenue,
        "daily_series": daily_series,
        "avg_order_value": (total_revenue / total_orders) if total_orders else 0,
    }


def get_orders_csv_rows() -> list[dict]:
    """Flat rows suitable for CSV export — one row per order item."""
    db = get_db()
    orders = db.table("orders").select("*, customers(wa_number), order_items(*)").order("created_at", desc=True).execute().data or []
    rows = []
    for o in orders:
        wa = o["customers"]["wa_number"] if o.get("customers") else ""
        for it in o.get("order_items", []):
            rows.append({
                "order_id": o["id"],
                "date": o["created_at"],
                "customer": wa,
                "status": o["status"],
                "source": o.get("source", "whatsapp"),
                "product": it["product_name"],
                "quantity": it["quantity"],
                "unit": it["unit"],
                "unit_price": it["unit_price"],
                "line_total": it["line_total"],
                "order_total": o["total"],
                "payment_mode": o["payment_mode"],
                "payment_status": o["payment_status"],
            })
    return rows
