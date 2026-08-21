import csv
import io
import asyncio
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.config import DASHBOARD_USERNAME, DASHBOARD_PASSWORD, SHOP_NAME
from app.services import orders as svc
from app.services.notifications import notify_status_change
from app.db import get_db

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _require_login(request: Request):
    if not request.session.get("logged_in"):
        return False
    return True


# ---------- auth ----------
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "shop_name": SHOP_NAME, "error": None})


@router.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == DASHBOARD_USERNAME and password == DASHBOARD_PASSWORD:
        request.session["logged_in"] = True
        return RedirectResponse(url="/orders", status_code=303)
    return templates.TemplateResponse(
        "login.html", {"request": request, "shop_name": SHOP_NAME, "error": "Wrong username or password"},
        status_code=401,
    )


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


# ---------- orders list ----------
@router.get("/orders", response_class=HTMLResponse)
async def orders_page(request: Request, status: str = "", source: str = "", search: str = ""):
    if not _require_login(request):
        return RedirectResponse(url="/login", status_code=303)

    orders = svc.list_orders(
        status=status or None,
        source=source or None,
        search=search or None,
    )
    today = orders[0]["created_at"][:10] if orders else ""
    today_total = sum(o["total"] for o in orders if o["created_at"][:10] == today)
    menu = svc.get_available_menu()

    return templates.TemplateResponse("orders.html", {
        "request": request, "shop_name": SHOP_NAME, "orders": orders,
        "today_total": today_total, "menu": menu,
        "filter_status": status, "filter_source": source, "filter_search": search,
    })


@router.post("/orders/{order_id}/status")
async def update_status(request: Request, order_id: int, status: str = Form(...)):
    if not _require_login(request):
        return RedirectResponse(url="/login", status_code=303)

    order = svc.get_order(order_id)
    svc.set_order_status(order_id, status)

    if order:
        db = get_db()
        cust = db.table("customers").select("*").eq("id", order["customer_id"]).execute().data
        if cust:
            customer = cust[0]
            lang = customer.get("preferred_language") or "en"
            try:
                await notify_status_change(customer["wa_number"], order_id, status, lang)
            except Exception:
                pass  # don't let a WhatsApp send failure break the dashboard

    return RedirectResponse(url="/orders", status_code=303)


@router.post("/orders/{order_id}/notes")
async def update_notes(request: Request, order_id: int, notes: str = Form("")):
    if not _require_login(request):
        return RedirectResponse(url="/login", status_code=303)
    svc.update_order_notes(order_id, notes)
    return RedirectResponse(url="/orders", status_code=303)


@router.post("/orders/{order_id}/add-item")
async def add_item(request: Request, order_id: int, product_id: int = Form(...), quantity: float = Form(...)):
    if not _require_login(request):
        return RedirectResponse(url="/login", status_code=303)
    products = {p["id"]: p for p in svc.get_all_products()}
    product = products.get(product_id)
    if product:
        svc.add_item_to_order(order_id, product, quantity)
    return RedirectResponse(url="/orders", status_code=303)


@router.post("/orders/{order_id}/remove-item")
async def remove_item(request: Request, order_id: int, product_name: str = Form(...)):
    if not _require_login(request):
        return RedirectResponse(url="/login", status_code=303)
    svc.remove_item_from_order(order_id, product_name)
    return RedirectResponse(url="/orders", status_code=303)


# ---------- manual (phone) order entry ----------
@router.get("/orders/new", response_class=HTMLResponse)
async def new_order_form(request: Request):
    if not _require_login(request):
        return RedirectResponse(url="/login", status_code=303)
    menu = svc.get_available_menu()
    return templates.TemplateResponse("new_order.html", {"request": request, "shop_name": SHOP_NAME, "menu": menu})


