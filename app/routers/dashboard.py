from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import DASHBOARD_USERNAME, DASHBOARD_PASSWORD, SHOP_NAME
from app.db import get_db
from app.services.orders import set_order_status

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def require_login(request: Request):
    if not request.session.get("logged_in"):
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    return True


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "shop_name": SHOP_NAME, "error": None})


@router.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == DASHBOARD_USERNAME and password == DASHBOARD_PASSWORD:
        request.session["logged_in"] = True
        return RedirectResponse(url="/orders", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "shop_name": SHOP_NAME, "error": "Wrong username or password"},
        status_code=401,
    )


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@router.get("/orders", response_class=HTMLResponse)
async def orders_page(request: Request):
    if not request.session.get("logged_in"):
        return RedirectResponse(url="/login", status_code=303)

    db = get_db()
    orders_res = (
        db.table("orders")
        .select("*, customers(wa_number, name, address), order_items(*)")
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    orders = orders_res.data or []

    today_total = sum(
        o["total"] for o in orders
        if o["created_at"][:10] == orders[0]["created_at"][:10]
    ) if orders else 0

    return templates.TemplateResponse(
        "orders.html",
        {"request": request, "shop_name": SHOP_NAME, "orders": orders, "today_total": today_total},
    )


@router.post("/orders/{order_id}/status")
async def update_status(request: Request, order_id: int, status: str = Form(...)):
    if not request.session.get("logged_in"):
        return RedirectResponse(url="/login", status_code=303)
    set_order_status(order_id, status)
    return RedirectResponse(url="/orders", status_code=303)
