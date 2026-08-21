from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import SHOP_NAME, SHOP_WHATSAPP_DISPLAY_NUMBER
from app.services import orders as svc

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/me/{token}", response_class=HTMLResponse)
async def customer_page(request: Request, token: str):
    customer = svc.get_customer_by_token(token)
    if not customer:
        return HTMLResponse("<h1>Link not found</h1><p>This link is invalid or expired.</p>", status_code=404)

    menu = svc.get_available_menu()
    order_history = svc.get_orders_for_customer(customer["id"], limit=20)

    return templates.TemplateResponse("customer_page.html", {
        "request": request,
        "shop_name": SHOP_NAME,
        "shop_number": SHOP_WHATSAPP_DISPLAY_NUMBER,
        "customer": customer,
        "menu": menu,
        "orders": order_history,
    })