@router.post("/orders/new")
async def create_manual_order(
    request: Request,
    wa_number: str = Form(...),
    address: str = Form(""),
    fulfillment: str = Form("delivery"),
    payment_mode: str = Form("cod"),
    notes: str = Form(""),
):
    if not _require_login(request):
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    menu = {str(p["id"]): p for p in svc.get_all_products()}

    items_for_order = []
    for key in form.keys():
        if key.startswith("qty_"):
            pid = key.replace("qty_", "")
            qty_str = form.get(key)
            if qty_str and float(qty_str) > 0 and pid in menu:
                items_for_order.append({"product": menu[pid], "quantity": float(qty_str)})

    if not items_for_order:
        raise HTTPException(status_code=400, detail="No items selected")

    wa_number_clean = wa_number.strip().replace(" ", "").replace("+", "")
    customer = svc.get_or_create_customer(wa_number_clean)
    if address:
        svc.set_customer_address(customer["id"], address)

    order = svc.create_order(
        customer["id"], items_for_order, raw_message="(phone order)",
        source="phone", notes=notes, delivery_address=address or customer.get("address", ""),
        fulfillment=fulfillment,
    )
    svc.set_order_payment_mode(order["id"], payment_mode)

    # confirm to the customer over WhatsApp same as a bot order would
    try:
        from app.services.whatsapp import send_text
        lines = [f"• {i['product']['name_en']} — {i['quantity']} {i['product']['unit']}" for i in items_for_order]
        msg = (
            f"Order confirmed! 🧾 (taken by phone)\n\n" + "\n".join(lines) +
            f"\n\n*Total: ₹{order['total']:.0f}*"
        )
        if order.get("eta_minutes"):
            msg += f"\n🚴 Estimated delivery: ~{order['eta_minutes']} minutes."
        await send_text(wa_number_clean, msg)
    except Exception:
        pass

    return RedirectResponse(url="/orders", status_code=303)


# ---------- products / availability ----------
@router.get("/products", response_class=HTMLResponse)
async def products_page(request: Request):
    if not _require_login(request):
        return RedirectResponse(url="/login", status_code=303)
    products = svc.get_all_products()
    return templates.TemplateResponse("products.html", {"request": request, "shop_name": SHOP_NAME, "products": products})


@router.post("/products/{product_id}/toggle")
async def toggle_product(request: Request, product_id: int, is_available: str = Form(...)):
    if not _require_login(request):
        return RedirectResponse(url="/login", status_code=303)
    svc.set_product_availability(product_id, is_available == "true")
    return RedirectResponse(url="/products", status_code=303)


@router.post("/products/{product_id}/update")
async def update_product_route(
    request: Request, product_id: int,
    price: float = Form(...), cost_price: float = Form(None),
):
    if not _require_login(request):
        return RedirectResponse(url="/login", status_code=303)
    fields = {"price": price}
    if cost_price is not None:
        fields["cost_price"] = cost_price
    svc.update_product(product_id, fields)
    return RedirectResponse(url="/products", status_code=303)


# ---------- customers ----------
@router.get("/customers", response_class=HTMLResponse)
async def customers_page(request: Request):
    if not _require_login(request):
        return RedirectResponse(url="/login", status_code=303)
    customers = svc.get_all_customers_with_stats()
    return templates.TemplateResponse("customers.html", {"request": request, "shop_name": SHOP_NAME, "customers": customers})


@router.get("/customers/{customer_id}", response_class=HTMLResponse)
async def customer_detail(request: Request, customer_id: int):
    if not _require_login(request):
        return RedirectResponse(url="/login", status_code=303)
    db = get_db()
    customer = db.table("customers").select("*").eq("id", customer_id).execute().data
    if not customer:
        raise HTTPException(status_code=404)
    customer = customer[0]
    orders = svc.get_orders_for_customer(customer_id, limit=50)
    return templates.TemplateResponse("customer_detail.html", {
        "request": request, "shop_name": SHOP_NAME, "customer": customer, "orders": orders,
    })


# ---------- analytics ----------
@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, days: int = 30):
    if not _require_login(request):
        return RedirectResponse(url="/login", status_code=303)
    data = svc.get_analytics(days=days)
    return templates.TemplateResponse("analytics.html", {
        "request": request, "shop_name": SHOP_NAME, "data": data, "days": days,
    })


# ---------- settings ----------
@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    if not _require_login(request):
        return RedirectResponse(url="/login", status_code=303)
    settings = svc.get_shop_settings()
    return templates.TemplateResponse("settings.html", {"request": request, "shop_name": SHOP_NAME, "settings": settings})


@router.post("/settings")
async def update_settings(
    request: Request,
    minimum_order_value: float = Form(0),
    business_hours_start: int = Form(7),
    business_hours_end: int = Form(22),
):
    if not _require_login(request):
        return RedirectResponse(url="/login", status_code=303)
    svc.update_shop_settings({
        "minimum_order_value": minimum_order_value,
        "business_hours_start": business_hours_start,
        "business_hours_end": business_hours_end,
    })
    return RedirectResponse(url="/settings", status_code=303)


# ---------- CSV export ----------
@router.get("/export.csv")
async def export_csv(request: Request):
    if not _require_login(request):
        return RedirectResponse(url="/login", status_code=303)
    rows = svc.get_orders_csv_rows()
    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=orders_export.csv"},
    )
